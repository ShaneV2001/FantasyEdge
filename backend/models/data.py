"""Historical nflverse data for the backtest, cached per season under data/backtest/.

Kept separate from the app's store on purpose: the backtest needs older seasons and players who
have since retired (the app's `players` table only holds today's Sleeper players), so positions
come from nflverse itself.
"""

from __future__ import annotations

import logging
from pathlib import Path

import polars as pl

from ingest import nflverse
from signals.schedule import Schedule, build_schedule

log = logging.getLogger("ff_edge.backtest")

FANTASY_POSITIONS = ("QB", "RB", "WR", "TE", "K")
CACHE_VERSION = 3  # bump when cached columns change (v2: K/DEF; v3: YAC, pass air yards)


def _positions(raw_stats: pl.DataFrame) -> pl.DataFrame:
    return (
        raw_stats.filter(pl.col("position").is_in(FANTASY_POSITIONS))
        .group_by("player_id")
        .agg(pl.col("position").last())
    )


def build_season(
    raw_stats: pl.DataFrame,
    pbp: pl.DataFrame | None,
    team_stats: pl.DataFrame | None = None,
    games: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """player_week_stats rows (no snaps: the projections don't use them) plus `position`."""
    weekly = nflverse.build_player_week_stats(raw_stats, pbp, None)
    if games is not None:
        weekly = pl.concat(
            [weekly, nflverse.build_kicker_and_defense(raw_stats, team_stats, games)]
        )
    positions = _positions(raw_stats)
    defenses = (
        weekly.filter(pl.col("player_id").str.starts_with("sl:"))
        .select("player_id")
        .unique()
        .with_columns(pl.lit("DEF").alias("position"))
    )
    return weekly.join(pl.concat([positions, defenses]), on="player_id", how="inner")


def _download(season: int) -> tuple[pl.DataFrame, pl.DataFrame]:
    import nflreadpy as nfl

    log.info("downloading nflverse %d (player stats, play-by-play, schedule)…", season)
    raw = nfl.load_player_stats([season], summary_level="week")
    team = nfl.load_team_stats([season], summary_level="week")
    pbp = nfl.load_pbp([season])
    games = nflverse.transform_schedule(nfl.load_schedules([season]))
    return build_season(raw, pbp, team, games), games


def load_seasons(
    seasons: list[int], cache_dir: Path, refresh: bool = False
) -> tuple[pl.DataFrame, dict[int, Schedule]]:
    """Stats (with position) and schedules for `seasons`, downloading any season not cached."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    stats, schedules = [], {}
    for season in seasons:
        s_path, g_path = (
            cache_dir / f"{season}_stats_v{CACHE_VERSION}.parquet",
            cache_dir / f"{season}_games.parquet",
        )
        if refresh or not (s_path.exists() and g_path.exists()):
            st, games = _download(season)
            st.write_parquet(s_path)
            games.write_parquet(g_path)
        stats.append(pl.read_parquet(s_path))
        schedules[season] = build_schedule(pl.read_parquet(g_path), season)
    return pl.concat(stats, how="diagonal_relaxed"), schedules
