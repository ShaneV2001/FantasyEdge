from __future__ import annotations

import json
import os
from pathlib import Path

import polars as pl
import pytest
from tenacity import wait_none

from ingest.http import CachedHttp

FIXTURES = Path(__file__).parent / "fixtures"

# The API's background NFL-data refresher would download real data: tests drive it directly
os.environ["FF_AUTO_REFRESH"] = "0"


def load_json(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def load_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def load_parquet(name: str) -> pl.DataFrame:
    return pl.read_parquet(FIXTURES / name)


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture(autouse=True)
def _no_retry_wait(monkeypatch):
    """Keep retry semantics in tests but skip the backoff sleeps."""
    monkeypatch.setattr(CachedHttp._fetch.retry, "wait", wait_none())
