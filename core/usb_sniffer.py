# =============================================================================
# core/usb_sniffer.py
#
# Monitor / Sniffer HID integrado para el lector RD200-M1-G.
#
# Dos modos de operación:
#
#   1. MODO MONITOR (listen-only):
#      Escucha continuamente el endpoint IN del lector y captura todo lo
#      que el dispositivo envía al host (p.ej. datos de tarjeta en modo
#      emulación de teclado, respuestas espontáneas, etc.).
#
#   2. MODO INTERACTIVO (send + receive):
#      Envía tramas hex crudas y captura la respuesta con timestamp.
#      Perfecto para explorar el protocolo del lector.
#
# Todas las capturas se almacenan en un buffer con timestamp, dirección
# (TX/RX), y datos crudos para posterior exportación.
# =============================================================================

import time
import threading
import logging
import csv
import io
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Callable, List

logger = logging.getLogger(__name__)


# =============================================================================
# Modelo de datos
# =============================================================================

@dataclass
class SnifferPacket:
    """Un paquete capturado por el sniffer."""
    timestamp: str              # ISO format con microsegundos
    direction: str              # "TX" (host→device) o "RX" (device→host)
    raw_bytes: bytes            # Payload crudo (trama HID completa)
    protocol_bytes: bytes = b"" # Solo bytes del protocolo RD200 (sin HID overhead)
    hex_display: str = ""       # Versión formateada para mostrar en la GUI
    ascii_display: str = ""     # Interpretación ASCII printable
    notes: str = ""             # Anotación del usuario o auto-parse
    report_id: int = -1         # Report ID HID (-1 = desconocido)

    def __post_init__(self):
        if not self.protocol_bytes:
            self.protocol_bytes = self.raw_bytes
        if not self.hex_display:
            self.hex_display = self.protocol_bytes.hex(" ").upper() if self.protocol_bytes else ""
        if not self.ascii_display:
            display_bytes = self.protocol_bytes or self.raw_bytes
            self.ascii_display = "".join(
                chr(b) if 32 <= b < 127 else "." for b in display_bytes
            )


# =============================================================================
# Sniffer Engine
# =============================================================================

