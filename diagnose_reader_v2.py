#!/usr/bin/env python3
"""
Diagnostico v2: prueba comunicacion cruzada entre interfaces
y usa ctypes para Windows HID API directa.
"""

import sys
import time
import ctypes
from ctypes import wintypes

VID = 0x0E6A
PID = 0x0317

# Comando Get S/N: [STX=0x02][LEN=0x01][CMD=0x0D]
GET_SN_CMD = bytes([0x02, 0x01, 0x0D])


def main():
    try:
        import hid
    except ImportError:
        print("ERROR: pip install hidapi")
        sys.exit(1)

    interfaces = [d for d in hid.enumerate()
                  if d["vendor_id"] == VID and d["product_id"] == PID]

    if not interfaces:
        print("No se encontro el lector RD200.")
        sys.exit(1)

    print("=" * 70)
    print("DIAGNOSTICO V2 - RD200-M1-G")
    print("=" * 70)

    for i, intf in enumerate(interfaces):
        print(f"  [{i}] intf={intf.get('interface_number','?')} "
              f"usage_page=0x{intf.get('usage_page',0):04X} "
              f"usage=0x{intf.get('usage',0):04X}")

    # ================================================================
    # TEST 1: Feature report como canal de comandos (Interface 0)
    # ================================================================
    print("\n" + "=" * 70)
    print("TEST 1: Feature report como canal de comandos (Interface 0)")
    print("=" * 70)

    intf0 = interfaces[0]
    dev0 = hid.device()
    try:
        dev0.open_path(intf0["path"])
        print("Interface 0 abierta.")

        # Leer feature report ANTES del comando
        pre_data = dev0.get_feature_report(0x00, 64)
        pre = bytes(pre_data) if pre_data else b""
        print(f"\n  Feature report ANTES: {pre.hex(' ').upper()[:80]}...")

        # Enviar comando via feature report
        # Probar con el comando embebido en diferentes posiciones
        for label, payload in [
            ("CMD en pos 0", GET_SN_CMD.ljust(64, b'\x00')),
            ("ReportID+CMD", bytes([0x00]) + GET_SN_CMD.ljust(63, b'\x00')),
        ]:
            print(f"\n  Enviando {label}...")
            try:
                r = dev0.send_feature_report(list(payload))
                print(f"    send_feature_report retorno: {r}")
                time.sleep(0.2)

                post_data = dev0.get_feature_report(0x00, 64)
                post = bytes(post_data) if post_data else b""
                print(f"    Feature report DESPUES: {post.hex(' ').upper()[:80]}...")

                if post != pre:
                    print(f"    >>> DATOS CAMBIARON! <<<")
                    # Verificar si contiene respuesta RD200
                    for off in range(min(4, len(post))):
                        if off < len(post) and post[off] == 0x02:
                            print(f"    >>> Posible STX en offset {off}")
                            if len(post) > off + 3:
                                print(f"    >>> LEN={post[off+1]} CMD=0x{post[off+2]:02X} "
                                      f"STATUS=0x{post[off+3]:02X}")
                else:
                    print(f"    Feature report no cambio.")
            except Exception as e:
                print(f"    Error: {e}")

        dev0.close()
    except Exception as e:
        print(f"  Error abriendo interface 0: {e}")

    # ================================================================
    # TEST 2: Enviar en Interface 1, leer en Interface 0 (feature)
    # ================================================================
    print("\n" + "=" * 70)
    print("TEST 2: Escribir en Interface 1 Col01, leer feature de Interface 0")
    print("=" * 70)

    if len(interfaces) >= 2:
        try:
            dev0 = hid.device()
            dev0.open_path(interfaces[0]["path"])

            dev1 = hid.device()
            dev1.open_path(interfaces[1]["path"])

            # Leer feature report antes
            pre_data = dev0.get_feature_report(0x00, 64)
            pre = bytes(pre_data) if pre_data else b""
            print(f"  Feature pre:  {pre.hex(' ').upper()[:80]}...")

            # Escribir en interface 1 SIN report ID (que funciono en v1)
            payload = GET_SN_CMD.ljust(64, b'\x00')
            r = dev1.write(list(payload))
            print(f"  Write en intf1 (sin ReportID): retorno={r}")
            time.sleep(0.3)

            # Leer feature report despues
            post_data = dev0.get_feature_report(0x00, 64)
            post = bytes(post_data) if post_data else b""
            print(f"  Feature post: {post.hex(' ').upper()[:80]}...")

            if post != pre:
                print(f"  >>> DATOS CAMBIARON! <<<")
                for off in range(min(4, len(post))):
                    if off < len(post) and post[off] == 0x02:
                        if len(post) > off + 3:
                            print(f"  >>> offset={off} LEN={post[off+1]} "
                                  f"CMD=0x{post[off+2]:02X} STATUS=0x{post[off+3]:02X}")

            # Tambien leer de interface 1 y 2
            for idx in range(1, len(interfaces)):
                try:
                    if idx == 1:
                        data = dev1.read(64, timeout_ms=500)
                    else:
                        dev_x = hid.device()
                        dev_x.open_path(interfaces[idx]["path"])
                        data = dev_x.read(64, timeout_ms=500)
                        dev_x.close()
                    if data:
                        print(f"  Read intf[{idx}]: {bytes(data).rstrip(b'\\x00').hex(' ').upper()}")
                    else:
                        print(f"  Read intf[{idx}]: timeout")
                except Exception as e:
                    print(f"  Read intf[{idx}]: {e}")

            dev0.close()
            dev1.close()
        except Exception as e:
            print(f"  Error: {e}")

    # ================================================================
    # TEST 3: ctypes Windows HID API directa
    # ================================================================
    print("\n" + "=" * 70)
    print("TEST 3: Windows HID API directa (ctypes)")
    print("=" * 70)

    try:
        test_ctypes_hid(interfaces)
    except Exception as e:
        print(f"  Error: {e}")
        import traceback
        traceback.print_exc()

    # ================================================================
    # TEST 4: Diferentes Report IDs en Interface 1
    # ================================================================
    print("\n" + "=" * 70)
    print("TEST 4: Diferentes Report IDs en Interface 1 Col01")
    print("=" * 70)

    if len(interfaces) >= 2:
        try:
            dev1 = hid.device()
            dev1.open_path(interfaces[1]["path"])

            for report_id in [0x00, 0x01, 0x02, 0x03]:
                payload = bytes([report_id]) + GET_SN_CMD.ljust(63, b'\x00')
                try:
                    r = dev1.write(list(payload))
                    print(f"  ReportID=0x{report_id:02X}: write retorno={r}", end="")
                    if r > 0:
                        time.sleep(0.1)
                        data = dev1.read(64, timeout_ms=1000)
                        if data:
                            raw = bytes(data)
                            print(f"  READ: {raw.rstrip(b'\\x00').hex(' ').upper()}")
                        else:
                            print(f"  read timeout")
                    else:
                        print()
                except Exception as e:
                    print(f"  ReportID=0x{report_id:02X}: {e}")

            dev1.close()
        except Exception as e:
            print(f"  Error: {e}")

    # ================================================================
    # TEST 5: Probar con Interface 1 Col02 (System Control)
    # ================================================================
    if len(interfaces) >= 3:
        print("\n" + "=" * 70)
        print("TEST 5: Interface 1 Col02 (System Control 0x0080)")
        print("=" * 70)

        try:
            dev2 = hid.device()
            dev2.open_path(interfaces[2]["path"])

            for report_id in [0x00, 0x01, 0x02]:
                payload = bytes([report_id]) + GET_SN_CMD.ljust(63, b'\x00')
                try:
                    r = dev2.write(list(payload))
                    print(f"  ReportID=0x{report_id:02X}: write={r}", end="")
                    if r > 0:
                        time.sleep(0.1)
                        data = dev2.read(64, timeout_ms=1000)
                        if data:
                            print(f"  READ: {bytes(data).rstrip(b'\\x00').hex(' ').upper()}")
                        else:
                            print(f"  read timeout")
                    else:
                        print()
                except Exception as e:
                    print(f"  ReportID=0x{report_id:02X}: {e}")

            # Probar feature reports
            for report_id in [0x00, 0x01, 0x02]:
                try:
                    payload = bytes([report_id]) + GET_SN_CMD.ljust(63, b'\x00')
                    r = dev2.send_feature_report(list(payload))
                    print(f"  Feature send ReportID=0x{report_id:02X}: retorno={r}", end="")
                    if r > 0:
                        time.sleep(0.1)
                        data = dev2.get_feature_report(report_id, 64)
                        if data:
                            print(f"  READ: {bytes(data).rstrip(b'\\x00').hex(' ').upper()}")
                        else:
                            print(f"  no data")
                    else:
                        print()
                except Exception as e:
                    print(f"  Feature ReportID=0x{report_id:02X}: {e}")

            dev2.close()
        except Exception as e:
            print(f"  Error: {e}")

    print("\n" + "=" * 70)
    print("DIAGNOSTICO V2 COMPLETO")
    print("=" * 70)


