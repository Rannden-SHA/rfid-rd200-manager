# =============================================================================
# core/rfid_protocol.py
#
# Protocolo REAL del lector RD200 (SYRIS Technology) basado en el manual
# "RD200 Protocol Manual V0192".
#
# Formato de trama:
#   Request  (Host → Reader):  [STX] [LEN] [CMD] {DATA}
#   Response (Reader → Host):  [STX] [LEN] [CMD] [STATUS] {DATA}
#
#   STX = 0x02
#   LEN = numero de bytes de CMD + DATA (request) o CMD + STATUS + DATA (response)
#         NO incluye STX ni LEN.
#   STATUS: 0x00 = OK, 0x01 = No card, 0x10 = Command error
#
# NO hay BCC ni ETX en este protocolo.
# =============================================================================

from dataclasses import dataclass, field
from typing import Optional, List
import logging

logger = logging.getLogger(__name__)


@dataclass
class CardData:
    """Datos parseados de una pulsera RFID leida."""
    uid: str = ""                    # ID unico de la tarjeta (hex string)
    uid_decimal: str = ""            # UID en decimal
    card_type: str = ""              # "MIFARE Classic", "NTAG213", etc.
    blocks: dict = field(default_factory=dict)  # {bloque_num: bytes_hex}
    raw_response: bytes = b""        # Respuesta cruda del lector
    timestamp: str = ""              # ISO timestamp de la lectura
    is_valid: bool = False

    def __str__(self) -> str:
        return f"CardData(uid={self.uid}, type={self.card_type}, valid={self.is_valid})"


# =============================================================================
# Constantes de estado de respuesta
# =============================================================================
STATUS_OK = 0x00
STATUS_NO_CARD = 0x01
STATUS_ERROR = 0x10


# =============================================================================
# Protocolo RD200
# =============================================================================

