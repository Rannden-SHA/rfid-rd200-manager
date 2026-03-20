# =============================================================================
# gui/manual_tab.py
# Pestaña de operación manual: lectura, escritura y visualización de bloques.
# =============================================================================

import logging
import customtkinter as ctk
from typing import Optional, Callable

from core.reader_manager import ReaderManager, ReaderConnectionError, ReaderWriteError
from core.rfid_protocol import CardData
from utils.hex_utils import HexUtils
from gui.widgets.status_indicator import CardDisplayPanel

logger = logging.getLogger(__name__)


class ManualTab(ctk.CTkFrame):
    """
    Pestaña de modo manual.

    Funcionalidades:
      - Muestra en tiempo real el UID, tipo y timestamp de la tarjeta detectada
      - Panel de bloques con lectura individual o completa
      - Escritura de un bloque con datos hexadecimales
      - Acceso rápido a configuraciones frecuentes
    """

    def __init__(self, parent, reader: ReaderManager, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self._reader = reader

        self.grid_columnconfigure(0, weight=2)   # Panel izquierdo (tarjeta)
        self.grid_columnconfigure(1, weight=3)   # Panel derecho (bloques)
        self.grid_rowconfigure(0, weight=1)

        self._build_left_panel()
        self._build_right_panel()

    # -------------------------------------------------------------------------
    # Construcción de la UI
    # -------------------------------------------------------------------------

    def _build_left_panel(self):
        left = ctk.CTkFrame(self, corner_radius=12)
        left.grid(row=0, column=0, padx=(8, 4), pady=8, sticky="nsew")
        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            left, text="Tarjeta Actual",
            font=ctk.CTkFont(size=16, weight="bold")
        ).grid(row=0, column=0, padx=16, pady=(16, 4), sticky="w")

        # Panel de display de tarjeta
        self._card_panel = CardDisplayPanel(left)
        self._card_panel.grid(row=1, column=0, padx=12, pady=8, sticky="nsew")

        # Botones de acceso rápido
        btn_frame = ctk.CTkFrame(left, fg_color="transparent")
        btn_frame.grid(row=2, column=0, padx=12, pady=(0, 16), sticky="ew")
        btn_frame.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkButton(
            btn_frame, text="Leer UID",
            command=self._on_read_uid,
            height=38
        ).grid(row=0, column=0, padx=4, pady=4, sticky="ew")

        ctk.CTkButton(
            btn_frame, text="Leer todos\nlos bloques",
            command=self._on_read_all_blocks,
            height=38
        ).grid(row=0, column=1, padx=4, pady=4, sticky="ew")

        ctk.CTkButton(
            btn_frame, text="Limpiar pantalla",
            command=self._on_clear,
            fg_color="transparent",
            border_width=1,
            height=32
        ).grid(row=1, column=0, columnspan=2, padx=4, pady=(0, 4), sticky="ew")

    def _build_right_panel(self):
        right = ctk.CTkFrame(self, corner_radius=12)
        right.grid(row=0, column=1, padx=(4, 8), pady=8, sticky="nsew")
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            right, text="Bloques de Memoria",
            font=ctk.CTkFont(size=16, weight="bold")
        ).grid(row=0, column=0, padx=16, pady=(16, 4), sticky="w")

        # Área de texto para mostrar bloques
        self._blocks_text = ctk.CTkTextbox(
            right,
            font=ctk.CTkFont(family="Courier New", size=12),
            state="disabled",
            wrap="none"
        )
        self._blocks_text.grid(row=1, column=0, padx=12, pady=8, sticky="nsew")

        # Panel de escritura
        write_frame = ctk.CTkFrame(right, corner_radius=8)
        write_frame.grid(row=2, column=0, padx=12, pady=(0, 16), sticky="ew")
        write_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(write_frame, text="Escribir bloque:", width=110, anchor="w"
                     ).grid(row=0, column=0, padx=(12, 4), pady=8)

        self._block_num_var = ctk.StringVar(value="4")
        self._block_num_entry = ctk.CTkEntry(
            write_frame, textvariable=self._block_num_var,
            width=60, placeholder_text="Nº"
        )
        self._block_num_entry.grid(row=0, column=1, padx=4, pady=8, sticky="w")

        ctk.CTkLabel(write_frame, text="Datos (hex 16B):", anchor="w", width=130
                     ).grid(row=1, column=0, padx=(12, 4), pady=4)

        self._write_data_var = ctk.StringVar()
        self._write_data_entry = ctk.CTkEntry(
            write_frame, textvariable=self._write_data_var,
            placeholder_text="00 11 22 33 44 55 66 77 88 99 AA BB CC DD EE FF",
            width=380
        )
        self._write_data_entry.grid(row=1, column=1, padx=(4, 12), pady=4, sticky="ew")

        ctk.CTkLabel(write_frame, text="Clave Auth (hex):", anchor="w", width=130
                     ).grid(row=2, column=0, padx=(12, 4), pady=4)

        self._key_var = ctk.StringVar(value="FF FF FF FF FF FF")
        self._key_entry = ctk.CTkEntry(
            write_frame, textvariable=self._key_var,
            placeholder_text="FF FF FF FF FF FF"
        )
        self._key_entry.grid(row=2, column=1, padx=(4, 12), pady=4, sticky="ew")

        self._key_type_var = ctk.StringVar(value="A")
        ctk.CTkSegmentedButton(
            write_frame, values=["A", "B"],
            variable=self._key_type_var
        ).grid(row=3, column=1, padx=(4, 12), pady=(0, 8), sticky="w")

        ctk.CTkButton(
            write_frame, text="Escribir bloque",
            command=self._on_write_block,
            fg_color="#E53935",
            hover_color="#B71C1C",
            height=38
        ).grid(row=3, column=0, padx=(12, 4), pady=(0, 8), sticky="ew")

        # Barra de estado/resultado
        self._result_label = ctk.CTkLabel(
            right, text="", font=ctk.CTkFont(size=12),
            text_color=("gray50", "gray60")
        )
        self._result_label.grid(row=3, column=0, padx=12, pady=(0, 8))

    # -------------------------------------------------------------------------
    # Acciones
    # -------------------------------------------------------------------------

    def _on_read_uid(self):
        """Lee el UID de la tarjeta presente."""
        if not self._reader.is_connected:
            self._show_result("El lector no está conectado.", error=True)
            return
        try:
            card = self._reader.read_card(timeout_s=2.0)
            if card:
                self._card_panel.update_card(
                    uid=card.uid,
                    uid_decimal=card.uid_decimal,
                    card_type=card.card_type,
                    timestamp=card.timestamp,
                )
                self._show_result(f"UID leído: {card.uid}")
            else:
                self._show_result("No se detectó ninguna tarjeta.", error=True)
        except ReaderConnectionError as e:
            self._show_result(str(e), error=True)

    def _on_read_all_blocks(self):
        """Lee todos los bloques disponibles de la tarjeta."""
        if not self._reader.is_connected:
            self._show_result("El lector no está conectado.", error=True)
            return

        self._set_blocks_text("Leyendo bloques... por favor espere.\n")

        try:
            key = HexUtils.str_to_bytes(self._key_var.get())
        except ValueError as e:
            self._show_result(f"Clave inválida: {e}", error=True)
            return

        key_type = self._key_type_var.get()
        lines = []
        errors = 0

        # Leer los primeros 16 bloques (sector 0-3 de MIFARE 1K)
        for block_num in range(16):
            try:
                sector = block_num // 4
                data = self._reader.read_block(
                    block_num, key_type=key_type, sector=sector, key=key)
                if data:
                    lines.append(HexUtils.format_block_display(block_num, data))
                else:
                    lines.append(f"Bloque {block_num:03d}: [sin datos / sin acceso]")
                    errors += 1
            except ReaderConnectionError as e:
                self._show_result(str(e), error=True)
                return

        self._set_blocks_text("\n".join(lines))
        self._show_result(
            f"Lectura completada: {16 - errors}/16 bloques leídos."
            + (f" ({errors} con error)" if errors else "")
        )

    def _on_write_block(self):
        """Escribe datos en un bloque específico de la tarjeta."""
        if not self._reader.is_connected:
            self._show_result("El lector no está conectado.", error=True)
            return

        # Validar número de bloque
        try:
            block_num = int(self._block_num_var.get())
            if not (0 <= block_num <= 255):
                raise ValueError()
        except ValueError:
            self._show_result("Número de bloque inválido (0-255).", error=True)
            return

        # Advertencia para bloques de sector trailer (cada 4to bloque: 3,7,11...)
        if (block_num + 1) % 4 == 0:
            logger.warning(f"Intento de escritura en sector trailer (bloque {block_num})")
            # En una app completa, aquí mostrarías un diálogo de confirmación

        # Validar datos hex
        try:
            data = HexUtils.str_to_bytes(self._write_data_var.get())
            data = HexUtils.pad_block_data(data)  # Rellenar/truncar a 16 bytes
        except ValueError as e:
            self._show_result(f"Datos hex inválidos: {e}", error=True)
            return

        # Validar clave
        try:
            key = HexUtils.str_to_bytes(self._key_var.get())
        except ValueError as e:
            self._show_result(f"Clave inválida: {e}", error=True)
            return

        key_type = self._key_type_var.get()

        try:
            sector = block_num // 4
            success = self._reader.write_block(
                block_num, data, key_type=key_type, sector=sector, key=key)
            if success:
                self._show_result(
                    f"Bloque {block_num} escrito: {HexUtils.bytes_to_str(data)}"
                )
            else:
                self._show_result(
                    f"No se pudo escribir el bloque {block_num}.", error=True
                )
        except ReaderWriteError as e:
            self._show_result(str(e), error=True)
        except ReaderConnectionError as e:
            self._show_result(str(e), error=True)

    def _on_clear(self):
        self._card_panel.clear()
        self._set_blocks_text("")
        self._result_label.configure(text="")

    # -------------------------------------------------------------------------
    # Actualización desde el hilo de polling (llamar con root.after)
    # -------------------------------------------------------------------------

    def on_card_detected(self, card: CardData):
        """
        Llamado por el hilo de polling cuando se detecta una tarjeta.
        Debe llamarse desde el hilo de la GUI usando root.after().
        """
        self._card_panel.update_card(
            uid=card.uid,
            uid_decimal=card.uid_decimal,
            card_type=card.card_type,
            timestamp=card.timestamp,
        )

    # -------------------------------------------------------------------------
    # Utilidades internas
    # -------------------------------------------------------------------------

    def _set_blocks_text(self, content: str):
        self._blocks_text.configure(state="normal")
        self._blocks_text.delete("1.0", "end")
        self._blocks_text.insert("1.0", content)
        self._blocks_text.configure(state="disabled")

    def _show_result(self, message: str, error: bool = False):
        color = ("#E53935", "#E53935") if error else ("#1DB954", "#1DB954")
        self._result_label.configure(text=message, text_color=color)
        logger.info(f"ManualTab: {message}")