def test_ctypes_hid(interfaces):
    """Usa ctypes para llamar a Windows HID API directamente."""

    GENERIC_READ = 0x80000000
    GENERIC_WRITE = 0x40000000
    FILE_SHARE_READ = 0x00000001
    FILE_SHARE_WRITE = 0x00000002
    OPEN_EXISTING = 3
    INVALID_HANDLE = wintypes.HANDLE(-1).value

    kernel32 = ctypes.windll.kernel32
    CreateFileW = kernel32.CreateFileW
    CreateFileW.restype = wintypes.HANDLE
    CloseHandle = kernel32.CloseHandle

    # HidD functions
    try:
        hid_dll = ctypes.windll.hid
    except OSError:
        print("  No se pudo cargar hid.dll")
        return

    HidD_SetOutputReport = hid_dll.HidD_SetOutputReport
    HidD_SetOutputReport.restype = wintypes.BOOL
    HidD_SetOutputReport.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]

    HidD_GetInputReport = hid_dll.HidD_GetInputReport
    HidD_GetInputReport.restype = wintypes.BOOL
    HidD_GetInputReport.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]

    HidD_GetAttributes = hid_dll.HidD_GetAttributes

    class HIDD_ATTRIBUTES(ctypes.Structure):
        _fields_ = [
            ("Size", wintypes.ULONG),
            ("VendorID", ctypes.c_ushort),
            ("ProductID", ctypes.c_ushort),
            ("VersionNumber", ctypes.c_ushort),
        ]

    for i, intf in enumerate(interfaces):
        path = intf.get("path", b"")
        if isinstance(path, bytes):
            path_str = path.decode("utf-8", errors="replace")
        else:
            path_str = str(path)

        intf_num = intf.get("interface_number", "?")
        usage_page = intf.get("usage_page", 0)

        print(f"\n  Interface [{i}] (intf={intf_num}, 0x{usage_page:04X}) via ctypes:")

        # Abrir dispositivo
        handle = CreateFileW(
            path_str,
            GENERIC_READ | GENERIC_WRITE,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            None,
            OPEN_EXISTING,
            0,
            None
        )

        if handle == INVALID_HANDLE or handle == 0:
            err = ctypes.get_last_error() or kernel32.GetLastError()
            print(f"    CreateFile fallo (error={err})")
            continue

        print(f"    CreateFile OK (handle={handle})")

        # Verificar atributos
        attrs = HIDD_ATTRIBUTES()
        attrs.Size = ctypes.sizeof(HIDD_ATTRIBUTES)
        if HidD_GetAttributes(handle, ctypes.byref(attrs)):
            print(f"    VID=0x{attrs.VendorID:04X} PID=0x{attrs.ProductID:04X} "
                  f"Ver=0x{attrs.VersionNumber:04X}")

        # Probar HidD_SetOutputReport + HidD_GetInputReport
        # Buffer: Report ID (1 byte) + data
        report_size = 65  # Report ID + 64 bytes
        for report_id in [0x00, 0x01, 0x02]:
            out_buf = (ctypes.c_ubyte * report_size)()
            out_buf[0] = report_id
            cmd = GET_SN_CMD
            for j, b in enumerate(cmd):
                if j + 1 < report_size:
                    out_buf[j + 1] = b

            ok = HidD_SetOutputReport(handle, ctypes.byref(out_buf), report_size)
            err = kernel32.GetLastError() if not ok else 0
            print(f"    SetOutputReport(ReportID=0x{report_id:02X}): "
                  f"{'OK' if ok else f'FAIL (err={err})'}", end="")

            if ok:
                time.sleep(0.1)
                in_buf = (ctypes.c_ubyte * report_size)()
                in_buf[0] = report_id
                ok2 = HidD_GetInputReport(handle, ctypes.byref(in_buf), report_size)
                err2 = kernel32.GetLastError() if not ok2 else 0
                if ok2:
                    raw = bytes(in_buf)
                    trimmed = raw.rstrip(b'\x00')
                    print(f"  GetInputReport: {trimmed.hex(' ').upper()}")

                    # Buscar protocolo RD200
                    for off in range(min(4, len(raw))):
                        if raw[off] == 0x02 and len(raw) > off + 3:
                            cmd_byte = raw[off + 2]
                            status = raw[off + 3]
                            if cmd_byte == 0x0D:
                                print(f"    >>> GET_SERIAL RESPONSE! STATUS=0x{status:02X}")
                                if status == 0x00:
                                    data_start = off + 4
                                    data_len = raw[off + 1] - 2
                                    if data_len > 0:
                                        sn = raw[data_start:data_start+data_len]
                                        print(f"    >>> SERIAL: {sn.decode('ascii', errors='replace')}")
                else:
                    print(f"  GetInputReport: FAIL (err={err2})")
            else:
                print()

        CloseHandle(handle)


if __name__ == "__main__":
    main()
