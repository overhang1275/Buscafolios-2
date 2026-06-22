from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Callable

import duckdb
import pandas as pd

from busca_folios.models import FileConfig, SearchConfig, SearchStats

LOGGER = logging.getLogger(__name__)
Progress = Callable[[int, str], None]


def file_size_label(path: Path) -> str:
    size = path.stat().st_size
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:,.2f} {unit}"
        value /= 1024
    return f"{size:,} B"


def delimiter_value(label: str, custom: str = "") -> str:
    mapping = {"Coma (,)": ",", "Pipe (|)": "|", "Tabulacion": "\t", "Punto y coma (;)": ";"}
    return custom if label == "Personalizado" else mapping[label]


def duckdb_encoding(label: str) -> str:
    return {"UTF-8": "utf-8", "Latin1": "latin-1", "ANSI": "latin-1"}[label]


def sql_literal(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def read_csv_sql(config: FileConfig) -> str:
    return (
        "read_csv("
        f"{sql_literal(config.path)}, "
        f"delim={sql_literal(config.delimiter)}, "
        f"header={'true' if config.has_header else 'false'}, "
        f"encoding={sql_literal(config.encoding)}, "
        "all_varchar=true, "
        "ignore_errors=true, "
        "null_padding=true, "
        "sample_size=20480"
        ")"
    )


def preview_file(config: FileConfig, rows: int = 50) -> pd.DataFrame:
    con = duckdb.connect()
    try:
        return con.execute(f"SELECT * FROM {read_csv_sql(config)} LIMIT {int(rows)}").fetchdf()
    finally:
        con.close()


def detect_columns(config: FileConfig) -> list[str]:
    con = duckdb.connect()
    try:
        return [d[0] for d in con.execute(f"SELECT * FROM {read_csv_sql(config)} LIMIT 0").description]
    finally:
        con.close()


def _copy_csv(con: duckdb.DuckDBPyConnection, query: str, output: Path) -> None:
    con.execute(
        f"COPY ({query}) TO {sql_literal(output)} "
        "(HEADER, DELIMITER ',', QUOTE '\"', ESCAPE '\"')"
    )


def export_csv_to_xlsx(csv_path: Path, xlsx_path: Path, sheet_prefix: str) -> None:
    max_rows = 1_048_576
    chunk_rows = max_rows - 1
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        for index, chunk in enumerate(pd.read_csv(csv_path, chunksize=chunk_rows, dtype=str), start=1):
            chunk.to_excel(writer, index=False, sheet_name=f"{sheet_prefix}_{index}")


class FolioSearchEngine:
    def __init__(self) -> None:
        self.con = duckdb.connect()

    def close(self) -> None:
        self.con.close()

    def cancel(self) -> None:
        interrupt = getattr(self.con, "interrupt", None)
        if interrupt:
            interrupt()

    def run(self, config: SearchConfig, progress: Progress) -> SearchStats:
        started = time.perf_counter()
        config.output_dir.mkdir(parents=True, exist_ok=True)
        found_csv = config.output_dir / "encontrados.csv"
        missing_csv = config.output_dir / "no_encontrados.csv"

        prod = read_csv_sql(config.production)
        folios = read_csv_sql(config.folios)
        prod_folio = ident(config.production.folio_column)
        folio_col = ident(config.folios.folio_column)

        if config.start_row is None and config.end_row is None:
            production_cte = f"SELECT * FROM {prod}"
        else:
            start = 0 if config.start_row is None else config.start_row
            end = 9_223_372_036_854_775_807 if config.end_row is None else config.end_row
            production_cte = (
                "SELECT * EXCLUDE (__busca_rn) FROM ("
                f"SELECT *, row_number() OVER () - 1 AS __busca_rn FROM {prod}"
                f") WHERE __busca_rn BETWEEN {int(start)} AND {int(end)}"
            )

        folios_cte = (
            f"SELECT DISTINCT trim(CAST({folio_col} AS VARCHAR)) AS __folio "
            f"FROM {folios} WHERE {folio_col} IS NOT NULL AND trim(CAST({folio_col} AS VARCHAR)) <> ''"
        )
        found_query = (
            "WITH production AS ("
            f"{production_cte}"
            "), wanted AS ("
            f"{folios_cte}"
            ") SELECT production.* FROM production "
            f"JOIN wanted ON trim(CAST(production.{prod_folio} AS VARCHAR)) = wanted.__folio"
        )
        missing_query = (
            "WITH production AS ("
            f"{production_cte}"
            "), wanted AS ("
            f"{folios_cte}"
            "), found AS ("
            f"SELECT DISTINCT wanted.__folio FROM production "
            f"JOIN wanted ON trim(CAST(production.{prod_folio} AS VARCHAR)) = wanted.__folio"
            ") SELECT wanted.__folio AS folio FROM wanted ANTI JOIN found USING (__folio)"
        )

        progress(5, "Contando folios a buscar")
        searched = self.con.execute(f"WITH wanted AS ({folios_cte}) SELECT count(*) FROM wanted").fetchone()[0]

        progress(15, "Exportando encontrados.csv")
        LOGGER.info("Writing found rows to %s", found_csv)
        _copy_csv(self.con, found_query, found_csv)

        progress(55, "Exportando no_encontrados.csv")
        LOGGER.info("Writing missing rows to %s", missing_csv)
        _copy_csv(self.con, missing_query, missing_csv)

        progress(75, "Calculando resumen")
        found = self.con.execute(f"SELECT count(*) FROM read_csv({sql_literal(found_csv)}, header=true)").fetchone()[0]
        not_found = self.con.execute(
            f"SELECT count(*) FROM read_csv({sql_literal(missing_csv)}, header=true)"
        ).fetchone()[0]
        processed = self.con.execute(f"WITH production AS ({production_cte}) SELECT count(*) FROM production").fetchone()[0]

        if config.export_xlsx:
            progress(85, "Exportando XLSX")
            export_csv_to_xlsx(found_csv, config.output_dir / "encontrados.xlsx", "encontrados")
            export_csv_to_xlsx(missing_csv, config.output_dir / "no_encontrados.xlsx", "no_encontrados")

        elapsed = time.perf_counter() - started
        progress(100, "Finalizado")
        return SearchStats(
            processed_rows=int(processed),
            searched_folios=int(searched),
            found=int(found),
            not_found=int(not_found),
            elapsed_seconds=elapsed,
        )
