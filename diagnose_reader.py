#!/usr/bin/env python3
"""
Diagnóstico completo del lector RD200-M1-G.
Prueba TODOS los métodos de comunicación en cada interfaz HID.

Ejecutar:
  venv\Scripts\python.exe diagnose_reader.py
"""

import sys
import time

VID = 0x0E6A
PID = 0x0317

# Comando Get S/N del protocolo RD200: [STX=0x02][LEN=0x01][CMD=0x0D]
GET_SN_CMD = bytes([0x02, 0x01, 0x0D])


def main():
    try:
        import hid
    except ImportError:
        print("ERROR: hidapi no instalado. Ejecuta: pip install hidapi")
        sys.exit(1)

    print("=" * 70)
    print("DIAGNÓSTICO DEL LECTOR RD200-M1-G")
    print("=" * 70)

    # 1. Enumerar interfaces
    interfaces = [d for d in hid.enumerate() if d["vendor_id"] == VID and d["product_id"] == PID]

    if not interfaces:
        print(f"\n[ERROR] No se encontró ningún dispositivo con VID={VID:#06x} PID={PID:#06x}")
        print("\nDispositivos HID disponibles:")
        for d in hid.enumerate():
            print(f"  VID={d['vendor_id']:#06x} PID={d['product_id']:#06x} "
                  f"product={d.get('product_string', '?')}")
        sys.exit(1)

    print(f"\nEncontradas {len(interfaces)} interfaces HID del RD200:\n")
    for i, intf in enumerate(interfaces):
        print(f"  [{i}] interface_number = {intf.get('interface_number', '?')}")
        print(f"      usage_page = 0x{intf.get('usage_page', 0):04X}")
        print(f"      usage      = 0x{intf.get('usage', 0):04X}")
        print(f"      product    = {intf.get('product_string', '?')}")
        print(f"      path       = {intf.get('path', b'?')}")
        print()

    # 2. Probar cada interfaz con múltiples métodos
    print("=" * 70)
    print("PROBANDO COMUNICACIÓN EN CADA INTERFAZ")
    print("=" * 70)

    for i, intf in enumerate(interfaces):
        intf_num = intf.get("interface_number", "?")
        usage_page = intf.get("usage_page", 0)
        path = intf.get("path")

        print(f"\n--- Interfaz [{i}] (intf={intf_num}, usage_page=0x{usage_page:04X}) ---")

        if not path:
            print("  [SKIP] Sin path")
            continue

        try:
            dev = hid.device()
            dev.open_path(path)
            print("  [OK] Abierta correctamente")
        except OSError as e:
            print(f"  [FAIL] No se pudo abrir: {e}")
            continue

        # Método 1: write() con Report ID 0x00 + read() (estándar)
        try_method(dev, "Método 1: write(ReportID=0x00) + read()",
                   write_func=lambda d: d.write(list(bytes([0x00]) + GET_SN_CMD.ljust(63, b'\x00'))),
                   read_func=lambda d: d.read(64, timeout_ms=2000))

        # Método 2: write() SIN Report ID + read()
        try_method(dev, "Método 2: write(sin ReportID) + read()",
                   write_func=lambda d: d.write(list(GET_SN_CMD.ljust(64, b'\x00'))),
                   read_func=lambda d: d.read(64, timeout_ms=2000))

        # Método 3: write() con Report ID 0x00 (solo cmd, 8 bytes) + read()
        try_method(dev, "Método 3: write(ReportID=0x00, 8B) + read()",
                   write_func=lambda d: d.write(list(bytes([0x00]) + GET_SN_CMD.ljust(7, b'\x00'))),
                   read_func=lambda d: d.read(64, timeout_ms=2000))

        # Método 4: send_feature_report() + get_feature_report()
        try_method(dev, "Método 4: send_feature_report + get_feature_report",
                   write_func=lambda d: d.send_feature_report(
                       list(bytes([0x00]) + GET_SN_CMD.ljust(63, b'\x00'))),
                   read_func=lambda d: d.get_feature_report(0x00, 64))

        # Método 5: write() + get_input_report() (control transfer)
        try_method(dev, "Método 5: write(ReportID=0x00) + get_input_report()",
                   write_func=lambda d: d.write(list(bytes([0x00]) + GET_SN_CMD.ljust(63, b'\x00'))),
                   read_func=lambda d: d.get_input_report(0x00, 64))

        # Método 6: Solo read() sin write (por si envía datos espontáneamente)
        print(f"\n  Método 6: Solo read() pasivo (2 segundos)...")
        print("  (Pasa una pulsera por el lector ahora si quieres)")
        try:
            dev.set_nonblocking(False)
            data = dev.read(64, timeout_ms=2000)
            if data:
                raw = bytes(data)
                print(f"    [DATA] {len(raw)} bytes: {raw.rstrip(b'\\x00').hex(' ').upper()}")
                analyze_response(raw)
            else:
                print(f"    [TIMEOUT] Sin datos en 2s")
        except OSError as e:
            print(f"    [ERROR] {e}")
        except Exception as e:
            print(f"    [ERROR] {type(e).__name__}: {e}")

        try:
            dev.close()
        except Exception:
            pass

    print("\n" + "=" * 70)
    print("DIAGNÓSTICO COMPLETO")
    print("=" * 70)
    print("\nSi algún método respondió con datos del protocolo RD200")
    print("(STX=0x02, CMD=0x0D, STATUS=0x00), ese es el método correcto.")
    print("\nSi solo el Método 6 (pasivo) funcionó, el lector solo emite")
    print("keyboard reports y necesita cambio de modo USB.")


