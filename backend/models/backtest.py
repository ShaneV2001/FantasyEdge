"""Walk-forward backtest: project each past week using only earlier data, then score it.

For every target week W of a season, an engine sees the prior season plus this season's weeks
before W (nothing from W onward) and every player at full availability (no injury reports leak
in). Its per-game projection is compared with what actually happened:

* `actual_1`: fantasy points in week W (only players who played in W are scored)
* `actual_4`: average points over the games the player played in weeks W..W+3

Metrics are reported per position for all projected players and for a fantasy-relevant subset
(the top-N projected each week, roughly the startable pool).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

import polars as pl

from projections.base import LeagueShape, ProjectionEngine, ProjectionInputs
from scoring.rules import score
from signals.schedule import Schedule

POSITIONS = ("QB", "RB", "WR", "TE", "K", "DEF")
RELEVANT_TOP = {"QB": 24, "RB": 60, "WR": 60, "TE": 24, "K": 16, "DEF": 16}
HORIZON = 4
MIN_RANK_GROUP = 5  # weekly position groups smaller than this give no meaningful rank corr.


def _players(stats: pl.DataFrame) -> pl.DataFrame:
    return (
        stats.sort(["season", "week"])
        .group_by("player_id")
        .agg(pl.col("position").last(), pl.col("team").last().alias("nfl_team"))
        .with_columns(
            pl.lit(None, pl.Utf8).alias("injury_status"), pl.lit(None, pl.Utf8).alias("status")
        )
    )


def walk_forward(
    engine: ProjectionEngine,
    stats: pl.DataFrame,
    schedules: Mapping[int, Schedule],
    rules: dict[str, float],
    seasons: Iterable[int],
    weeks: Sequence[int] = range(1, 18),
) -> pl.DataFrame:
    """One row per (season, week, player) that the engine projected and who played that week."""
    scored = score(stats, rules)
    out = []
    for s in seasons:
        both = scored.filter(pl.col("season").is_in([s - 1, s]))
        actual = scored.filter(pl.col("season") == s).select("player_id", "week", "fp")
        players = _players(both)
        for w in weeks:
            hist = both.filter((pl.col("season") == s - 1) | (pl.col("week") < w))
            if hist.is_empty():
                continue
            inputs = ProjectionInputs(hist, players, schedules[s], rules, s, w, LeagueShape())
            proj = (
                engine.per_game(inputs)
                .filter(~pl.col("method").is_in(["default", "no_data"]))
                .select("player_id", "ppg", "p10", "p90")
                .join(players.select("player_id", "position"), on="player_id", how="left")
                .with_columns(
                    pl.col("ppg").rank("ordinal", descending=True).over("position").alias("rank")
                )
            )
            played = actual.filter(pl.col("week") == w).select(
                "player_id", pl.col("fp").alias("actual_1")
            )
            future = (
                actual.filter(pl.col("week").is_between(w, w + HORIZON - 1))
                .group_by("player_id")
                .agg(pl.col("fp").mean().alias("actual_4"), pl.len().alias("n_future"))
            )
            out.append(
                proj.join(played, on="player_id", how="inner")
                .join(future, on="player_id", how="left")
                .with_columns(pl.lit(s).alias("season"), pl.lit(w).alias("week"))
            )
    if not out:
        return pl.DataFrame()
    df = pl.concat(out, how="vertical_relaxed")
    top = pl.col("position").replace_strict(RELEVANT_TOP, default=0)
    return df.with_columns((pl.col("rank") <= top).alias("relevant")).with_columns(
        pl.lit(engine.run_id).alias("engine")
    )


def metrics(preds: pl.DataFrame, relevant_only: bool = False) -> pl.DataFrame:
    """MAE (next week, next 4), bias, mean weekly Spearman and p10–p90 coverage by position."""
    df = preds.filter(pl.col("relevant")) if relevant_only else preds
    if df.is_empty():
        return pl.DataFrame()
    err1 = pl.col("ppg") - pl.col("actual_1")
    base = [
        pl.len().alias("n"),
        err1.abs().mean().alias("mae_1"),
        (pl.col("ppg") - pl.col("actual_4")).abs().mean().alias("mae_4"),
        err1.mean().alias("bias"),
        pl.col("actual_1").is_between(pl.col("p10"), pl.col("p90")).mean().alias("coverage"),
    ]
    by_pos = df.group_by("position").agg(base)
    overall = df.select(base).with_columns(pl.lit("ALL").alias("position"))
    rho = (
        df.group_by("season", "week", "position")
        .agg(
            pl.corr("ppg", "actual_1", method="spearman").alias("rho"),
            pl.len().alias("k"),
        )
        .filter((pl.col("k") >= MIN_RANK_GROUP) & pl.col("rho").is_not_nan())
    )
    rho_pos = rho.group_by("position").agg(pl.col("rho").mean().alias("spearman"))
    rho_all = rho.select(pl.col("rho").mean().alias("spearman")).with_columns(
        pl.lit("ALL").alias("position")
    )
    order = {p: i for i, p in enumerate((*POSITIONS, "ALL"))}
    return (
        pl.concat([by_pos, overall.select(by_pos.columns)])
        .join(pl.concat([rho_pos, rho_all.select(rho_pos.columns)]), on="position", how="left")
        .with_columns(pl.col("position").replace_strict(order, default=99).alias("_o"))
        .sort("_o")
        .drop("_o")
    )


def metrics_json(preds: pl.DataFrame) -> dict:
    """Both populations, keyed for storage in model_runs.metrics."""
    return {
        pop: {
            r["position"]: {k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()}
            for r in metrics(preds, relevant_only=(pop == "relevant")).iter_rows(named=True)
        }
        for pop in ("all", "relevant")
    }
