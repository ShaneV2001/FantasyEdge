"""Player analytics: usage, efficiency, YAC and scoring-opportunity stats over recent games.

Every rate is a ratio of sums over the window (catch rate over the last 3 games = catches / targets
in those games), never a mean of weekly rates, so one low-volume game can't swing it. Counts are per
game so a window compares directly with the season. Team shares divide by the team's total over the
same games; the store holds QB/RB/WR/TE rows, which carry nearly all of a team's carries and targets.
"""

from __future__ import annotations

import polars as pl

from app.schemas import models as m

WINDOWS = (("L3", 3), ("L5", 5))

GROUPS = (
    ("usage", "Usage", ("snap_pct", "rush_share", "target_share", "air_yards_share", "wopr")),
    ("efficiency", "Efficiency", ("cmp_pct", "yds_per_att", "adot", "catch_rate",
                                  "yds_per_target", "yds_per_carry", "epa_per_play")),
    ("yac", "Yards after catch", ("yac_per_game", "yac_pct", "yac_per_rec")),
    ("scoring", "Scoring opportunity", ("rz_carries", "rz_targets", "gl_carries", "rz_td")),
)  # fmt: skip

_RECEIVER = frozenset({"snap_pct", "target_share", "air_yards_share", "wopr", "adot", "catch_rate",
                       "yds_per_target", "epa_per_play", "yac_per_game", "yac_per_rec",
                       "rz_targets", "rz_td"})  # fmt: skip
BY_POSITION: dict[str, frozenset[str]] = {
    "QB": frozenset({"rush_share", "cmp_pct", "yds_per_att", "adot", "epa_per_play",
                     "yac_per_game", "yac_pct", "rz_carries", "gl_carries", "rz_td"}),
    "RB": frozenset({"snap_pct", "rush_share", "target_share", "yds_per_carry", "yds_per_target",
                     "epa_per_play", "yac_per_game", "yac_per_rec", "rz_carries", "rz_targets",
                     "gl_carries", "rz_td"}),
    "WR": _RECEIVER,
    "TE": _RECEIVER,
}  # fmt: skip

SUMS = ("pass_att", "pass_cmp", "pass_yds", "pass_air_yards", "pass_yac", "sacks_taken", "carries",
        "rush_yds", "targets", "receptions", "rec_yds", "air_yards", "rec_yac", "epa_total",
        "rz_carries", "rz_targets", "gl_carries", "rz_td")  # fmt: skip
TEAM_SUMS = ("carries", "targets", "air_yards")


def _div(a: float | None, b: float | None, digits: int = 3) -> float | None:
    if a is None or not b:
        return None
    return round(a / b, digits)


def _sum(games: pl.DataFrame, col: str) -> float | None:
    """Window total; None if any game lacks the stat (e.g. YAC before a data refresh)."""
    if col not in games.columns or games[col].null_count():
        return None
    return float(games[col].sum())


def _metrics(games: pl.DataFrame, position: str) -> dict[str, float | None]:
    n = games.height
    s = {c: _sum(games, c) for c in SUMS}
    t = {c: _sum(games, f"team_{c}") for c in TEAM_SUMS}
    snaps = games["snap_pct"].drop_nulls()
    plays = sum(s[c] or 0 for c in ("pass_att", "sacks_taken", "carries", "targets"))
    ts = _div(s["targets"], t["targets"])
    ays = _div(s["air_yards"], t["air_yards"])
    qb = position == "QB"
    out = {
        "snap_pct": round(float(snaps.mean()), 3) if snaps.len() else None,
        "rush_share": _div(s["carries"], t["carries"]),
        "target_share": ts,
        "air_yards_share": ays,
        "wopr": round(1.5 * ts + 0.7 * ays, 3) if ts is not None and ays is not None else None,
        "cmp_pct": _div(s["pass_cmp"], s["pass_att"]),
        "yds_per_att": _div(s["pass_yds"], s["pass_att"], 2),
        "adot": _div(s["pass_air_yards"], s["pass_att"], 2) if qb
        else _div(s["air_yards"], s["targets"], 2),
        "catch_rate": _div(s["receptions"], s["targets"]),
        "yds_per_target": _div(s["rec_yds"], s["targets"], 2),
        "yds_per_carry": _div(s["rush_yds"], s["carries"], 2),
        "epa_per_play": _div(s["epa_total"], plays),
        "yac_per_game": _div(s["pass_yac"] if qb else s["rec_yac"], n, 1),
        "yac_pct": _div(s["pass_yac"], s["pass_yds"]),
        "yac_per_rec": _div(s["rec_yac"], s["receptions"], 2),
        "rz_carries": _div(s["rz_carries"], n, 2),
        "rz_targets": _div(s["rz_targets"], n, 2),
        "gl_carries": _div(s["gl_carries"], n, 2),
        "rz_td": _div(s["rz_td"], n, 2),
    }  # fmt: skip
    keep = BY_POSITION[position]
    return {k: v for k, v in out.items() if k in keep}


def player_analytics(
    stats: pl.DataFrame, player_id: str, season: int, position: str
) -> m.PlayerAnalyticsOut | None:
    """L3 / L5 / Season analytics for one player (None for K/DEF or no games this season)."""
    if position not in BY_POSITION:
        return None
    cur = stats.filter(pl.col("season") == season)
    games = cur.filter(pl.col("player_id") == player_id).sort("week")
    if games.is_empty():
        return None
    team = cur.group_by("team", "week").agg([pl.col(c).sum().alias(f"team_{c}") for c in TEAM_SUMS])
    games = games.join(team, on=["team", "week"], how="left")
    windows = [
        m.AnalyticsWindowOut(label=label, games=k, metrics=_metrics(games.tail(k), position))
        for label, k in WINDOWS
        if games.height > k
    ]
    windows.append(
        m.AnalyticsWindowOut(label="Season", games=games.height, metrics=_metrics(games, position))
    )
    keep = BY_POSITION[position]
    groups = [
        m.AnalyticsGroupOut(key=key, label=label, metrics=[k for k in keys if k in keep])
        for key, label, keys in GROUPS
        if any(k in keep for k in keys)
    ]
    return m.PlayerAnalyticsOut(groups=groups, windows=windows)
