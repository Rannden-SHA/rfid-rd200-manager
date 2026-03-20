# =============================================================================
# gui/sniffer_tab.py
#
# Pestaña de Sniffer / Monitor HID integrado.
# Reemplaza la necesidad de Wireshark + USBPcap para descubrir el protocolo.
#
# Funcionalidades:
#   - Monitor en tiempo real de tráfico TX/RX con colores diferenciados
#   - Panel de envío de tramas hex crudas con historial de comandos
#   - Filtros (TX, RX, ambos) + buscar en capturas
#   - Auto-scroll con pausa
#   - Exportar a CSV, texto plano o fragmento Python listo para rfid_protocol.py
#   - Copiar paquete individual al portapapeles
# =============================================================================

import json
import logging
import os
import tkinter as tk
from tkinter import filedialog
from datetime import datetime

import customtkinter as ctk

from core.usb_sniffer import USBSniffer, SnifferPacket
from core.reader_manager import ReaderManager
from utils.hex_utils import HexUtils

logger = logging.getLogger(__name__)


class SnifferTab(ctk.CTkFrame):
    """Pestaña completa del sniffer HID integrado."""

    # Historial de comandos enviados (máximo 50)
    MAX_HISTORY = 50

    # Archivo donde se guardan los comandos personalizados
    CUSTOM_CMDS_FILE = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config", "custom_sniffer_cmds.json"
    )
    MAX_CUSTOM_SLOTS = 8

    def __init__(self, parent, reader: ReaderManager, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self._reader = reader
        self._sniffer = USBSniffer()
        self._auto_scroll = True
        self._paused = False
        self._filter_dir = "ALL"     # "ALL", "TX", "RX"
        self._show_raw_hid = False   # False = protocolo limpio, True = HID crudo
        self._cmd_history: list[str] = []
        self._cmd_history_idx = -1
        self._pending_packets: list[SnifferPacket] = []

        # Comandos personalizados: [{name: str, hex: str}, ...]
        self._custom_cmds: list[dict] = self._load_custom_cmds()
        self._custom_buttons: list[ctk.CTkButton] = []

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)  # El log ocupa todo el espacio vertical

        self._build_toolbar()
        self._build_main_area()
        self._build_send_panel()

    # =====================================================================
    # UI Construction
    # =====================================================================

    def _build_toolbar(self):
        """Barra superior con controles de captura."""
        toolbar = ctk.CTkFrame(self, height=44, corner_radius=0)
        toolbar.grid(row=0, column=0, sticky="ew", padx=4, pady=(4, 0))
        toolbar.grid_columnconfigure(6, weight=1)  # spacer

        # Botón Iniciar / Detener captura
        self._capture_btn = ctk.CTkButton(
            toolbar, text="▶  Iniciar captura",
            command=self._toggle_capture,
            width=160, height=32,
            fg_color="#1DB954", hover_color="#158a3e",
            font=ctk.CTkFont(size=13, weight="bold")
        )
        self._capture_btn.grid(row=0, column=0, padx=6, pady=6)

        # Pausa
        self._pause_btn = ctk.CTkButton(
            toolbar, text="⏸ Pausar", width=90, height=32,
            command=self._toggle_pause,
            fg_color="transparent", border_width=1,
            state="disabled"
        )
        self._pause_btn.grid(row=0, column=1, padx=4, pady=6)

        # Limpiar
        ctk.CTkButton(
            toolbar, text="🗑 Limpiar", width=90, height=32,
            command=self._on_clear,
            fg_color="transparent", border_width=1
        ).grid(row=0, column=2, padx=4, pady=6)

        # Filtro de dirección
        self._filter_var = ctk.StringVar(value="ALL")
        ctk.CTkSegmentedButton(
            toolbar, values=["ALL", "TX", "RX"],
            variable=self._filter_var,
            command=self._on_filter_changed,
            width=180
        ).grid(row=0, column=3, padx=8, pady=6)

        # Auto-scroll toggle
        self._autoscroll_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            toolbar, text="Auto-scroll",
            variable=self._autoscroll_var,
            command=lambda: setattr(self, '_auto_scroll', self._autoscroll_var.get()),
            width=100
        ).grid(row=0, column=4, padx=8, pady=6)

        # Raw HID toggle
        self._raw_hid_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            toolbar, text="Raw HID",
            variable=self._raw_hid_var,
            command=self._on_raw_toggle,
            width=80
        ).grid(row=0, column=5, padx=4, pady=6)

        # Spacer
        ctk.CTkLabel(toolbar, text="").grid(row=0, column=6, sticky="ew")

        # Contador
        self._counter_label = ctk.CTkLabel(
            toolbar, text="0 paquetes",
            font=ctk.CTkFont(size=11),
            text_color=("gray50", "gray60")
        )
        self._counter_label.grid(row=0, column=7, padx=8, pady=6)

        # Menú de exportar
        self._export_menu_btn = ctk.CTkButton(
            toolbar, text="Exportar ▾", width=100, height=32,
            command=self._show_export_menu,
            fg_color="transparent", border_width=1
        )
        self._export_menu_btn.grid(row=0, column=8, padx=6, pady=6)

    def _build_main_area(self):
        """Área principal: log de paquetes con scroll."""
        log_frame = ctk.CTkFrame(self, corner_radius=8)
        log_frame.grid(row=1, column=0, padx=4, pady=4, sticky="nsew")
        log_frame.grid_columnconfigure(0, weight=1)
        log_frame.grid_rowconfigure(0, weight=0)
        log_frame.grid_rowconfigure(1, weight=1)

        # Cabecera de tabla
        header = ctk.CTkFrame(log_frame, height=24, fg_color=("gray80", "gray25"))
        header.grid(row=0, column=0, sticky="ew", padx=2, pady=(2, 0))
        header_text = (
            f"{'#':>5}    {'Hora':<12}  {'Dir':>3}    "
            f"{'Protocolo RD200 (Hex)':<56}  {'ASCII':<18}  Notas"
        )
        ctk.CTkLabel(
            header, text=header_text,
            font=ctk.CTkFont(family="Courier New", size=11),
            anchor="w"
        ).pack(fill="x", padx=8, pady=2)

        # Textbox para el log
        self._log_text = ctk.CTkTextbox(
            log_frame,
            font=ctk.CTkFont(family="Courier New", size=12),
            state="disabled",
            wrap="none",
        )
        self._log_text.grid(row=1, column=0, padx=2, pady=(0, 2), sticky="nsew")

        # Configurar tags de color en el widget tk interno
        inner_text = self._log_text._textbox
        inner_text.tag_configure("tx", foreground="#42A5F5")       # Azul para TX
        inner_text.tag_configure("rx", foreground="#66BB6A")       # Verde para RX
        inner_text.tag_configure("error", foreground="#EF5350")    # Rojo para errores
        inner_text.tag_configure("info", foreground="#BDBDBD")     # Gris para info
        inner_text.tag_configure("highlight", background="#FDD835", foreground="#212121")

        # Menú contextual (clic derecho)
        self._context_menu = tk.Menu(inner_text, tearoff=0)
        self._context_menu.add_command(label="Copiar línea", command=self._copy_selected_line)
        self._context_menu.add_command(label="Copiar hex", command=self._copy_selected_hex)
        self._context_menu.add_separator()
        self._context_menu.add_command(label="Reenviar este TX", command=self._resend_selected)
        inner_text.bind("<Button-3>", self._on_right_click)

    def _build_send_panel(self):
        """Panel inferior: envío de tramas hex y comandos rápidos."""
        bottom = ctk.CTkFrame(self, corner_radius=8)
        bottom.grid(row=2, column=0, padx=4, pady=(0, 4), sticky="ew")
        bottom.grid_columnconfigure(1, weight=1)

        # Label
        ctk.CTkLabel(
            bottom, text="Enviar HEX:",
            font=ctk.CTkFont(size=13, weight="bold"),
            width=100, anchor="w"
        ).grid(row=0, column=0, padx=(12, 4), pady=8)

        # Entry con historial (↑ ↓)
        self._hex_entry = ctk.CTkEntry(
            bottom,
            placeholder_text="02 01 0D  (STX LEN CMD DATA — Enter para enviar)",
            font=ctk.CTkFont(family="Courier New", size=13),
            height=36
        )
        self._hex_entry.grid(row=0, column=1, padx=4, pady=8, sticky="ew")
        self._hex_entry.bind("<Return>", lambda e: self._on_send())
        self._hex_entry.bind("<Up>", self._on_history_up)
        self._hex_entry.bind("<Down>", self._on_history_down)

        # Botón enviar
        ctk.CTkButton(
            bottom, text="Enviar",
            command=self._on_send,
            width=80, height=36,
            fg_color="#1565C0", hover_color="#0D47A1",
            font=ctk.CTkFont(size=13, weight="bold")
        ).grid(row=0, column=2, padx=4, pady=8)

        # Timeout selector
        ctk.CTkLabel(bottom, text="Timeout:", width=60).grid(
            row=0, column=3, padx=(8, 2), pady=8)
        self._timeout_var = ctk.StringVar(value="1000")
        ctk.CTkOptionMenu(
            bottom, variable=self._timeout_var,
            values=["200", "500", "1000", "2000", "5000"],
            width=80
        ).grid(row=0, column=4, padx=(2, 4), pady=8)
        ctk.CTkLabel(bottom, text="ms", width=20).grid(
            row=0, column=5, padx=(0, 8), pady=8)

        # Fila 1: Comandos rápidos - Lectura e Info
        quick_frame1 = ctk.CTkFrame(bottom, fg_color="transparent")
        quick_frame1.grid(row=1, column=0, columnspan=6, padx=8, pady=(0, 2), sticky="ew")

        ctk.CTkLabel(
            quick_frame1, text="Info:",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=("gray50", "gray60"), width=40
        ).pack(side="left", padx=(4, 4))

        row1_commands = [
            ("Read Tag",     "02 01 01"),
            ("Mifare UID",   "02 01 11"),
            ("Get S/N",      "02 01 0D"),
            ("Get Version",  "02 01 0E"),
            ("Read S0 B0",   "02 04 15 60 00 00"),
            ("Read S0 B1",   "02 04 15 60 00 01"),
            ("Read S0 B2",   "02 04 15 60 00 02"),
            ("Read S1 B4",   "02 04 15 60 01 04"),
        ]
        for label, hex_cmd in row1_commands:
            ctk.CTkButton(
                quick_frame1, text=label,
                command=lambda h=hex_cmd: self._send_quick(h),
                width=78, height=24,
                fg_color="transparent", border_width=1,
                font=ctk.CTkFont(size=10)
            ).pack(side="left", padx=1)

        # Fila 2: Acciones del lector
        quick_frame2 = ctk.CTkFrame(bottom, fg_color="transparent")
        quick_frame2.grid(row=2, column=0, columnspan=6, padx=8, pady=(0, 2), sticky="ew")

        ctk.CTkLabel(
            quick_frame2, text="Acción:",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=("gray50", "gray60"), width=50
        ).pack(side="left", padx=(4, 2))

        row2_commands = [
            ("Beep",          "02 02 02 06"),
            ("Beep+Verde",    "02 02 02 02"),
            ("Beep+Off",      "02 02 02 03"),
            ("LED Verde",     "02 02 02 08"),
            ("LED Off",       "02 02 02 09"),
            ("Stop Sense",    "02 02 02 11"),
            ("Start Sense",   "02 02 02 12"),
            ("Reset",         "02 02 02 13"),
            ("Reboot",        "02 02 0F 01"),
        ]
        for label, hex_cmd in row2_commands:
            ctk.CTkButton(
                quick_frame2, text=label,
                command=lambda h=hex_cmd: self._send_quick(h),
                width=78, height=24,
                fg_color="transparent", border_width=1,
                font=ctk.CTkFont(size=10)
            ).pack(side="left", padx=1)

        # Fila 3: Configuración rápida
        quick_frame3 = ctk.CTkFrame(bottom, fg_color="transparent")
        quick_frame3.grid(row=3, column=0, columnspan=6, padx=8, pady=(0, 2), sticky="ew")

        ctk.CTkLabel(
            quick_frame3, text="Config:",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=("gray50", "gray60"), width=50
        ).pack(side="left", padx=(4, 2))

        row3_commands = [
            ("Get USB Mode",   "02 02 03 01"),
            ("Get Kbd Fmt",    "02 02 03 03"),
            ("Get ReadMode",   "02 02 03 02"),
            ("8H+CR",          "02 05 03 03 05 01 80"),
            ("8H sin CR",      "02 05 03 03 05 01 00"),
            ("10D+CR",         "02 05 03 03 06 01 80"),
            ("USB Teclado",    "02 03 03 01 01"),
            ("USB HID",        "02 03 03 01 02"),
            ("Factory Reset",  "02 02 0F 02"),
        ]
        for label, hex_cmd in row3_commands:
            ctk.CTkButton(
                quick_frame3, text=label,
                command=lambda h=hex_cmd: self._send_quick(h),
                width=82, height=24,
                fg_color="transparent", border_width=1,
                font=ctk.CTkFont(size=10)
            ).pack(side="left", padx=1)

        # Fila 2: comandos personalizados del usuario
        self._custom_frame = ctk.CTkFrame(bottom, fg_color="transparent")
        self._custom_frame.grid(row=4, column=0, columnspan=6, padx=8, pady=(0, 8), sticky="ew")
        self._rebuild_custom_buttons()

    # =====================================================================
    # Capture control
    # =====================================================================

    def _toggle_capture(self):
        if self._sniffer.is_capturing:
            self._stop_capture()
        else:
            self._start_capture()

    def _start_capture(self):
        """Conecta el sniffer al device del ReaderManager e inicia la captura."""
        if not self._reader.is_connected:
            self._log_info("El lector no está conectado. Conecta primero desde otra pestaña.")
            return

        # Detener el polling normal para evitar conflictos de acceso concurrente
        was_polling = self._reader.is_polling
        if was_polling:
            self._reader.stop_polling()
            self._log_info("Polling de tarjetas detenido para modo sniffer.")

        # Compartir el device del ReaderManager (con su Report ID)
        report_id = getattr(self._reader, '_cmd_report_id', 0x03)
        self._sniffer.attach_device(self._reader._device, self._reader.backend, report_id)
        self._sniffer.start_capture(on_packet=self._on_packet_captured)

        self._capture_btn.configure(
            text="⏹  Detener captura",
            fg_color="#E53935", hover_color="#B71C1C"
        )
        self._pause_btn.configure(state="normal")
        self._log_info(
            "Captura iniciada. El tráfico RX del lector se mostrará aquí.\n"
            "Usa el panel inferior para enviar comandos y ver las respuestas."
        )

    def _stop_capture(self):
        """Detiene la captura."""
        self._sniffer.stop_capture()
        self._capture_btn.configure(
            text="▶  Iniciar captura",
            fg_color="#1DB954", hover_color="#158a3e"
        )
        self._pause_btn.configure(state="disabled")
        self._log_info("Captura detenida.")

    def _toggle_pause(self):
        self._paused = not self._paused
        if self._paused:
            self._pause_btn.configure(text="▶ Reanudar")
            self._log_info("--- PAUSADO (los paquetes se siguen capturando en buffer) ---")
        else:
            self._pause_btn.configure(text="⏸ Pausar")
            # Volcar paquetes acumulados durante la pausa
            for pkt in self._pending_packets:
                self._append_packet_to_log(pkt)
            self._pending_packets.clear()

    # =====================================================================
    # Packet display
    # =====================================================================

    def _on_packet_captured(self, pkt: SnifferPacket):
        """
        Callback del sniffer (llamado desde el hilo de captura).
        Programa la actualización de la GUI en el hilo principal.
        """
        try:
            self.after(0, self._handle_packet, pkt)
        except Exception:
            pass  # Widget destruido

    def _handle_packet(self, pkt: SnifferPacket):
        """Procesa un paquete en el hilo de la GUI."""
        # Actualizar contador
        self._counter_label.configure(text=f"{self._sniffer.packet_count} paquetes")

        if self._paused:
            self._pending_packets.append(pkt)
            return

        self._append_packet_to_log(pkt)

    def _append_packet_to_log(self, pkt: SnifferPacket):
        """Añade una línea al log visual con el color apropiado."""
        # Filtro de dirección
        if self._filter_dir != "ALL" and pkt.direction != self._filter_dir:
            return

        # Formatear la línea
        idx = self._sniffer.packet_count

        if self._show_raw_hid:
            # Modo raw: mostrar todo el frame HID (sin trailing zeros)
            display_bytes = pkt.raw_bytes.rstrip(b'\x00') if pkt.raw_bytes else b""
            hex_str = display_bytes.hex(" ").upper() if display_bytes else pkt.hex_display
        else:
            # Modo protocolo: solo bytes RD200 limpios
            hex_str = pkt.protocol_bytes.hex(" ").upper() if pkt.protocol_bytes else pkt.hex_display

        ascii_disp = pkt.ascii_display[:18] if pkt.ascii_display else ""

        # Mostrar Report ID como prefijo si existe y estamos en modo raw
        rid_prefix = ""
        if self._show_raw_hid and pkt.report_id >= 0:
            rid_prefix = f"[RID=0x{pkt.report_id:02X}] "

        line = (
            f"{idx:>5}    {pkt.timestamp:<12}  {pkt.direction:>3}    "
            f"{rid_prefix}{hex_str:<56}  {ascii_disp:<18}  {pkt.notes}\n"
        )

        # Tag de color
        tag = "tx" if pkt.direction == "TX" else "rx"
        if "TIMEOUT" in pkt.hex_display or "error" in pkt.notes.lower():
            tag = "error"

        # Insertar en el textbox
        self._log_text.configure(state="normal")
        inner = self._log_text._textbox
        inner.insert("end", line, tag)
        self._log_text.configure(state="disabled")

        if self._auto_scroll:
            self._log_text.see("end")

    def _log_info(self, message: str):
        """Inserta un mensaje informativo en el log (no es un paquete)."""
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        line = f"  ---  {ts}  {message}\n"
        self._log_text.configure(state="normal")
        self._log_text._textbox.insert("end", line, "info")
        self._log_text.configure(state="disabled")
        if self._auto_scroll:
            self._log_text.see("end")

    # =====================================================================
    # Send commands
    # =====================================================================

    def _on_send(self):
        """Envía la trama hex del entry."""
        hex_str = self._hex_entry.get().strip()
        if not hex_str:
            return

        if not HexUtils.is_valid_hex(hex_str):
            self._log_info(f"ERROR: hex inválido → '{hex_str}'")
            return

        try:
            data = HexUtils.str_to_bytes(hex_str)
        except ValueError as e:
            self._log_info(f"ERROR: {e}")
            return

        # Guardar en historial
        if not self._cmd_history or self._cmd_history[-1] != hex_str:
            self._cmd_history.append(hex_str)
            if len(self._cmd_history) > self.MAX_HISTORY:
                self._cmd_history.pop(0)
        self._cmd_history_idx = -1

        # Limpiar entry
        self._hex_entry.delete(0, "end")

        # Enviar
        timeout = int(self._timeout_var.get())
        if not self._sniffer.is_attached:
            self._log_info("Sniffer no conectado. Inicia la captura primero.")
            return

        # Usar un hilo para no bloquear la GUI durante el timeout
        import threading
        threading.Thread(
            target=self._send_worker,
            args=(data, timeout),
            daemon=True
        ).start()

    def _send_worker(self, data: bytes, timeout_ms: int):
        """Envía desde un hilo para no bloquear la GUI."""
        try:
            self._sniffer.send_raw(data, wait_response=True, timeout_ms=timeout_ms)
        except Exception as e:
            self.after(0, self._log_info, f"ERROR al enviar: {e}")

    def _send_quick(self, hex_str: str):
        """Envía un comando rápido predefinido."""
        self._hex_entry.delete(0, "end")
        self._hex_entry.insert(0, hex_str)
        self._on_send()

    # =====================================================================
    # Command history (arrow keys)
    # =====================================================================

    def _on_history_up(self, event=None):
        if not self._cmd_history:
            return
        if self._cmd_history_idx == -1:
            self._cmd_history_idx = len(self._cmd_history) - 1
        elif self._cmd_history_idx > 0:
            self._cmd_history_idx -= 1
        self._hex_entry.delete(0, "end")
        self._hex_entry.insert(0, self._cmd_history[self._cmd_history_idx])

    def _on_history_down(self, event=None):
        if not self._cmd_history or self._cmd_history_idx == -1:
            return
        if self._cmd_history_idx < len(self._cmd_history) - 1:
            self._cmd_history_idx += 1
            self._hex_entry.delete(0, "end")
            self._hex_entry.insert(0, self._cmd_history[self._cmd_history_idx])
        else:
            self._cmd_history_idx = -1
            self._hex_entry.delete(0, "end")

    # =====================================================================
    # Context menu (right-click)
    # =====================================================================

    def _on_right_click(self, event):
        try:
            self._context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._context_menu.grab_release()

    def _get_current_line(self) -> str:
        """Obtiene la línea del log donde está el cursor."""
        inner = self._log_text._textbox
        try:
            idx = inner.index("current")
            line_start = f"{idx.split('.')[0]}.0"
            line_end = f"{idx.split('.')[0]}.end"
            return inner.get(line_start, line_end).strip()
        except Exception:
            return ""

    def _copy_selected_line(self):
        """Copia la línea completa al portapapeles."""
        line = self._get_current_line()
        if line:
            self.clipboard_clear()
            self.clipboard_append(line)

    def _copy_selected_hex(self):
        """Extrae y copia solo los datos hex de la línea seleccionada."""
        line = self._get_current_line()
        # El hex está entre las posiciones ~22 y ~78 según nuestro formato
        if line and len(line) > 30:
            parts = line.split()
            hex_bytes = []
            for p in parts:
                p_clean = p.strip()
                if len(p_clean) == 2 and HexUtils.is_valid_hex(p_clean):
                    hex_bytes.append(p_clean)
            if hex_bytes:
                self.clipboard_clear()
                self.clipboard_append(" ".join(hex_bytes))

    def _resend_selected(self):
        """Reenvía el comando TX de la línea seleccionada."""
        line = self._get_current_line()
        if "TX" not in line:
            self._log_info("Solo se pueden reenviar paquetes TX.")
            return
        # Extraer hex bytes de la línea (buscar secuencia que empieza con 02)
        parts = line.split()
        hex_bytes = []
        found_stx = False
        for p in parts:
            p_clean = p.strip()
            if len(p_clean) == 2 and HexUtils.is_valid_hex(p_clean):
                if p_clean == "02" and not found_stx:
                    found_stx = True
                if found_stx:
                    hex_bytes.append(p_clean)
        if hex_bytes:
            hex_str = " ".join(hex_bytes)
            self._hex_entry.delete(0, "end")
            self._hex_entry.insert(0, hex_str)
            self._on_send()

    # =====================================================================
    # Filter
    # =====================================================================

    def _on_raw_toggle(self):
        """Cambia entre vista protocolo limpio y raw HID."""
        self._show_raw_hid = self._raw_hid_var.get()
        self._refresh_log()

    def _on_filter_changed(self, value: str):
        self._filter_dir = value
        # Re-renderizar el log con el nuevo filtro
        self._refresh_log()

    def _refresh_log(self):
        """Reconstruye el log aplicando el filtro actual."""
        self._log_text.configure(state="normal")
        self._log_text._textbox.delete("1.0", "end")
        self._log_text.configure(state="disabled")

        for pkt in self._sniffer.packets:
            self._append_packet_to_log(pkt)

    # =====================================================================
    # Clear / Export
    # =====================================================================

    def _on_clear(self):
        """Limpia el log y el buffer."""
        self._sniffer.clear_buffer()
        self._log_text.configure(state="normal")
        self._log_text._textbox.delete("1.0", "end")
        self._log_text.configure(state="disabled")
        self._counter_label.configure(text="0 paquetes")
        self._pending_packets.clear()

    def _show_export_menu(self):
        """Muestra un menú de exportación."""
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Exportar a CSV...", command=self._export_csv)
        menu.add_command(label="Copiar como texto", command=self._export_clipboard_text)
        menu.add_separator()
        menu.add_command(
            label="Generar código Python (para rfid_protocol.py)",
            command=self._export_python
        )

        # Mostrar debajo del botón
        btn = self._export_menu_btn
        x = btn.winfo_rootx()
        y = btn.winfo_rooty() + btn.winfo_height()
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _export_csv(self):
        filepath = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("Todos", "*.*")],
            initialfile=f"sniffer_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        )
        if filepath:
            self._sniffer.export_csv(filepath)
            self._log_info(f"Exportado a: {filepath}")

    def _export_clipboard_text(self):
        text = self._sniffer.export_text()
        self.clipboard_clear()
        self.clipboard_append(text)
        self._log_info("Captura copiada al portapapeles como texto.")

    def _export_python(self):
        """Genera código Python y lo muestra en una ventana auxiliar."""
        snippet = self._sniffer.export_python_snippet()

        # Ventana emergente con el código
        win = ctk.CTkToplevel(self)
        win.title("Código Python generado — Pega en rfid_protocol.py")
        win.geometry("700x500")
        win.transient(self.winfo_toplevel())

        ctk.CTkLabel(
            win,
            text="Copia este código en core/rfid_protocol.py",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(padx=16, pady=(16, 4))

        text_widget = ctk.CTkTextbox(
            win,
            font=ctk.CTkFont(family="Courier New", size=12),
            wrap="none"
        )
        text_widget.pack(fill="both", expand=True, padx=12, pady=8)
        text_widget.insert("1.0", snippet)

        def copy_all():
            self.clipboard_clear()
            self.clipboard_append(snippet)
            copy_btn.configure(text="Copiado ✓")

        copy_btn = ctk.CTkButton(
            win, text="Copiar al portapapeles",
            command=copy_all,
            height=36
        )
        copy_btn.pack(padx=12, pady=(0, 12))

    # =====================================================================
    # Custom commands (comandos personalizados del usuario)
    # =====================================================================

    def _load_custom_cmds(self) -> list:
        """Carga comandos personalizados desde JSON."""
        try:
            if os.path.exists(self.CUSTOM_CMDS_FILE):
                with open(self.CUSTOM_CMDS_FILE, "r", encoding="utf-8") as f:
                    cmds = json.load(f)
                if isinstance(cmds, list):
                    return cmds[:self.MAX_CUSTOM_SLOTS]
        except Exception as e:
            logger.warning(f"Error cargando comandos personalizados: {e}")
        return []

    def _save_custom_cmds(self):
        """Guarda comandos personalizados a JSON."""
        try:
            os.makedirs(os.path.dirname(self.CUSTOM_CMDS_FILE), exist_ok=True)
            with open(self.CUSTOM_CMDS_FILE, "w", encoding="utf-8") as f:
                json.dump(self._custom_cmds, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"Error guardando comandos personalizados: {e}")

    def _rebuild_custom_buttons(self):
        """Reconstruye la fila de botones personalizados."""
        for widget in self._custom_frame.winfo_children():
            widget.destroy()
        self._custom_buttons.clear()

        ctk.CTkLabel(
            self._custom_frame, text="Mis cmds:",
            font=ctk.CTkFont(size=11),
            text_color=("gray50", "gray60")
        ).pack(side="left", padx=(4, 6))

        # Botones de comandos guardados
        for i, cmd in enumerate(self._custom_cmds):
            name = cmd.get("name", f"Cmd {i+1}")
            hex_val = cmd.get("hex", "")

            btn = ctk.CTkButton(
                self._custom_frame, text=name,
                command=lambda h=hex_val: self._send_quick(h),
                width=90, height=26,
                fg_color="#2E4057", hover_color="#3D556B",
                border_width=1,
                font=ctk.CTkFont(size=11)
            )
            btn.pack(side="left", padx=2)
            # Clic derecho para editar/borrar
            btn.bind("<Button-3>", lambda e, idx=i: self._on_custom_cmd_rightclick(e, idx))
            self._custom_buttons.append(btn)

        # Botón [+] para añadir nuevo comando
        if len(self._custom_cmds) < self.MAX_CUSTOM_SLOTS:
            ctk.CTkButton(
                self._custom_frame, text="+",
                command=self._on_add_custom_cmd,
                width=32, height=26,
                fg_color="transparent", border_width=1,
                font=ctk.CTkFont(size=14, weight="bold"),
                text_color=("#1DB954", "#1DB954")
            ).pack(side="left", padx=(6, 2))

        ctk.CTkLabel(
            self._custom_frame,
            text="(clic derecho = editar/borrar)",
            font=ctk.CTkFont(size=10),
            text_color=("gray60", "gray50")
        ).pack(side="left", padx=8)

    def _on_add_custom_cmd(self):
        """Abre diálogo para añadir un comando personalizado."""
        # Prellenar con el contenido actual del entry hex (si hay)
        current_hex = self._hex_entry.get().strip()
        self._show_custom_cmd_dialog(
            title="Nuevo comando personalizado",
            initial_name="",
            initial_hex=current_hex,
            on_save=self._save_new_custom_cmd
        )

    def _save_new_custom_cmd(self, name: str, hex_val: str):
        """Guarda un nuevo comando personalizado."""
        self._custom_cmds.append({"name": name, "hex": hex_val})
        self._save_custom_cmds()
        self._rebuild_custom_buttons()

    def _on_custom_cmd_rightclick(self, event, idx: int):
        """Menú contextual para un botón personalizado."""
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(
            label="Editar...",
            command=lambda: self._edit_custom_cmd(idx))
        menu.add_command(
            label="Borrar",
            command=lambda: self._delete_custom_cmd(idx))
        menu.add_separator()
        cmd = self._custom_cmds[idx]
        menu.add_command(
            label=f"Hex: {cmd.get('hex', '')}",
            state="disabled")
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _edit_custom_cmd(self, idx: int):
        """Editar un comando personalizado existente."""
        cmd = self._custom_cmds[idx]
        self._show_custom_cmd_dialog(
            title="Editar comando personalizado",
            initial_name=cmd.get("name", ""),
            initial_hex=cmd.get("hex", ""),
            on_save=lambda name, hex_val: self._update_custom_cmd(idx, name, hex_val)
        )

    def _update_custom_cmd(self, idx: int, name: str, hex_val: str):
        """Actualiza un comando personalizado."""
        self._custom_cmds[idx] = {"name": name, "hex": hex_val}
        self._save_custom_cmds()
        self._rebuild_custom_buttons()

    def _delete_custom_cmd(self, idx: int):
        """Borra un comando personalizado."""
        if 0 <= idx < len(self._custom_cmds):
            del self._custom_cmds[idx]
            self._save_custom_cmds()
            self._rebuild_custom_buttons()

    def _show_custom_cmd_dialog(self, title: str, initial_name: str,
                                 initial_hex: str, on_save):
        """Diálogo para crear/editar un comando personalizado."""
        dialog = ctk.CTkToplevel(self)
        dialog.title(title)
        dialog.geometry("460x220")
        dialog.transient(self.winfo_toplevel())
        dialog.grab_set()
        dialog.resizable(False, False)

        # Nombre
        ctk.CTkLabel(
            dialog, text="Nombre del botón:",
            font=ctk.CTkFont(size=13)
        ).grid(row=0, column=0, padx=16, pady=(16, 4), sticky="w")

        name_entry = ctk.CTkEntry(
            dialog, width=300,
            placeholder_text="Ej: Set 8H+CR",
            font=ctk.CTkFont(size=13)
        )
        name_entry.grid(row=0, column=1, padx=(4, 16), pady=(16, 4), sticky="ew")
        if initial_name:
            name_entry.insert(0, initial_name)

        # Hex
        ctk.CTkLabel(
            dialog, text="Comando HEX:",
            font=ctk.CTkFont(size=13)
        ).grid(row=1, column=0, padx=16, pady=4, sticky="w")

        hex_entry = ctk.CTkEntry(
            dialog, width=300,
            placeholder_text="02 05 03 03 05 01 80",
            font=ctk.CTkFont(family="Courier New", size=13)
        )
        hex_entry.grid(row=1, column=1, padx=(4, 16), pady=4, sticky="ew")
        if initial_hex:
            hex_entry.insert(0, initial_hex)

        # Info
        ctk.CTkLabel(
            dialog,
            text="Formato: [STX=02][LEN][CMD]{DATA}  —  el Report ID se calcula solo",
            font=ctk.CTkFont(size=10),
            text_color=("gray60", "gray50")
        ).grid(row=2, column=0, columnspan=2, padx=16, pady=(2, 8))

        # Botones
        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.grid(row=3, column=0, columnspan=2, padx=16, pady=(8, 16), sticky="ew")

        def do_save():
            name = name_entry.get().strip()
            hex_val = hex_entry.get().strip()
            if not name:
                name = hex_val[:20] if hex_val else "Cmd"
            if not hex_val or not HexUtils.is_valid_hex(hex_val):
                name_entry.configure(border_color="red")
                return
            on_save(name, hex_val)
            dialog.destroy()

        ctk.CTkButton(
            btn_frame, text="Guardar",
            command=do_save,
            width=120, height=36,
            fg_color="#1DB954", hover_color="#158a3e",
            font=ctk.CTkFont(size=13, weight="bold")
        ).pack(side="right", padx=4)

        ctk.CTkButton(
            btn_frame, text="Cancelar",
            command=dialog.destroy,
            width=100, height=36,
            fg_color="transparent", border_width=1
        ).pack(side="right", padx=4)

        dialog.grid_columnconfigure(1, weight=1)
        name_entry.focus_set()
        hex_entry.bind("<Return>", lambda e: do_save())

    # =====================================================================
    # Public API (llamado desde MainWindow)
    # =====================================================================

    def on_reader_connected(self):
        """Notificación de que el lector se ha conectado."""
        self._log_info("Lector conectado. Puedes iniciar la captura.")

    def on_reader_disconnected(self):
        """Notificación de que el lector se ha desconectado."""
        if self._sniffer.is_capturing:
            self._stop_capture()
        self._log_info("Lector desconectado. Captura detenida.")

    def cleanup(self):
        """Limpieza al cerrar la aplicación."""
        if self._sniffer.is_capturing:
            self._sniffer.stop_capture()
