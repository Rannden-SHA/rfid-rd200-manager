#!/usr/bin/env python3
"""
build_exe.py - Script para construir el ejecutable .exe
Ejecutar: venv\\Scripts\\python.exe build_exe.py
"""

import os
import sys
import subprocess
import shutil

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(BASE_DIR, "dist")
BUILD_DIR = os.path.join(BASE_DIR, "build")
SPEC_FILE = os.path.join(BASE_DIR, "rfid_manager.spec")
ICON_PATH = os.path.join(BASE_DIR, "assets", "icons", "app_icon.ico")

def main():
    print("=" * 60)
    print("  RFID Manager - Build Executable")
    print("=" * 60)

    # 1. Verificar que el icono existe
    if not os.path.exists(ICON_PATH):
        print("\n[!] Icono no encontrado. Generando...")
        subprocess.run([sys.executable, os.path.join(BASE_DIR, "generate_icon.py")], check=True)

    # 2. Verificar PyInstaller
    try:
        import PyInstaller
        print(f"\nPyInstaller version: {PyInstaller.__version__}")
    except ImportError:
        print("\n[ERROR] PyInstaller no instalado. Ejecuta:")
        print("  venv\\Scripts\\pip.exe install pyinstaller")
        sys.exit(1)

    # 3. Limpiar builds anteriores
    print("\nLimpiando builds anteriores...")
    for d in [BUILD_DIR]:
        if os.path.exists(d):
            shutil.rmtree(d, ignore_errors=True)

    # 4. Ejecutar PyInstaller
    print("\nConstruyendo ejecutable...")
    print("  (esto puede tardar 1-3 minutos)\n")

    pyinstaller_path = os.path.join(BASE_DIR, "venv", "Scripts", "pyinstaller.exe")
    if not os.path.exists(pyinstaller_path):
        pyinstaller_path = "pyinstaller"

    cmd = [
        pyinstaller_path,
        SPEC_FILE,
        "--noconfirm",
        "--clean",
        "--workpath", BUILD_DIR,
        "--distpath", DIST_DIR,
    ]

    print(f"  Comando: {' '.join(cmd)}\n")

    result = subprocess.run(cmd, cwd=BASE_DIR)

    if result.returncode != 0:
        print("\n[ERROR] La construccion fallo. Revisa los errores arriba.")
        sys.exit(1)

    # 5. Verificar resultado
    exe_dir = os.path.join(DIST_DIR, "RFID Manager")
    exe_path = os.path.join(exe_dir, "RFID Manager.exe")

    if os.path.exists(exe_path):
        size_mb = os.path.getsize(exe_path) / (1024 * 1024)
        print("\n" + "=" * 60)
        print("  BUILD EXITOSO!")
        print("=" * 60)
        print(f"\n  Ejecutable: {exe_path}")
        print(f"  Tamano EXE: {size_mb:.1f} MB")

        # Calcular tamano total de la carpeta
        total = sum(
            os.path.getsize(os.path.join(dp, f))
            for dp, _, fn in os.walk(exe_dir)
            for f in fn
        )
        print(f"  Tamano total carpeta: {total / (1024*1024):.1f} MB")
        print(f"\n  Para ejecutar: \"{exe_path}\"")
        print(f"\n  Para distribuir: comprime la carpeta")
        print(f"    '{exe_dir}'")
        print(f"  como ZIP y compartela.")
    else:
        print(f"\n[ERROR] No se encontro el ejecutable en: {exe_path}")
        sys.exit(1)


if __name__ == "__main__":
    main()
