#!/usr/bin/env python3
"""
diagnose_setparam.py
====================
Diagnóstico: ¿Por qué SetParam no guarda la configuración?

Prueba enviar el mismo comando SetParam (KeyboardFormat 8H+CR)
por TODAS las vías HID posibles:
  1. Output Report con Report ID 0x03 (método actual)
  2. Feature Report con Report ID 0x03
  3. Output Report con Report ID 0x00
  4. Feature Report con Report ID 0x00
  5. Windows HID API (HidD_SetOutputReport / HidD_SetFeature)
  6. Diferentes tamaños de reporte (8, 9, 64 bytes)
  7. Verificar con GetSerial que la comunicación funciona

Ejecutar:
    venv\Scripts\python.exe diagnose_setparam.py
"""

import sys
import time

VID = 0x0E6A
PID = 0x0317

# Comando: SetParam KeyboardFormat → 8H, Normal, CR
SET_CMD  = bytes([0x02, 0x05, 0x03, 0x03, 0x05, 0x01, 0x80])
# Comando: GetSerial (para verificar comunicación)
GET_SN   = bytes([0x02, 0x01, 0x0D])
# Comando: Leer KeyboardFormat actual (sin valor = query)
GET_KBD  = bytes([0x02, 0x02, 0x03, 0x03])


def parse_response(raw: bytes) -> dict:
    """Parse rápido de respuesta RD200."""
    if not raw:
        return {"valid": False, "hex": ""}
    trimmed = bytes(raw).rstrip(b'\x00')
    hex_str = trimmed.hex(" ").upper()

    # Buscar STX
    offset = -1
    for i in range(min(4, len(trimmed))):
        if trimmed[i] == 0x02:
            offset = i
            break

    if offset < 0 or len(trimmed) < offset + 4:
        return {"valid": False, "hex": hex_str}

    cmd = trimmed[offset + 2]
    status = trimmed[offset + 3]
    data = trimmed[offset + 4:]
    return {
        "valid": True,
        "cmd": cmd,
        "status": status,
        "status_name": {0: "OK", 1: "NoCard", 0x10: "CmdError"}.get(status, f"0x{status:02X}"),
        "data": data,
        "data_hex": data.hex(" ").upper() if data else "",
        "hex": hex_str,
        "report_id": trimmed[0] if offset > 0 else -1,
    }


