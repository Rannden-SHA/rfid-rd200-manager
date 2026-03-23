# =============================================================================
# utils/logger.py
# Configuración centralizada del sistema de logging.
# =============================================================================

import logging
import logging.handlers
import os
from pathlib import Path


def setup_logging(level: str = "INFO", log_file: str = "rfid_manager.log") -> None:
    """
    Configura el sistema de logging para toda la aplicación.

    - Consola: nivel configurado (INFO por defecto)
    - Archivo rotativo: nivel DEBUG siempre (para diagnóstico completo)

    Args:
        level: Nivel mínimo para la consola ("DEBUG", "INFO", "WARNING", "ERROR")
        log_file: Nombre del archivo de log (relativo al directorio de la app)
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    # Formato detallado para archivo, conciso para consola
    file_fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)-25s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    console_fmt = logging.Formatter(
        fmt="%(levelname)-8s | %(name)-20s | %(message)s"
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)  # Capturar todo; los handlers filtran

    # Limpiar handlers existentes (evitar duplicados en reinicios)
    root_logger.handlers.clear()

    # Handler de consola
    console_handler = logging.StreamHandler()
    console_handler.setLevel(numeric_level)
    console_handler.setFormatter(console_fmt)
    root_logger.addHandler(console_handler)

    # Handler de archivo rotativo (máx 5MB × 3 archivos)
    # En modo .exe, guardar el log junto al ejecutable
    import sys
    if getattr(sys, 'frozen', False):
        log_path = Path(os.path.dirname(sys.executable)) / log_file
    else:
        log_path = Path(log_file)
    try:
        file_handler = logging.handlers.RotatingFileHandler(
            filename=log_path,
            maxBytes=5 * 1024 * 1024,  # 5 MB
            backupCount=3,
            encoding="utf-8"
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(file_fmt)
        root_logger.addHandler(file_handler)
    except OSError as e:
        logging.warning(f"No se pudo crear el archivo de log '{log_file}': {e}")

    # Silenciar loggers ruidosos de librerías externas
    logging.getLogger("usb").setLevel(logging.WARNING)
    logging.getLogger("hid").setLevel(logging.WARNING)

    logging.debug("Sistema de logging inicializado.")
