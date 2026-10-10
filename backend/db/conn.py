"""DuckDB connection + small write helpers (Polars in, Polars out)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import polars as pl

from db.migrations import BASELINE_VERSION, MIGRATIONS

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect(path: Path | str) -> duckdb.DuckDBPyConnection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    init_schema(con)
    return con


@contextmanager
def transaction(con: duckdb.DuckDBPyConnection) -> Iterator[duckdb.DuckDBPyConnection]:
    """All-or-nothing writes: commit on success, roll back if anything inside raises."""
    con.execute("BEGIN TRANSACTION")
    try:
        yield con
    except BaseException:
        con.execute("ROLLBACK")
        raise
    con.execute("COMMIT")


def schema_version(con: duckdb.DuckDBPyConnection) -> int:
    row = con.execute("SELECT max(version) FROM schema_version").fetchone()
    return int(row[0]) if row and row[0] is not None else BASELINE_VERSION


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Create the v1 baseline (idempotent), then apply any pending migrations in order."""
    con.execute(SCHEMA_PATH.read_text(encoding="utf-8"))
    con.execute(
        "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, applied_at TIMESTAMP)"
    )
    current = schema_version(con)
    for version, sql in sorted(MIGRATIONS):
        if version <= current:
            continue
        with transaction(con):
            con.execute(sql)
            con.execute(
                "INSERT INTO schema_version VALUES (?, ?)",
                [version, datetime.now(UTC).replace(tzinfo=None)],
            )


def upsert(con: duckdb.DuckDBPyConnection, table: str, df: pl.DataFrame) -> int:
    """INSERT OR REPLACE rows by column name (table must have a primary key)."""
    if df.is_empty():
        return 0
    con.register("_upsert_df", df.to_arrow())
    try:
        con.execute(f"INSERT OR REPLACE INTO {table} BY NAME SELECT * FROM _upsert_df")
    finally:
        con.unregister("_upsert_df")
    return df.height


def replace_where(
    con: duckdb.DuckDBPyConnection, table: str, df: pl.DataFrame, where: str, params: list
) -> int:
    """Delete rows matching `where`, then insert `df` (for tables without a primary key)."""
    con.execute(f"DELETE FROM {table} WHERE {where}", params)
    if df.is_empty():
        return 0
    con.register("_replace_df", df.to_arrow())
    try:
        con.execute(f"INSERT INTO {table} BY NAME SELECT * FROM _replace_df")
    finally:
        con.unregister("_replace_df")
    return df.height


def query_df(con: duckdb.DuckDBPyConnection, sql: str, params: list | None = None) -> pl.DataFrame:
    return con.execute(sql, params or []).pl()


def log_sync(
    con: duckdb.DuckDBPyConnection, source: str, status: str = "ok", detail: str = ""
) -> None:
    con.execute(
        "INSERT OR REPLACE INTO sync_log VALUES (?, ?, ?, ?)",
        [source, datetime.now(UTC).replace(tzinfo=None), status, detail],
    )
