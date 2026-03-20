# =============================================================================
# utils/hex_utils.py
# Utilidades para manipulación, validación y visualización de datos hexadecimales.
# =============================================================================


class HexUtils:
    """Métodos estáticos para trabajar con hex strings y bytes."""

    @staticmethod
    def str_to_bytes(hex_str: str) -> bytes:
        """
        Convierte un string hexadecimal a bytes.
        Acepta formatos: "A1B2C3", "A1 B2 C3", "A1:B2:C3", "0xA1,0xB2".

        Raises:
            ValueError: Si el string contiene caracteres no hexadecimales.
        """
        # Normalizar separadores comunes
        clean = (hex_str
                 .replace(" ", "")
                 .replace(":", "")
                 .replace(",", "")
                 .replace("0x", "")
                 .replace("0X", "")
                 .upper()
                 .strip())
        if len(clean) % 2 != 0:
            raise ValueError(f"La cadena hex tiene longitud impar: '{hex_str}'")
        try:
            return bytes.fromhex(clean)
        except ValueError as e:
            raise ValueError(f"Cadena hex inválida '{hex_str}': {e}")

    @staticmethod
    def bytes_to_str(data: bytes, sep: str = " ") -> str:
        """
        Convierte bytes a string hexadecimal formateado.
        sep: separador entre bytes (ej. " ", ":", "")
        """
        return sep.join(f"{b:02X}" for b in data)

    @staticmethod
    def bytes_to_int(data: bytes, byteorder: str = "big") -> int:
        """Convierte bytes a entero."""
        return int.from_bytes(data, byteorder=byteorder)

    @staticmethod
    def int_to_bytes(value: int, length: int, byteorder: str = "big") -> bytes:
        """Convierte entero a bytes de longitud fija."""
        return value.to_bytes(length, byteorder=byteorder)

    @staticmethod
    def uid_to_decimal(uid_hex: str) -> str:
        """
        Convierte un UID hexadecimal a su representación decimal de 10 dígitos.
        Formato común en lectores de acceso (Wiegand / HID Prox).

        Ejemplo: "A1B2C3D4" → "2714189780"
        """
        try:
            value = int(uid_hex, 16)
            return str(value).zfill(10)
        except ValueError:
            return ""

    @staticmethod
    def is_valid_hex(hex_str: str) -> bool:
        """Devuelve True si el string es hexadecimal válido (pares de chars)."""
        clean = hex_str.replace(" ", "").replace(":", "")
        if len(clean) % 2 != 0:
            return False
        try:
            bytes.fromhex(clean)
            return True
        except ValueError:
            return False

    @staticmethod
    def format_block_display(block_number: int, data: bytes) -> str:
        """
        Formatea un bloque MIFARE para visualización en la GUI.
        Ejemplo:
            Block 04: A1 B2 C3 D4 E5 F6 07 08 09 0A 0B 0C 0D 0E 0F 10
                      [ carácter ASCII printable de cada byte ]
        """
        hex_part = HexUtils.bytes_to_str(data)
        ascii_part = "".join(
            chr(b) if 32 <= b < 127 else "." for b in data
        )
        return f"Bloque {block_number:03d}: {hex_part}  |  {ascii_part}"

    @staticmethod
    def pad_block_data(data: bytes, fill: int = 0x00) -> bytes:
        """Rellena data hasta 16 bytes con fill. Trunca si es más largo."""
        if len(data) > 16:
            return data[:16]
        return data.ljust(16, bytes([fill]))

    @staticmethod
    def xor_bytes(a: bytes, b: bytes) -> bytes:
        """XOR byte a byte entre dos secuencias de igual longitud."""
        if len(a) != len(b):
            raise ValueError("Las secuencias deben tener la misma longitud.")
        return bytes(x ^ y for x, y in zip(a, b))
