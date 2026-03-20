# =============================================================================
# gui/reader_config_tab.py
# Pestaña de configuración completa del lector RD200-M1-G.
# Lee TODOS los parámetros, permite cambiarlos y replicar a otros lectores.
# =============================================================================

import json
import logging
import os
import threading
from datetime import datetime
from typing import Optional

import customtkinter as ctk

from core.reader_manager import ReaderManager, ReaderConnectionError

logger = logging.getLogger(__name__)

PROFILES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "profiles"
)
AUTO_PROFILE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "auto_profile.json"
)


class ReaderConfigTab(ctk.CTkFrame):
    """
    Pestaña profesional de configuración del lector RD200-M1-G.
    Lee todos los parámetros, permite cambiarlos y replicar a múltiples lectores.
    """

    # ── Mapas de valores legibles ──
    USB_MODES = {
        0x01: "HID + Teclado (emula teclado)",
        0x02: "HID Dispositivo (solo comandos)",
        0x03: "HID Auto-Send (envío automático)",
    }
    USB_MODE_VALUES = {v: k for k, v in USB_MODES.items()}

    KBD_FORMATS = {
        0x01: "4H  (4 hex chars)",
        0x02: "5D  (5 decimal)",
        0x03: "6H  (6 hex chars)",
        0x04: "8D  (8 decimal)",
        0x05: "8H  (8 hex chars)",
        0x06: "10D (10 decimal)",
        0x07: "10H (10 hex chars)",
        0x08: "Custom",
    }
    KBD_FORMAT_VALUES = {v: k for k, v in KBD_FORMATS.items()}

    KBD_REVERSE = {
        0x01: "Normal",
        0x02: "Reverse Byte",
        0x03: "Reverse Bit",
    }
    KBD_REVERSE_VALUES = {v: k for k, v in KBD_REVERSE.items()}

    def __init__(self, parent, reader: ReaderManager, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self._reader = reader
        self._current_config: dict = {}
        self._auto_replicate = False
        self._auto_profile: Optional[dict] = self._load_auto_profile()
        self._readers_configured = 0

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build_header()
        self._build_main()
        self._build_footer()

    # =====================================================================
    # UI Construction
    # =====================================================================

    def _build_header(self):
        """Header con info del lector y botón de lectura."""
        header = ctk.CTkFrame(self, corner_radius=10)
        header.grid(row=0, column=0, padx=8, pady=(8, 4), sticky="ew")
        header.grid_columnconfigure(1, weight=1)

        # Info del lector
        info_frame = ctk.CTkFrame(header, fg_color="transparent")
        info_frame.grid(row=0, column=0, padx=16, pady=12, sticky="w")

        ctk.CTkLabel(
            info_frame, text="Configuración del Lector RD200",
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(anchor="w")

        self._info_label = ctk.CTkLabel(
            info_frame, text="No conectado",
            font=ctk.CTkFont(size=12),
            text_color=("gray50", "gray60")
        )
        self._info_label.pack(anchor="w", pady=(2, 0))

        # Botones
        btn_frame = ctk.CTkFrame(header, fg_color="transparent")
        btn_frame.grid(row=0, column=1, padx=16, pady=12, sticky="e")

        self._read_btn = ctk.CTkButton(
            btn_frame, text="Leer Config",
            command=self._on_read_config,
            width=130, height=38,
            fg_color="#1565C0", hover_color="#0D47A1",
            font=ctk.CTkFont(size=13, weight="bold")
        )
        self._read_btn.pack(side="left", padx=4)

        self._apply_btn = ctk.CTkButton(
            btn_frame, text="Aplicar Cambios",
            command=self._on_apply_config,
            width=140, height=38,
            fg_color="#1DB954", hover_color="#158a3e",
            font=ctk.CTkFont(size=13, weight="bold")
        )
        self._apply_btn.pack(side="left", padx=4)

    def _build_main(self):
        """Área principal con scroll: todas las configuraciones."""
        # ScrollableFrame dentro de un contenedor
        container = ctk.CTkFrame(self, fg_color="transparent")
        container.grid(row=1, column=0, padx=4, pady=0, sticky="nsew")
        container.grid_columnconfigure(0, weight=1)
        container.grid_columnconfigure(1, weight=1)
        container.grid_rowconfigure(0, weight=1)

        # === COLUMNA IZQUIERDA: Parámetros ===
        left_scroll = ctk.CTkScrollableFrame(container, corner_radius=10)
        left_scroll.grid(row=0, column=0, padx=(4, 2), pady=4, sticky="nsew")
        left_scroll.grid_columnconfigure(0, weight=1)

        row = 0

        # ── Sección: Modo USB ──
        row = self._add_section_header(left_scroll, "Modo USB", row)
        self._usb_mode_var = ctk.StringVar(value=self.USB_MODES.get(0x01, ""))
        ctk.CTkOptionMenu(
            left_scroll, variable=self._usb_mode_var,
            values=list(self.USB_MODES.values()),
            width=320
        ).grid(row=row, column=0, padx=20, pady=(0, 4), sticky="w")
        row += 1
        ctk.CTkLabel(
            left_scroll,
            text="Teclado = escribe UID como teclas | Dispositivo = solo comandos | Auto-Send = envío HID auto",
            font=ctk.CTkFont(size=10), text_color=("gray55", "gray55"), wraplength=380
        ).grid(row=row, column=0, padx=24, pady=(0, 8), sticky="w")
        row += 1

        # ── Sección: Modo de Lectura ──
        row = self._add_section_header(left_scroll, "Modo de Lectura de Tarjeta", row)
        mode_frame = ctk.CTkFrame(left_scroll, fg_color="transparent")
        mode_frame.grid(row=row, column=0, padx=20, pady=(0, 8), sticky="w")
        row += 1

        self._auto_read_var = ctk.BooleanVar(value=True)
        self._beep_var = ctk.BooleanVar(value=True)
        self._led_var = ctk.BooleanVar(value=True)
        self._same_card_var = ctk.BooleanVar(value=True)
        self._green_mode_var = ctk.BooleanVar(value=False)

        for i, (var, text, tip) in enumerate([
            (self._auto_read_var, "Auto Read", "Lectura automática al detectar tarjeta"),
            (self._beep_var, "Beep", "Sonido al leer tarjeta"),
            (self._led_var, "LED", "LED al leer tarjeta"),
            (self._same_card_var, "Same Card Detect", "Detectar misma tarjeta repetida"),
            (self._green_mode_var, "Energy Saving", "Modo ahorro de energía"),
        ]):
            f = ctk.CTkFrame(mode_frame, fg_color="transparent")
            f.pack(anchor="w", pady=1)
            ctk.CTkCheckBox(f, text=text, variable=var, width=180,
                           font=ctk.CTkFont(size=12)).pack(side="left")
            ctk.CTkLabel(f, text=tip, font=ctk.CTkFont(size=10),
                        text_color=("gray55", "gray55")).pack(side="left", padx=8)

        # ── Sección: Formato de Teclado ──
        row = self._add_section_header(left_scroll, "Formato de Teclado (Keyboard Output)", row)

        ctk.CTkLabel(left_scroll, text="Formato UID:", font=ctk.CTkFont(size=12)
                    ).grid(row=row, column=0, padx=20, pady=(0, 0), sticky="w")
        row += 1
        self._kbd_format_var = ctk.StringVar(value=self.KBD_FORMATS.get(0x05, ""))
        ctk.CTkOptionMenu(
            left_scroll, variable=self._kbd_format_var,
            values=list(self.KBD_FORMATS.values()), width=280
        ).grid(row=row, column=0, padx=20, pady=(0, 6), sticky="w")
        row += 1

        ctk.CTkLabel(left_scroll, text="Orden de bytes:", font=ctk.CTkFont(size=12)
                    ).grid(row=row, column=0, padx=20, pady=(0, 0), sticky="w")
        row += 1
        self._kbd_reverse_var = ctk.StringVar(value=self.KBD_REVERSE.get(0x01, ""))
        ctk.CTkOptionMenu(
            left_scroll, variable=self._kbd_reverse_var,
            values=list(self.KBD_REVERSE.values()), width=280
        ).grid(row=row, column=0, padx=20, pady=(0, 6), sticky="w")
        row += 1

        ctk.CTkLabel(left_scroll, text="Carácter adicional al final:", font=ctk.CTkFont(size=12)
                    ).grid(row=row, column=0, padx=20, pady=(0, 0), sticky="w")
        row += 1

        add_frame = ctk.CTkFrame(left_scroll, fg_color="transparent")
        add_frame.grid(row=row, column=0, padx=20, pady=(0, 8), sticky="w")
        row += 1

        self._add_cr_var = ctk.BooleanVar(value=False)
        self._add_lf_var = ctk.BooleanVar(value=False)
        self._add_comma_var = ctk.BooleanVar(value=False)

        ctk.CTkCheckBox(add_frame, text="Enter (CR)", variable=self._add_cr_var,
                        font=ctk.CTkFont(size=12), width=120).pack(side="left", padx=(0, 8))
        ctk.CTkCheckBox(add_frame, text="Line Feed (LF)", variable=self._add_lf_var,
                        font=ctk.CTkFont(size=12), width=130).pack(side="left", padx=(0, 8))
        ctk.CTkCheckBox(add_frame, text="Coma (,)", variable=self._add_comma_var,
                        font=ctk.CTkFont(size=12), width=100).pack(side="left")

        # ── Sección: Tiempos ──
        row = self._add_section_header(left_scroll, "Tiempos y Delays", row)

        # Postponement Time
        ctk.CTkLabel(left_scroll, text="Postponement Time (x10ms):",
                    font=ctk.CTkFont(size=12)).grid(row=row, column=0, padx=20, pady=(0, 0), sticky="w")
        row += 1
        time_frame1 = ctk.CTkFrame(left_scroll, fg_color="transparent")
        time_frame1.grid(row=row, column=0, padx=20, pady=(0, 6), sticky="w")
        row += 1
        self._postponement_var = ctk.IntVar(value=5)
        self._postponement_slider = ctk.CTkSlider(
            time_frame1, from_=0, to=255, number_of_steps=255,
            variable=self._postponement_var, width=240,
            command=lambda v: self._postponement_label.configure(
                text=f"{int(v)} ({int(v)*10}ms)")
        )
        self._postponement_slider.pack(side="left")
        self._postponement_label = ctk.CTkLabel(
            time_frame1, text="5 (50ms)", font=ctk.CTkFont(size=11), width=100)
        self._postponement_label.pack(side="left", padx=8)

        # Same Card Time
        ctk.CTkLabel(left_scroll, text="Same Card Time (x100ms):",
                    font=ctk.CTkFont(size=12)).grid(row=row, column=0, padx=20, pady=(0, 0), sticky="w")
        row += 1
        time_frame2 = ctk.CTkFrame(left_scroll, fg_color="transparent")
        time_frame2.grid(row=row, column=0, padx=20, pady=(0, 6), sticky="w")
        row += 1
        self._same_card_time_var = ctk.IntVar(value=15)
        self._same_card_slider = ctk.CTkSlider(
            time_frame2, from_=0, to=255, number_of_steps=255,
            variable=self._same_card_time_var, width=240,
            command=lambda v: self._same_card_label.configure(
                text=f"{int(v)} ({int(v)*100}ms = {int(v)*0.1:.1f}s)")
        )
        self._same_card_slider.pack(side="left")
        self._same_card_label = ctk.CTkLabel(
            time_frame2, text="15 (1500ms = 1.5s)", font=ctk.CTkFont(size=11), width=160)
        self._same_card_label.pack(side="left", padx=8)

        # Keypad Delay
        ctk.CTkLabel(left_scroll, text="Keypad Delay (ms entre teclas):",
                    font=ctk.CTkFont(size=12)).grid(row=row, column=0, padx=20, pady=(0, 0), sticky="w")
        row += 1
        time_frame3 = ctk.CTkFrame(left_scroll, fg_color="transparent")
        time_frame3.grid(row=row, column=0, padx=20, pady=(0, 6), sticky="w")
        row += 1
        self._keypad_delay_var = ctk.IntVar(value=10)
        self._keypad_delay_slider = ctk.CTkSlider(
            time_frame3, from_=0, to=100, number_of_steps=100,
            variable=self._keypad_delay_var, width=240,
            command=lambda v: self._keypad_delay_label.configure(text=f"{int(v)}ms")
        )
        self._keypad_delay_slider.pack(side="left")
        self._keypad_delay_label = ctk.CTkLabel(
            time_frame3, text="10ms", font=ctk.CTkFont(size=11), width=60)
        self._keypad_delay_label.pack(side="left", padx=8)

        # ── Sección: Mifare ──
        row = self._add_section_header(left_scroll, "Configuración Mifare", row)
        ctk.CTkLabel(left_scroll, text="Sector para lectura Mifare:",
                    font=ctk.CTkFont(size=12)).grid(row=row, column=0, padx=20, pady=(0, 0), sticky="w")
        row += 1
        self._mifare_sector_var = ctk.IntVar(value=0)
        ctk.CTkOptionMenu(
            left_scroll,
            values=[str(i) for i in range(16)],
            variable=ctk.StringVar(value="0"),
            command=lambda v: self._mifare_sector_var.set(int(v)),
            width=100
        ).grid(row=row, column=0, padx=20, pady=(0, 12), sticky="w")
        row += 1

        # === COLUMNA DERECHA: Perfiles + Diagnóstico ===
        right_frame = ctk.CTkFrame(container, corner_radius=10)
        right_frame.grid(row=0, column=1, padx=(2, 4), pady=4, sticky="nsew")
        right_frame.grid_columnconfigure(0, weight=1)

        # ── Perfiles de configuración ──
        ctk.CTkLabel(
            right_frame, text="Perfiles de Configuración",
            font=ctk.CTkFont(size=15, weight="bold")
        ).grid(row=0, column=0, padx=16, pady=(16, 8), sticky="w")

        profile_btns = ctk.CTkFrame(right_frame, fg_color="transparent")
        profile_btns.grid(row=1, column=0, padx=12, pady=(0, 4), sticky="ew")
        profile_btns.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkButton(
            profile_btns, text="Guardar Perfil...",
            command=self._on_save_profile,
            height=34, fg_color="#795548", hover_color="#5D4037",
            font=ctk.CTkFont(size=12)
        ).grid(row=0, column=0, padx=4, pady=4, sticky="ew")

        ctk.CTkButton(
            profile_btns, text="Cargar Perfil...",
            command=self._on_load_profile,
            height=34, fg_color="transparent", border_width=1,
            font=ctk.CTkFont(size=12)
        ).grid(row=0, column=1, padx=4, pady=4, sticky="ew")

        # Separador
        ctk.CTkFrame(right_frame, height=2, fg_color=("gray80", "gray30")
                     ).grid(row=2, column=0, padx=16, pady=8, sticky="ew")

        # ── Auto-Replicar ──
        ctk.CTkLabel(
            right_frame, text="Replicar a Múltiples Lectores",
            font=ctk.CTkFont(size=15, weight="bold")
        ).grid(row=3, column=0, padx=16, pady=(8, 4), sticky="w")

        ctk.CTkLabel(
            right_frame,
            text="Activa esta opción para aplicar automáticamente\n"
                 "la configuración guardada cada vez que conectes\n"
                 "un nuevo lector. Ideal para configurar en masa.",
            font=ctk.CTkFont(size=11), text_color=("gray55", "gray55"),
            justify="left"
        ).grid(row=4, column=0, padx=20, pady=(0, 6), sticky="w")

        self._auto_replicate_var = ctk.BooleanVar(value=False)
        self._auto_switch = ctk.CTkSwitch(
            right_frame, text="Auto-replicar al conectar",
            variable=self._auto_replicate_var,
            command=self._on_auto_replicate_toggle,
            font=ctk.CTkFont(size=13, weight="bold"),
            progress_color="#1DB954"
        )
        self._auto_switch.grid(row=5, column=0, padx=20, pady=(0, 4), sticky="w")

        self._auto_profile_label = ctk.CTkLabel(
            right_frame, text="Sin perfil cargado",
            font=ctk.CTkFont(size=11), text_color=("gray55", "gray55")
        )
        self._auto_profile_label.grid(row=6, column=0, padx=24, pady=(0, 4), sticky="w")

        ctk.CTkButton(
            right_frame, text="Usar config actual como perfil auto",
            command=self._on_set_auto_profile,
            height=34, fg_color="#1565C0", hover_color="#0D47A1",
            font=ctk.CTkFont(size=12)
        ).grid(row=7, column=0, padx=12, pady=4, sticky="ew")

        self._replicate_counter = ctk.CTkLabel(
            right_frame, text="Lectores configurados: 0",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=("#1DB954", "#1DB954")
        )
        self._replicate_counter.grid(row=8, column=0, padx=20, pady=(8, 4), sticky="w")

        # Separador
        ctk.CTkFrame(right_frame, height=2, fg_color=("gray80", "gray30")
                     ).grid(row=9, column=0, padx=16, pady=8, sticky="ew")

        # ── Diagnóstico / Acciones Rápidas ──
        ctk.CTkLabel(
            right_frame, text="Acciones Rápidas",
            font=ctk.CTkFont(size=15, weight="bold")
        ).grid(row=10, column=0, padx=16, pady=(8, 8), sticky="w")

        actions = [
            ("Obtener Nº de Serie", self._on_get_serial, None, None),
            ("Obtener Firmware", self._on_get_version, None, None),
            ("Test Beep", self._on_test_beep, None, None),
            ("Test LED Verde", lambda: self._on_test_led("green"), None, None),
            ("Stop Sense", self._on_stop_sense, None, None),
            ("Start Sense", self._on_start_sense, None, None),
            ("Reiniciar Lector", self._on_reboot, "#E53935", "#B71C1C"),
            ("Factory Reset", self._on_factory_reset, "#E53935", "#B71C1C"),
        ]

        for i, (text, cmd, fg, hover) in enumerate(actions):
            btn_kwargs = {
                "text": text, "command": cmd,
                "height": 32, "font": ctk.CTkFont(size=12),
            }
            if fg:
                btn_kwargs["fg_color"] = fg
                btn_kwargs["hover_color"] = hover
            else:
                btn_kwargs["fg_color"] = "transparent"
                btn_kwargs["border_width"] = 1
            ctk.CTkButton(right_frame, **btn_kwargs).grid(
                row=11 + i, column=0, padx=12, pady=2, sticky="ew")

        # Resultado / Log
        self._result_text = ctk.CTkTextbox(
            right_frame, height=120,
            font=ctk.CTkFont(family="Courier New", size=11),
            state="disabled"
        )
        self._result_text.grid(row=20, column=0, padx=12, pady=(8, 12), sticky="ew")

        # Actualizar label del auto-profile
        self._update_auto_profile_label()

    def _build_footer(self):
        """Barra inferior con estado."""
        footer = ctk.CTkFrame(self, height=36, corner_radius=0)
        footer.grid(row=2, column=0, padx=4, pady=(0, 4), sticky="ew")
        footer.grid_columnconfigure(0, weight=1)

        self._status_label = ctk.CTkLabel(
            footer, text="Conecta un lector y pulsa 'Leer Config' para empezar",
            font=ctk.CTkFont(size=11),
            text_color=("gray50", "gray60")
        )
        self._status_label.grid(row=0, column=0, padx=16, pady=6, sticky="w")

    # =====================================================================
    # Helper: Section headers
    # =====================================================================

    def _add_section_header(self, parent, title: str, row: int) -> int:
        """Añade un header de sección y devuelve row+1."""
        if row > 0:
            ctk.CTkFrame(parent, height=1, fg_color=("gray80", "gray30")
                        ).grid(row=row, column=0, padx=12, pady=6, sticky="ew")
            row += 1
        ctk.CTkLabel(
            parent, text=title,
            font=ctk.CTkFont(size=14, weight="bold")
        ).grid(row=row, column=0, padx=16, pady=(8, 4), sticky="w")
        return row + 1

    # =====================================================================
    # Leer configuración del lector
    # =====================================================================

    def _on_read_config(self):
        """Lee toda la configuración del lector en un hilo."""
        if not self._reader.is_connected:
            self._log_result("Error: Lector no conectado.")
            return
        if not self._reader.in_command_mode:
            self._log_result("Error: Lector en modo pasivo, no acepta comandos.")
            return

        self._read_btn.configure(state="disabled", text="Leyendo...")
        threading.Thread(target=self._read_config_worker, daemon=True).start()

    def _read_config_worker(self):
        """Worker thread para leer configuración."""
        try:
            config = self._reader.get_all_config()
            self._current_config = config
            self.after(0, lambda: self._populate_ui(config))
            self.after(0, lambda: self._log_result(
                f"Configuración leída correctamente.\n"
                f"SN: {config.get('serial_number', 'N/A')}\n"
                f"Modelo: {config.get('model_version', 'N/A')}\n"
                f"Parámetros: {len(config)} leídos"
            ))
        except Exception as e:
            self.after(0, lambda: self._log_result(f"Error leyendo config: {e}"))
        finally:
            self.after(0, lambda: self._read_btn.configure(
                state="normal", text="Leer Config"))

    def _populate_ui(self, config: dict):
        """Rellena la UI con los valores leídos del lector."""
        # Info header
        sn = config.get("serial_number", "N/A")
        model = config.get("model_version", "N/A")
        self._info_label.configure(
            text=f"SN: {sn}  |  Modelo: {model}  |  "
                 f"Modo: {'COMANDO' if self._reader.in_command_mode else 'PASIVO'}"
        )

        # USB Mode
        usb_mode = config.get("usb_mode", 0x01)
        self._usb_mode_var.set(self.USB_MODES.get(usb_mode, self.USB_MODES[0x01]))

        # Read Card Mode (bitmask)
        rcm = config.get("read_card_mode", 0x0F)
        self._auto_read_var.set(bool(rcm & 0x01))
        self._beep_var.set(bool(rcm & 0x02))
        self._led_var.set(bool(rcm & 0x04))
        self._same_card_var.set(bool(rcm & 0x08))
        self._green_mode_var.set(bool(rcm & 0x10))

        # Keyboard Format
        kbd_fmt = config.get("kbd_format", 0x05)
        self._kbd_format_var.set(self.KBD_FORMATS.get(kbd_fmt, self.KBD_FORMATS[0x05]))

        kbd_rev = config.get("kbd_reverse", 0x01)
        self._kbd_reverse_var.set(self.KBD_REVERSE.get(kbd_rev, self.KBD_REVERSE[0x01]))

        add_type = config.get("kbd_add_type", 0x00)
        self._add_cr_var.set(bool(add_type & 0x80))
        self._add_lf_var.set(bool(add_type & 0x40))
        self._add_comma_var.set(bool(add_type & 0x01))

        # Times
        self._postponement_var.set(config.get("postponement_time", 5))
        self._postponement_label.configure(
            text=f"{config.get('postponement_time', 5)} ({config.get('postponement_time', 5)*10}ms)")

        self._same_card_time_var.set(config.get("same_card_time", 15))
        sct = config.get("same_card_time", 15)
        self._same_card_label.configure(
            text=f"{sct} ({sct*100}ms = {sct*0.1:.1f}s)")

        self._keypad_delay_var.set(config.get("keypad_delay", 10))
        self._keypad_delay_label.configure(
            text=f"{config.get('keypad_delay', 10)}ms")

        # Mifare sector
        self._mifare_sector_var.set(config.get("mifare_sector", 0))

        self._status_label.configure(
            text=f"Config leída de {sn} a las {datetime.now().strftime('%H:%M:%S')}")

    # =====================================================================
    # Aplicar configuración al lector
    # =====================================================================

    def _on_apply_config(self):
        """Aplica los cambios de la UI al lector."""
        if not self._reader.is_connected or not self._reader.in_command_mode:
            self._log_result("Error: Lector no conectado o en modo pasivo.")
            return

        self._apply_btn.configure(state="disabled", text="Aplicando...")
        threading.Thread(target=self._apply_config_worker, daemon=True).start()

    def _apply_config_worker(self):
        """Worker thread para aplicar configuración."""
        try:
            profile = self._build_profile_from_ui()
            results = self._reader.apply_config_profile(profile)

            ok_count = sum(1 for v in results.values() if v)
            fail_count = sum(1 for v in results.values() if not v)

            lines = [f"Aplicados: {ok_count} OK, {fail_count} errores"]
            for param, success in results.items():
                status = "OK" if success else "FALLO"
                lines.append(f"  {param}: {status}")

            self.after(0, lambda: self._log_result("\n".join(lines)))
            self.after(0, lambda: self._status_label.configure(
                text=f"Config aplicada: {ok_count} OK, {fail_count} errores"))
        except Exception as e:
            self.after(0, lambda: self._log_result(f"Error aplicando: {e}"))
        finally:
            self.after(0, lambda: self._apply_btn.configure(
                state="normal", text="Aplicar Cambios"))

    def _build_profile_from_ui(self) -> dict:
        """Construye un dict de perfil desde los valores actuales de la UI."""
        # USB Mode
        usb_mode_name = self._usb_mode_var.get()
        usb_mode = self.USB_MODE_VALUES.get(usb_mode_name, 0x01)

        # Read Card Mode bitmask
        rcm = 0
        if self._auto_read_var.get(): rcm |= 0x01
        if self._beep_var.get(): rcm |= 0x02
        if self._led_var.get(): rcm |= 0x04
        if self._same_card_var.get(): rcm |= 0x08
        if self._green_mode_var.get(): rcm |= 0x10

        # Keyboard Format
        kbd_fmt_name = self._kbd_format_var.get()
        kbd_fmt = self.KBD_FORMAT_VALUES.get(kbd_fmt_name, 0x05)

        kbd_rev_name = self._kbd_reverse_var.get()
        kbd_rev = self.KBD_REVERSE_VALUES.get(kbd_rev_name, 0x01)

        add_type = 0
        if self._add_cr_var.get(): add_type |= 0x80
        if self._add_lf_var.get(): add_type |= 0x40
        if self._add_comma_var.get(): add_type |= 0x01

        return {
            "usb_mode": usb_mode,
            "read_card_mode": rcm,
            "kbd_format": kbd_fmt,
            "kbd_reverse": kbd_rev,
            "kbd_add_type": add_type,
            "postponement_time": self._postponement_var.get(),
            "same_card_time": self._same_card_time_var.get(),
            "keypad_delay": self._keypad_delay_var.get(),
            "mifare_sector": self._mifare_sector_var.get(),
        }

    # =====================================================================
    # Perfiles: guardar / cargar
    # =====================================================================

    def _on_save_profile(self):
        """Guarda la configuración actual como perfil JSON."""
        from tkinter import filedialog
        os.makedirs(PROFILES_DIR, exist_ok=True)
        filepath = filedialog.asksaveasfilename(
            initialdir=PROFILES_DIR,
            defaultextension=".json",
            filetypes=[("JSON Profile", "*.json")],
            initialfile=f"rd200_profile_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        if not filepath:
            return

        profile = self._build_profile_from_ui()
        profile["_meta"] = {
            "created": datetime.now().isoformat(),
            "serial_number": self._reader.serial_number or "unknown",
            "model_version": self._reader.model_version or "unknown",
        }

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(profile, f, indent=2, ensure_ascii=False)
            self._log_result(f"Perfil guardado en:\n{filepath}")
        except Exception as e:
            self._log_result(f"Error guardando perfil: {e}")

    def _on_load_profile(self):
        """Carga un perfil desde JSON y rellena la UI."""
        from tkinter import filedialog
        os.makedirs(PROFILES_DIR, exist_ok=True)
        filepath = filedialog.askopenfilename(
            initialdir=PROFILES_DIR,
            filetypes=[("JSON Profile", "*.json"), ("Todos", "*.*")]
        )
        if not filepath:
            return

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                profile = json.load(f)

            # Convertir profile a formato de config para populate_ui
            config = dict(profile)
            config.setdefault("serial_number", profile.get("_meta", {}).get("serial_number", "Perfil"))
            config.setdefault("model_version", profile.get("_meta", {}).get("model_version", "Cargado"))
            self._populate_ui(config)
            self._log_result(f"Perfil cargado desde:\n{os.path.basename(filepath)}")
        except Exception as e:
            self._log_result(f"Error cargando perfil: {e}")

    # =====================================================================
    # Auto-replicar
    # =====================================================================

    def _on_auto_replicate_toggle(self):
        """Activa/desactiva el modo auto-replicar."""
        self._auto_replicate = self._auto_replicate_var.get()
        if self._auto_replicate and not self._auto_profile:
            self._log_result(
                "Auto-replicar activado pero no hay perfil guardado.\n"
                "Pulsa 'Usar config actual como perfil auto'."
            )

    def _on_set_auto_profile(self):
        """Guarda la configuración actual como perfil para auto-replicar."""
        profile = self._build_profile_from_ui()
        profile["_meta"] = {
            "created": datetime.now().isoformat(),
            "source_serial": self._reader.serial_number or "unknown",
        }
        self._auto_profile = profile

        try:
            os.makedirs(os.path.dirname(AUTO_PROFILE_PATH), exist_ok=True)
            with open(AUTO_PROFILE_PATH, "w", encoding="utf-8") as f:
                json.dump(profile, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"Error guardando auto-profile: {e}")

        self._update_auto_profile_label()
        self._log_result(
            "Perfil auto-replicar guardado.\n"
            "Ahora activa el switch y conecta otro lector.\n"
            "La config se aplicará automáticamente."
        )

    def _load_auto_profile(self) -> Optional[dict]:
        """Carga el perfil auto-replicar desde disco."""
        try:
            if os.path.exists(AUTO_PROFILE_PATH):
                with open(AUTO_PROFILE_PATH, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return None

    def _update_auto_profile_label(self):
        """Actualiza el label que muestra el perfil auto-replicar."""
        if self._auto_profile:
            meta = self._auto_profile.get("_meta", {})
            src = meta.get("source_serial", "?")
            created = meta.get("created", "?")[:19]
            self._auto_profile_label.configure(
                text=f"Perfil de: SN {src} ({created})")
        else:
            self._auto_profile_label.configure(text="Sin perfil guardado")

    def on_reader_connected(self):
        """
        Llamado desde MainWindow cuando se conecta un lector.
        Si auto-replicar está activo, aplica el perfil automáticamente.
        """
        if self._auto_replicate and self._auto_profile:
            self._log_result(
                f"Nuevo lector detectado (SN: {self._reader.serial_number}).\n"
                "Aplicando perfil automáticamente..."
            )
            threading.Thread(
                target=self._auto_apply_worker, daemon=True).start()

    def _auto_apply_worker(self):
        """Worker para auto-aplicar perfil."""
        try:
            import time
            time.sleep(0.5)  # Dar tiempo al lector para estabilizarse
            results = self._reader.apply_config_profile(self._auto_profile)
            ok = sum(1 for v in results.values() if v)
            fail = sum(1 for v in results.values() if not v)
            self._readers_configured += 1

            self.after(0, lambda: self._replicate_counter.configure(
                text=f"Lectores configurados: {self._readers_configured}"))
            self.after(0, lambda: self._log_result(
                f"Auto-replicar completado: {ok} OK, {fail} errores\n"
                f"SN: {self._reader.serial_number}\n"
                f"Total lectores: {self._readers_configured}"))
            self.after(0, lambda: self._status_label.configure(
                text=f"Auto-config aplicada a SN:{self._reader.serial_number} "
                     f"({self._readers_configured} lectores)"))

            # Beep para indicar éxito
            try:
                self._reader.beep_green()
            except Exception:
                pass

        except Exception as e:
            self.after(0, lambda: self._log_result(f"Error auto-replicar: {e}"))

    # =====================================================================
    # Acciones rápidas
    # =====================================================================

    def _on_get_serial(self):
        if not self._reader.is_connected:
            self._log_result("Lector no conectado.")
            return
        try:
            sn = self._reader.get_serial_number()
            self._log_result(f"Nº de Serie: {sn}")
        except Exception as e:
            self._log_result(f"Error: {e}")

    def _on_get_version(self):
        if not self._reader.is_connected:
            self._log_result("Lector no conectado.")
            return
        try:
            ver = self._reader.get_version()
            self._log_result(f"Firmware: {ver}")
        except Exception as e:
            self._log_result(f"Error: {e}")

    def _on_test_beep(self):
        if not self._reader.is_connected:
            return
        try:
            self._reader.beep()
            self._log_result("Beep enviado.")
        except Exception as e:
            self._log_result(f"Error: {e}")

    def _on_test_led(self, color: str):
        if not self._reader.is_connected:
            return
        try:
            self._reader.set_led(color, True)
            self._log_result(f"LED {color} activado.")
        except Exception as e:
            self._log_result(f"Error: {e}")

    def _on_stop_sense(self):
        if not self._reader.is_connected:
            return
        try:
            self._reader.stop_sense()
            self._log_result("Stop Sense enviado. El lector dejará de detectar tarjetas.")
        except Exception as e:
            self._log_result(f"Error: {e}")

    def _on_start_sense(self):
        if not self._reader.is_connected:
            return
        try:
            self._reader.start_sense()
            self._log_result("Start Sense enviado. El lector reanuda la detección.")
        except Exception as e:
            self._log_result(f"Error: {e}")

    def _on_reboot(self):
        if not self._reader.is_connected:
            return
        self._log_result("Reiniciando lector... (se reconectará automáticamente)")
        try:
            self._reader.reboot()
        except Exception:
            pass

    def _on_factory_reset(self):
        if not self._reader.is_connected:
            return
        # Confirmar
        dialog = ctk.CTkInputDialog(
            text="Escribe RESET para confirmar el factory reset:",
            title="Factory Reset")
        if dialog.get_input() != "RESET":
            self._log_result("Factory reset cancelado.")
            return
        self._log_result("Factory reset enviado... El lector se reiniciará.")
        try:
            self._reader.factory_reset()
        except Exception:
            pass

    # =====================================================================
    # Utilidades
    # =====================================================================

    def _log_result(self, text: str):
        """Muestra texto en el log de resultados."""
        self._result_text.configure(state="normal")
        self._result_text.delete("1.0", "end")
        self._result_text.insert("1.0", text)
        self._result_text.configure(state="disabled")
