"""The background NFL-data refresher: when it refreshes, and that downloads skip the write lock."""

import threading
from datetime import UTC, datetime, timedelta

import pytest

from app.services import freshness
from db.conn import connect, log_sync

NOW = datetime(2026, 11, 2, 18, 0, tzinfo=UTC)  # Monday 1 PM Eastern


@pytest.fixture
def con(tmp_path):
    c = connect(tmp_path / "f.duckdb")
    yield c
    c.close()


def synced(con, source, ago):
    log_sync(con, source)
    con.execute(
        "UPDATE sync_log SET last_synced_at = ? WHERE source = ?",
        [(NOW - ago).replace(tzinfo=None), source],
    )


def game(con, week, kickoff_et, scored):
    con.execute(
        "INSERT INTO nfl_games (game_id, season, week, home_team, away_team, kickoff, home_score,"
        " away_score) VALUES (?, 2026, ?, 'AAA', 'BBB', ?, ?, ?)",
        [
            f"g{week}{kickoff_et:%H}",
            week,
            kickoff_et,
            20 if scored else None,
            17 if scored else None,
        ],
    )


def refresher(con, lock=None, fail=()):
    calls = []
    lock = lock or threading.Lock()

    def job(source, max_age, needs_scores=False):
        def fetch(_c):
            calls.append(("fetch", source, lock.locked()))
            if source in fail:
                raise RuntimeError("down")
            return source

        def write(c, _clients, data):
            calls.append(("write", data, lock.locked()))
            log_sync(c, source)

        return freshness.Job(source, max_age, fetch, write, needs_scores)

    r = freshness.Refresher(
        clients=lambda: None,
        cursor=lambda: con.cursor(),
        lock=lock,
        jobs=[
            job("nflverse", freshness.NFL_MAX_AGE, needs_scores=True),
            job("sleeper_players", freshness.PLAYERS_MAX_AGE),
        ],
    )
    return r, calls


def test_a_new_store_refreshes_everything_downloading_outside_the_lock(con, monkeypatch):
    invalidated = []
    monkeypatch.setattr(freshness.context, "invalidate", lambda lid=None: invalidated.append(lid))
    r, calls = refresher(con)
    assert r.check(NOW) == ["nflverse", "sleeper_players"]
    assert calls == [
        ("fetch", "nflverse", False), ("write", "nflverse", True),
        ("fetch", "sleeper_players", False), ("write", "sleeper_players", True),
    ]  # fmt: skip
    assert invalidated == [None] and not r.running
    assert r.check(NOW + timedelta(minutes=30)) == []  # fresh now


def test_fresh_data_waits_until_it_is_old(con):
    synced(con, "nflverse", timedelta(hours=11))
    synced(con, "sleeper_players", timedelta(hours=19))
    r, _ = refresher(con)
    assert r.due(con, NOW) == []
    assert [j.source for j in r.due(con, NOW + timedelta(hours=2))] == [
        "nflverse",
        "sleeper_players",
    ]


def test_a_played_game_without_a_score_triggers_nflverse_early(con):
    synced(con, "nflverse", timedelta(hours=1))
    synced(con, "sleeper_players", timedelta(hours=1))
    game(con, 8, datetime(2026, 11, 1, 13, 0), scored=True)
    game(con, 8, datetime(2026, 11, 2, 11, 0), scored=False)  # kicked off 2 h ago: too soon
    r, _ = refresher(con)
    assert r.due(con, NOW) == [] and freshness.unscored_week(con, NOW) is None
    game(con, 8, datetime(2026, 11, 1, 20, 20), scored=False)  # Sunday night, still no score
    assert [j.source for j in r.due(con, NOW)] == ["nflverse"]
    assert freshness.unscored_week(con, NOW) == 8 and freshness.nfl_stale(con, NOW)
    game(con, 1, datetime(2026, 9, 7, 13, 0), scored=False)  # weeks ago: a data gap, not "behind"
    assert freshness.unscored_week(con, NOW) == 8


def test_a_failed_download_waits_before_trying_again(con):
    synced(con, "sleeper_players", timedelta(hours=1))
    r, calls = refresher(con, fail={"nflverse"})
    assert r.check(NOW) == [] and r.last_error == "nflverse: RuntimeError"
    assert not any(c[0] == "write" for c in calls)
    assert r.due(con, NOW + timedelta(hours=1)) == []
    assert [j.source for j in r.due(con, NOW + freshness.RETRY_AFTER + timedelta(minutes=1))] == [
        "nflverse"
    ]


def test_stale_flag_follows_age(con):
    assert freshness.nfl_stale(con, NOW)  # never synced
    synced(con, "nflverse", timedelta(hours=30))
    assert not freshness.nfl_stale(con, NOW)
    synced(con, "nflverse", timedelta(hours=40))
    assert freshness.nfl_stale(con, NOW)