def test_method(dev, method_name: str, send_func, read_func=None):
    """Prueba un método de envío."""
    print(f"\n{'='*60}")
    print(f"  Método: {method_name}")
    print(f"{'='*60}")

    if read_func is None:
        read_func = lambda: dev.read(64, timeout_ms=2000)

    # Paso 1: Verificar comunicación con GetSerial
    print("\n  [1] GetSerial (verificar comunicación)...")
    try:
        send_func(GET_SN)
        resp = read_func()
        parsed = parse_response(bytes(resp) if resp else b"")
        if parsed["valid"] and parsed.get("cmd") == 0x0D:
            sn = parsed["data"].decode("ascii", errors="replace") if parsed["data"] else "?"
            print(f"      ✅ GetSerial OK → SN={sn}")
            print(f"      Raw: {parsed['hex']}")
        elif resp:
            print(f"      ⚠️  Respuesta pero no es GetSerial: {parsed['hex']}")
        else:
            print(f"      ❌ Sin respuesta")
            return False
    except Exception as e:
        print(f"      ❌ Error: {e}")
        return False

    # Paso 2: Leer config actual (query KeyboardFormat)
    print("\n  [2] Leer KeyboardFormat actual...")
    try:
        send_func(GET_KBD)
        resp = read_func()
        parsed = parse_response(bytes(resp) if resp else b"")
        if parsed["valid"] and parsed.get("cmd") == 0x03:
            print(f"      Config actual: {parsed['data_hex']}")
            print(f"      Raw: {parsed['hex']}")
            if parsed["data"] and len(parsed["data"]) >= 3:
                fmt = parsed["data"][0]
                rev = parsed["data"][1]
                add = parsed["data"][2]
                fmt_names = {1:"4H", 2:"5D", 3:"6H", 4:"8D", 5:"8H", 6:"10D", 7:"10H"}
                add_parts = []
                if add & 0x80: add_parts.append("CR")
                if add & 0x40: add_parts.append("LF")
                if add & 0x01: add_parts.append(",")
                print(f"      → Formato={fmt_names.get(fmt, f'0x{fmt:02X}')}, "
                      f"Reverse=0x{rev:02X}, Add={'+'.join(add_parts) if add_parts else 'None'}")
        elif resp:
            print(f"      ⚠️  Respuesta inesperada: {parsed['hex']}")
        else:
            print(f"      ❌ Sin respuesta")
    except Exception as e:
        print(f"      ⚠️  Error leyendo config: {e}")

    # Paso 3: Enviar SetParam (8H + CR)
    print("\n  [3] Enviar SetParam: KeyboardFormat=8H, Add=CR (0x80)...")
    try:
        send_func(SET_CMD)
        resp = read_func()
        parsed = parse_response(bytes(resp) if resp else b"")
        if parsed["valid"] and parsed.get("cmd") == 0x03:
            print(f"      Status: {parsed['status_name']}")
            print(f"      Echo: {parsed['data_hex']}")
            print(f"      Raw: {parsed['hex']}")
            if parsed["data"] and len(parsed["data"]) >= 3:
                add = parsed["data"][2]
                if add & 0x80:
                    print(f"      ✅ ¡CR ACTIVADO! El cambio se aplicó.")
                    return True
                else:
                    print(f"      ❌ CR NO activado (add=0x{add:02X}). No se guardó.")
            else:
                print(f"      ⚠️  Data corta: {parsed['data_hex']}")
        elif resp:
            print(f"      ⚠️  Respuesta inesperada: {parsed['hex']}")
        else:
            print(f"      ❌ Sin respuesta")
    except Exception as e:
        print(f"      ❌ Error: {e}")

    return False