class USBSniffer:
    """
    Motor de captura HID. Opera independientemente del ReaderManager
    para no interferir con el polling normal de la app.

    Puede compartir la misma conexión HID del ReaderManager (pasando
    el device ya abierto) o abrir su propia conexión exclusiva.

    Uso típico:
        sniffer = USBSniffer()
        sniffer.start_capture(on_packet=my_callback)
        ...
        sniffer.send_raw(bytes.fromhex("02 01 25 24 03"))
        ...
        sniffer.stop_capture()
        sniffer.export_csv("captura.csv")
    """

    MAX_BUFFER_SIZE = 10_000   # Máximo de paquetes en el buffer

    def __init__(self):
        self._device = None
        self._backend: Optional[str] = None
        self._lock = threading.Lock()
        self._capturing = False
        self._sending = False  # Pausa la captura durante send_raw()
        self._capture_thread: Optional[threading.Thread] = None

        # Buffer de capturas
        self._packets: List[SnifferPacket] = []
        self._packet_count = 0

        # Callbacks
        self._on_packet: Optional[Callable[[SnifferPacket], None]] = None

    # -------------------------------------------------------------------------
    # Conexión
    # -------------------------------------------------------------------------

    def attach_device(self, device, backend: str, report_id: int = 0x03):
        """
        Reutiliza una conexión HID ya abierta (del ReaderManager).

        Args:
            device: El objeto hid.device() o usb.core.Device ya abierto.
            backend: "hid" o "pyusb".
            report_id: Report ID para enviar comandos (RD200 usa 0x03).
        """
        self._device = device
        self._backend = backend
        self._report_id = report_id
        logger.info(f"Sniffer: device attached (backend={backend}, reportID=0x{report_id:02X})")

    def open_exclusive(self, vid: int = 0x0E6A, pid: int = 0x0317) -> bool:
        """
        Abre su propia conexión exclusiva al lector.
        Útil si no quieres interferir con el ReaderManager.

        Returns:
            True si la conexión se abrió correctamente.
        """
        try:
            import hid  # type: ignore
            dev = hid.device()
            dev.open(vid, pid)
            dev.set_nonblocking(True)
            self._device = dev
            self._backend = "hid"
            logger.info(f"Sniffer: conexión exclusiva abierta "
                        f"(VID={vid:#06x}, PID={pid:#06x})")
            return True
        except Exception as e:
            logger.error(f"Sniffer: no se pudo abrir conexión exclusiva → {e}")
            return False

    def close(self):
        """Cierra la conexión exclusiva (no afecta si se usó attach_device)."""
        self.stop_capture()
        # Solo cerrar si abrimos nosotros
        if self._device is not None and self._backend == "hid":
            try:
                self._device.close()
            except Exception:
                pass
        self._device = None

    @property
    def is_attached(self) -> bool:
        return self._device is not None

    # -------------------------------------------------------------------------
    # Captura pasiva (escuchar IN del dispositivo)
    # -------------------------------------------------------------------------

    def start_capture(self, on_packet: Optional[Callable[[SnifferPacket], None]] = None,
                      read_timeout_ms: int = 100):
        """
        Inicia la captura pasiva en un hilo dedicado.
        Escucha continuamente los datos que el lector envía al host.

        Args:
            on_packet: Callback invocado por cada paquete capturado (desde el hilo
                       de captura — usa after() para actualizar la GUI).
            read_timeout_ms: Timeout de lectura HID por iteración.
        """
        if self._capturing:
            logger.warning("Sniffer: la captura ya está activa.")
            return
        if not self.is_attached:
            logger.error("Sniffer: no hay dispositivo conectado.")
            return

        self._on_packet = on_packet
        self._capturing = True
        self._capture_thread = threading.Thread(
            target=self._capture_loop,
            args=(read_timeout_ms,),
            daemon=True,
            name="SnifferCaptureThread"
        )
        self._capture_thread.start()
        logger.info("Sniffer: captura iniciada.")

    def stop_capture(self):
        """Detiene la captura pasiva."""
        self._capturing = False
        if self._capture_thread and self._capture_thread.is_alive():
            self._capture_thread.join(timeout=2.0)
        self._capture_thread = None
        logger.info("Sniffer: captura detenida.")

    @property
    def is_capturing(self) -> bool:
        return self._capturing

    def _capture_loop(self, read_timeout_ms: int):
        """Loop de captura: lee continuamente del endpoint IN del dispositivo."""
        logger.debug("Sniffer capture loop started.")
        consecutive_errors = 0
        MAX_ERRORS = 10

        while self._capturing:
            # Pausar durante send_raw() para evitar race condition
            if self._sending:
                time.sleep(0.01)
                continue

            try:
                data = self._read_device(read_timeout_ms)
                if data:
                    consecutive_errors = 0  # Reset on success
                    proto, rid = self.extract_protocol_frame(data, "RX")
                    pkt = SnifferPacket(
                        timestamp=datetime.now().strftime("%H:%M:%S.%f")[:-3],
                        direction="RX",
                        raw_bytes=data,
                        protocol_bytes=proto,
                        report_id=rid,
                        notes=self._auto_annotate(data, "RX"),
                    )
                    self._record_packet(pkt)
                else:
                    consecutive_errors = 0  # Timeout is normal, not an error
            except OSError as e:
                if not self._capturing:
                    break
                consecutive_errors += 1
                if consecutive_errors >= MAX_ERRORS:
                    logger.error(
                        f"Sniffer: {consecutive_errors} errores consecutivos, "
                        f"deteniendo captura → {e}")
                    self._capturing = False
                    # Notify via a special packet
                    err_pkt = SnifferPacket(
                        timestamp=datetime.now().strftime("%H:%M:%S.%f")[:-3],
                        direction="RX",
                        raw_bytes=b"",
                        hex_display="[DEVICE ERROR - captura detenida]",
                        notes=f"Circuit breaker: {consecutive_errors} errores → {e}",
                    )
                    self._record_packet(err_pkt)
                    break
                time.sleep(0.5)
            except Exception as e:
                if self._capturing:
                    logger.warning(f"Sniffer: error en captura → {e}")
                    time.sleep(0.5)

    def _read_device(self, timeout_ms: int) -> Optional[bytes]:
        """Lee datos del dispositivo. Devuelve None si no hay datos."""
        with self._lock:
            if self._backend == "hid":
                raw = self._device.read(64, timeout_ms=timeout_ms)
                if raw:
                    return bytes(raw)
                return None
            elif self._backend == "pyusb":
                import usb.core  # type: ignore
                import usb.util  # type: ignore
                cfg = self._device.get_active_configuration()
                intf = cfg[(0, 0)]
                ep_in = usb.util.find_descriptor(
                    intf, custom_match=lambda e:
                    usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_IN
                )
                if ep_in is None:
                    return None
                try:
                    data = ep_in.read(64, timeout=timeout_ms)
                    return bytes(data)
                except usb.core.USBTimeoutError:
                    return None
        return None

    # -------------------------------------------------------------------------
    # Envío de tramas crudas (modo interactivo)
    # -------------------------------------------------------------------------

    def send_raw(self, data: bytes, wait_response: bool = True,
                 timeout_ms: int = 1000) -> Optional[SnifferPacket]:
        """
        Envía una trama cruda al lector y opcionalmente espera la respuesta.

        Args:
            data: Bytes a enviar (se padea automáticamente a 64 bytes).
            wait_response: Si True, espera y retorna la respuesta.
            timeout_ms: Timeout en ms para esperar la respuesta.

        Returns:
            SnifferPacket con la respuesta, o None si wait_response=False
            o si hubo timeout.
        """
        if not self.is_attached:
            raise ConnectionError("Sniffer: no hay dispositivo conectado.")

        # Pausar la captura para evitar race condition
        self._sending = True
        time.sleep(0.05)  # Dar tiempo al capture loop para pausarse

        try:
            return self._send_raw_locked(data, wait_response, timeout_ms)
        finally:
            self._sending = False

    def _send_raw_locked(self, data: bytes, wait_response: bool,
                         timeout_ms: int) -> Optional[SnifferPacket]:
        """Envío atómico: write + read bajo el mismo lock."""
        # Preparar TX packet
        proto_tx, _ = self.extract_protocol_frame(data, "TX")
        tx_pkt = SnifferPacket(
            timestamp=datetime.now().strftime("%H:%M:%S.%f")[:-3],
            direction="TX",
            raw_bytes=data,
            protocol_bytes=proto_tx,
            notes=self._auto_annotate(data, "TX"),
        )

        rx_data = None

        with self._lock:
            # === ENVIAR ===
            if self._backend == "hid":
                # RD200: Report ID = longitud del frame de protocolo
                proto_frame = data.rstrip(b'\x00')
                report_id = len(proto_frame) if len(proto_frame) > 0 else getattr(self, '_report_id', 0x03)
                padded = data.ljust(63, b'\x00')  # 63 bytes de datos
                to_write = list(bytes([report_id]) + padded)
                written = self._device.write(to_write)
                logger.debug(
                    f"Sniffer TX (RID=0x{report_id:02X}, wrote={written}): "
                    f"{data.hex(' ').upper()}")
            elif self._backend == "pyusb":
                import usb.util  # type: ignore
                padded = data.ljust(64, b'\x00')
                cfg = self._device.get_active_configuration()
                intf = cfg[(0, 0)]
                ep_out = usb.util.find_descriptor(
                    intf, custom_match=lambda e:
                    usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT
                )
                if ep_out:
                    ep_out.write(padded, timeout=500)

            # === LEER RESPUESTA (bajo el mismo lock) ===
            if wait_response:
                response = self._device.read(64, timeout_ms=timeout_ms)
                if response:
                    rx_data = bytes(response)
                    logger.debug(
                        f"Sniffer RX: {rx_data.rstrip(b'\\x00').hex(' ').upper()}")

        # Registrar TX
        self._record_packet(tx_pkt)

        if not wait_response:
            return None

        if rx_data:
            proto_rx, rid = self.extract_protocol_frame(rx_data, "RX")
            rx_pkt = SnifferPacket(
                timestamp=datetime.now().strftime("%H:%M:%S.%f")[:-3],
                direction="RX",
                raw_bytes=rx_data,
                protocol_bytes=proto_rx,
                report_id=rid,
                notes=self._auto_annotate(rx_data, "RX"),
            )
            self._record_packet(rx_pkt)
            return rx_pkt

        # Timeout
        no_resp = SnifferPacket(
            timestamp=datetime.now().strftime("%H:%M:%S.%f")[:-3],
            direction="RX",
            raw_bytes=b"",
            hex_display="[TIMEOUT - sin respuesta]",
            notes=f"Timeout tras {timeout_ms}ms",
        )
        self._record_packet(no_resp)
        return no_resp

    # -------------------------------------------------------------------------
    # Buffer y gestión de paquetes
    # -------------------------------------------------------------------------

    def _record_packet(self, pkt: SnifferPacket):
        """Añade un paquete al buffer y notifica al callback."""
        self._packets.append(pkt)
        self._packet_count += 1

        # Limitar tamaño del buffer
        if len(self._packets) > self.MAX_BUFFER_SIZE:
            self._packets = self._packets[-self.MAX_BUFFER_SIZE:]

        if self._on_packet:
            try:
                self._on_packet(pkt)
            except Exception as e:
                logger.warning(f"Sniffer: error en callback on_packet → {e}")

    @property
    def packets(self) -> List[SnifferPacket]:
        return list(self._packets)

    @property
    def packet_count(self) -> int:
        return self._packet_count

    def clear_buffer(self):
        """Limpia el buffer de capturas."""
        self._packets.clear()
        self._packet_count = 0

    # -------------------------------------------------------------------------
    # Exportación
    # -------------------------------------------------------------------------

    def export_csv(self, filepath: str):
        """
        Exporta todas las capturas a un archivo CSV.

        Formato:
          Nº, Timestamp, Dir, Hex, ASCII, Notas
        """
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["#", "Timestamp", "Direction", "Hex Data", "ASCII", "Notes"])
            for i, pkt in enumerate(self._packets, start=1):
                writer.writerow([
                    i,
                    pkt.timestamp,
                    pkt.direction,
                    pkt.hex_display,
                    pkt.ascii_display,
                    pkt.notes,
                ])
        logger.info(f"Sniffer: {len(self._packets)} paquetes exportados a '{filepath}'")

    def export_text(self) -> str:
        """
        Exporta las capturas como texto plano formateado (para copiar al portapapeles).
        """
        lines = []
        lines.append(f"{'#':>5}  {'Time':<12}  {'Dir':>3}  {'Protocol Hex':<50}  Notes")
        lines.append("-" * 90)
        for i, pkt in enumerate(self._packets, start=1):
            proto_hex = pkt.protocol_bytes.hex(" ").upper() if pkt.protocol_bytes else pkt.hex_display
            lines.append(
                f"{i:>5}  {pkt.timestamp:<12}  {pkt.direction:>3}  {proto_hex:<50}  {pkt.notes}"
            )
        return "\n".join(lines)

    def export_python_snippet(self) -> str:
        """
        Genera un fragmento de Python listo para copiar en rfid_protocol.py
        con los comandos capturados como constantes bytes.fromhex().
        """
        lines = [
            "# ===========================================",
            "# Tramas capturadas con el Sniffer integrado",
            "# Copia estas líneas a core/rfid_protocol.py",
            "# ===========================================",
            "",
        ]
        tx_count = 0
        for i, pkt in enumerate(self._packets):
            if pkt.direction == "TX" and pkt.raw_bytes:
                tx_count += 1
                trimmed = pkt.raw_bytes.rstrip(b'\x00')
                hex_str = trimmed.hex(" ").upper()
                lines.append(f"# Paquete TX #{tx_count} @ {pkt.timestamp}")
                if pkt.notes:
                    lines.append(f"# Nota: {pkt.notes}")
                lines.append(f'CMD_{tx_count:03d} = bytes.fromhex("{trimmed.hex()}")')
                lines.append("")

        if tx_count == 0:
            lines.append("# No se encontraron paquetes TX en la captura.")

        return "\n".join(lines)

    # -------------------------------------------------------------------------
    # Extracción de protocolo limpio desde trama HID
    # -------------------------------------------------------------------------

    @staticmethod
    def extract_protocol_frame(raw: bytes, direction: str) -> tuple:
        """
        Extrae la trama del protocolo RD200 de un frame HID crudo.

        En RX, el frame HID puede contener:
          [ReportID] [STX=02] [LEN] [CMD] [STATUS] {DATA} [basura/padding]

        En TX, el usuario envía solo bytes de protocolo (ya limpios).

        Returns:
            (protocol_bytes, report_id)
            protocol_bytes: solo los bytes del protocolo RD200
            report_id: Report ID HID encontrado (-1 si no hay)
        """
        if not raw:
            return b"", -1

        trimmed = raw.rstrip(b'\x00')
        if not trimmed:
            return b"", -1

        # Buscar STX=0x02 en las primeras posiciones
        report_id = -1
        stx_offset = -1
        for i in range(min(4, len(trimmed))):
            if trimmed[i] == 0x02:
                stx_offset = i
                if i > 0:
                    report_id = trimmed[0]
                break

        if stx_offset < 0:
            return trimmed, report_id  # No es trama RD200

        # Calcular el final de la trama de protocolo
        if len(trimmed) > stx_offset + 1:
            msg_len = trimmed[stx_offset + 1]

            if msg_len == 0 and direction == "RX":
                # Modo HID: LEN=0x00, la trama real termina al final de datos útiles
                # Pero puede haber basura al final (modelo del lector, etc.)
                # Usamos el CMD para determinar el largo esperado
                if len(trimmed) > stx_offset + 3:
                    cmd = trimmed[stx_offset + 2]
                    status = trimmed[stx_offset + 3]
                    # Calcular largo real basándose en el tipo de respuesta
                    real_len = USBSniffer._estimate_response_length(
                        cmd, trimmed[stx_offset:])
                    if real_len > 0:
                        end = stx_offset + real_len
                        return bytes(trimmed[stx_offset:end]), report_id
                # Fallback: devolver desde STX hasta el final limpio
                return bytes(trimmed[stx_offset:]), report_id

            elif msg_len > 0:
                # Modo serial normal: LEN dice exactamente cuántos bytes hay
                # Total = STX(1) + LEN(1) + msg_len bytes
                frame_end = stx_offset + 2 + msg_len
                if frame_end <= len(trimmed):
                    return bytes(trimmed[stx_offset:frame_end]), report_id
                # Si no hay suficientes bytes, devolver lo que hay
                return bytes(trimmed[stx_offset:]), report_id

        return bytes(trimmed[stx_offset:]), report_id

    @staticmethod
    def _estimate_response_length(cmd: int, frame: bytes) -> int:
        """
        Estima la longitud de una respuesta RD200 basándose en el comando.
        frame empieza en STX.

        Formato respuesta: [STX][LEN][CMD][STATUS]{DATA}
        Para LEN=0 (modo HID), estimamos según el comando.
        """
        if len(frame) < 4:
            return 0

        status = frame[3]

        # Si STATUS indica error o NoCard, no hay data adicional
        if status != 0x00:
            return 4  # STX + LEN + CMD + STATUS

        # Respuestas de longitud conocida según CMD
        known_lengths = {
            0x02: 4,    # Action: sin data
            0x0F: 4,    # System: sin data
        }
        if cmd in known_lengths:
            return known_lengths[cmd]

        # Para otros comandos, intentar usar el LEN del frame si no es 0
        msg_len = frame[1]
        if msg_len > 0:
            return 2 + msg_len

        # LEN=0 (HID): buscar patrones conocidos
        # GetSerial (0x0D): 8 bytes ASCII de serial → 4 + 8 = 12
        # GetVersion (0x0E): ~16 bytes ASCII → 4 + 16 = 20
        # SetParam (0x03): echo de los parámetros enviados
        # ReadTag (0x01): UID variable (4-10 bytes)
        # MifareUID (0x11): 4 bytes UID → 4 + 4 = 8
        # ReadData (0x15): 16 bytes → 4 + 16 = 20
        # NTAGRead (0x13): 16 bytes → 4 + 16 = 20

        # No podemos saber exacto — devolver 0 para usar todo el frame limpio
        return 0

    # -------------------------------------------------------------------------
    # Auto-anotación de paquetes
    # -------------------------------------------------------------------------

    # RD200 command names for auto-annotation
    _CMD_NAMES = {
        0x01: "ReadTag", 0x02: "Action", 0x03: "SetParam",
        0x0C: "EEPROM", 0x0D: "GetSerial", 0x0E: "GetVersion",
        0x0F: "System", 0x11: "MifareUID", 0x12: "WriteKey",
        0x13: "NTAGRead", 0x14: "NTAGWrite", 0x15: "ReadData",
        0x16: "WriteData",
    }

    _STATUS_NAMES = {0x00: "OK", 0x01: "NoCard", 0x10: "CmdError"}

    # Sub-nombres de parámetros para SetParam (CMD 0x03)
    _PARAM_NAMES = {
        0x01: "USBMode", 0x02: "ReadCardMode", 0x03: "KeyboardFormat",
        0x04: "PostponementTime", 0x05: "SameCardTime", 0x06: "KeypadDelay",
        0x11: "MifareSector", 0x21: "ISO15693Block", 0x23: "MICCardType",
        0x31: "LFCardType",
    }

    # Nombres de formatos de teclado
    _KBD_FORMAT_NAMES = {
        0x01: "4H", 0x02: "5D", 0x03: "6H", 0x04: "8D", 0x05: "8H",
        0x06: "10D", 0x07: "10H", 0x08: "Custom",
    }

    # Nombres de acciones
    _ACTION_NAMES = {
        0x01: "RestoreDefault", 0x02: "Beep+Green 0.5s",
        0x03: "Beep+Off 0.5s", 0x04: "Beep+Green 1s",
        0x05: "Beep+Off 1s", 0x06: "Beep 0.5s",
        0x07: "Bell 1s", 0x08: "Green 1s", 0x09: "Off 1s",
        0x11: "StopSense", 0x12: "StartSense", 0x13: "Reset",
    }

    @classmethod
    def _auto_annotate(cls, data: bytes, direction: str) -> str:
        """
        Anota automáticamente un paquete basándose en el protocolo RD200.
        Usa los bytes de protocolo limpios (sin HID overhead).
        """
        if not data:
            return ""

        # Extraer trama limpia para anotar
        proto, _ = cls.extract_protocol_frame(data, direction)
        if not proto:
            return "Paquete vacío"

        # Verificar que sea trama RD200
        if proto[0] != 0x02:
            trimmed = data.rstrip(b'\x00')
            if len(trimmed) <= 8 and direction == "RX":
                return "posible keyboard report"
            return f"No-RD200 ({len(trimmed)}B)"

        if len(proto) < 3:
            return "Trama incompleta"

        notes = []
        msg_len = proto[1]
        cmd = proto[2]
        cmd_name = cls._CMD_NAMES.get(cmd, f"CMD=0x{cmd:02X}")
        notes.append(f"RD200 {cmd_name}")

        if direction == "RX":
            if len(proto) < 4:
                return " | ".join(notes)

            status = proto[3]
            status_name = cls._STATUS_NAMES.get(status, f"0x{status:02X}")
            notes.append(f"STATUS={status_name}")

            # Decodificar data de la respuesta
            resp_data = proto[4:]
            if resp_data and status == 0x00:
                notes.append(cls._decode_response_data(cmd, resp_data))

        elif direction == "TX":
            # Decodificar data del comando
            cmd_data = proto[3:]  # Después de STX, LEN, CMD
            if cmd_data:
                notes.append(cls._decode_command_data(cmd, cmd_data))

        return " | ".join(n for n in notes if n)

    @classmethod
    def _decode_command_data(cls, cmd: int, data: bytes) -> str:
        """Decodifica los datos de un comando TX."""
        if cmd == 0x02 and len(data) >= 1:
            # Action
            action = data[0]
            return cls._ACTION_NAMES.get(action, f"action=0x{action:02X}")

        if cmd == 0x03 and len(data) >= 1:
            # SetParam
            param = data[0]
            param_name = cls._PARAM_NAMES.get(param, f"param=0x{param:02X}")
            if len(data) >= 2:
                vals = " ".join(f"{b:02X}" for b in data[1:])
                # Decodificar valores conocidos
                if param == 0x03 and len(data) >= 4:
                    fmt_name = cls._KBD_FORMAT_NAMES.get(data[1], f"0x{data[1]:02X}")
                    add_parts = []
                    add_byte = data[3]
                    if add_byte & 0x80:
                        add_parts.append("CR")
                    if add_byte & 0x40:
                        add_parts.append("LF")
                    if add_byte & 0x01:
                        add_parts.append(",")
                    add_str = "+".join(add_parts) if add_parts else "None"
                    return f"{param_name}: {fmt_name}, add={add_str}"
                if param == 0x01 and len(data) >= 2:
                    modes = {1: "Keyboard", 2: "HIDDevice", 3: "AutoSend"}
                    return f"{param_name}={modes.get(data[1], f'0x{data[1]:02X}')}"
                return f"{param_name}=[{vals}]"
            return param_name

        if cmd == 0x15 and len(data) >= 3:
            # ReadData: key_type, sector, block (o key_type, key[6], sector, block)
            kt = "KeyA" if data[0] == 0x60 else "KeyB"
            if len(data) == 3:
                return f"{kt} S{data[1]}B{data[2]}"
            elif len(data) >= 9:
                return f"{kt} key={data[1:7].hex()} S{data[7]}B{data[8]}"

        if cmd == 0x16 and len(data) >= 3:
            # WriteData
            kt = "KeyA" if data[0] == 0x60 else "KeyB"
            if len(data) >= 19:
                return f"{kt} S{data[1]}B{data[2]} data={data[3:19].hex(' ')}"

        return f"{len(data)}B"

    @classmethod
    def _decode_response_data(cls, cmd: int, data: bytes) -> str:
        """Decodifica los datos de una respuesta RX exitosa."""
        if cmd == 0x0D:
            # GetSerial: ASCII
            try:
                return f'SN="{data.decode("ascii", errors="replace")}"'
            except Exception:
                return f"SN={data.hex()}"

        if cmd == 0x0E:
            # GetVersion: ASCII
            try:
                return f'ver="{data.decode("ascii", errors="replace").rstrip(chr(0))}"'
            except Exception:
                return f"ver={data.hex()}"

        if cmd == 0x01 or cmd == 0x11:
            # ReadTag / MifareUID
            return f"UID={data.hex().upper()}"

        if cmd == 0x03 and len(data) >= 1:
            # SetParam echo
            param = data[0]
            param_name = cls._PARAM_NAMES.get(param, f"0x{param:02X}")
            if len(data) >= 2:
                vals = " ".join(f"{b:02X}" for b in data[1:])
                return f"{param_name}=[{vals}]"
            return param_name

        if cmd in (0x15, 0x13):
            # ReadData / NTAGRead: 16 bytes de datos
            return f"data[{len(data)}B]={data.hex(' ').upper()}"

        if len(data) > 0:
            return f"data[{len(data)}B]"

        return ""