class RFIDProtocol:
    """
    Protocolo real del RD200 basado en el manual V0192.

    Comandos implementados (para RD200-M1):
      0x01 - Read Tag Data (UID)
      0x02 - Reader Action (beep, LED, stop/start sense)
      0x03 - Set Reader Parameters
      0x0C - Read/Write User Data on EEPROM
      0x0D - Get Serial Number
      0x0E - Get Model & Firmware Version
      0x0F - System Command (reboot, factory reset)
      0x11 - Read Mifare UID
      0x12 - Write Key to EEPROM
      0x13 - Ultralight/NTAG Read Data
      0x14 - Ultralight/NTAG Write Data
      0x15 - Read Data (Mifare block with key)
      0x16 - Write Data (Mifare block with key)
    """

    STX = 0x02

    # -- Command codes --
    CMD_READ_TAG_DATA     = 0x01
    CMD_READER_ACTION     = 0x02
    CMD_SET_PARAMETER     = 0x03
    CMD_EEPROM_DATA       = 0x0C
    CMD_GET_SERIAL        = 0x0D
    CMD_GET_MODEL_VERSION = 0x0E
    CMD_SYSTEM            = 0x0F
    CMD_READ_MIFARE_UID   = 0x11
    CMD_WRITE_KEY_EEPROM  = 0x12
    CMD_NTAG_READ         = 0x13
    CMD_NTAG_WRITE        = 0x14
    CMD_READ_DATA         = 0x15
    CMD_WRITE_DATA        = 0x16

    # -- Reader Action sub-commands (DATA byte for CMD 0x02) --
    ACTION_RESTORE_DEFAULT    = 0x01
    ACTION_BEEP_GREEN_05S     = 0x02
    ACTION_BEEP_LIGHT_OFF_05S = 0x03
    ACTION_BEEP_GREEN_1S      = 0x04
    ACTION_BEEP_LIGHT_OFF_1S  = 0x05
    ACTION_BEEP_05S           = 0x06
    ACTION_BELL_1S            = 0x07
    ACTION_GREEN_LIGHT_1S     = 0x08
    ACTION_LIGHT_OFF_1S       = 0x09
    ACTION_STOP_SENSE         = 0x11
    ACTION_START_SENSE        = 0x12
    ACTION_RESET_READER       = 0x13

    # -- Set Parameter sub-command IDs (first DATA byte for CMD 0x03) --
    PARAM_USB_MODE            = 0x01
    PARAM_READ_CARD_MODE      = 0x02
    PARAM_KEYBOARD_FORMAT     = 0x03
    PARAM_POSTPONEMENT_TIME   = 0x04
    PARAM_SAME_CARD_TIME      = 0x05
    PARAM_KEYPAD_DELAY        = 0x06
    PARAM_MIFARE_SECTOR_SETTING = 0x11
    PARAM_ISO15693_BLOCK_SETTING = 0x21
    PARAM_MIC_CARD_TYPE       = 0x23
    PARAM_LF_CARD_TYPE        = 0x31

    # -- USB Mode values --
    USB_HID_KEYBOARD     = 0x01  # HID + Keyboard emulation (default)
    USB_HID_DEVICE       = 0x02  # HID-Compliant Device (command only)
    USB_HID_AUTO_SEND    = 0x03  # HID-Compliant Device Auto Send

    # -------------------------------------------------------------------------
    # Frame building
    # -------------------------------------------------------------------------

    @classmethod
    def build_command(cls, cmd: int, data: bytes = b"") -> bytes:
        """
        Construye una trama de comando RD200.
        Formato: [STX=0x02] [LEN] [CMD] {DATA}
        LEN = len(CMD + DATA) = 1 + len(data)
        """
        msg_len = 1 + len(data)  # CMD byte + DATA bytes
        return bytes([cls.STX, msg_len, cmd]) + data

    @classmethod
    def build_hid_report(cls, cmd: int, data: bytes = b"") -> bytes:
        """
        Construye un paquete HID completo listo para enviar con hidapi.

        RD200: Report ID = longitud del frame de protocolo.
        El lector usa el Report ID para saber cuántos bytes leer.
        Ejemplo: frame de 7 bytes → Report ID = 0x07
        """
        frame = cls.build_command(cmd, data)
        # RD200: Report ID = len(frame)
        report_id = len(frame)
        report = bytes([report_id]) + frame
        # Pad hasta 64 bytes total (Report ID + 63 bytes)
        return report.ljust(64, b'\x00')

    # -------------------------------------------------------------------------
    # Response parsing
    # -------------------------------------------------------------------------

    # Report IDs para comunicacion HID con el RD200
    HID_REPORT_ID_CMD = 0x03   # Output: enviar comandos
    HID_REPORT_ID_RESP = 0x0C  # Input: respuestas (incluido por hidapi)

    @classmethod
    def parse_response(cls, raw: bytes) -> dict:
        """
        Parsea una respuesta del RD200.

        Formato serial:  [STX=0x02] [LEN] [CMD] [STATUS] {DATA}
        Formato HID:     [ReportID=0x0C] [STX=0x02] [0x00] [CMD] [STATUS] {DATA}

        En modo HID, el campo LEN viene como 0x00 (el largo se deduce del
        payload util). hidapi incluye el Report ID como primer byte cuando
        este es != 0x00.

        Returns:
            {
              "valid": bool,
              "success": bool,
              "status": int,
              "cmd": int,
              "data": bytes,
              "raw": bytes
            }
        """
        result = {
            "valid": False,
            "success": False,
            "status": -1,
            "cmd": -1,
            "data": b"",
            "raw": raw,
        }

        if not raw or len(raw) < 3:
            return result

        # Buscar STX=0x02 en las primeras posiciones
        # Puede estar en pos 0 (directo), pos 1 (con Report ID), pos 2, etc.
        offset = -1
        for i in range(min(4, len(raw))):
            if raw[i] == cls.STX:
                offset = i
                break

        if offset < 0 or len(raw) < offset + 4:
            return result

        msg_len = raw[offset + 1]
        cmd = raw[offset + 2]
        status = raw[offset + 3]

        result["valid"] = True
        result["cmd"] = cmd
        result["status"] = status
        result["success"] = (status == STATUS_OK)

        # Calcular longitud de DATA
        data_start = offset + 4

        if msg_len >= 2:
            # Modo serial normal: LEN incluye CMD + STATUS + DATA
            data_len = msg_len - 2
        elif msg_len == 0:
            # Modo HID: LEN=0x00, calcular data desde bytes utiles
            # Buscar el final de los datos utiles (antes del padding de zeros)
            trimmed = raw.rstrip(b'\x00')
            data_len = len(trimmed) - data_start
        else:
            # msg_len == 1: solo CMD, sin STATUS ni DATA
            data_len = 0

        if data_len > 0 and len(raw) >= data_start + data_len:
            result["data"] = bytes(raw[data_start: data_start + data_len])
        elif data_len > 0:
            result["data"] = bytes(raw[data_start:]).rstrip(b'\x00')

        return result

    # -------------------------------------------------------------------------
    # 2.2 Read Tag Data (0x01)
    # -------------------------------------------------------------------------

    @classmethod
    def cmd_read_tag(cls, erase_after_remove: bool = False) -> bytes:
        """
        Lee el UID de la tarjeta presente.
        erase_after_remove=False: borra antes de retirar (default)
        erase_after_remove=True:  borra despues de retirar
        """
        if erase_after_remove:
            return cls.build_hid_report(cls.CMD_READ_TAG_DATA, bytes([0x01]))
        return cls.build_hid_report(cls.CMD_READ_TAG_DATA)

    # -------------------------------------------------------------------------
    # 2.3 Reader Action Command (0x02)
    # -------------------------------------------------------------------------

    @classmethod
    def cmd_reader_action(cls, action: int) -> bytes:
        """Envia un comando de accion al lector (beep, LED, etc.)."""
        return cls.build_hid_report(cls.CMD_READER_ACTION, bytes([action]))

    @classmethod
    def cmd_beep(cls) -> bytes:
        """Beep corto (0.5s)."""
        return cls.cmd_reader_action(cls.ACTION_BEEP_05S)

    @classmethod
    def cmd_beep_green(cls) -> bytes:
        """Beep + LED verde (0.5s)."""
        return cls.cmd_reader_action(cls.ACTION_BEEP_GREEN_05S)

    @classmethod
    def cmd_green_light(cls) -> bytes:
        """LED verde 1 segundo."""
        return cls.cmd_reader_action(cls.ACTION_GREEN_LIGHT_1S)

    @classmethod
    def cmd_light_off(cls) -> bytes:
        """Apagar LED 1 segundo."""
        return cls.cmd_reader_action(cls.ACTION_LIGHT_OFF_1S)

    @classmethod
    def cmd_stop_sense(cls) -> bytes:
        """Dejar de detectar tarjetas."""
        return cls.cmd_reader_action(cls.ACTION_STOP_SENSE)

    @classmethod
    def cmd_start_sense(cls) -> bytes:
        """Comenzar a detectar tarjetas."""
        return cls.cmd_reader_action(cls.ACTION_START_SENSE)

    # -------------------------------------------------------------------------
    # 2.4 Set Reader Parameter (0x03)
    # -------------------------------------------------------------------------

    @classmethod
    def cmd_set_usb_mode(cls, mode: int) -> bytes:
        """
        Cambia el modo USB del lector.
        mode: USB_HID_KEYBOARD(0x01), USB_HID_DEVICE(0x02), USB_HID_AUTO_SEND(0x03)
        """
        return cls.build_hid_report(cls.CMD_SET_PARAMETER,
                                    bytes([cls.PARAM_USB_MODE, mode]))

    @classmethod
    def cmd_get_usb_mode(cls) -> bytes:
        """Lee el modo USB actual. Envia PARAM_USB_MODE sin valor extra."""
        return cls.build_hid_report(cls.CMD_SET_PARAMETER,
                                    bytes([cls.PARAM_USB_MODE]))

    @classmethod
    def cmd_set_read_card_mode(cls, mode_byte: int) -> bytes:
        """
        Configura el modo de lectura de tarjeta.
        mode_byte es un bitmask:
          Bit 0: Auto Read (1=ON)
          Bit 1: Beep (1=ON)
          Bit 2: LED (1=ON)
          Bit 3: Same Card Detection (1=ON)
          Bit 4: Energy Saving / Green Mode (1=ON)
        Default: 0x0F (Auto+Beep+LED+SameCard ON)
        """
        return cls.build_hid_report(cls.CMD_SET_PARAMETER,
                                    bytes([cls.PARAM_READ_CARD_MODE, mode_byte]))

    @classmethod
    def cmd_set_keyboard_format(cls, uid_format: int, reverse_uid: int,
                                add_type: int) -> bytes:
        """
        Configura el formato de emulacion de teclado.
        uid_format: 0x01=4H, 0x02=5D, 0x03=6H, 0x04=8D, 0x05=8H, etc.
        reverse_uid: 0x01=Normal, 0x02=Reverse Byte, 0x03=Reverse Bit
        add_type: bitmask para separadores (Bit7=Enter, Bit0=Comma, etc.)
        """
        return cls.build_hid_report(cls.CMD_SET_PARAMETER,
                                    bytes([cls.PARAM_KEYBOARD_FORMAT,
                                           uid_format, reverse_uid, add_type]))

    @classmethod
    def cmd_set_postponement_time(cls, time_val: int) -> bytes:
        """Tiempo de postponement de lectura. Unidad: 10ms. Default: 5 (=50ms)."""
        return cls.build_hid_report(cls.CMD_SET_PARAMETER,
                                    bytes([cls.PARAM_POSTPONEMENT_TIME, time_val]))

    @classmethod
    def cmd_set_same_card_time(cls, time_val: int) -> bytes:
        """Tiempo de deteccion de misma tarjeta. Unidad: 100ms. Default: 15 (=1500ms)."""
        return cls.build_hid_report(cls.CMD_SET_PARAMETER,
                                    bytes([cls.PARAM_SAME_CARD_TIME, time_val]))

    @classmethod
    def cmd_set_keypad_delay(cls, delay_ms: int) -> bytes:
        """Delay de teclado en ms. Default: 10."""
        return cls.build_hid_report(cls.CMD_SET_PARAMETER,
                                    bytes([cls.PARAM_KEYPAD_DELAY, delay_ms]))

    # -------------------------------------------------------------------------
    # 2.5 Read/Write User Data on EEPROM (0x0C)
    # -------------------------------------------------------------------------

    @classmethod
    def cmd_read_eeprom(cls, addr_high: int, addr_low: int, num: int) -> bytes:
        """Lee datos del EEPROM del lector."""
        return cls.build_hid_report(cls.CMD_EEPROM_DATA,
                                    bytes([addr_high, addr_low, num]))

    @classmethod
    def cmd_write_eeprom(cls, addr_high: int, addr_low: int, num: int,
                         data: bytes) -> bytes:
        """Escribe datos en el EEPROM del lector."""
        return cls.build_hid_report(cls.CMD_EEPROM_DATA,
                                    bytes([addr_high, addr_low, num]) + data)

    # -------------------------------------------------------------------------
    # 2.6 Get Serial Number (0x0D)
    # -------------------------------------------------------------------------

    @classmethod
    def cmd_get_serial(cls) -> bytes:
        """Obtiene el numero de serie del lector."""
        return cls.build_hid_report(cls.CMD_GET_SERIAL)

    # -------------------------------------------------------------------------
    # 2.7 Get Model & Firmware Version (0x0E)
    # -------------------------------------------------------------------------

    @classmethod
    def cmd_get_version(cls) -> bytes:
        """Obtiene modelo y version de firmware."""
        return cls.build_hid_report(cls.CMD_GET_MODEL_VERSION)

    # -------------------------------------------------------------------------
    # 2.8 System Command (0x0F)
    # -------------------------------------------------------------------------

    @classmethod
    def cmd_reboot(cls) -> bytes:
        """Reinicia el lector."""
        return cls.build_hid_report(cls.CMD_SYSTEM, bytes([0x01]))

    @classmethod
    def cmd_factory_reset(cls) -> bytes:
        """Restaura configuracion de fabrica."""
        return cls.build_hid_report(cls.CMD_SYSTEM, bytes([0x02]))

    # -------------------------------------------------------------------------
    # 3.1 Read Mifare UID (0x11) - RD200-M1
    # -------------------------------------------------------------------------

    @classmethod
    def cmd_read_mifare_uid(cls) -> bytes:
        """Lee el UID de una tarjeta Mifare (4 bytes)."""
        return cls.build_hid_report(cls.CMD_READ_MIFARE_UID)

    # -------------------------------------------------------------------------
    # 3.2 Write Key to EEPROM (0x12)
    # -------------------------------------------------------------------------

    @classmethod
    def cmd_write_key_to_eeprom(cls, key_type: str, key: bytes,
                                sector: int) -> bytes:
        """
        Guarda una clave Mifare en el EEPROM del lector.
        key_type: "A" o "B"
        key: 6 bytes
        sector: numero de sector
        """
        kt = 0x60 if key_type.upper() == "A" else 0x61
        return cls.build_hid_report(cls.CMD_WRITE_KEY_EEPROM,
                                    bytes([kt]) + key + bytes([sector]))

    # -------------------------------------------------------------------------
    # 3.3 Ultralight/NTAG Read Data (0x13)
    # -------------------------------------------------------------------------

    @classmethod
    def cmd_ntag_read(cls, block: int) -> bytes:
        """Lee 16 bytes de un bloque NTAG/Ultralight."""
        return cls.build_hid_report(cls.CMD_NTAG_READ,
                                    bytes([0x00, 0x00, block]))

    # -------------------------------------------------------------------------
    # 3.4 Ultralight/NTAG Write Data (0x14)
    # -------------------------------------------------------------------------

    @classmethod
    def cmd_ntag_write(cls, block: int, data: bytes) -> bytes:
        """Escribe 16 bytes en un bloque NTAG/Ultralight."""
        if len(data) != 16:
            raise ValueError("Los datos deben ser exactamente 16 bytes.")
        return cls.build_hid_report(cls.CMD_NTAG_WRITE,
                                    bytes([0x00, 0x00, block]) + data)

    # -------------------------------------------------------------------------
    # 3.5 Read Data (0x15) - Mifare Classic with key
    # -------------------------------------------------------------------------

    @classmethod
    def cmd_read_block(cls, key_type: str = "A", sector: int = 0,
                       block: int = 0,
                       key: Optional[bytes] = None) -> bytes:
        """
        Lee 16 bytes de un bloque Mifare Classic.
        Sin key: usa autenticacion simple (4 bytes: key_type, sector, block)
        Con key: autenticacion completa (key_type + key + sector + block)
        """
        kt = 0x60 if key_type.upper() == "A" else 0x61
        if key is None:
            return cls.build_hid_report(cls.CMD_READ_DATA,
                                        bytes([kt, sector, block]))
        return cls.build_hid_report(cls.CMD_READ_DATA,
                                    bytes([kt]) + key + bytes([sector, block]))

    # -------------------------------------------------------------------------
    # 3.6 Write Data (0x16) - Mifare Classic with key
    # -------------------------------------------------------------------------

    @classmethod
    def cmd_write_block(cls, key_type: str = "A", sector: int = 0,
                        block: int = 0, data: bytes = b"",
                        key: Optional[bytes] = None) -> bytes:
        """
        Escribe 16 bytes en un bloque Mifare Classic.
        """
        if len(data) != 16:
            raise ValueError("Los datos deben ser exactamente 16 bytes.")
        kt = 0x60 if key_type.upper() == "A" else 0x61
        if key is None:
            return cls.build_hid_report(cls.CMD_WRITE_DATA,
                                        bytes([kt, sector, block]) + data)
        return cls.build_hid_report(cls.CMD_WRITE_DATA,
                                    bytes([kt]) + key + bytes([sector, block]) + data)

    # -------------------------------------------------------------------------
    # Utilidades
    # -------------------------------------------------------------------------

    @staticmethod
    def parse_uid_from_data(data: bytes) -> str:
        """Convierte bytes de UID a hex string."""
        return data.hex().upper() if data else ""

    @staticmethod
    def parse_serial_from_data(data: bytes) -> str:
        """El serial viene como ASCII en el campo DATA."""
        return data.decode("ascii", errors="replace") if data else ""

    @staticmethod
    def parse_version_from_data(data: bytes) -> str:
        """El modelo+version viene como ASCII en el campo DATA (16 bytes)."""
        return data.decode("ascii", errors="replace").strip('\x00') if data else ""

    @staticmethod
    def format_command_name(cmd: int) -> str:
        """Nombre legible de un comando."""
        names = {
            0x01: "Read Tag Data",
            0x02: "Reader Action",
            0x03: "Set Parameter",
            0x0C: "EEPROM Data",
            0x0D: "Get Serial",
            0x0E: "Get Version",
            0x0F: "System Command",
            0x11: "Read Mifare UID",
            0x12: "Write Key EEPROM",
            0x13: "NTAG Read",
            0x14: "NTAG Write",
            0x15: "Read Data",
            0x16: "Write Data",
        }
        return names.get(cmd, f"Unknown(0x{cmd:02X})")
