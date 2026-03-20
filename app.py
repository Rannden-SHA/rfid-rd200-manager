#!/usr/bin/env python3
# =============================================================================
# app.py  —  Punto de entrada principal
#
# Uso como GUI:
#   python app.py
#   python app.py --theme light
#
# Uso como CLI (configurar el lector sin abrir la GUI):
#   python app.py --config-reader --beep off
#   python app.py --config-reader --keyboard-emulation on --id-format 10D
#   python app.py --config-reader --beep on --keyboard-emulation off --save
#
# Diagnóstico:
#   python app.py --list-devices
#   python app.py --debug
# =============================================================================

import sys
import argparse
import logging

from utils.logger import setup_logging


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="rfid-manager",
        description="RFID Wristband Manager para el lector RD200-M1-G",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python app.py                                          # Abre la GUI
  python app.py --debug                                  # GUI con log DEBUG
  python app.py --list-devices                           # Lista HIDs conectados
  python app.py --config-reader --beep off               # Desactiva buzzer y abre GUI
  python app.py --config-reader --keyboard-emulation on --id-format 10D --no-gui
        """
    )

    # --- GUI / General ---
    parser.add_argument(
        "--theme",
        choices=["dark", "light", "system"],
        default=None,
        help="Tema de la interfaz gráfica (sobreescribe settings.json)"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Activar logging de nivel DEBUG en consola"
    )
    parser.add_argument(
        "--no-gui",
        action="store_true",
        help="No abrir la GUI (usar con --config-reader o --list-devices)"
    )

    # --- Configuración del lector ---
    reader_group = parser.add_argument_group("Configuración del Lector")
    reader_group.add_argument(
        "--config-reader",
        action="store_true",
        help="Aplicar configuración al lector antes de abrir la GUI"
    )
    reader_group.add_argument(
        "--beep",
        choices=["on", "off"],
        default=None,
        metavar="on|off",
        help="Activar o desactivar el buzzer del lector"
    )
    reader_group.add_argument(
        "--keyboard-emulation",
        choices=["on", "off"],
        default=None,
        metavar="on|off",
        help="Activar o desactivar la emulación de teclado HID"
    )
    reader_group.add_argument(
        "--id-format",
        choices=["10H", "10D", "13D", "10H-13D", "RAW"],
        default=None,
        metavar="FORMAT",
        help="Formato de salida del UID: 10H, 10D, 13D, 10H-13D, RAW"
    )
    reader_group.add_argument(
        "--save",
        action="store_true",
        help="Guardar la configuración en la EEPROM del lector"
    )

    # --- Diagnóstico ---
    diag_group = parser.add_argument_group("Diagnóstico")
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
        print("Asegúrate de que hidapi esté instalado: pip install hidapi")
        return

    print(f"\n{'VID':>8}  {'PID':>8}  {'Fabricante':<28}  Producto")
    print("-" * 80)
    for d in devices:
        vid = f"{d.get('vendor_id', 0):#06x}"
        pid = f"{d.get('product_id', 0):#06x}"
        mfr = d.get("manufacturer_string", "")[:28]
        prod = d.get("product_string", "")[:36]
        marker = "  ◄◄◄ RD200-M1-G" if (
            d.get("vendor_id") == ReaderManager.VID
            and d.get("product_id") == ReaderManager.PID
        ) else ""
        print(f"{vid}  {pid}  {mfr:<28}  {prod}{marker}")
    print()


def cmd_configure_reader(args: argparse.Namespace):
    """
    Conecta al lector, aplica la configuración especificada por CLI y desconecta.
    Retorna True si fue exitoso, False si hubo algún error.
    """
    from core.reader_manager import ReaderManager, ReaderConnectionError

    print(f"\nConectando al lector RD200-M1-G (VID={ReaderManager.VID:#06x}, "
          f"PID={ReaderManager.PID:#06x})...")

    reader = ReaderManager()
    try:
        reader.connect()
    except ReaderConnectionError as e:
        print(f"\n[ERROR] No se pudo conectar: {e}")
        print("Sugerencias:")
        print("  1. Verifica que el lector esté conectado por USB.")
        print("  2. En Windows: usa Zadig para instalar el driver WinUSB/LibUSB.")
        print("  3. Ejecuta: python app.py --list-devices  para ver dispositivos HID.")
        return False

    print("Lector conectado.")

    # Construir mapa de cambios
    beep = None if args.beep is None else (args.beep == "on")
    kb_emu = None if args.keyboard_emulation is None else (args.keyboard_emulation == "on")
    id_fmt = args.id_format
    save = args.save

    if beep is None and kb_emu is None and id_fmt is None:
        print("[AVISO] No se especificó ningún parámetro para cambiar.")
        print("  Usa --beep on|off, --keyboard-emulation on|off, --id-format FORMAT")
        reader.disconnect()
        return True

    print("\nAplicando configuración:")
    if beep is not None:
        print(f"  buzzer           → {'ON' if beep else 'OFF'}")
    if kb_emu is not None:
        print(f"  emulación teclado → {'ON' if kb_emu else 'OFF'}")
    if id_fmt is not None:
        print(f"  formato de ID    → {id_fmt}")
    if save:
        print("  [Se guardará en EEPROM]")

    try:
        results = reader.apply_reader_config(
            beep=beep,
            keyboard_emulation=kb_emu,
            id_format=id_fmt,
            save=save,
        )
    except Exception as e:
        print(f"\n[ERROR] Error al aplicar configuración: {e}")
        reader.disconnect()
        return False
    finally:
        reader.disconnect()

    print("\nResultados:")
    all_ok = True
    for key, ok in results.items():
        status = "✓ OK" if ok else "✗ FALLO"
        print(f"  {key:<25} {status}")
        if not ok:
            all_ok = False

    if all_ok:
        print("\nConfiguración aplicada correctamente.")
    else:
        print("\n[AVISO] Algunos comandos fallaron. Verifica el protocolo (rfid_protocol.py).")

    return all_ok


def launch_gui(args: argparse.Namespace):
    """Lanza la ventana principal de la aplicación."""
    import customtkinter as ctk
    from gui.main_window import MainWindow

    # Sobreescribir tema si se pasó por CLI
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
    logger.debug(f"Argumentos recibidos: {args}")

    # --- Modo: listar dispositivos ---
    if args.list_devices:
        cmd_list_devices()
        sys.exit(0)

    # --- Modo: configurar lector vía CLI ---
    if args.config_reader:
        success = cmd_configure_reader(args)
        if args.no_gui:
            sys.exit(0 if success else 1)
        # Si no se pasó --no-gui, continúa y abre la GUI

    # --- Modo: GUI ---
    if not args.no_gui:
        launch_gui(args)


if __name__ == "__main__":
    main()
