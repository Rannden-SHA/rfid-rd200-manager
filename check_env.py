#!/usr/bin/env python3
"""
check_env.py  —  Verifica que el entorno esté correctamente configurado.
Ejecuta este script ANTES de app.py para diagnosticar problemas.

  python check_env.py
"""

import sys

REQUIRED = {
    "customtkinter": "customtkinter",
    "hidapi":        "hid",
    "pyusb":         "usb.core",
    "Pillow":        "PIL",
    "pyserial":      "serial",
}

print("=" * 60)
print("  RFID Wristband Manager — Verificación de Entorno")
print("=" * 60)
print(f"  Python: {sys.version}")
print()

all_ok = True
for package_name, import_name in REQUIRED.items():
    try:
        __import__(import_name)
        print(f"  ✓  {package_name:<20} OK")
    except ImportError:
        print(f"  ✗  {package_name:<20} NO INSTALADO  →  pip install {package_name}")
        all_ok = False

print()

# Buscar el lector
print("  Buscando lector RD200-M1-G...")
try:
    import hid  # type: ignore
    VID, PID = 0x0E6A, 0x0317
    found = False
    for d in hid.enumerate():
        if d["vendor_id"] == VID and d["product_id"] == PID:
            print(f"  ✓  Lector encontrado: {d.get('product_string', 'RD200-M1-G')}")
            print(f"     Path: {d.get('path', 'N/A')}")
            print(f"     Serial: {d.get('serial_number', 'N/A')}")
            found = True
    if not found:
        print(f"  ✗  Lector NO detectado (VID={VID:#06x}, PID={PID:#06x})")
        print("     → Verifica la conexión USB")
        print("     → En Windows: instala WinUSB/LibUSB con Zadig")
except ImportError:
    print("  -  hidapi no disponible, no se puede buscar el lector")

print()
if all_ok:
    print("  ✅  Entorno listo. Ejecuta: python app.py")
else:
    print("  ⚠   Instala las dependencias faltantes:")
    print("      pip install -r requirements.txt")
print("=" * 60)
