# =============================================================================
# gui/widgets/status_indicator.py
# Widgets reutilizables para la GUI: barra de estado, panel de tarjeta, etc.
# =============================================================================

import customtkinter as ctk
from typing import Optional


class ConnectionStatusBar(ctk.CTkFrame):
    """
    Barra inferior que muestra el estado de la conexión con el lector.
    Cambia de color según el estado: conectado (verde), error (rojo), buscando (amarillo).
    """

    COLORS = {
        "connected":     ("#1DB954", "#1DB954"),   # Verde Spotify
        "disconnected":  ("#E53935", "#E53935"),   # Rojo
        "searching":     ("#FFA726", "#FFA726"),   # Naranja
        "idle":          ("#555555", "#333333"),
    }

    def __init__(self, parent, **kwargs):
        super().__init__(parent, height=36, corner_radius=0, **kwargs)
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_columnconfigure(2, weight=0)

        # Indicador LED circular
        self._dot = ctk.CTkLabel(self, text="●", font=ctk.CTkFont(size=18))
        self._dot.grid(row=0, column=0, padx=(12, 4), pady=4)

        # Texto de estado
        self._label = ctk.CTkLabel(
            self, text="Buscando lector...",
            font=ctk.CTkFont(size=12),
            anchor="w"
        )
        self._label.grid(row=0, column=1, padx=4, pady=4, sticky="w")

        # Versión de firmware (derecha)
        self._fw_label = ctk.CTkLabel(
            self, text="",
            font=ctk.CTkFont(size=11),
            text_color=("gray50", "gray60")
        )
        self._fw_label.grid(row=0, column=2, padx=12, pady=4)

        self.set_state("searching")

    def set_state(self, state: str, detail: str = "", firmware: str = ""):
        """
        state: "connected" | "disconnected" | "searching" | "idle"
        detail: Texto adicional (ej. path del dispositivo)
        firmware: Versión de firmware a mostrar en la derecha
        """
        color = self.COLORS.get(state, self.COLORS["idle"])
        self._dot.configure(text_color=color)

        messages = {
            "connected":    f"Lector conectado  {detail}",
            "disconnected": f"Lector desconectado  {detail}",
            "searching":    "Buscando lector...",
            "idle":         "Sin actividad",
        }
        self._label.configure(text=messages.get(state, detail))
        if firmware:
            self._fw_label.configure(text=f"FW: {firmware}")


class CardDisplayPanel(ctk.CTkFrame):
    """
    Panel grande que muestra la información de la última tarjeta leída.
    Se actualiza con update_card() y se limpia con clear().
    """

    def __init__(self, parent, **kwargs):
        super().__init__(parent, corner_radius=12, **kwargs)
        self.grid_columnconfigure(0, weight=1)

        # Título / estado
        self._status_label = ctk.CTkLabel(
            self,
            text="Acerque una pulsera al lector",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=("gray50", "gray60"),
        )
        self._status_label.grid(row=0, column=0, pady=(24, 4), padx=24)

        # UID grande
        self._uid_label = ctk.CTkLabel(
            self, text="--",
            font=ctk.CTkFont(size=36, weight="bold"),
            text_color=("gray20", "gray90"),
        )
        self._uid_label.grid(row=1, column=0, pady=4)

        # UID decimal
        self._uid_dec_label = ctk.CTkLabel(
            self, text="",
            font=ctk.CTkFont(size=13),
            text_color=("gray40", "gray60"),
        )
        self._uid_dec_label.grid(row=2, column=0, pady=(0, 8))

        # Tipo de tarjeta
        self._type_label = ctk.CTkLabel(
            self, text="",
            font=ctk.CTkFont(size=13),
        )
        self._type_label.grid(row=3, column=0, pady=4)

        # Timestamp
        self._time_label = ctk.CTkLabel(
            self, text="",
            font=ctk.CTkFont(size=11),
            text_color=("gray50", "gray60"),
        )
        self._time_label.grid(row=4, column=0, pady=(0, 16))

    def update_card(self, uid: str, uid_decimal: str = "",
                    card_type: str = "", timestamp: str = ""):
        """Actualiza el panel con los datos de la tarjeta leída."""
        self._status_label.configure(
            text="Tarjeta detectada",
            text_color=("#1DB954", "#1DB954")
        )
        self._uid_label.configure(text=uid or "--")
        self._uid_dec_label.configure(
            text=f"Dec: {uid_decimal}" if uid_decimal else ""
        )
        self._type_label.configure(text=card_type)
        self._time_label.configure(text=timestamp)

    def clear(self):
        """Limpia el panel al estado inicial."""
        self._status_label.configure(
            text="Acerque una pulsera al lector",
            text_color=("gray50", "gray60")
        )
        self._uid_label.configure(text="--")
        self._uid_dec_label.configure(text="")
        self._type_label.configure(text="")
        self._time_label.configure(text="")


