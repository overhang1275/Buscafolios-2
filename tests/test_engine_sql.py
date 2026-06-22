from __future__ import annotations

from pathlib import Path

from busca_folios.duckdb_engine import detect_columns, preview_file
from busca_folios.models import FileConfig


def test_preview_and_columns(tmp_path: Path) -> None:
    data = tmp_path / "prod.csv"
    data.write_text("folio,nombre\n001,Ana\n002,Luis\n", encoding="utf-8")
    config = FileConfig(data, True, ",", "utf-8", "folio")
    assert detect_columns(config) == ["folio", "nombre"]
    assert preview_file(config, 1).iloc[0]["folio"] == "001"

