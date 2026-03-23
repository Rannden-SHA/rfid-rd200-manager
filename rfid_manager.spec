# -*- mode: python ; coding: utf-8 -*-
# =============================================================================
# rfid_manager.spec - PyInstaller build specification (ONEFILE portable)
# Ejecutar: venv\Scripts\pyinstaller.exe rfid_manager.spec
# =============================================================================

import os
import sys

block_cipher = None

# Rutas
BASE_DIR = os.path.abspath('.')
VENV_SITE = os.path.join(BASE_DIR, 'venv', 'Lib', 'site-packages')
CTK_DIR = os.path.join(VENV_SITE, 'customtkinter')
ICON_PATH = os.path.join(BASE_DIR, 'assets', 'icons', 'app_icon.ico')

a = Analysis(
    ['app.py'],
    pathex=[BASE_DIR],
    binaries=[],
    datas=[
        # CustomTkinter assets (themes, icons)
        (CTK_DIR, 'customtkinter'),
        # App icon
        (os.path.join(BASE_DIR, 'assets'), 'assets'),
    ],
    hiddenimports=[
        'hid',
        'customtkinter',
        'PIL',
        'PIL._tkinter_finder',
        'tkinter',
        'tkinter.filedialog',
        'json',
        'logging',
        'threading',
        'queue',
        'time',
        'struct',
        'core',
        'core.reader_manager',
        'core.rfid_protocol',
        'core.usb_sniffer',
        'core.batch_processor',
        'gui',
        'gui.main_window',
        'gui.manual_tab',
        'gui.batch_tab',
        'gui.sniffer_tab',
        'gui.reader_config_tab',
        'gui.widgets',
        'gui.widgets.status_indicator',
        'utils',
        'utils.logger',
        'utils.hex_utils',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'numpy',
        'scipy',
        'pandas',
        'pytest',
        'unittest',
        'pyusb',
        'usb',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# === ONEFILE: todo empaquetado en un solo .exe portable ===
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,        # Incluir binarios DENTRO del exe
    a.zipfiles,        # Incluir zips DENTRO del exe
    a.datas,           # Incluir datos DENTRO del exe
    [],
    name='RFID Manager',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,        # Con consola para modo CLI (se oculta en modo GUI)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON_PATH,
    version_info=None,
)
