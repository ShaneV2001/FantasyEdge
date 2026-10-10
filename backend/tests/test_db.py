import duckdb
import polars as pl
import pytest

from db import conn
from db.conn import connect, init_schema, schema_version, transaction, upsert
from db.migrations import MIGRATIONS, latest_version


def _columns(con, table: str) -> set[str]:
    return {r[0] for r in con.execute(f"DESCRIBE {table}").fetchall()}


def test_fresh_store_is_at_latest_version(tmp_path):
    con = connect(tmp_path / "ff.duckdb")
    assert schema_version(con) == latest_version()


def test_init_schema_is_idempotent(tmp_path):
    con = connect(tmp_path / "ff.duckdb")
    init_schema(con)
    init_schema(con)
    assert schema_version(con) == latest_version()
    versions = [r[0] for r in con.execute("SELECT version FROM schema_version").fetchall()]
    assert len(versions) == len(set(versions))


def test_pending_migrations_reach_an_existing_store(tmp_path, monkeypatch):
    path = tmp_path / "ff.duckdb"
    con = connect(path)
    upsert(con, "sync_log", pl.DataFrame({"source": ["x"], "status": ["ok"], "detail": [""]}))
    con.close()

    extra = [(latest_version() + 1, "ALTER TABLE sync_log ADD COLUMN IF NOT EXISTS note VARCHAR")]
    monkeypatch.setattr(conn, "MIGRATIONS", MIGRATIONS + extra)
    con = duckdb.connect(str(path))
    init_schema(con)
    assert "note" in _columns(con, "sync_log")
    assert schema_version(con) == latest_version() + 1
    assert con.execute("SELECT count(*) FROM sync_log").fetchone()[0] == 1


def test_failed_migration_leaves_version_unchanged(tmp_path, monkeypatch):
    path = tmp_path / "ff.duckdb"
    connect(path).close()
    bad = [(latest_version() + 1, "ALTER TABLE no_such_table ADD COLUMN x INT")]
    monkeypatch.setattr(conn, "MIGRATIONS", MIGRATIONS + bad)
    con = duckdb.connect(str(path))
    with pytest.raises(duckdb.Error):
        init_schema(con)
    assert schema_version(con) == latest_version()


def test_transaction_rolls_back_on_error(tmp_path):
    con = connect(tmp_path / "ff.duckdb")
    upsert(con, "sync_log", pl.DataFrame({"source": ["keep"], "status": ["ok"], "detail": [""]}))
    with pytest.raises(RuntimeError), transaction(con):
        con.execute("DELETE FROM sync_log")
        raise RuntimeError("boom")
    assert con.execute("SELECT source FROM sync_log").fetchall() == [("keep",)]
