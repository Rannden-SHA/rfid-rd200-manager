# =============================================================================
# core/batch_processor.py
#
# Lógica del modo Batch (cadena de montaje / kiosko).
# Completamente separado de la GUI: emite eventos mediante callbacks.
# =============================================================================

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Optional, Callable, List
from datetime import datetime

from .reader_manager import ReaderManager, ReaderConnectionError, ReaderWriteError
from .rfid_protocol import CardData

logger = logging.getLogger(__name__)


@dataclass
class BatchConfig:
    """
    Configuración predefinida para aplicar a cada tarjeta en modo batch.
    Extiende este dataclass con los campos que tu sistema requiera.
    """
    # Bloque y datos a escribir (None = no escribir nada)
    target_block: Optional[int] = None
    block_data: Optional[bytes] = None    # Exactamente 16 bytes si se usa

    # Clave MIFARE (default: FFFFFFFFFFFF)
    auth_key: bytes = field(default_factory=lambda: b'\xFF\xFF\xFF\xFF\xFF\xFF')
    auth_key_type: str = "A"

    # Comportamiento del lector al finalizar
    led_success_color: str = "green"
    led_error_color: str = "red"
    beep_on_success: bool = True
    beep_on_error: bool = True

    # Datos extra que quieras grabar (ej. código de evento, fecha, etc.)
    custom_payload: bytes = b""           # Se integrará en block_data si está vacío

    def validate(self) -> List[str]:
        """
        Valida la configuración. Devuelve lista de errores (vacía si es válida).
        """
        errors = []
        if self.target_block is not None:
            if not (0 <= self.target_block <= 255):
                errors.append("target_block debe estar entre 0 y 255.")
            if self.block_data is not None and len(self.block_data) != 16:
                errors.append("block_data debe ser exactamente 16 bytes.")
        if len(self.auth_key) != 6:
            errors.append("auth_key debe ser exactamente 6 bytes.")
        if self.auth_key_type not in ("A", "B"):
            errors.append("auth_key_type debe ser 'A' o 'B'.")
        return errors


@dataclass
class BatchResult:
    """Resultado de procesar una tarjeta en modo batch."""
    uid: str
    success: bool
    message: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    duration_ms: float = 0.0


