#!/usr/bin/env python3
"""
test_add_type.py - Probar diferentes valores de add_type para entender el protocolo.

Ejecutar: venv\\Scripts\\python.exe test_add_type.py
"""

import time
import hid

VID = 0x0E6A
PID = 0x0317

def build_cmd(cmd_byte, data=b""):
    msg_len = 1 + len(data)
    return bytes([0x02, msg_len, cmd_byte]) + data

def send_recv(dev, frame, timeout_ms=2000):
    report_id = len(frame)
    report = bytes([report_id]) + frame.ljust(63, b'\x00')
    written = dev.write(list(report))
    if written < 0:
        return None
    resp = dev.read(64, timeout_ms=timeout_ms)
    if not resp:
        return None
    raw = bytes(resp)
    for i in range(min(4, len(raw))):
        if raw[i] == 0x02:
            msg_len = raw[i + 1]
            end = i + 2 + msg_len
            return raw[i:end]
    return raw

def read_config(dev):
    frame = build_cmd(0x03, bytes([0x03]))
    return send_recv(dev, frame)

def set_config(dev, fmt, reverse, add_type):
    frame = build_cmd(0x03, bytes([0x03, fmt, reverse, add_type]))
    return send_recv(dev, frame)

def main():
    interfaces = [d for d in hid.enumerate()
                  if d["vendor_id"] == VID and d["product_id"] == PID]
    consumer = next((d for d in interfaces if d.get("usage_page") == 0x000C), None)
    if not consumer:
        print("ERROR: Lector no encontrado")
        return

    dev = hid.device()
    dev.open_path(consumer["path"])

    print("Config inicial:")
    r = read_config(dev)
    if r:
        print(f"  {r.hex(' ').upper()}")
        print(f"  DATA: sub=0x{r[4]:02X} fmt=0x{r[5]:02X} rev=0x{r[6]:02X} add=0x{r[7]:02X}")

    # Probar diferentes valores de add_type
    test_values = [
        (0x00, "Sin nada"),
        (0x01, "Comma (,)"),
        (0x02, "Bit1"),
        (0x40, "LF"),
        (0x80, "CR (Enter)"),
        (0x81, "CR + Comma"),
        (0xC0, "CR + LF"),
    ]

    for add_val, desc in test_values:
        print(f"\n--- Probando add=0x{add_val:02X} ({desc}) ---")
        result = set_config(dev, 0x05, 0x01, add_val)
        if result:
            print(f"  Echo: {result.hex(' ').upper()}")
            echo_add = result[7] if len(result) > 7 else -1
            print(f"  Echo add=0x{echo_add:02X}")
            match = "SI" if echo_add == add_val else "NO"
            print(f"  Coincide: {match}")
        else:
            print("  Sin respuesta")

        # Verificar leyendo
        time.sleep(0.2)
        verify = read_config(dev)
        if verify:
            v_add = verify[7] if len(verify) > 7 else -1
            print(f"  Verify: {verify.hex(' ').upper()} → add=0x{v_add:02X}")
            if v_add == add_val:
                print(f"  GUARDADO OK")
            else:
                print(f"  NO GUARDADO (esperado 0x{add_val:02X}, got 0x{v_add:02X})")

    # Restaurar a 8H sin enter
    print("\n--- Restaurando a 8H sin enter ---")
    set_config(dev, 0x05, 0x01, 0x00)
    time.sleep(0.2)
    final = read_config(dev)
    if final:
        print(f"  Final: {final.hex(' ').upper()}")

    dev.close()
    print("\nHecho.")

if __name__ == "__main__":
    main()