class BatchStatusPanel(ctk.CTkFrame):
    """
    Panel de estado para el modo batch.
    Muestra el estado actual (ESPERANDO / ÉXITO / ERROR) con colores llamativos.
    """

    STATE_COLORS = {
        "waiting": {
            "bg":   ("#2B2B2B", "#1A1A1A"),
            "text": ("gray60", "gray50"),
            "icon": "⏳",
        },
        "detected": {
            "bg":   ("#1565C0", "#0D47A1"),
            "text": ("white", "white"),
            "icon": "📡",
        },
        "success": {
            "bg":   ("#1B5E20", "#1B5E20"),
            "text": ("white", "white"),
            "icon": "✅",
        },
        "error": {
            "bg":   ("#B71C1C", "#B71C1C"),
            "text": ("white", "white"),
            "icon": "❌",
        },
    }

    def __init__(self, parent, **kwargs):
        kwargs.setdefault("corner_radius", 16)
        super().__init__(parent, **kwargs)
        self.grid_columnconfigure(0, weight=1)

        # Icono de estado grande
        self._icon_label = ctk.CTkLabel(
            self, text="⏳",
            font=ctk.CTkFont(size=64),
        )
        self._icon_label.grid(row=0, column=0, pady=(32, 8))

        # Texto de estado principal
        self._main_label = ctk.CTkLabel(
            self,
            text="ESPERANDO PULSERA",
            font=ctk.CTkFont(size=28, weight="bold"),
        )
        self._main_label.grid(row=1, column=0, pady=4)

        # Mensaje secundario (UID, error, etc.)
        self._detail_label = ctk.CTkLabel(
            self, text="",
            font=ctk.CTkFont(size=14),
        )
        self._detail_label.grid(row=2, column=0, pady=(0, 8))

        # Contadores
        self._counter_frame = ctk.CTkFrame(self, fg_color="transparent")
        self._counter_frame.grid(row=3, column=0, pady=16, padx=32, sticky="ew")
        self._counter_frame.grid_columnconfigure((0, 1, 2), weight=1)

        self._total_var  = ctk.StringVar(value="0")
        self._ok_var     = ctk.StringVar(value="0")
        self._error_var  = ctk.StringVar(value="0")

        for col, (label, var, color) in enumerate([
            ("Total",   self._total_var,  ("gray70", "gray70")),
            ("OK",      self._ok_var,     ("#1DB954", "#1DB954")),
            ("Errores", self._error_var,  ("#E53935", "#E53935")),
        ]):
            f = ctk.CTkFrame(self._counter_frame, corner_radius=8)
            f.grid(row=0, column=col, padx=6, sticky="ew")
            ctk.CTkLabel(f, textvariable=var,
                         font=ctk.CTkFont(size=28, weight="bold"),
                         text_color=color).pack(pady=(8, 0))
            ctk.CTkLabel(f, text=label,
                         font=ctk.CTkFont(size=11)).pack(pady=(0, 8))

    def set_state(self, state: str, uid: str = "", message: str = ""):
        """
        Actualiza el panel al estado dado.
        state: "waiting" | "detected" | "success" | "error"
        """
        cfg = self.STATE_COLORS.get(state, self.STATE_COLORS["waiting"])
        self.configure(fg_color=cfg["bg"])
        self._icon_label.configure(text=cfg["icon"])
        self._main_label.configure(text_color=cfg["text"])
        self._detail_label.configure(text_color=cfg["text"])

        state_texts = {
            "waiting":  "ESPERANDO PULSERA",
            "detected": f"LEYENDO...  {uid}",
            "success":  "CONFIGURACIÓN EXITOSA",
            "error":    "ERROR EN CONFIGURACIÓN",
        }
        self._main_label.configure(text=state_texts.get(state, state.upper()))
        self._detail_label.configure(
            text=f"UID: {uid}" if uid and state == "success" else message
        )

    def update_counters(self, total: int, ok: int, errors: int):
        self._total_var.set(str(total))
        self._ok_var.set(str(ok))
        self._error_var.set(str(errors))

    def reset_counters(self):
        self.update_counters(0, 0, 0)
