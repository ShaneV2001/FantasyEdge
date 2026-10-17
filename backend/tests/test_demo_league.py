"""scripts/demo_league.py: a fictional league built from a copy of the store, with nothing of the
user's own leagues left in it."""

import importlib.util
import sys
from collections import Counter
from pathlib import Path

import pytest

from db.conn import connect

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "demo_league.py"
spec = importlib.util.spec_from_file_location("demo_league", SCRIPT)
demo = importlib.util.module_from_spec(spec)
sys.modules["demo_league"] = demo
spec.loader.exec_module(demo)

PRIVATE = "es-987654321-2026"  # a "real" league that must not survive


@pytest.fixture
def store(tmp_path):
    src = tmp_path / "ff.duckdb"
    con = connect(src)
    counts = {"QB": 30, "RB": 70, "WR": 70, "TE": 25, "K": 12, "DEF": 12}
    players, values = [], []
    for pos, n in counts.items():
        for i in range(n):
            pid = f"{pos}{i:02d}"
            players.append((pid, f"{pos} Player {i}", pos, "AAA"))
            if pos not in ("K", "DEF"):
                values.append((pid, 10_000 - i * 50 - len(pos)))
    con.executemany(
        "INSERT INTO players (player_id, full_name, position, nfl_team) VALUES (?, ?, ?, ?)",
        players,
    )
    con.executemany(
        """INSERT INTO market_values (player_id, source, snapshot_date, format, value)
           VALUES (?, 'fantasycalc', DATE '2026-10-17', 'redraft_1qb_10_ppr1', ?)""",
        values,
    )
    con.execute("INSERT INTO nfl_games (game_id, season, week) VALUES ('g1', 2026, 1)")
    # the user's own league, credentials and a log line naming it
    con.execute(
        "INSERT INTO leagues (league_id, platform, name) VALUES (?, 'espn', 'My Real League')",
        [PRIVATE],
    )
    con.execute(
        "INSERT INTO teams (team_id, league_id, team_name) VALUES (?, ?, 'My Real Team')",
        [f"{PRIVATE}-9", PRIVATE],
    )
    con.execute("INSERT INTO roster_spots VALUES (?, 'QB00', 'starter', NULL)", [f"{PRIVATE}-9"])
    con.execute("INSERT INTO league_credentials VALUES (?, 'secret-s2', '{SWID}', NULL)", [PRIVATE])
    con.execute("INSERT INTO sync_log VALUES (?, NULL, 'ok', 'synced')", [f"league:{PRIVATE}"])
    con.close()
    return src, tmp_path / "demo" / "ff.duckdb"


def test_builds_a_fictional_league_and_nothing_else(store):
    src, dest = store
    team = demo.build(src, dest, needles=["987654321", "secret-s2"])
    assert team == "demo-league-5"
    con = connect(dest)
    assert con.execute("SELECT league_id, platform FROM leagues").fetchall() == [
        ("demo-league", "demo")
    ]
    assert con.execute("SELECT count(*) FROM league_credentials").fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM sync_log").fetchone()[0] == 0
    teams = con.execute("SELECT team_id, team_name, is_mine FROM teams ORDER BY team_id").fetchall()
    assert len(teams) == 10 and [t for t in teams if t[2]] == [("demo-league-5", "Demo Team", True)]
    assert "My Real Team" not in {t[1] for t in teams}

    spots = con.execute(
        """SELECT r.team_id, r.player_id, r.slot, p.position
           FROM roster_spots r JOIN players p USING (player_id)"""
    ).fetchall()
    assert len({s[1] for s in spots}) == len(spots) == 150  # 15 each, nobody on two teams
    for tid, *_ in teams:
        mine = [s for s in spots if s[0] == tid]
        starters = Counter(s[3] for s in mine if s[2] == "starter")
        assert len(mine) == 15 and sum(starters.values()) == 9
        assert starters["QB"] == 1 and starters["K"] == 1 and starters["DEF"] == 1
        assert starters["TE"] >= 1 and starters["RB"] >= 2 and starters["WR"] >= 2
        held = Counter(s[3] for s in mine)
        assert held["QB"] <= 2 and held["TE"] <= 2
    con.close()


def test_the_draft_is_repeatable(store):
    src, dest = store
    demo.build(src, dest, needles=[])
    con = connect(dest)
    first = con.execute("SELECT * FROM roster_spots ORDER BY ALL").fetchall()
    con.close()
    demo.build(src, dest, needles=[])
    con = connect(dest)
    again = con.execute("SELECT * FROM roster_spots ORDER BY ALL").fetchall()
    con.close()
    assert [r[:3] for r in first] == [r[:3] for r in again]


def test_refuses_when_a_private_id_survives(store):
    src, dest = store
    con = connect(src)  # an identifier somewhere that isn't league-scoped
    con.execute("UPDATE players SET status = 'seen in 987654321' WHERE player_id = 'QB00'")
    con.close()
    with pytest.raises(SystemExit, match="players.status"):
        demo.build(src, dest, needles=["987654321"])
    assert not dest.exists()
