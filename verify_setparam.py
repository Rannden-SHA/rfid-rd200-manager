#!/usr/bin/env python3
"""
verify_setparam.py - Verificar que SetParam funciona con Report ID dinámico.

Prueba:
  1. Leer config actual
  2. Cambiar a 8H + CR
  3. Leer config de nuevo para confirmar
  4. Restaurar config original

Ejecutar: venv\\Scripts\\python.exe verify_setparam.py
"""

import time
import hid

VID = 0x0E6A
PID = 0x0317


def build_cmd(cmd_byte, data=b""):
    """Construye frame RD200: [STX][LEN][CMD]{DATA}"""
    msg_len = 1 + len(data)
    return bytes([0x02, msg_len, cmd_byte]) + data


def send_recv(dev, frame, timeout_ms=2000):
    """Envia con Report ID = len(frame) y lee respuesta."""
    report_id = len(frame)
    report = bytes([report_id]) + frame.ljust(63, b'\x00')
    written = dev.write(list(report))
    if written < 0:
        print(f"  ERROR: write returned {written}")
        return None

    resp = dev.read(64, timeout_ms=timeout_ms)
    if not resp:
        print(f"  ERROR: sin respuesta (timeout {timeout_ms}ms)")
        return None

    raw = bytes(resp)
    # Encontrar STX y parsear
    for i in range(min(4, len(raw))):
        if raw[i] == 0x02:
            msg_len = raw[i + 1]
            end = i + 2 + msg_len
            proto = raw[i:end]
            rid = raw[0] if i > 0 else -1
            return {"proto": proto, "report_id": rid, "raw": raw}
    return {"proto": raw, "report_id": -1, "raw": raw}


def read_kbd_config(dev):
    """Lee la configuración actual de KeyboardFormat."""
    frame = build_cmd(0x03, bytes([0x03]))  # Query KeyboardFormat
    result = send_recv(dev, frame)
    if result and len(result["proto"]) >= 8:
        p = result["proto"]
        # proto = 02 LL 03 00 03 FF RR AA
        status = p[3]
        data = p[4:]
        if status == 0x00 and len(data) >= 4:
            return {
                "sub_param": data[0],
                "format": data[1],
                "reverse": data[2],
                "add": data[3],
                "raw_data": data,
                "proto_hex": p.hex(" ").upper(),
            }
    return None


def set_kbd_config(dev, fmt, reverse, add_type):
    """Escribe configuración de KeyboardFormat."""
    frame = build_cmd(0x03, bytes([0x03, fmt, reverse, add_type]))
    result = send_recv(dev, frame)
    if result and len(result["proto"]) >= 8:
        p = result["proto"]
        status = p[3]
        data = p[4:]
        return {
            "status": status,
            "sub_param": data[0] if len(data) > 0 else -1,
            "format": data[1] if len(data) > 1 else -1,
            "reverse": data[2] if len(data) > 2 else -1,
            "add": data[3] if len(data) > 3 else -1,
            "proto_hex": p.hex(" ").upper(),
        }
    return None


FMT_NAMES = {1: "4H", 2: "5D", 3: "6H", 4: "8D", 5: "8H", 6: "10D", 7: "10H"}


def show_config(cfg, label=""):
    if not cfg:
        print(f"  {label}: ERROR - no se pudo leer")
        return
    fmt_name = FMT_NAMES.get(cfg["format"], f"0x{cfg['format']:02X}")
    add_parts = []
    if cfg["add"] & 0x80:
        add_parts.append("CR")
    if cfg["add"] & 0x40:
        add_parts.append("LF")
    if cfg["add"] & 0x01:
        add_parts.append(",")
    add_str = "+".join(add_parts) if add_parts else "None"
    rev_names = {1: "Normal", 2: "ReverseBytes", 3: "ReverseBits"}
    rev_name = rev_names.get(cfg["reverse"], f"0x{cfg['reverse']:02X}")
    print(f"  {label}: Formato={fmt_name}, Reverse={rev_name}, Add={add_str}")
    print(f"    Proto: {cfg['proto_hex']}")


def main():
    # Buscar interfaz Consumer (0x000C)
    interfaces = [d for d in hid.enumerate()
                  if d["vendor_id"] == VID and d["product_id"] == PID]

    if not interfaces:
        print("ERROR: Lector no encontrado")
        return

    consumer = None
    for intf in interfaces:
        if intf.get("usage_page") == 0x000C:
            consumer = intf
            break

    if not consumer:
        consumer = interfaces[0]

    print(f"Conectando a interfaz {consumer.get('interface_number', '?')} "
          f"(usage_page=0x{consumer.get('usage_page', 0):04X})...")

    dev = hid.device()
    dev.open_path(consumer["path"])

    # 1. Verificar comunicación
    print("\n[1] Verificar comunicación (GetSerial)...")
    frame = build_cmd(0x0D)  # GetSerial = 3 bytes → RID=0x03
    result = send_recv(dev, frame)
    if result:
        p = result["proto"]
        if len(p) >= 5 and p[3] == 0x00:
            sn = p[4:].decode("ascii", errors="replace")
            print(f"  OK - Serial: {sn}")
            print(f"  RID respuesta: 0x{result['report_id']:02X}")
        else:
            print(f"  Respuesta: {result['proto'].hex(' ').upper()}")
    else:
        print("  FALLO - no hay comunicación")
        dev.close()
        return

    # 2. Leer config actual
    print("\n[2] Leer configuración actual...")
    original = read_kbd_config(dev)
    show_config(original, "ACTUAL")

    if not original:
        dev.close()
        return

    # 3. Cambiar a 8H + Normal + CR
    print("\n[3] Escribir configuración: 8H + Normal + CR...")
    result = set_kbd_config(dev, 0x05, 0x01, 0x80)
    if result:
        print(f"  Status: {'OK' if result['status'] == 0 else 'ERROR'}")
        print(f"  Echo: fmt=0x{result['format']:02X}, "
              f"rev=0x{result['reverse']:02X}, add=0x{result['add']:02X}")
        print(f"  Proto: {result['proto_hex']}")

        if result["format"] == 0x05 and result["add"] == 0x80:
            print("  ✅ ¡CONFIRMADO! La configuración se aplicó correctamente.")
        else:
            print("  ❌ Los valores del echo no coinciden con lo enviado.")

    # 4. Verificar leyendo de nuevo
    print("\n[4] Releer configuración para confirmar persistencia...")
    time.sleep(0.3)
    verify = read_kbd_config(dev)
    show_config(verify, "DESPUES")

    if verify and verify["format"] == 0x05 and verify["add"] == 0x80:
        print("\n  ✅✅ ¡ÉXITO TOTAL! SetParam funciona con Report ID dinámico.")
    else:
        print("\n  ❌ La configuración no persistió.")

    # 5. Restaurar config original
    print(f"\n[5] Restaurar config original "
          f"(fmt=0x{original['format']:02X}, "
          f"rev=0x{original['reverse']:02X}, "
          f"add=0x{original['add']:02X})...")
    result = set_kbd_config(dev, original["format"], original["reverse"], original["add"])
    if result and result["status"] == 0:
        print("  Config original restaurada.")
    else:
        print("  ⚠ No se pudo restaurar la config original.")

    dev.close()
    print("\nHecho.")


if __name__ == "__main__":
    main()
