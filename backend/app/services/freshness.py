"""Keeps the NFL data fresh while the API runs.

The current week, projections, recaps and injury alerts all come from local copies of nflverse
(schedule, scores, stats, injury reports) and Sleeper's player list. Without this, they only
changed when someone ran `python tasks.py data` with the API stopped, so the app could sit on a
week that ended days ago.

A daemon thread checks every `CHECK_EVERY`:
- nflverse refreshes when its copy is older than `NFL_MAX_AGE`, or when a game that kicked off
  more than `SCORE_LAG` ago still has no score (results are usually published within hours);
- Sleeper's player list (injury statuses) refreshes when older than `PLAYERS_MAX_AGE` (Sleeper
  asks callers to fetch it at most once a day).
A failed or fruitless attempt waits `RETRY_AFTER` before the next. Downloads run outside the
database write lock; only the writes take it, so pages never wait on a download.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import duckdb

from app.services import context
from ingest import run as jobs
from ingest.run import Clients
from signals.schedule import EASTERN

log = logging.getLogger("fantasyedge.freshness")

CHECK_EVERY = timedelta(minutes=30)
NFL_MAX_AGE = timedelta(hours=12)
PLAYERS_MAX_AGE = timedelta(hours=20)
SCORE_LAG = timedelta(hours=4)  # a game should have its final score this long after kickoff
SCORE_WINDOW = timedelta(days=8)  # older unscored games (postponed, data gaps) don't count
RETRY_AFTER = timedelta(hours=2)
STALE_AFTER = timedelta(hours=36)


def _utc(now: datetime) -> datetime:
    """Naive UTC, like the `sync_log` timestamps."""
    return now.astimezone(UTC).replace(tzinfo=None) if now.tzinfo else now


def last_synced(con: duckdb.DuckDBPyConnection, source: str) -> datetime | None:
    row = con.execute(
        "SELECT last_synced_at FROM sync_log WHERE source = ? AND status = 'ok'", [source]
    ).fetchone()
    return row[0] if row else None


def unscored_week(con: duckdb.DuckDBPyConnection, now: datetime) -> int | None:
    """The earliest week with a recent game that kicked off `SCORE_LAG` ago and has no score yet,
    or None. nflverse kickoffs are naive US/Eastern."""
    now_et = now.astimezone(EASTERN).replace(tzinfo=None) if now.tzinfo else now
    row = con.execute(
        "SELECT min(week) FROM nfl_games WHERE home_score IS NULL AND kickoff BETWEEN ? AND ?",
        [now_et - SCORE_WINDOW, now_et - SCORE_LAG],
    ).fetchone()
    return row[0] if row else None


def nfl_stale(con: duckdb.DuckDBPyConnection, now: datetime) -> bool:
    """What the app shows may be behind: results missing, or the copy is days old."""
    synced = last_synced(con, "nflverse")
    return synced is None or _utc(now) - synced > STALE_AFTER or unscored_week(con, now) is not None


@dataclass
class Job:
    source: str  # its sync_log source
    max_age: timedelta
    fetch: Callable[[Clients], object]
    write: Callable[[duckdb.DuckDBPyConnection, Clients, object], object]
    needs_scores: bool = False  # also due when a played game has no score


JOBS = [
    Job(
        "nflverse",
        NFL_MAX_AGE,
        jobs.fetch_nflverse,
        lambda con, c, tables: jobs.write_nflverse(con, c, tables),  # type: ignore[arg-type]
        needs_scores=True,
    ),
    Job(
        "sleeper_players",
        PLAYERS_MAX_AGE,
        lambda c: jobs.fetch_players(c),
        lambda con, c, df: jobs.write_players(con, df),  # type: ignore[arg-type]
    ),
]


@dataclass
class Refresher:
    clients: Callable[[], Clients]
    cursor: Callable[[], duckdb.DuckDBPyConnection]
    lock: threading.Lock
    jobs: list[Job] = field(default_factory=lambda: list(JOBS))
    running: bool = False
    last_error: str | None = None
    attempts: dict[str, datetime] = field(default_factory=dict)
    _stop: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = None

    def due(self, con: duckdb.DuckDBPyConnection, now: datetime) -> list[Job]:
        out = []
        for job in self.jobs:
            tried = self.attempts.get(job.source)
            if tried is not None and _utc(now) - tried < RETRY_AFTER:
                continue
            synced = last_synced(con, job.source)
            old = synced is None or _utc(now) - synced > job.max_age
            behind = job.needs_scores and unscored_week(con, now) is not None
            if old or behind:
                out.append(job)
        return out

    def check(self, now: datetime | None = None) -> list[str]:
        """Run every job that is due; the sources refreshed."""
        now = now or datetime.now(UTC)
        con = self.cursor()
        try:
            todo = self.due(con, now)
            if not todo:
                return []
            self.running = True
            done = []
            for job in todo:
                self.attempts[job.source] = _utc(now)
                try:
                    data = job.fetch(self.clients())  # the slow part: no lock held
                    with self.lock:
                        job.write(con, self.clients(), data)
                    done.append(job.source)
                    self.last_error = None
                except Exception as exc:  # retried after RETRY_AFTER
                    log.exception("refreshing %s failed", job.source)
                    self.last_error = f"{job.source}: {type(exc).__name__}"
            if done:
                context.invalidate(None)
                log.info("refreshed %s", ", ".join(done))
            return done
        finally:
            self.running = False
            con.close()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="freshness", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.check()
            except Exception:  # never let the thread die
                log.exception("freshness check failed")
            self._stop.wait(CHECK_EVERY.total_seconds())


_refresher: Refresher | None = None


def get() -> Refresher | None:
    return _refresher


def start(refresher: Refresher) -> None:
    global _refresher
    _refresher = refresher
    refresher.start()
