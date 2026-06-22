from __future__ import annotations

import logging
import traceback

from PySide6.QtCore import QObject, Signal, Slot

from busca_folios.duckdb_engine import FolioSearchEngine
from busca_folios.models import SearchConfig, SearchStats

LOGGER = logging.getLogger(__name__)


class SearchWorker(QObject):
    progress = Signal(int, str)
    log = Signal(str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, config: SearchConfig) -> None:
        super().__init__()
        self.config = config
        self.engine: FolioSearchEngine | None = None

    @Slot()
    def run(self) -> None:
        self.engine = FolioSearchEngine()
        try:
            self.log.emit("Proceso iniciado")
            stats = self.engine.run(self.config, self._progress)
            self.finished.emit(stats)
        except Exception as exc:
            LOGGER.exception("Search failed")
            self.failed.emit(f"{exc}\n\n{traceback.format_exc(limit=5)}")
        finally:
            self.engine.close()
            self.engine = None

    @Slot()
    def cancel(self) -> None:
        if self.engine:
            self.log.emit("Cancelando consulta en DuckDB")
            self.engine.cancel()

    def _progress(self, percent: int, message: str) -> None:
        self.progress.emit(percent, message)
        self.log.emit(message)

