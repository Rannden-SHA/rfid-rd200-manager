# =============================================================================
# core/reader_manager.py
#
# Comunicacion con el lector RD200-M1-G (VID: 0x0E6A, PID: 0x0317).
#
# El RD200 expone multiples interfaces HID. Este modulo:
#   1. Enumera TODAS las interfaces HID del VID/PID
#   2. Intenta enviar un comando real (Get S/N) en cada una
#   3. La que responda correctamente es la interfaz de comandos
#   4. Si ninguna responde, intenta modo pasivo (escuchar teclado)
#
# Protocolo: [STX=0x02][LEN][CMD]{DATA} (sin BCC ni ETX)
# Referencia: "RD200 Protocol Manual V0192" - SYRIS Technology
# =============================================================================

import time
import threading
import logging
from typing import Optional, Callable, List
from datetime import datetime

from .rfid_protocol import RFIDProtocol, CardData, STATUS_OK, STATUS_NO_CARD, STATUS_ERROR

logger = logging.getLogger(__name__)


# =============================================================================
# Excepciones
# =============================================================================

class ReaderConnectionError(Exception):
    """El lector no esta disponible o no se puede abrir."""

class ReaderTimeoutError(Exception):
    """El lector tardo demasiado en responder."""

class ReaderWriteError(Exception):
    """Error al escribir datos en una tarjeta RFID."""

class ReaderProtocolError(Exception):
    """La respuesta del lector no coincide con el protocolo esperado."""


# =============================================================================
# Clase principal
# =============================================================================