class BatchProcessor:
    """
    Motor del modo batch. Usa ReaderManager para detectar y procesar
    tarjetas una a una, de forma autónoma.

    Flujo:
      1. start(config, callbacks) → inicia hilo de procesamiento
      2. Espera tarjeta → procesa → emite resultado → espera siguiente
      3. stop() → detiene el procesamiento

    Todos los callbacks se llaman desde el hilo batch. Si actualizas la GUI,
    usa root.after() en tkinter o invokeMethod() en Qt.
    """

    def __init__(self, reader: ReaderManager):
        self._reader = reader
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._config: Optional[BatchConfig] = None

        # Contadores de sesión
        self.total_processed = 0
        self.total_success = 0
        self.total_errors = 0
        self._history: List[BatchResult] = []

    # -------------------------------------------------------------------------
    # API pública
    # -------------------------------------------------------------------------

    def start(self,
              config: BatchConfig,
              on_waiting: Optional[Callable[[], None]] = None,
              on_card_detected: Optional[Callable[[CardData], None]] = None,
              on_success: Optional[Callable[[BatchResult], None]] = None,
              on_error: Optional[Callable[[BatchResult], None]] = None,
              on_reader_disconnected: Optional[Callable[[], None]] = None):
        """
        Inicia el modo batch.

        Args:
            config: Configuración a aplicar a cada tarjeta.
            on_waiting: Llamado cuando el sistema vuelve a estado de espera.
            on_card_detected: Llamado inmediatamente al detectar una tarjeta.
            on_success: Llamado tras aplicar la configuración con éxito.
            on_error: Llamado si hay un error al procesar una tarjeta.
            on_reader_disconnected: Llamado si el lector se desconecta.
        """
        if self._running:
            logger.warning("El modo batch ya está activo.")
            return

        # Validar configuración antes de empezar
        errors = config.validate()
        if errors:
            raise ValueError(f"Configuración batch inválida: {'; '.join(errors)}")

        self._config = config
        self._running = True
        self._reset_counters()

        self._thread = threading.Thread(
            target=self._batch_loop,
            kwargs={
                "on_waiting": on_waiting,
                "on_card_detected": on_card_detected,
                "on_success": on_success,
                "on_error": on_error,
                "on_reader_disconnected": on_reader_disconnected,
            },
            daemon=True,
            name="BatchProcessorThread"
        )
        self._thread.start()
        logger.info("Modo batch iniciado.")

    def stop(self):
        """Detiene el modo batch de forma segura."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self._thread = None
        logger.info("Modo batch detenido.")

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def history(self) -> List[BatchResult]:
        """Lista de resultados de las tarjetas procesadas en esta sesión."""
        return list(self._history)

    # -------------------------------------------------------------------------
    # Loop interno
    # -------------------------------------------------------------------------

    def _batch_loop(self, on_waiting, on_card_detected,
                    on_success, on_error, on_reader_disconnected):
        """Loop principal del modo batch. Se ejecuta en su propio hilo."""
        last_uid_processed: Optional[str] = None

        logger.debug("Batch loop iniciado.")

        while self._running:
            try:
                # --- Estado: ESPERANDO TARJETA ---
                if on_waiting:
                    on_waiting()

                card = self._wait_for_new_card(last_uid_processed)

                if card is None:
                    # Timeout o lector sin tarjeta → seguir esperando
                    continue

                # --- Tarjeta detectada ---
                logger.info(f"Batch: tarjeta detectada → UID={card.uid}")
                if on_card_detected:
                    on_card_detected(card)

                # --- Procesar tarjeta ---
                result = self._process_card(card)
                last_uid_processed = card.uid
                self._history.append(result)

                if result.success:
                    self.total_success += 1
                    if on_success:
                        on_success(result)
                else:
                    self.total_errors += 1
                    if on_error:
                        on_error(result)

                self.total_processed += 1

                # Pequeña pausa para que el operario retire la tarjeta
                time.sleep(0.8)

            except ReaderConnectionError as e:
                logger.error(f"Batch: lector desconectado → {e}")
                self._running = False
                if on_reader_disconnected:
                    on_reader_disconnected()
                break

            except Exception as e:
                logger.exception(f"Batch: error inesperado en el loop → {e}")
                self.total_errors += 1
                time.sleep(0.5)

        logger.debug("Batch loop terminado.")

    def _wait_for_new_card(self, last_uid: Optional[str],
                           poll_interval: float = 0.3) -> Optional[CardData]:
        """
        Bloquea hasta detectar una tarjeta diferente a last_uid.
        Devuelve None si no se detecta nada en un ciclo (para permitir stop()).
        Usa read_card() que funciona tanto en modo comando como pasivo.
        """
        deadline = time.time() + 0.5  # Check breve antes de volver al loop
        while self._running and time.time() < deadline:
            card = self._reader.read_card(timeout_s=0.3)
            if card and card.uid != last_uid:
                return card
            time.sleep(poll_interval)
        return None

    def _process_card(self, card: CardData) -> BatchResult:
        """
        Aplica la configuración batch a la tarjeta detectada.

        Returns:
            BatchResult con éxito o fallo y mensaje descriptivo.
        """
        t_start = time.time()
        config = self._config

        try:
            # --- Escritura de bloque (si está configurada) ---
            if config.target_block is not None and config.block_data is not None:
                # Sector se calcula del bloque (MIFARE Classic: 4 bloques/sector)
                sector = config.target_block // 4
                success = self._reader.write_block(
                    block_number=config.target_block,
                    data=config.block_data,
                    key_type=config.auth_key_type,
                    sector=sector,
                    key=config.auth_key,
                )
                if not success:
                    return BatchResult(
                        uid=card.uid,
                        success=False,
                        message=f"Fallo al escribir bloque {config.target_block} "
                                f"(autenticación incorrecta o bloque protegido).",
                        duration_ms=(time.time() - t_start) * 1000,
                    )

            # --- Feedback visual/sonoro en el lector ---
            if config.beep_on_success:
                self._reader.set_buzzer(True)
                time.sleep(0.1)
                self._reader.set_buzzer(False)

            self._reader.set_led(config.led_success_color, True)
            time.sleep(0.5)
            self._reader.set_led(config.led_success_color, False)

            duration = (time.time() - t_start) * 1000
            return BatchResult(
                uid=card.uid,
                success=True,
                message="Configuración aplicada correctamente.",
                duration_ms=duration,
            )

        except ReaderWriteError as e:
            # Tarjeta retirada a mitad de escritura u otro error de escritura
            logger.warning(f"BatchProcessor: error de escritura → {e}")
            self._try_error_feedback(config)
            return BatchResult(
                uid=card.uid,
                success=False,
                message=str(e),
                duration_ms=(time.time() - t_start) * 1000,
            )

        except ReaderConnectionError:
            raise  # Propagar al loop principal para manejo de desconexión

        except Exception as e:
            logger.exception(f"BatchProcessor: error inesperado procesando {card.uid}")
            self._try_error_feedback(config)
            return BatchResult(
                uid=card.uid,
                success=False,
                message=f"Error inesperado: {e}",
                duration_ms=(time.time() - t_start) * 1000,
            )

    def _try_error_feedback(self, config: BatchConfig):
        """Intenta emitir feedback de error en el lector (sin lanzar excepciones)."""
        try:
            if config.beep_on_error:
                self._reader.set_buzzer(True)
                time.sleep(0.3)
                self._reader.set_buzzer(False)
            self._reader.set_led(config.led_error_color, True)
            time.sleep(0.5)
            self._reader.set_led(config.led_error_color, False)
        except Exception:
            pass  # Si el lector falló, no podemos hacer feedback

    def _reset_counters(self):
        self.total_processed = 0
        self.total_success = 0
        self.total_errors = 0
        self._history = []