def try_method(dev, name, write_func, read_func):
    """Prueba un método de comunicación específico."""
    print(f"\n  {name}...")

    # Write
    try:
        result = write_func(dev)
        print(f"    [WRITE OK] retorno={result}")
    except OSError as e:
        print(f"    [WRITE FAIL] OSError: {e}")
        return
    except Exception as e:
        print(f"    [WRITE FAIL] {type(e).__name__}: {e}")
        return

    # Pequeña pausa para que el lector procese
    time.sleep(0.05)

    # Read
    try:
        data = read_func(dev)
        if data:
            raw = bytes(data)
            trimmed = raw.rstrip(b'\x00')
            if trimmed:
                print(f"    [READ OK] {len(trimmed)} bytes: {trimmed.hex(' ').upper()}")
                analyze_response(raw)
            else:
                print(f"    [READ OK] Solo zeros (padding)")
        else:
            print(f"    [READ TIMEOUT] Sin respuesta")
    except OSError as e:
        print(f"    [READ FAIL] OSError: {e}")
    except Exception as e:
        print(f"    [READ FAIL] {type(e).__name__}: {e}")


def analyze_response(raw: bytes):
    """Intenta parsear la respuesta como protocolo RD200."""
    # Buscar STX
    for offset in range(min(3, len(raw))):
        if raw[offset] == 0x02:
            if len(raw) > offset + 3:
                msg_len = raw[offset + 1]
                cmd = raw[offset + 2]
                status = raw[offset + 3]

                cmd_names = {
                    0x01: "ReadTag", 0x02: "Action", 0x03: "SetParam",
                    0x0D: "GetSerial", 0x0E: "GetVersion", 0x0F: "System",
                    0x11: "MifareUID", 0x15: "ReadData", 0x16: "WriteData",
                }
                status_names = {0x00: "OK", 0x01: "NoCard", 0x10: "CmdError"}

                cmd_name = cmd_names.get(cmd, f"0x{cmd:02X}")
                status_name = status_names.get(status, f"0x{status:02X}")

                print(f"    >>> PROTOCOLO RD200 DETECTADO <<<")
                print(f"    >>> offset={offset}, LEN={msg_len}, CMD={cmd_name}, STATUS={status_name}")

                if cmd == 0x0D and status == 0x00:
                    data_start = offset + 4
                    data_len = msg_len - 2
                    if data_len > 0 and len(raw) >= data_start + data_len:
                        sn = raw[data_start:data_start + data_len]
                        print(f"    >>> SERIAL NUMBER: {sn.decode('ascii', errors='replace')}")
                return

    # No encontró protocolo RD200 - podría ser keyboard report
    trimmed = raw.rstrip(b'\x00')
    if len(trimmed) <= 8:
        print(f"    (Posible keyboard report: mod=0x{trimmed[0]:02X})")


if __name__ == "__main__":
    main()
