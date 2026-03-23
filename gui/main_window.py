# =============================================================================
# gui/main_window.py
# Ventana principal de la aplicación. Orquesta las pestañas y el ciclo de
# conexión/reconexión con el lector.
# =============================================================================

import json
import logging
import threading
from pathlib import Path

import customtkinter as ctk

from core.reader_manager import ReaderManager, ReaderConnectionError
from core.rfid_protocol import CardData
from gui.manual_tab import ManualTab
from gui.batch_tab import BatchTab
from gui.reader_config_tab import ReaderConfigTab
from gui.sniffer_tab import SnifferTab
from gui.widgets.status_indicator import ConnectionStatusBar

logger = logging.getLogger(__name__)

SETTINGS_PATH = Path(__file__).parent.parent / "config" / "settings.json"


class MainWindow(ctk.CTk):
    """
    Ventana raíz de la aplicación.

    Responsabilidades:
      - Cargar configuración desde settings.json
      - Gestionar el ciclo de vida de ReaderManager (connect / auto-reconnect)
      - Iniciar el polling en segundo plano y despachar eventos a las pestañas
      - Proporcionar la barra de estado global
    """

    def __init__(self):
        super().__init__()

        self._settings = self._load_settings()
        self._reader = ReaderManager()
        self._reconnect_job = None   # ID del after() de reconexión

        self._apply_theme()
        self._build_ui()
        self._start_connection_loop()

    # -------------------------------------------------------------------------
    # Configuración y tema
    # -------------------------------------------------------------------------

    def _load_settings(self) -> dict:
        try:
            with open(SETTINGS_PATH, encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            logger.warning("settings.json no encontrado, usando valores por defecto.")
            return {}
        except json.JSONDecodeError as e:
            logger.error(f"settings.json malformado: {e}")
            return {}

    def _apply_theme(self):
        gui = self._settings.get("gui", {})
        theme = gui.get("theme", "dark")
        scheme = gui.get("color_scheme", "blue")
        ctk.set_appearance_mode(theme)
        ctk.set_default_color_theme(scheme)

        w = gui.get("window_width", 1100)
        h = gui.get("window_height", 700)
        self.geometry(f"{w}x{h}")
        self.minsize(900, 580)
        self.title("RFID Wristband Manager  —  RD200-M1-G")

    # -------------------------------------------------------------------------
    # Construcción de la UI
    # -------------------------------------------------------------------------

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=0)   # Header
        self.grid_rowconfigure(1, weight=1)   # Tabs
        self.grid_rowconfigure(2, weight=0)   # Status bar

        # Header
        header = ctk.CTkFrame(self, height=52, corner_radius=0)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="RFID Wristband Manager",
            font=ctk.CTkFont(size=20, weight="bold"),
            anchor="w"
        ).grid(row=0, column=0, padx=20, pady=12, sticky="w")

        ctk.CTkLabel(
            header,
            text="RD200-M1-G  |  VID:0E6A  PID:0317",
            font=ctk.CTkFont(size=11),
            text_color=("gray50", "gray60"),
            anchor="e"
        ).grid(row=0, column=1, padx=20, pady=12, sticky="e")

        # TabView
        self._tabs = ctk.CTkTabview(self, corner_radius=8)
        self._tabs.grid(row=1, column=0, padx=8, pady=(4, 0), sticky="nsew")

        # Crear pestañas
        self._tabs.add("Manual")
        self._tabs.add("Batch / Kiosko")
        self._tabs.add("Sniffer HID")
        self._tabs.add("Config. Lector")

        # Instanciar contenido de cada pestaña
        self._manual_tab = ManualTab(
            self._tabs.tab("Manual"), self._reader
        )
        self._manual_tab.pack(fill="both", expand=True)

        self._batch_tab = BatchTab(
            self._tabs.tab("Batch / Kiosko"), self._reader
        )
        self._batch_tab.pack(fill="both", expand=True)

        self._sniffer_tab = SnifferTab(
            self._tabs.tab("Sniffer HID"), self._reader
        )
        self._sniffer_tab.pack(fill="both", expand=True)

        self._reader_config_tab = ReaderConfigTab(
            self._tabs.tab("Config. Lector"), self._reader
        )
        self._reader_config_tab.pack(fill="both", expand=True)

        # Barra de estado
        self._status_bar = ConnectionStatusBar(self)
        self._status_bar.grid(row=2, column=0, sticky="ew")

    # -------------------------------------------------------------------------
    # Ciclo de conexión con hot-swap automático
    # -------------------------------------------------------------------------

    def _start_connection_loop(self):
        """Intenta conectar al lector en un hilo para no bloquear la GUI."""
        # Cancelar cualquier reconexión programada previa
        if self._reconnect_job:
            self.after_cancel(self._reconnect_job)
            self._reconnect_job = None

        threading.Thread(
            target=self._connect_worker,
            daemon=True,
            name="ConnectionWorker"
        ).start()

    def _connect_worker(self):
        """Worker que intenta conectar y lanza el polling si lo logra."""
        self.after(0, lambda: self._status_bar.set_state("searching"))

        # IMPORTANTE: desconectar limpiamente antes de reconectar
        # Esto permite hot-swap de lectores
        try:
            self._reader.disconnect()
        except Exception:
            pass

        try:
            self._reader.connect()
            self.after(0, self._on_connected)
        except ReaderConnectionError as e:
            logger.warning(f"Conexión fallida: {e}")
            self.after(0, lambda: self._on_connection_failed(str(e)))

    def _on_connected(self):
        """Llamado en el hilo de GUI cuando la conexión es exitosa."""
        mode = "COMANDO" if self._reader.in_command_mode else "PASIVO"
        sn = self._reader.serial_number or ""
        logger.info(f"MainWindow: lector conectado (modo={mode}, SN={sn}).")

        # Obtener versión de firmware
        fw = "N/A"
        try:
            fw = self._reader.get_version()
        except Exception:
            pass

        detail = f"[{mode}]"
        if sn:
            detail += f"  SN: {sn}"
        self._status_bar.set_state("connected", detail=detail, firmware=fw)
        self._batch_tab.on_reader_reconnected()
        self._sniffer_tab.on_reader_connected()
        self._reader_config_tab.on_reader_connected()

        # Iniciar polling
        self._reader.start_polling(
            callback=self._on_card_from_polling,
            on_error=self._on_polling_error,
        )

    def _on_connection_failed(self, detail: str):
        """Programa un reintento de conexión."""
        self._status_bar.set_state(
            "disconnected",
            detail=f"Buscando lector... (cada {self._reconnect_interval}s)"
        )
        interval_ms = self._reconnect_interval * 1000
        self._reconnect_job = self.after(interval_ms, self._start_connection_loop)

    def _on_polling_error(self, exc: Exception):
        """Llamado desde el hilo de polling cuando el lector se desconecta."""
        logger.warning(f"MainWindow: lector desconectado durante polling → {exc}")
        self.after(0, self._on_reader_disconnected)

    def _on_reader_disconnected(self):
        """Reacciona a la desconexión del lector."""
        self._status_bar.set_state(
            "disconnected",
            detail="Lector desconectado. Esperando nuevo lector..."
        )
        self._sniffer_tab.on_reader_disconnected()
        # Reconectar rápido (1s) para detectar nuevo lector
        self._reconnect_job = self.after(1000, self._start_connection_loop)

    @property
    def _reconnect_interval(self) -> int:
        return self._settings.get("reader", {}).get("reconnect_interval_s", 3)

    # -------------------------------------------------------------------------
    # Dispatch de eventos de tarjeta a las pestañas
    # -------------------------------------------------------------------------

    def _on_card_from_polling(self, card: CardData):
        """
        Llamado desde el hilo de polling. Usa after() para despachar
        a las pestañas en el hilo de la GUI.
        """
        self.after(0, self._dispatch_card, card)

    def _dispatch_card(self, card: CardData):
        """Entrega la tarjeta a la pestaña activa."""
        active = self._tabs.get()
        if active == "Manual":
            self._manual_tab.on_card_detected(card)
        # El batch_tab tiene su propio loop interno; no necesita dispatch externo

    # -------------------------------------------------------------------------
    # Cierre de la aplicación
    # -------------------------------------------------------------------------

    def on_closing(self):
        """Limpieza antes de cerrar la ventana."""
        logger.info("Cerrando aplicación...")
        if self._reconnect_job:
            self.after_cancel(self._reconnect_job)
        if hasattr(self, "_sniffer_tab"):
            self._sniffer_tab.cleanup()
        if hasattr(self, "_batch_tab"):
            self._batch_tab._processor.stop()
        self._reader.disconnect()
        self.destroy()
