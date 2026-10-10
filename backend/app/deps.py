"""Process-wide resources: one DuckDB connection (cursor per request) and the HTTP clients."""

from __future__ import annotations

import threading
from collections.abc import Iterator

import duckdb

from app.config import get_settings
from db.conn import connect
from ingest.run import Clients, make_clients

_con: duckdb.DuckDBPyConnection | None = None
_clients: Clients | None = None
_lock = threading.Lock()
# DuckDB allows one writer; serialise requests that write (sync, connect, manual, refresh).
write_lock = threading.Lock()


def init(con: duckdb.DuckDBPyConnection | None = None, clients: Clients | None = None) -> None:
    global _con, _clients
    with _lock:
        _con = con or connect(get_settings().db_path)
        _clients = clients or make_clients()


def get_con() -> Iterator[duckdb.DuckDBPyConnection]:
    if _con is None:
        init()
    assert _con is not None
    cur = _con.cursor()
    try:
        yield cur
    finally:
        cur.close()


def get_clients() -> Clients:
    if _clients is None:
        init()
    assert _clients is not None
    return _clients
