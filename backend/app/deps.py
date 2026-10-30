"""Process-wide resources: one DuckDB connection (cursor per request) and the HTTP clients."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path

import anthropic
import duckdb

from app import user_settings
from app.config import Settings, get_settings
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


def new_cursor() -> duckdb.DuckDBPyConnection:
    """A cursor for work that outlives a request's own (a streamed response); the caller closes it."""
    if _con is None:
        init()
    assert _con is not None
    return _con.cursor()


_ai: anthropic.Anthropic | None = None


def get_ai_settings() -> Settings:
    return get_settings()


def get_ai() -> anthropic.Anthropic | None:
    """The Anthropic client for the advisor chat, or None when no ANTHROPIC_API_KEY is set."""
    global _ai
    s = get_settings()
    if not s.ai_enabled:
        return None
    if _ai is None:
        _ai = anthropic.Anthropic(api_key=s.anthropic_api_key)
    return _ai


def get_clients() -> Clients:
    if _clients is None:
        init()
    assert _clients is not None
    return _clients


def settings_path() -> Path:
    return get_clients().settings.data_dir / "settings.json"


def get_tuning() -> user_settings.UserSettings:
    return user_settings.load(settings_path())[0]
