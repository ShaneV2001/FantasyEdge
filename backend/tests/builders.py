"""Tiny builders for synthetic stats/schedules used across unit tests."""

from __future__ import annotations

import polars as pl

from ingest.nflverse import STATS_COLUMNS
from scoring.rules import HALF_PPR, score
from signals.schedule import Schedule

INT_COLS = {
    "pass_att", "pass_cmp", "pass_yds", "pass_td", "interceptions", "carries", "rush_yds",
    "rush_td", "targets", "receptions", "rec_yds", "rec_td", "air_yards", "rz_carries",
    "rz_targets", "gl_carries", "rz_td", "fumbles_lost", "two_pt", "snaps", "routes",
}  # fmt: skip


def stat_row(player_id: str, position: str, season: int, week: int, team: str = "AAA", **kw):
    row = {c: 0 for c in INT_COLS} | {
        "player_id": player_id,
        "position": position,
        "season": season,
        "week": week,
        "team": team,
        "opponent": kw.pop("opponent", "BBB"),
        "game_id": f"{season}_{week:02d}_{team}",
        "snap_pct": None,
        "target_share": None,
        "air_yards_share": None,
        "wopr": None,
        "epa_total": 0.0,
    }
    row.update(kw)
    return row


def stats_frame(rows: list[dict], rules: dict | None = None) -> pl.DataFrame:
    df = pl.DataFrame(rows, infer_schema_length=None)
    df = df.select([*STATS_COLUMNS, "position"])
    return score(df, rules or HALF_PPR)


def schedule(
    teams: list[str],
    weeks: int = 18,
    byes: dict[str, int] | None = None,
    completed_through: int = 0,
) -> Schedule:
    byes = byes or {}
    games: dict[tuple[str, int], str] = {}
    for w in range(1, weeks + 1):
        playing = [t for t in teams if byes.get(t) != w]
        for t in playing:
            games[(t, w)] = "OPP"
    completed = frozenset(k for k in games if k[1] <= completed_through)
    return Schedule(2026, weeks, games, dict(byes), completed)
