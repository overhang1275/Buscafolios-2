from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FileConfig:
    path: Path
    has_header: bool
    delimiter: str
    encoding: str
    folio_column: str


@dataclass(frozen=True)
class SearchConfig:
    production: FileConfig
    folios: FileConfig
    output_dir: Path
    start_row: int | None = None
    end_row: int | None = None
    export_xlsx: bool = False


@dataclass(frozen=True)
class SearchStats:
    processed_rows: int
    searched_folios: int
    found: int
    not_found: int
    elapsed_seconds: float

    @property
    def rows_per_second(self) -> float:
        return self.processed_rows / self.elapsed_seconds if self.elapsed_seconds else 0.0