class ReaderManager:
    """
    Gestiona la conexion y comunicacion con el lector RD200-M1-G.

    Soporta dos modos:
      - MODO COMANDO: Envia comandos del protocolo RD200 y recibe respuestas.
        Funciona cuando se encuentra la interfaz HID de comandos correcta.
      - MODO PASIVO: Escucha HID keyboard reports (fallback).
    """

    VID = 0x0E6A
    PID = 0x0317

    POLL_INTERVAL = 0.3     # 300ms entre polls en modo comando
    READ_TIMEOUT_MS = 500   # Timeout para leer respuestas
    MAX_CONSECUTIVE_ERRORS = 3

    def __init__(self):
        self._device = None
        self._device_path: Optional[bytes] = None
        self._backend: Optional[str] = None
        self._lock = threading.Lock()

        # Modo de operacion
        self._command_mode = False  # True si la interfaz acepta comandos
        self._cmd_report_id = 0x03  # Report ID para enviar comandos

        # Info del lector (obtenida al conectar)
        self.serial_number: str = ""
        self.model_version: str = ""

        # Estado del polling
        self._polling = False
        self._poll_thread: Optional[threading.Thread] = None
        self._last_uid: Optional[str] = None

        # Buffer para modo pasivo (keyboard reports)
        self._uid_buffer: List[str] = []

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
        return False

    # -------------------------------------------------------------------------
    # Conexion
    # -------------------------------------------------------------------------

    def connect(self) -> bool:
        """
        Conecta al lector. Enumera interfaces HID y prueba cada una
        enviando un comando real (Get S/N).
        Si ya hay una conexión activa, la cierra primero para permitir
        hot-swap de lectores.
        """
        if self._device is not None:
            logger.info("Cerrando conexion previa antes de reconectar...")
            self.disconnect()

        if self._try_connect_hid():
            return True

        raise ReaderConnectionError(
            f"No se pudo conectar al lector RD200-M1-G "
            f"(VID={self.VID:#06x}, PID={self.PID:#06x}). "
            "Verifica que el dispositivo este conectado por USB."
        )

    # El RD200 usa el Report ID como indicador de longitud del payload.
    # Report ID = número de bytes del frame de protocolo que el lector debe leer.
    # Ejemplo: GetSerial = 02 01 0D (3 bytes) → Report ID = 0x03
    #          SetParam  = 02 05 03 03 05 01 80 (7 bytes) → Report ID = 0x07
    # La respuesta también usa Report ID = longitud de su frame.
    REPORT_ID_CMD = 0x03   # Default para comandos cortos (ej. GetSerial)
    REPORT_ID_RESP = 0x0C  # Input: respuestas del lector (incluido por hidapi)

    def _try_connect_hid(self) -> bool:
        """
        Enumera TODAS las interfaces HID del lector.
        Estrategia de conexion basada en diagnostico del RD200:
          1. Buscar la interfaz Consumer (usage_page=0x000C)
          2. Enviar Get S/N con Report ID 0x03
          3. Leer respuesta (viene con Report ID 0x0C)
          4. Si funciona → modo comando
          5. Si no → probar todas las interfaces con Report IDs variados
          6. Fallback → modo pasivo (keyboard)
        """
        try:
            import hid  # type: ignore
        except ImportError:
            logger.error("hidapi no esta instalado: pip install hidapi")
            return False

        interfaces = [
            d for d in hid.enumerate()
            if d["vendor_id"] == self.VID and d["product_id"] == self.PID
        ]

        if not interfaces:
            logger.debug("HID: no se encontro ninguna interfaz del RD200.")
            return False

        logger.info(f"HID: encontradas {len(interfaces)} interfaces para el RD200:")
        for i, intf in enumerate(interfaces):
            logger.info(
                f"  [{i}] interface={intf.get('interface_number', '?')}  "
                f"usage_page=0x{intf.get('usage_page', 0):04X}  "
                f"usage=0x{intf.get('usage', 0):04X}  "
                f"product={intf.get('product_string', '?')}"
            )

        # Ordenar: Consumer (0x000C) primero, luego vendor-specific, luego otros
        def sort_key(intf):
            up = intf.get("usage_page", 0)
            if up == 0x000C:  # Consumer — canal de comandos del RD200
                return (0, intf.get("interface_number", 99))
            if up >= 0xFF00:  # Vendor-specific
                return (1, intf.get("interface_number", 99))
            if up == 0x0001 and intf.get("usage", 0) != 0x0006:
                return (2, intf.get("interface_number", 99))
            # Keyboard (0x0001/0x0006) al final
            return (3, intf.get("interface_number", 99))

        sorted_interfaces = sorted(interfaces, key=sort_key)

        # Intentar cada interfaz con multiples Report IDs
        report_ids_to_try = [self.REPORT_ID_CMD, 0x00, 0x01, 0x02]

        for intf in sorted_interfaces:
            path = intf.get("path")
            if not path:
                continue

            intf_num = intf.get("interface_number", "?")
            usage_page = intf.get("usage_page", 0)
            usage = intf.get("usage", 0)

            try:
                dev = hid.device()
                dev.open_path(path)
            except OSError as e:
                logger.debug(
                    f"  Interface {intf_num} (0x{usage_page:04X}): "
                    f"no se pudo abrir → {e}")
                continue
            except Exception as e:
                logger.debug(f"  Interface {intf_num}: error → {e}")
                continue

            # Probar con Report ID = longitud del frame (método RD200)
            # GetSerial frame = 02 01 0D → 3 bytes → RID=0x03
            for report_id in report_ids_to_try:
                try:
                    cmd = RFIDProtocol.build_command(RFIDProtocol.CMD_GET_SERIAL)
                    # En discovery, el primer intento es REPORT_ID_CMD=0x03
                    # que coincide con len(GetSerial)=3. Los demás son fallback.
                    report = bytes([report_id]) + cmd.ljust(63, b'\x00')
                    written = dev.write(list(report))

                    if written < 0:
                        continue  # Este Report ID no funciona

                    response = dev.read(64, timeout_ms=2000)

                    if not response:
                        continue

                    raw = bytes(response)
                    parsed = RFIDProtocol.parse_response(raw)

                    if parsed["valid"] and parsed["cmd"] == RFIDProtocol.CMD_GET_SERIAL:
                        # Interfaz de comandos encontrada
                        self._device = dev
                        self._device_path = path
                        self._backend = "hid"
                        self._command_mode = True
                        self._cmd_report_id = report_id

                        if parsed["success"] and parsed["data"]:
                            self.serial_number = RFIDProtocol.parse_serial_from_data(
                                parsed["data"])

                        logger.info(
                            f"Lector conectado via HID COMANDO "
                            f"(interface={intf_num}, "
                            f"usage_page=0x{usage_page:04X}, "
                            f"ReportID=0x{report_id:02X}, "
                            f"SN={self.serial_number})"
                        )

                        self._fetch_model_version()
                        return True

                except OSError:
                    continue
                except Exception:
                    continue

            # Ningun Report ID funciono en esta interfaz
            try:
                dev.close()
            except Exception:
                pass

        # Ninguna interfaz respondio a comandos
        logger.warning(
            "HID: ninguna interfaz respondio a comandos. "
            "Intentando modo pasivo (keyboard)..."
        )
        return self._try_passive_fallback(sorted_interfaces)

    def _try_passive_fallback(self, interfaces: list) -> bool:
        """Intenta abrir una interfaz para escuchar keyboard reports."""
        try:
            import hid  # type: ignore
        except ImportError:
            return False

        for intf in interfaces:
            path = intf.get("path")
            if not path:
                continue
            try:
                dev = hid.device()
                dev.open_path(path)
                dev.set_nonblocking(True)

                # Test read (no deberia fallar en nonblocking)
                test = dev.read(64, timeout_ms=50)

                self._device = dev
                self._device_path = path
                self._backend = "hid"
                self._command_mode = False

                intf_num = intf.get("interface_number", "?")
                usage_page = intf.get("usage_page", 0)
                logger.info(
                    f"Lector conectado via HID PASIVO "
                    f"(interface={intf_num}, usage_page=0x{usage_page:04X})"
                )
                return True

            except OSError:
                try:
                    dev.close()
                except Exception:
                    pass
            except Exception:
                try:
                    dev.close()
                except Exception:
                    pass

        logger.error("HID: no se pudo abrir ninguna interfaz.")
        return False

    def _fetch_model_version(self):
        """Obtiene modelo y version del lector tras conectar."""
        try:
            resp = self._send_and_receive(
                RFIDProtocol.CMD_GET_MODEL_VERSION, timeout_ms=1000)
            if resp["success"] and resp["data"]:
                self.model_version = RFIDProtocol.parse_version_from_data(
                    resp["data"])
                logger.info(f"Modelo/Version: {self.model_version}")
        except Exception as e:
            logger.debug(f"No se pudo obtener modelo/version: {e}")

    def disconnect(self):
        """Cierra la conexion de forma segura."""
        self.stop_polling()
        with self._lock:
            if self._device is None:
                return
            try:
                self._device.close()
                logger.info("Lector desconectado.")
            except Exception as e:
                logger.warning(f"Error al cerrar: {e}")
            finally:
                self._device = None
                self._backend = None
                self._command_mode = False
                self._cmd_report_id = 0x03
                self.serial_number = ""
                self.model_version = ""

    @property
    def is_connected(self) -> bool:
        return self._device is not None

    @property
    def in_command_mode(self) -> bool:
        return self._command_mode

    @property
    def backend(self) -> Optional[str]:
        return self._backend

    @property
    def is_polling(self) -> bool:
        return self._polling

    # -------------------------------------------------------------------------
    # Comunicacion de bajo nivel
    # -------------------------------------------------------------------------

    @staticmethod
    def _calc_report_id(frame: bytes) -> int:
        """
        Calcula el Report ID correcto para el RD200.
        El RD200 usa Report ID = longitud del frame de protocolo.
        Esto le indica al lector cuántos bytes del reporte HID debe leer.
        """
        return len(frame)

    def _send_and_receive(self, cmd: int, data: bytes = b"",
                          timeout_ms: int = 2000) -> dict:
        """
        Envia un comando y espera la respuesta.
        El Report ID se calcula dinámicamente según la longitud del frame.
        Retorna el dict parseado de RFIDProtocol.parse_response().
        """
        if not self.is_connected:
            raise ReaderConnectionError("No hay conexion activa.")
        if not self._command_mode:
            raise ReaderProtocolError(
                "El lector esta en modo pasivo, no acepta comandos.")

        frame = RFIDProtocol.build_command(cmd, data)
        report_id = self._calc_report_id(frame)
        report = bytes([report_id]) + frame.ljust(63, b'\x00')

        with self._lock:
            written = self._device.write(list(report))
            logger.debug(
                f"TX (ReportID=0x{report_id:02X}, len={len(frame)}): "
                f"{frame.hex(' ').upper()} [write={written}]")

            response = self._device.read(64, timeout_ms=timeout_ms)

        if not response:
            raise ReaderTimeoutError(
                f"Sin respuesta del lector ({timeout_ms}ms).")

        raw = bytes(response)
        logger.debug(f"RX: {raw.rstrip(b'\\x00').hex(' ').upper()}")
        return RFIDProtocol.parse_response(raw)

    def send_command(self, packet: bytes) -> bytes:
        """
        Envia un paquete HID crudo (para sniffer/config tab).
        packet: bytes del protocolo (sin Report ID — se calcula automáticamente).
        Retorna los bytes crudos de la respuesta.
        """
        if not self.is_connected:
            raise ReaderConnectionError("No hay conexion activa.")

        # Calcular Report ID = longitud del frame de protocolo
        proto_frame = packet.rstrip(b'\x00')
        report_id = self._calc_report_id(proto_frame)

        with self._lock:
            padded = packet[:63].ljust(63, b'\x00')
            to_write = bytes([report_id]) + padded
            self._device.write(list(to_write))
            logger.debug(
                f"TX raw (ReportID=0x{report_id:02X}): "
                f"{proto_frame.hex(' ').upper()}")

            response = self._device.read(64, timeout_ms=2000)
            if not response:
                raise ReaderTimeoutError("Sin respuesta del lector (2000ms).")
            raw = bytes(response)
            logger.debug(f"RX raw: {raw.rstrip(b'\\x00').hex(' ').upper()}")
            return raw

    def send_raw_bytes(self, data: bytes, timeout_ms: int = 2000) -> Optional[bytes]:
        """
        Envia bytes crudos y lee respuesta. Para el sniffer.
        El Report ID se calcula dinámicamente = longitud del frame.
        """
        if not self.is_connected:
            return None
        try:
            proto_frame = data.rstrip(b'\x00')
            report_id = self._calc_report_id(proto_frame)

            with self._lock:
                padded = data[:63].ljust(63, b'\x00')
                to_write = bytes([report_id]) + padded
                self._device.write(list(to_write))
                resp = self._device.read(64, timeout_ms=timeout_ms)
                return bytes(resp) if resp else None
        except Exception as e:
            logger.warning(f"send_raw_bytes error: {e}")
            return None

    # -------------------------------------------------------------------------
    # Operaciones RFID de alto nivel
    # -------------------------------------------------------------------------

    def get_version(self) -> str:
        """Obtiene modelo y version de firmware."""
        if not self._command_mode:
            return self.model_version or "N/A (modo pasivo)"
        try:
            resp = self._send_and_receive(RFIDProtocol.CMD_GET_MODEL_VERSION)
            if resp["success"] and resp["data"]:
                return RFIDProtocol.parse_version_from_data(resp["data"])
            return "N/A"
        except Exception:
            return "N/A"

    def get_serial_number(self) -> str:
        """Obtiene el numero de serie."""
        if self.serial_number:
            return self.serial_number
        if not self._command_mode:
            return "N/A"
        try:
            resp = self._send_and_receive(RFIDProtocol.CMD_GET_SERIAL)
            if resp["success"] and resp["data"]:
                self.serial_number = RFIDProtocol.parse_serial_from_data(
                    resp["data"])
                return self.serial_number
        except Exception:
            pass
        return "N/A"

    def read_card(self, timeout_s: float = 3.0) -> Optional[CardData]:
        """
        Lee el UID de la tarjeta presente.
        En modo comando: envia CMD_READ_TAG_DATA (0x01)
        En modo pasivo: escucha keyboard reports
        """
        if self._command_mode:
            return self._read_card_command(timeout_s)
        return self._read_card_passive(timeout_s)

    def _read_card_command(self, timeout_s: float) -> Optional[CardData]:
        """Lee tarjeta usando comandos del protocolo."""
        try:
            resp = self._send_and_receive(
                RFIDProtocol.CMD_READ_TAG_DATA,
                timeout_ms=int(timeout_s * 1000))

            if resp["success"] and resp["data"]:
                uid = resp["data"].hex().upper()
                uid_decimal = ""
                try:
                    uid_decimal = str(int(uid, 16)).zfill(10)
                except ValueError:
                    uid_decimal = uid

                return CardData(
                    uid=uid,
                    uid_decimal=uid_decimal,
                    card_type="RFID (modo comando)",
                    raw_response=resp["raw"],
                    timestamp=datetime.now().isoformat(),
                    is_valid=True,
                )

            if resp.get("status") == STATUS_NO_CARD:
                return None  # Sin tarjeta, normal

        except ReaderTimeoutError:
            return None
        except Exception as e:
            logger.warning(f"read_card_command: {e}")
        return None

    def _read_card_passive(self, timeout_s: float) -> Optional[CardData]:
        """Lee tarjeta escuchando keyboard reports."""
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            try:
                card = self.try_read_passive()
                if card:
                    return card
            except OSError:
                return None
            time.sleep(0.02)
        return None

    def read_mifare_uid(self) -> Optional[CardData]:
        """Lee UID Mifare (4 bytes) usando CMD 0x11."""
        if not self._command_mode:
            return self.read_card(timeout_s=2.0)
        try:
            resp = self._send_and_receive(RFIDProtocol.CMD_READ_MIFARE_UID)
            if resp["success"] and resp["data"]:
                uid = resp["data"].hex().upper()
                return CardData(
                    uid=uid,
                    uid_decimal=str(int(uid, 16)).zfill(10) if uid else "",
                    card_type="Mifare",
                    raw_response=resp["raw"],
                    timestamp=datetime.now().isoformat(),
                    is_valid=True,
                )
            if resp.get("status") == STATUS_NO_CARD:
                return None
        except Exception as e:
            logger.warning(f"read_mifare_uid: {e}")
        return None

    def read_block(self, block_number: int, key_type: str = "A",
                   sector: int = 0,
                   key: bytes = b'\xFF\xFF\xFF\xFF\xFF\xFF') -> Optional[bytes]:
        """Lee 16 bytes de un bloque Mifare Classic."""
        if not self._command_mode:
            logger.warning("read_block requiere modo comando.")
            return None
        try:
            resp = self._send_and_receive(
                RFIDProtocol.CMD_READ_DATA,
                bytes([0x60 if key_type == "A" else 0x61]) + key +
                bytes([sector, block_number]))
            if resp["success"] and resp["data"]:
                return bytes(resp["data"][:16])
        except Exception as e:
            logger.warning(f"read_block({sector}/{block_number}): {e}")
        return None

    def write_block(self, block_number: int, data: bytes,
                    key_type: str = "A", sector: int = 0,
                    key: bytes = b'\xFF\xFF\xFF\xFF\xFF\xFF') -> bool:
        """Escribe 16 bytes en un bloque Mifare Classic."""
        if not self._command_mode:
            raise ReaderWriteError("Escribir requiere modo comando.")
        if len(data) != 16:
            raise ValueError("Los datos deben ser exactamente 16 bytes.")
        try:
            resp = self._send_and_receive(
                RFIDProtocol.CMD_WRITE_DATA,
                bytes([0x60 if key_type == "A" else 0x61]) + key +
                bytes([sector, block_number]) + data)
            return resp["success"]
        except Exception as e:
            raise ReaderWriteError(f"Error escribiendo bloque {block_number}: {e}")

    def ntag_read(self, block: int) -> Optional[bytes]:
        """Lee 16 bytes de un bloque NTAG/Ultralight."""
        if not self._command_mode:
            return None
        try:
            resp = self._send_and_receive(
                RFIDProtocol.CMD_NTAG_READ,
                bytes([0x00, 0x00, block]))
            if resp["success"] and resp["data"]:
                return bytes(resp["data"][:16])
        except Exception as e:
            logger.warning(f"ntag_read({block}): {e}")
        return None

    def ntag_write(self, block: int, data: bytes) -> bool:
        """Escribe 16 bytes en un bloque NTAG/Ultralight."""
        if not self._command_mode:
            raise ReaderWriteError("Escribir requiere modo comando.")
        if len(data) != 16:
            raise ValueError("Los datos deben ser exactamente 16 bytes.")
        try:
            resp = self._send_and_receive(
                RFIDProtocol.CMD_NTAG_WRITE,
                bytes([0x00, 0x00, block]) + data)
            return resp["success"]
        except Exception as e:
            raise ReaderWriteError(f"Error escribiendo NTAG bloque {block}: {e}")

    # -------------------------------------------------------------------------
    # Configuracion del lector
    # -------------------------------------------------------------------------

    def set_usb_mode(self, mode: int) -> bool:
        """Cambia el modo USB (keyboard/HID/auto-send)."""
        if not self._command_mode:
            return False
        try:
            resp = self._send_and_receive(
                RFIDProtocol.CMD_SET_PARAMETER,
                bytes([RFIDProtocol.PARAM_USB_MODE, mode]))
            return resp["success"]
        except Exception:
            return False

    def get_usb_mode(self) -> Optional[int]:
        """Obtiene el modo USB actual."""
        if not self._command_mode:
            return None
        try:
            resp = self._send_and_receive(
                RFIDProtocol.CMD_SET_PARAMETER,
                bytes([RFIDProtocol.PARAM_USB_MODE]))
            if resp["success"] and resp["data"]:
                # DATA = [PARAM_ID, mode_value]
                return resp["data"][-1] if len(resp["data"]) >= 1 else None
        except Exception:
            pass
        return None

    def reader_action(self, action: int) -> bool:
        """Envia un comando de accion (beep, LED, etc.)."""
        if not self._command_mode:
            return False
        try:
            resp = self._send_and_receive(
                RFIDProtocol.CMD_READER_ACTION, bytes([action]))
            return resp["success"]
        except Exception:
            return False

    def beep(self) -> bool:
        """Beep corto."""
        return self.reader_action(RFIDProtocol.ACTION_BEEP_05S)

    def beep_green(self) -> bool:
        """Beep + LED verde."""
        return self.reader_action(RFIDProtocol.ACTION_BEEP_GREEN_05S)

    def set_buzzer(self, enable: bool) -> bool:
        """Compatibilidad: beep si enable=True."""
        if enable:
            return self.beep()
        return True

    def set_led(self, color: str, state: bool) -> bool:
        """Compatibilidad: LED verde on/off."""
        if state:
            return self.reader_action(RFIDProtocol.ACTION_GREEN_LIGHT_1S)
        return self.reader_action(RFIDProtocol.ACTION_LIGHT_OFF_1S)

    def reboot(self) -> bool:
        """Reinicia el lector."""
        if not self._command_mode:
            return False
        try:
            resp = self._send_and_receive(
                RFIDProtocol.CMD_SYSTEM, bytes([0x01]))
            return resp["success"]
        except Exception:
            return False

    def factory_reset(self) -> bool:
        """Restaura configuracion de fabrica."""
        if not self._command_mode:
            return False
        try:
            resp = self._send_and_receive(
                RFIDProtocol.CMD_SYSTEM, bytes([0x02]))
            return resp["success"]
        except Exception:
            return False

    def set_read_card_mode(self, mode_byte: int) -> bool:
        """Configura modo de lectura (auto, beep, LED, etc.)."""
        if not self._command_mode:
            return False
        try:
            resp = self._send_and_receive(
                RFIDProtocol.CMD_SET_PARAMETER,
                bytes([RFIDProtocol.PARAM_READ_CARD_MODE, mode_byte]))
            return resp["success"]
        except Exception:
            return False

    def set_keyboard_format(self, uid_format: int, reverse_uid: int,
                            add_type: int) -> bool:
        """Configura formato de emulacion de teclado."""
        if not self._command_mode:
            return False
        try:
            resp = self._send_and_receive(
                RFIDProtocol.CMD_SET_PARAMETER,
                bytes([RFIDProtocol.PARAM_KEYBOARD_FORMAT,
                       uid_format, reverse_uid, add_type]))
            return resp["success"]
        except Exception:
            return False

    # -------------------------------------------------------------------------
    # Lectura de configuración completa
    # -------------------------------------------------------------------------

    def get_all_config(self) -> dict:
        """
        Lee TODOS los parámetros de configuración del lector.
        Returns dict with all readable parameters.
        """
        config = {}
        if not self._command_mode:
            return config

        # USB Mode
        try:
            resp = self._send_and_receive(
                RFIDProtocol.CMD_SET_PARAMETER,
                bytes([RFIDProtocol.PARAM_USB_MODE]))
            if resp["success"] and resp["data"] and len(resp["data"]) >= 2:
                config["usb_mode"] = resp["data"][1]
        except Exception:
            pass

        # Read Card Mode
        try:
            resp = self._send_and_receive(
                RFIDProtocol.CMD_SET_PARAMETER,
                bytes([RFIDProtocol.PARAM_READ_CARD_MODE]))
            if resp["success"] and resp["data"] and len(resp["data"]) >= 2:
                config["read_card_mode"] = resp["data"][1]
        except Exception:
            pass

        # Keyboard Format
        try:
            resp = self._send_and_receive(
                RFIDProtocol.CMD_SET_PARAMETER,
                bytes([RFIDProtocol.PARAM_KEYBOARD_FORMAT]))
            if resp["success"] and resp["data"] and len(resp["data"]) >= 4:
                config["kbd_format"] = resp["data"][1]
                config["kbd_reverse"] = resp["data"][2]
                config["kbd_add_type"] = resp["data"][3]
        except Exception:
            pass

        # Postponement Time
        try:
            resp = self._send_and_receive(
                RFIDProtocol.CMD_SET_PARAMETER,
                bytes([RFIDProtocol.PARAM_POSTPONEMENT_TIME]))
            if resp["success"] and resp["data"] and len(resp["data"]) >= 2:
                config["postponement_time"] = resp["data"][1]
        except Exception:
            pass

        # Same Card Time
        try:
            resp = self._send_and_receive(
                RFIDProtocol.CMD_SET_PARAMETER,
                bytes([RFIDProtocol.PARAM_SAME_CARD_TIME]))
            if resp["success"] and resp["data"] and len(resp["data"]) >= 2:
                config["same_card_time"] = resp["data"][1]
        except Exception:
            pass

        # Keypad Delay
        try:
            resp = self._send_and_receive(
                RFIDProtocol.CMD_SET_PARAMETER,
                bytes([RFIDProtocol.PARAM_KEYPAD_DELAY]))
            if resp["success"] and resp["data"] and len(resp["data"]) >= 2:
                config["keypad_delay"] = resp["data"][1]
        except Exception:
            pass

        # Mifare Sector Setting
        try:
            resp = self._send_and_receive(
                RFIDProtocol.CMD_SET_PARAMETER,
                bytes([RFIDProtocol.PARAM_MIFARE_SECTOR_SETTING]))
            if resp["success"] and resp["data"] and len(resp["data"]) >= 2:
                config["mifare_sector"] = resp["data"][1]
        except Exception:
            pass

        # Serial Number & Version
        config["serial_number"] = self.serial_number or ""
        config["model_version"] = self.model_version or ""

        return config

    def apply_config_profile(self, profile: dict) -> dict:
        """
        Aplica un perfil de configuración completo al lector.
        Returns dict of {param_name: success_bool}.
        """
        results = {}
        if not self._command_mode:
            return results

        # USB Mode
        if "usb_mode" in profile:
            results["usb_mode"] = self.set_usb_mode(profile["usb_mode"])

        # Read Card Mode
        if "read_card_mode" in profile:
            results["read_card_mode"] = self.set_read_card_mode(profile["read_card_mode"])

        # Keyboard Format
        if all(k in profile for k in ("kbd_format", "kbd_reverse", "kbd_add_type")):
            results["keyboard_format"] = self.set_keyboard_format(
                profile["kbd_format"], profile["kbd_reverse"], profile["kbd_add_type"])

        # Postponement Time
        if "postponement_time" in profile:
            try:
                resp = self._send_and_receive(
                    RFIDProtocol.CMD_SET_PARAMETER,
                    bytes([RFIDProtocol.PARAM_POSTPONEMENT_TIME, profile["postponement_time"]]))
                results["postponement_time"] = resp["success"]
            except Exception:
                results["postponement_time"] = False

        # Same Card Time
        if "same_card_time" in profile:
            try:
                resp = self._send_and_receive(
                    RFIDProtocol.CMD_SET_PARAMETER,
                    bytes([RFIDProtocol.PARAM_SAME_CARD_TIME, profile["same_card_time"]]))
                results["same_card_time"] = resp["success"]
            except Exception:
                results["same_card_time"] = False

        # Keypad Delay
        if "keypad_delay" in profile:
            try:
                resp = self._send_and_receive(
                    RFIDProtocol.CMD_SET_PARAMETER,
                    bytes([RFIDProtocol.PARAM_KEYPAD_DELAY, profile["keypad_delay"]]))
                results["keypad_delay"] = resp["success"]
            except Exception:
                results["keypad_delay"] = False

        # Mifare Sector
        if "mifare_sector" in profile:
            try:
                resp = self._send_and_receive(
                    RFIDProtocol.CMD_SET_PARAMETER,
                    bytes([RFIDProtocol.PARAM_MIFARE_SECTOR_SETTING, profile["mifare_sector"]]))
                results["mifare_sector"] = resp["success"]
            except Exception:
                results["mifare_sector"] = False

        return results

    def get_keyboard_format(self) -> Optional[dict]:
        """Lee la configuración de formato de teclado."""
        if not self._command_mode:
            return None
        try:
            resp = self._send_and_receive(
                RFIDProtocol.CMD_SET_PARAMETER,
                bytes([RFIDProtocol.PARAM_KEYBOARD_FORMAT]))
            if resp["success"] and resp["data"] and len(resp["data"]) >= 4:
                return {
                    "format": resp["data"][1],
                    "reverse": resp["data"][2],
                    "add_type": resp["data"][3],
                }
        except Exception:
            pass
        return None

    def get_read_card_mode(self) -> Optional[int]:
        """Lee el modo de lectura de tarjeta."""
        if not self._command_mode:
            return None
        try:
            resp = self._send_and_receive(
                RFIDProtocol.CMD_SET_PARAMETER,
                bytes([RFIDProtocol.PARAM_READ_CARD_MODE]))
            if resp["success"] and resp["data"] and len(resp["data"]) >= 2:
                return resp["data"][1]
        except Exception:
            pass
        return None

    def set_postponement_time(self, value: int) -> bool:
        """Configura el tiempo de postponement (unidad: 10ms)."""
        if not self._command_mode:
            return False
        try:
            resp = self._send_and_receive(
                RFIDProtocol.CMD_SET_PARAMETER,
                bytes([RFIDProtocol.PARAM_POSTPONEMENT_TIME, value]))
            return resp["success"]
        except Exception:
            return False

    def set_same_card_time(self, value: int) -> bool:
        """Configura el tiempo de misma tarjeta (unidad: 100ms)."""
        if not self._command_mode:
            return False
        try:
            resp = self._send_and_receive(
                RFIDProtocol.CMD_SET_PARAMETER,
                bytes([RFIDProtocol.PARAM_SAME_CARD_TIME, value]))
            return resp["success"]
        except Exception:
            return False

    def set_keypad_delay(self, value: int) -> bool:
        """Configura el delay de teclado (ms)."""
        if not self._command_mode:
            return False
        try:
            resp = self._send_and_receive(
                RFIDProtocol.CMD_SET_PARAMETER,
                bytes([RFIDProtocol.PARAM_KEYPAD_DELAY, value]))
            return resp["success"]
        except Exception:
            return False

    def stop_sense(self) -> bool:
        """Detiene la detección de tarjetas."""
        return self.reader_action(RFIDProtocol.ACTION_STOP_SENSE)

    def start_sense(self) -> bool:
        """Inicia la detección de tarjetas."""
        return self.reader_action(RFIDProtocol.ACTION_START_SENSE)

    # Compatibility aliases
    def set_keyboard_emulation(self, enable: bool) -> bool:
        if enable:
            return self.set_usb_mode(RFIDProtocol.USB_HID_KEYBOARD)
        return self.set_usb_mode(RFIDProtocol.USB_HID_DEVICE)

    def set_output_format(self, format_code: str) -> bool:
        return False  # Requires specific keyboard format params

    def save_config(self) -> bool:
        return True  # RD200 saves immediately

    def apply_reader_config(self, beep=None, keyboard_emulation=None,
                            id_format=None, save=True) -> dict:
        results = {}
        if keyboard_emulation is not None:
            results["keyboard_emulation"] = self.set_keyboard_emulation(
                keyboard_emulation)
        return results

    # -------------------------------------------------------------------------
    # Modo pasivo (keyboard reports)
    # -------------------------------------------------------------------------

    # HID Usage ID -> caracter
    HID_KEYCODE_MAP = {
        0x04: ('a', 'A'), 0x05: ('b', 'B'), 0x06: ('c', 'C'), 0x07: ('d', 'D'),
        0x08: ('e', 'E'), 0x09: ('f', 'F'), 0x0A: ('g', 'G'), 0x0B: ('h', 'H'),
        0x0C: ('i', 'I'), 0x0D: ('j', 'J'), 0x0E: ('k', 'K'), 0x0F: ('l', 'L'),
        0x10: ('m', 'M'), 0x11: ('n', 'N'), 0x12: ('o', 'O'), 0x13: ('p', 'P'),
        0x14: ('q', 'Q'), 0x15: ('r', 'R'), 0x16: ('s', 'S'), 0x17: ('t', 'T'),
        0x18: ('u', 'U'), 0x19: ('v', 'V'), 0x1A: ('w', 'W'), 0x1B: ('x', 'X'),
        0x1C: ('y', 'Y'), 0x1D: ('z', 'Z'),
        0x1E: ('1', '!'), 0x1F: ('2', '@'), 0x20: ('3', '#'), 0x21: ('4', '$'),
        0x22: ('5', '%'), 0x23: ('6', '^'), 0x24: ('7', '&'), 0x25: ('8', '*'),
        0x26: ('9', '('), 0x27: ('0', ')'),
        0x28: ('\n', '\n'), 0x2C: (' ', ' '), 0x2B: ('\t', '\t'),
        0x2D: ('-', '_'), 0x2E: ('=', '+'), 0x36: (',', '<'), 0x37: ('.', '>'),
    }

    def try_read_passive(self) -> Optional[CardData]:
        """
        Intento unico de lectura pasiva (keyboard report).
        Solo para modo pasivo.
        """
        if not self._device:
            return None
        try:
            with self._lock:
                data = self._device.read(64, timeout_ms=self.READ_TIMEOUT_MS)
        except OSError:
            raise

        if not data:
            return None

        report = bytes(data)
        uid = self._process_keyboard_report(report)
        if uid is None:
            return None

        uid_decimal = ""
        try:
            uid_decimal = str(int(uid, 16)).zfill(10)
        except ValueError:
            uid_decimal = uid

        return CardData(
            uid=uid,
            uid_decimal=uid_decimal,
            card_type="RFID (teclado)",
            raw_response=report,
            timestamp=datetime.now().isoformat(),
            is_valid=True,
        )

    def _process_keyboard_report(self, report: bytes) -> Optional[str]:
        """Procesa keyboard report, acumula chars, retorna UID al detectar Enter."""
        if len(report) < 3:
            return None

        modifier = report[0]
        shift = bool(modifier & 0x22)

        for i in range(2, min(len(report), 8)):
            keycode = report[i]
            if keycode == 0x00:
                continue
            if keycode in self.HID_KEYCODE_MAP:
                normal, shifted = self.HID_KEYCODE_MAP[keycode]
                ch = shifted if shift else normal
                if ch == '\n':
                    if self._uid_buffer:
                        uid = "".join(self._uid_buffer).strip().upper()
                        self._uid_buffer.clear()
                        return uid
                    self._uid_buffer.clear()
                elif ch not in ('\t', ' ') or self._uid_buffer:
                    self._uid_buffer.append(ch)

        return None

    # -------------------------------------------------------------------------
    # Polling (background thread)
    # -------------------------------------------------------------------------

    def start_polling(self, callback: Callable[[CardData], None],
                      on_error: Optional[Callable[[Exception], None]] = None):
        """
        Inicia polling en segundo plano.
        Modo comando: envia CMD_READ_TAG_DATA periodicamente
        Modo pasivo: escucha keyboard reports
        """
        if self._polling:
            return

        self._polling = True
        self._uid_buffer.clear()
        self._poll_thread = threading.Thread(
            target=self._poll_loop,
            args=(callback, on_error),
            daemon=True,
            name="RFIDPollingThread"
        )
        self._poll_thread.start()
        mode = "comando" if self._command_mode else "pasivo"
        logger.info(f"Polling iniciado (modo {mode}).")

    def stop_polling(self):
        self._polling = False
        if self._poll_thread and self._poll_thread.is_alive():
            self._poll_thread.join(timeout=2.0)
        self._poll_thread = None
        self._last_uid = None
        self._uid_buffer.clear()
        logger.info("Polling detenido.")

    def _poll_loop(self, callback: Callable, on_error: Optional[Callable]):
        """Loop de polling segun el modo de operacion."""
        consecutive_errors = 0

        while self._polling:
            try:
                if not self.is_connected:
                    raise ReaderConnectionError("Lector desconectado.")

                card = None
                if self._command_mode:
                    card = self._read_card_command(timeout_s=1.0)
                else:
                    card = self.try_read_passive()

                consecutive_errors = 0

                if card and card.uid != self._last_uid:
                    self._last_uid = card.uid
                    callback(card)

                time.sleep(self.POLL_INTERVAL)

            except OSError as e:
                consecutive_errors += 1
                if consecutive_errors >= self.MAX_CONSECUTIVE_ERRORS:
                    logger.error(
                        f"Polling: {consecutive_errors} errores → {e}")
                    with self._lock:
                        self._device = None
                        self._backend = None
                    if on_error:
                        on_error(ReaderConnectionError(str(e)))
                    break
                time.sleep(0.5)

            except (ReaderConnectionError, ReaderTimeoutError) as e:
                consecutive_errors += 1
                if consecutive_errors >= self.MAX_CONSECUTIVE_ERRORS:
                    logger.error(f"Polling: {e}")
                    if on_error:
                        on_error(e)
                    break
                time.sleep(0.5)

    # -------------------------------------------------------------------------
    # Diagnostico
    # -------------------------------------------------------------------------

    @staticmethod
    def list_hid_devices() -> list:
        try:
            import hid  # type: ignore
            return hid.enumerate()
        except ImportError:
            return []

    @staticmethod
    def find_reader() -> Optional[dict]:
        try:
            import hid  # type: ignore
            for d in hid.enumerate():
                if d["vendor_id"] == ReaderManager.VID \
                   and d["product_id"] == ReaderManager.PID:
                    return d
        except ImportError:
            pass
        return None

    @staticmethod
    def enumerate_reader_interfaces() -> List[dict]:
        """Lista todas las interfaces HID del lector."""
        try:
            import hid  # type: ignore
            return [
                d for d in hid.enumerate()
                if d["vendor_id"] == ReaderManager.VID
                and d["product_id"] == ReaderManager.PID
            ]
        except ImportError:
            return []
