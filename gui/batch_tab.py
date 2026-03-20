# =============================================================================
# gui/batch_tab.py
# Pestaña de Modo Batch (cadena de montaje / kiosko).
# =============================================================================

import logging
import customtkinter as ctk
from typing import Optional

from core.reader_manager import ReaderManager
from core.batch_processor import BatchProcessor, BatchConfig, BatchResult
from core.rfid_protocol import CardData
from utils.hex_utils import HexUtils
from gui.widgets.status_indicator import BatchStatusPanel

logger = logging.getLogger(__name__)


class BatchTab(ctk.CTkFrame):
    """
    Pestaña de modo batch / kiosko.

    Cuando el modo está activo:
      - La pantalla muestra un estado visual grande (ESPERANDO / ÉXITO / ERROR)
      - Cada tarjeta detectada se procesa automáticamente
      - Se lleva un contador de tarjetas procesadas en la sesión
    """

    def __init__(self, parent, reader: ReaderManager, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self._reader = reader
        self._processor = BatchProcessor(reader)
        self._was_polling = False  # Track si el polling estaba activo antes del batch

        self.grid_columnconfigure(0, weight=2)
        self.grid_columnconfigure(1, weight=3)
        self.grid_rowconfigure(0, weight=1)

        self._build_config_panel()
        self._build_status_panel()

    # -------------------------------------------------------------------------
    # Construcción de UI
    # -------------------------------------------------------------------------

    def _build_config_panel(self):
        """Panel izquierdo: configuración del batch."""
        panel = ctk.CTkFrame(self, corner_radius=12)
        panel.grid(row=0, column=0, padx=(8, 4), pady=8, sticky="nsew")
        panel.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            panel, text="Configuración Batch",
            font=ctk.CTkFont(size=16, weight="bold")
        ).grid(row=0, column=0, padx=16, pady=(16, 12), sticky="w")

        # --- Bloque destino ---
        self._enable_write = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            panel, text="Escribir en bloque",
            variable=self._enable_write,
            command=self._toggle_write_fields
        ).grid(row=1, column=0, padx=16, pady=(4, 0), sticky="w")

        write_inner = ctk.CTkFrame(panel, fg_color="transparent")
        write_inner.grid(row=2, column=0, padx=16, pady=4, sticky="ew")
        write_inner.grid_columnconfigure(1, weight=1)
        self._write_inner = write_inner

        ctk.CTkLabel(write_inner, text="Nº Bloque:", width=90, anchor="w"
                     ).grid(row=0, column=0, pady=4)
        self._block_var = ctk.StringVar(value="4")
        self._block_entry = ctk.CTkEntry(
            write_inner, textvariable=self._block_var, width=60
        )
        self._block_entry.grid(row=0, column=1, padx=4, pady=4, sticky="w")

        ctk.CTkLabel(write_inner, text="Datos (hex):", width=90, anchor="w"
                     ).grid(row=1, column=0, pady=4)
        self._data_var = ctk.StringVar()
        self._data_entry = ctk.CTkEntry(
            write_inner, textvariable=self._data_var,
            placeholder_text="00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00"
        )
        self._data_entry.grid(row=1, column=1, padx=4, pady=4, sticky="ew")

        ctk.CTkLabel(write_inner, text="Clave Auth:", width=90, anchor="w"
                     ).grid(row=2, column=0, pady=4)
        self._key_var = ctk.StringVar(value="FF FF FF FF FF FF")
        self._key_entry = ctk.CTkEntry(write_inner, textvariable=self._key_var)
        self._key_entry.grid(row=2, column=1, padx=4, pady=4, sticky="ew")

        self._key_type_var = ctk.StringVar(value="A")
        ctk.CTkSegmentedButton(
            write_inner, values=["A", "B"], variable=self._key_type_var, width=80
        ).grid(row=3, column=1, padx=4, pady=(0, 4), sticky="w")

        self._toggle_write_fields()  # Estado inicial

        # Separador
        ctk.CTkFrame(panel, height=2, fg_color=("gray80", "gray30")
                     ).grid(row=3, column=0, padx=16, pady=12, sticky="ew")

        # --- Opciones de feedback ---
        ctk.CTkLabel(panel, text="Feedback del lector",
                     font=ctk.CTkFont(size=13, weight="bold")
                     ).grid(row=4, column=0, padx=16, pady=(0, 4), sticky="w")

        self._beep_ok = ctk.BooleanVar(value=True)
        self._beep_err = ctk.BooleanVar(value=True)

        ctk.CTkCheckBox(panel, text="Beep al éxito",
                        variable=self._beep_ok
                        ).grid(row=5, column=0, padx=24, pady=2, sticky="w")
        ctk.CTkCheckBox(panel, text="Beep al error",
                        variable=self._beep_err
                        ).grid(row=6, column=0, padx=24, pady=2, sticky="w")

        # --- Botones de control ---
        ctrl_frame = ctk.CTkFrame(panel, fg_color="transparent")
        ctrl_frame.grid(row=7, column=0, padx=16, pady=16, sticky="ew")
        ctrl_frame.grid_columnconfigure((0, 1), weight=1)

        self._start_btn = ctk.CTkButton(
            ctrl_frame, text="▶  INICIAR",
            command=self._on_start,
            fg_color="#1DB954", hover_color="#158a3e",
            height=44, font=ctk.CTkFont(size=14, weight="bold")
        )
        self._start_btn.grid(row=0, column=0, padx=4, pady=4, sticky="ew")

        self._stop_btn = ctk.CTkButton(
            ctrl_frame, text="⏹  DETENER",
            command=self._on_stop,
            fg_color="#E53935", hover_color="#B71C1C",
            height=44, font=ctk.CTkFont(size=14, weight="bold"),
            state="disabled"
        )
        self._stop_btn.grid(row=0, column=1, padx=4, pady=4, sticky="ew")

        ctk.CTkButton(
            ctrl_frame, text="Resetear contadores",
            command=self._on_reset_counters,
            fg_color="transparent", border_width=1,
            height=32
        ).grid(row=1, column=0, columnspan=2, padx=4, pady=(0, 4), sticky="ew")

        # Historial de sesión
        ctk.CTkLabel(panel, text="Historial de sesión",
                     font=ctk.CTkFont(size=13, weight="bold")
                     ).grid(row=8, column=0, padx=16, pady=(8, 4), sticky="w")

        self._history_text = ctk.CTkTextbox(
            panel, height=140,
            font=ctk.CTkFont(family="Courier New", size=11),
            state="disabled"
        )
        self._history_text.grid(row=9, column=0, padx=12, pady=(0, 16), sticky="ew")

    def _build_status_panel(self):
        """Panel derecho: estado visual del modo batch."""
        self._status_panel = BatchStatusPanel(self, corner_radius=16)
        self._status_panel.grid(row=0, column=1, padx=(4, 8), pady=8, sticky="nsew")

    # -------------------------------------------------------------------------
    # Acciones de control
    # -------------------------------------------------------------------------

    def _on_start(self):
        """Valida la configuración e inicia el modo batch."""
        if not self._reader.is_connected:
            logger.warning("Batch: intento de iniciar sin lector conectado.")
            return

        try:
            config = self._build_batch_config()
        except ValueError as e:
            # Mostrar error de validación
            self._status_panel.set_state("error", message=str(e))
            return

        # Detener el polling principal para evitar conflictos de acceso HID
        self._was_polling = self._reader.is_polling
        if self._was_polling:
            self._reader.stop_polling()
            logger.info("Batch: polling principal detenido para modo batch.")

        self._start_btn.configure(state="disabled")
        self._stop_btn.configure(state="normal")
        self._status_panel.set_state("waiting")

        self._processor.start(
            config=config,
            on_waiting=lambda: self._safe_gui(self._on_batch_waiting),
            on_card_detected=lambda c: self._safe_gui(self._on_batch_detected, c),
            on_success=lambda r: self._safe_gui(self._on_batch_success, r),
            on_error=lambda r: self._safe_gui(self._on_batch_error, r),
            on_reader_disconnected=lambda: self._safe_gui(self._on_reader_disc),
        )

    def _on_stop(self):
        """Detiene el modo batch y restaura el polling principal."""
        self._processor.stop()
        self._start_btn.configure(state="normal")
        self._stop_btn.configure(state="disabled")
        self._status_panel.set_state("waiting")
        # Notificar a MainWindow para que reinicie el polling si es necesario
        if self._was_polling:
            self._was_polling = False
            logger.info("Batch: modo batch detenido, polling puede reiniciarse.")

    def _on_reset_counters(self):
        if not self._processor.is_running:
            self._processor._reset_counters()
            self._status_panel.reset_counters()
            self._set_history_text("")

    # -------------------------------------------------------------------------
    # Callbacks del BatchProcessor (ejecutados en hilo batch → via after())
    # -------------------------------------------------------------------------

    def _on_batch_waiting(self):
        self._status_panel.set_state("waiting")

    def _on_batch_detected(self, card: CardData):
        self._status_panel.set_state("detected", uid=card.uid)

    def _on_batch_success(self, result: BatchResult):
        self._status_panel.set_state("success", uid=result.uid)
        self._status_panel.update_counters(
            self._processor.total_processed,
            self._processor.total_success,
            self._processor.total_errors,
        )
        self._append_history(result)

    def _on_batch_error(self, result: BatchResult):
        self._status_panel.set_state("error", message=result.message)
        self._status_panel.update_counters(
            self._processor.total_processed,
            self._processor.total_success,
            self._processor.total_errors,
        )
        self._append_history(result)

    def _on_reader_disc(self):
        self._stop_btn.configure(state="disabled")
        self._start_btn.configure(state="disabled")  # Hasta reconexión
        self._status_panel.set_state("error", message="Lector desconectado")

    def on_reader_reconnected(self):
        """Llamar desde MainWindow cuando el lector se reconecta."""
        self._start_btn.configure(state="normal")

    # -------------------------------------------------------------------------
    # Utilidades
    # -------------------------------------------------------------------------

    def _build_batch_config(self) -> BatchConfig:
        """
        Lee los campos de la UI y construye un BatchConfig validado.
        Raises ValueError si algún campo es inválido.
        """
        config = BatchConfig(
            beep_on_success=self._beep_ok.get(),
            beep_on_error=self._beep_err.get(),
        )

        if self._enable_write.get():
            # Bloque
            try:
                block_num = int(self._block_var.get())
            except ValueError:
                raise ValueError("Número de bloque inválido.")
            config.target_block = block_num

            # Datos
            data_str = self._data_var.get().strip()
            if not data_str:
                raise ValueError("Ingresa los datos hex a escribir.")
            try:
                raw_data = HexUtils.str_to_bytes(data_str)
                config.block_data = HexUtils.pad_block_data(raw_data)
            except ValueError as e:
                raise ValueError(f"Datos hex inválidos: {e}")

            # Clave
            try:
                config.auth_key = HexUtils.str_to_bytes(self._key_var.get())
            except ValueError as e:
                raise ValueError(f"Clave de autenticación inválida: {e}")
            config.auth_key_type = self._key_type_var.get()

        # Validar config completa
        errors = config.validate()
        if errors:
            raise ValueError("; ".join(errors))

        return config

    def _toggle_write_fields(self):
        """Habilita/deshabilita los campos de escritura."""
        state = "normal" if self._enable_write.get() else "disabled"
        for w in self._write_inner.winfo_children():
            try:
                w.configure(state=state)
            except Exception:
                pass

    def _safe_gui(self, func, *args):
        """
        Ejecuta func en el hilo de la GUI usando after().
        Los callbacks del BatchProcessor llegan desde un hilo secundario.
        """
        try:
            self.after(0, func, *args)
        except Exception as e:
            logger.warning(f"_safe_gui: error programando callback → {e}")

    def _append_history(self, result: BatchResult):
        """Agrega una línea al historial de sesión."""
        icon = "✓" if result.success else "✗"
        line = f"{icon} {result.timestamp[11:19]}  UID:{result.uid}  {result.message[:40]}\n"
        self._history_text.configure(state="normal")
        self._history_text.insert("end", line)
        self._history_text.see("end")
        self._history_text.configure(state="disabled")

    def _set_history_text(self, content: str):
        self._history_text.configure(state="normal")
        self._history_text.delete("1.0", "end")
        self._history_text.insert("1.0", content)
        self._history_text.configure(state="disabled")
