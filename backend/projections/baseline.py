"""Phase-1 transparent projection.

    ppg = 0.5 × last-3-game PPG + 0.3 × season PPG + 0.2 × usage-implied PPG

* usage-implied PPG = opportunities over the last 4 games × positional league-average points per
  opportunity (targets, carries, pass attempts) + expected TDs from red-zone/non-RZ opportunities.
* Early season (< 4 games) the season PPG is shrunk toward last season's PPG.
* p10/p90 = ppg ∓ 1.28 × weekly std-dev (shrunk toward a positional prior).
"""

from __future__ import annotations

import polars as pl

from projections.base import ProjectionInputs
from projections.norms import expected_td_expr, norms_window, position_rates
from scoring.rules import normalize

W_L3, W_SEASON, W_USAGE = 0.5, 0.3, 0.2
SHRINK_GAMES = 4
Z90 = 1.2816
DEFAULT_PPG = {"K": 8.0, "DEF": 7.0}


def history_before(stats: pl.DataFrame, season: int, week: int) -> pl.DataFrame:
    """Leakage guard: prior season + current season through `week`, never later weeks.

    Stat rows only exist for completed games, so week-`week` rows are games already played
    (e.g. Thursday night) — those games are also excluded from rest-of-season points.
    """
    return stats.filter(
        (pl.col("season") == season - 1) | ((pl.col("season") == season) & (pl.col("week") <= week))
    )


def usage_points_expr(inputs: ProjectionInputs, hist: pl.DataFrame) -> pl.Expr:
    rates = position_rates(norms_window(hist, inputs.season, inputs.week), inputs.rules)
    r = normalize(inputs.rules)
    td_pts = (r["rush_td"] + r["rec_td"]) / 2

    def per_pos(attr: str) -> pl.Expr:
        expr = pl.lit(0.0)
        for pos, pr in rates.items():
            expr = pl.when(pl.col("position") == pos).then(getattr(pr, attr)).otherwise(expr)
        return expr

    return (
        pl.col("targets").fill_null(0) * per_pos("fp_per_target")
        + pl.col("carries").fill_null(0) * per_pos("fp_per_carry")
        + pl.col("pass_att").fill_null(0) * per_pos("fp_per_att")
        + pl.col("pass_att").fill_null(0) * per_pos("pass_td_rate") * r["pass_td"]
        + expected_td_expr(rates) * td_pts
    )


class BaselineEngine:
    run_id = "baseline-v1"

    def per_game(self, inputs: ProjectionInputs) -> pl.DataFrame:
        s, w = inputs.season, inputs.week
        hist = history_before(inputs.stats, s, w)
        hist = hist.with_columns(usage_points_expr(inputs, hist).alias("usage_fp")).sort(
            ["player_id", "season", "week"]
        )
        agg = hist.group_by("player_id").agg(
            pl.col("position").last(),
            pl.col("fp").tail(3).mean().alias("l3_ppg"),
            pl.col("fp").filter(pl.col("season") == s).mean().alias("cur_ppg"),
            (pl.col("season") == s).sum().cast(pl.Int64).alias("games_played"),
            pl.col("fp").filter(pl.col("season") == s - 1).mean().alias("prior_ppg"),
            (pl.col("season") == s - 1).sum().cast(pl.Int64).alias("prior_games"),
            pl.col("usage_fp").tail(4).mean().alias("usage_ppg"),
            pl.col("fp").tail(8).std().alias("sd_raw"),
            pl.col("fp").tail(8).len().alias("n_sd"),
        )
        k = (SHRINK_GAMES - pl.col("games_played")).clip(lower_bound=0)
        season_ppg = (
            pl.when(pl.col("prior_ppg").is_null() | (pl.col("prior_games") < SHRINK_GAMES))
            .then(pl.col("cur_ppg"))
            .when(pl.col("cur_ppg").is_null())
            .then(pl.col("prior_ppg"))
            .otherwise(
                (pl.col("games_played") * pl.col("cur_ppg") + k * pl.col("prior_ppg"))
                / (pl.col("games_played") + k)
            )
        )
        agg = agg.with_columns(season_ppg.alias("season_ppg"))
        agg = agg.with_columns(
            (
                W_L3 * pl.col("l3_ppg")
                + W_SEASON * pl.col("season_ppg").fill_null(pl.col("l3_ppg"))
                + W_USAGE * pl.col("usage_ppg")
            ).alias("ppg")
        )
        prior_sd = 0.45 * pl.col("ppg") + 1.5
        sd = (
            (
                (pl.col("n_sd") - 1).clip(lower_bound=0) * pl.col("sd_raw").fill_null(0) ** 2
                + 4 * prior_sd**2
            )
            / ((pl.col("n_sd") - 1).clip(lower_bound=0) + 4)
        ).sqrt()
        agg = agg.with_columns(sd.alias("sd")).with_columns(
            (pl.col("ppg") - Z90 * pl.col("sd")).clip(lower_bound=0).alias("p10"),
            (pl.col("ppg") + Z90 * pl.col("sd")).alias("p90"),
            pl.lit("baseline").alias("method"),
        )
        projected = agg.select(
            "player_id", "ppg", "p10", "p90", "l3_ppg", "season_ppg", "usage_ppg",
            "games_played", "method",
        )  # fmt: skip

        # Players without usable history: K/DEF get flat defaults, others project 0.
        rest = inputs.players.filter(~pl.col("player_id").is_in(projected["player_id"].implode()))
        rest = rest.select(
            "player_id",
            pl.col("position")
            .replace_strict(DEFAULT_PPG, default=0.0)
            .cast(pl.Float64)
            .alias("ppg"),
        ).with_columns(
            (pl.col("ppg") * 0.5).alias("p10"),
            (pl.col("ppg") * 1.5).alias("p90"),
            pl.lit(None, pl.Float64).alias("l3_ppg"),
            pl.lit(None, pl.Float64).alias("season_ppg"),
            pl.lit(None, pl.Float64).alias("usage_ppg"),
            pl.lit(0, pl.UInt32).alias("games_played"),
            pl.when(pl.col("ppg") > 0)
            .then(pl.lit("default"))
            .otherwise(pl.lit("no_data"))
            .alias("method"),
        )
        out = pl.concat([projected.with_columns(pl.col("games_played").cast(pl.UInt32)), rest])
        return out.with_columns(
            pl.col(c).round(2) for c in ("ppg", "p10", "p90", "l3_ppg", "season_ppg", "usage_ppg")
        )
