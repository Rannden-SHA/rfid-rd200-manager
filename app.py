#!/usr/bin/env python3
# =============================================================================
# app.py  —  Punto de entrada principal
#
# Uso como GUI:
#   "RFID Manager.exe"
#   "RFID Manager.exe" --theme light
#
# Uso como CLI (aplicar perfil JSON a un lector conectado, sin GUI):
#   "RFID Manager.exe" --apply-profile config.json
#   "RFID Manager.exe" --apply-profile config.json --wait 10
#   "RFID Manager.exe" --apply-profile config.json --wait 30 --retries 5
#
# Diagnóstico:
#   "RFID Manager.exe" --list-devices
#   "RFID Manager.exe" --debug
# =============================================================================

import sys
import os
import argparse
import json
import logging
import time

from utils.logger import setup_logging


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="RFID Manager",
        description="RFID Wristband Manager para el lector RD200-M1-G",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  "RFID Manager.exe"                                        Abre la GUI
  "RFID Manager.exe" --apply-profile perfil.json            Aplica perfil y sale
  "RFID Manager.exe" --apply-profile perfil.json --wait 30  Espera hasta 30s al lector
  "RFID Manager.exe" --list-devices                         Lista dispositivos HID
  "RFID Manager.exe" --debug                                GUI con log DEBUG
        """
    )

    # --- GUI / General ---
    parser.add_argument(
        "--theme",
        choices=["dark", "light", "system"],
        default=None,
        help="Tema de la interfaz grafica"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Activar logging de nivel DEBUG en consola"
    )
    parser.add_argument(
        "--no-gui",
        action="store_true",
        help="No abrir la GUI"
    )

    # --- Aplicar perfil (modo CLI principal) ---
    profile_group = parser.add_argument_group("Aplicar perfil de configuracion")
    profile_group.add_argument(
        "--apply-profile",
        metavar="PERFIL.json",
        help="Ruta al archivo JSON con el perfil de configuracion a aplicar"
    )
    profile_group.add_argument(
        "--wait",
        type=int,
        default=10,
        metavar="SEGUNDOS",
        help="Tiempo maximo de espera para encontrar el lector (default: 10s)"
    )
    profile_group.add_argument(
        "--retries",
        type=int,
        default=3,
        metavar="N",
        help="Numero de reintentos de conexion (default: 3)"
    )

    # --- Configuracion legacy ---
    reader_group = parser.add_argument_group("Configuracion del Lector (legacy)")
    reader_group.add_argument(
        "--config-reader",
        action="store_true",
        help="Aplicar configuracion al lector antes de abrir la GUI"
    )
    reader_group.add_argument("--beep", choices=["on", "off"], default=None)
    reader_group.add_argument("--keyboard-emulation", choices=["on", "off"], default=None)
    reader_group.add_argument("--id-format", default=None)
    reader_group.add_argument("--save", action="store_true")

    # --- Diagnostico ---
    diag_group = parser.add_argument_group("Diagnostico")
    diag_group.add_argument(
        "--list-devices",
        action="store_true",
        help="Listar todos los dispositivos HID conectados y salir"
    )

    return parser.parse_args()


def cmd_list_devices():
    """Imprime todos los dispositivos HID conectados."""
    from core.reader_manager import ReaderManager
    devices = ReaderManager.list_hid_devices()
    if not devices:
        print("No se encontraron dispositivos HID.")
        return

    print(f"\n{'VID':>8}  {'PID':>8}  {'Fabricante':<28}  Producto")
    print("-" * 80)
    for d in devices:
        vid = f"{d.get('vendor_id', 0):#06x}"
        pid = f"{d.get('product_id', 0):#06x}"
        mfr = d.get("manufacturer_string", "")[:28]
        prod = d.get("product_string", "")[:36]
        marker = "  <<< RD200-M1-G" if (
            d.get("vendor_id") == ReaderManager.VID
            and d.get("product_id") == ReaderManager.PID
        ) else ""
        print(f"{vid}  {pid}  {mfr:<28}  {prod}{marker}")
    print()


def cmd_apply_profile(profile_path: str, wait_s: int = 10, retries: int = 3) -> bool:
    """
    Modo CLI: aplica un perfil JSON al lector conectado.
    Espera hasta wait_s segundos a que el lector esté disponible.
    Retorna True si fue exitoso.
    """
    from core.reader_manager import ReaderManager, ReaderConnectionError

    # 1. Cargar perfil JSON
    if not os.path.isabs(profile_path):
        # Buscar relativo al exe o al directorio actual
        if getattr(sys, 'frozen', False):
            base = os.path.dirname(sys.executable)
        else:
            base = os.getcwd()
        profile_path = os.path.join(base, profile_path)

    if not os.path.exists(profile_path):
        print(f"[ERROR] Perfil no encontrado: {profile_path}")
        return False

    try:
        with open(profile_path, "r", encoding="utf-8") as f:
            profile = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"[ERROR] No se pudo leer el perfil: {e}")
        return False

    # Mostrar info del perfil
    meta = profile.get("_meta", {})
    print("=" * 60)
    print("  RFID Manager - Aplicar Perfil de Configuracion")
    print("=" * 60)
    print(f"  Perfil: {os.path.basename(profile_path)}")
    if meta:
        print(f"  Origen: SN {meta.get('source_serial', meta.get('serial_number', '?'))}")
        print(f"  Modelo: {meta.get('model_version', '?')}")
        print(f"  Creado: {meta.get('created', '?')[:19]}")
    print(f"  Timeout: {wait_s}s | Reintentos: {retries}")
    print()

    # 2. Conectar al lector (con reintentos)
    reader = ReaderManager()
    connected = False
    deadline = time.time() + wait_s

    attempt = 0
    while attempt < retries and time.time() < deadline:
        attempt += 1
        remaining = max(1, int(deadline - time.time()))
        print(f"  [{attempt}/{retries}] Buscando lector... ({remaining}s restantes)")

        try:
            reader.connect()
            connected = True
            break
        except ReaderConnectionError:
            if attempt < retries and time.time() < deadline:
                sleep_time = min(2, deadline - time.time())
                if sleep_time > 0:
                    time.sleep(sleep_time)

    if not connected:
        print(f"\n[ERROR] No se encontro ningun lector RD200 en {wait_s} segundos.")
        print("  Verifica que el lector este conectado por USB.")
        return False

    sn = reader.serial_number or "desconocido"
    mode = "COMANDO" if reader.in_command_mode else "PASIVO"
    print(f"\n  Lector conectado!")
    print(f"  SN: {sn}")
    print(f"  Modo: {mode}")

    if not reader.in_command_mode:
        print(f"\n[ERROR] Lector en modo PASIVO - no acepta comandos de configuracion.")
        reader.disconnect()
        return False

    # 3. Aplicar perfil
    print(f"\n  Aplicando configuracion...")

    try:
        results = reader.apply_config_profile(profile)
    except Exception as e:
        print(f"\n[ERROR] Error aplicando perfil: {e}")
        reader.disconnect()
        return False

    # 4. Mostrar resultados
    ok_count = sum(1 for v in results.values() if v)
    fail_count = sum(1 for v in results.values() if not v)

    print()
    for param, success in results.items():
        status = "OK" if success else "FALLO"
        symbol = "+" if success else "!"
        print(f"  [{symbol}] {param:<25} {status}")

    print()

    if fail_count == 0:
        print(f"  RESULTADO: {ok_count}/{ok_count} parametros aplicados correctamente")
        # Beep de confirmacion
        try:
            reader.reader_action(0x02)  # Beep + LED verde
        except Exception:
            pass
    else:
        print(f"  RESULTADO: {ok_count} OK, {fail_count} ERRORES")

    # 5. Limpiar
    reader.disconnect()
    print(f"\n  Lector desconectado. Listo.")
    print("=" * 60)

    return fail_count == 0


def cmd_configure_reader(args: argparse.Namespace):
    """Legacy: configurar lector con parametros individuales."""
    from core.reader_manager import ReaderManager, ReaderConnectionError

    reader = ReaderManager()
    try:
        reader.connect()
    except ReaderConnectionError as e:
        print(f"[ERROR] No se pudo conectar: {e}")
        return False

    beep = None if args.beep is None else (args.beep == "on")
    kb_emu = None if args.keyboard_emulation is None else (args.keyboard_emulation == "on")
    id_fmt = args.id_format

    if beep is None and kb_emu is None and id_fmt is None:
        print("[AVISO] No se especifico ningun parametro.")
        reader.disconnect()
        return True

    try:
        results = reader.apply_reader_config(
            beep=beep, keyboard_emulation=kb_emu,
            id_format=id_fmt, save=args.save)
    except Exception as e:
        print(f"[ERROR] {e}")
        reader.disconnect()
        return False
    finally:
        reader.disconnect()

    all_ok = all(results.values())
    for key, ok in results.items():
        print(f"  {key:<25} {'OK' if ok else 'FALLO'}")
    return all_ok


def _hide_console():
    """Oculta la ventana de consola en Windows (modo GUI)."""
    if sys.platform == "win32":
        try:
            import ctypes
            hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE
        except Exception:
            pass


def launch_gui(args: argparse.Namespace):
    """Lanza la ventana principal de la aplicacion."""
    _hide_console()

    import customtkinter as ctk
    from gui.main_window import MainWindow

    if args.theme:
        ctk.set_appearance_mode(args.theme)

    app = MainWindow()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()


def main():
    args = parse_args()

    # Configurar logging
    log_level = "DEBUG" if args.debug else "INFO"
    setup_logging(level=log_level)

    logger = logging.getLogger(__name__)
    logger.debug(f"Argumentos: {args}")

    # --- Modo: listar dispositivos ---
    if args.list_devices:
        cmd_list_devices()
        sys.exit(0)

    # --- Modo: aplicar perfil (CLI principal) ---
    if args.apply_profile:
        success = cmd_apply_profile(
            args.apply_profile,
            wait_s=args.wait,
            retries=args.retries
        )
        sys.exit(0 if success else 1)

    # --- Modo: configurar lector legacy ---
    if args.config_reader:
        success = cmd_configure_reader(args)
        if args.no_gui:
            sys.exit(0 if success else 1)

    # --- Modo: GUI ---
    if not args.no_gui:
        launch_gui(args)


if __name__ == "__main__":
    main()