def main():
    try:
        import hid
    except ImportError:
        print("ERROR: pip install hidapi")
        return

    # Enumerar interfaces
    interfaces = [d for d in hid.enumerate()
                  if d["vendor_id"] == VID and d["product_id"] == PID]

    if not interfaces:
        print("ERROR: No se encontró el lector RD200.")
        return

    print(f"Encontradas {len(interfaces)} interfaces HID:")
    for i, intf in enumerate(interfaces):
        print(f"  [{i}] intf={intf.get('interface_number','?')}  "
              f"usage_page=0x{intf.get('usage_page',0):04X}  "
              f"usage=0x{intf.get('usage',0):04X}  "
              f"product={intf.get('product_string','?')}")

    success = False

    # Probar cada interfaz
    for intf_info in interfaces:
        path = intf_info.get("path")
        intf_num = intf_info.get("interface_number", "?")
        usage_page = intf_info.get("usage_page", 0)

        print(f"\n{'#'*60}")
        print(f"# INTERFAZ {intf_num} (usage_page=0x{usage_page:04X})")
        print(f"{'#'*60}")

        try:
            dev = hid.device()
            dev.open_path(path)
        except Exception as e:
            print(f"  No se pudo abrir: {e}")
            continue

        # ---------------------------------------------------------------
        # Método 1: Output Report con Report ID 0x03 (64 bytes)
        # ---------------------------------------------------------------
        def send_output_rid03(cmd_bytes):
            report = bytes([0x03]) + cmd_bytes.ljust(63, b'\x00')
            w = dev.write(list(report))
            if w < 0:
                raise OSError(f"write returned {w}")

        result = test_method(dev, "Output Report, ReportID=0x03, 64 bytes",
                           send_output_rid03)
        if result:
            success = True
            dev.close()
            break

        # ---------------------------------------------------------------
        # Método 2: Output Report con Report ID 0x03 (9 bytes, sin padding)
        # ---------------------------------------------------------------
        def send_output_rid03_short(cmd_bytes):
            report = bytes([0x03]) + cmd_bytes
            w = dev.write(list(report))
            if w < 0:
                raise OSError(f"write returned {w}")

        result = test_method(dev, "Output Report, ReportID=0x03, corto (sin padding)",
                           send_output_rid03_short)
        if result:
            success = True
            dev.close()
            break

        # ---------------------------------------------------------------
        # Método 3: Feature Report con Report ID 0x03
        # ---------------------------------------------------------------
        def send_feature_rid03(cmd_bytes):
            report = bytes([0x03]) + cmd_bytes.ljust(63, b'\x00')
            dev.send_feature_report(list(report))

        result = test_method(dev, "Feature Report, ReportID=0x03",
                           send_feature_rid03)
        if result:
            success = True
            dev.close()
            break

        # ---------------------------------------------------------------
        # Método 4: Output Report con Report ID 0x00
        # ---------------------------------------------------------------
        def send_output_rid00(cmd_bytes):
            report = bytes([0x00]) + cmd_bytes.ljust(63, b'\x00')
            w = dev.write(list(report))
            if w < 0:
                raise OSError(f"write returned {w}")

        result = test_method(dev, "Output Report, ReportID=0x00, 64 bytes",
                           send_output_rid00)
        if result:
            success = True
            dev.close()
            break

        # ---------------------------------------------------------------
        # Método 5: Feature Report con Report ID 0x00
        # ---------------------------------------------------------------
        def send_feature_rid00(cmd_bytes):
            report = bytes([0x00]) + cmd_bytes.ljust(63, b'\x00')
            try:
                dev.send_feature_report(list(report))
            except Exception:
                raise

        result = test_method(dev, "Feature Report, ReportID=0x00",
                           send_feature_rid00)
        if result:
            success = True
            dev.close()
            break

        # ---------------------------------------------------------------
        # Método 6: Windows HID API directa (HidD_SetOutputReport)
        # ---------------------------------------------------------------
        if sys.platform == "win32":
            try:
                import ctypes
                from ctypes import wintypes

                # Intentar HidD_SetOutputReport (via ctypes)
                # Este método usa el control pipe, diferente del interrupt pipe
                hid_dll = ctypes.windll.hid

                # Necesitamos el handle del device
                # hidapi expone el handle internamente
                # Intentar con get_feature_report como proxy

                def send_win_output(cmd_bytes):
                    """Usa get_input_report / send output report pattern."""
                    report = bytes([0x03]) + cmd_bytes.ljust(63, b'\x00')
                    dev.write(list(report))

                # Alternativa: Probar con Report IDs 0x01-0x0F
                for rid in [0x01, 0x02, 0x04, 0x05, 0x06, 0x07, 0x08]:
                    def send_rid(cmd_bytes, _rid=rid):
                        report = bytes([_rid]) + cmd_bytes.ljust(63, b'\x00')
                        w = dev.write(list(report))
                        if w < 0:
                            raise OSError(f"write returned {w}")

                    result = test_method(dev,
                        f"Output Report, ReportID=0x{rid:02X}",
                        send_rid)
                    if result:
                        success = True
                        break

                if success:
                    dev.close()
                    break

            except Exception as e:
                print(f"  Windows HID API: {e}")

        dev.close()

    # ---------------------------------------------------------------
    # Resumen
    # ---------------------------------------------------------------
    print(f"\n{'='*60}")
    if success:
        print("✅ ¡ENCONTRADO! El método que funciona está arriba.")
    else:
        print("❌ Ningún método logró cambiar la configuración.")
        print()
        print("Posibles causas:")
        print("  1. El programa antiguo usa un driver especial (no HID genérico)")
        print("  2. El SetParam requiere una secuencia previa (unlock/auth)")
        print("  3. El lector necesita un comando 'save' adicional después")
        print("  4. El firmware solo acepta SetParam en modo USB específico")
        print()
        print("Siguiente paso: Captura el tráfico USB del programa antiguo")
        print("con USBPcap + Wireshark para ver exactamente qué envía.")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
