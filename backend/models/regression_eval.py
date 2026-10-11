"""Do regression flags predict regression? Walk-forward check of every flag kind.

For each week W, flags are built from data through W-1 exactly as the app would. A flagged
player's "move" is next-4-week PPG minus season-to-date PPG. Plain hit rates would flatter the
flags (hot starts cool off anyway), so each move is compared with what unflagged players at the
same position and similar season-to-date PPG did over the same weeks:

* `lift`  = average (move − expected move) × direction, in fantasy points per game; > 0 means the
  flag carries information beyond ordinary regression to the mean
* `hit_adj` = share of flags whose move beat the expectation in the flagged direction (0.5 = coin)
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

import polars as pl

from projections.norms import norms_window, position_rates
from scoring.rules import score
from signals.regression import RegressionConfig, build_report

PPG_BUCKET = 3.0  # season-to-date PPG band used to match unflagged comparison players
MIN_PAST_GAMES = 4
MIN_FUTURE_GAMES = 2
MIN_PAST_PPG = 5.0  # ignore deep bench players; flags matter for players people roster


def flag_outcomes(
    stats: pl.DataFrame,
    rules: dict[str, float],
    seasons: Iterable[int],
    weeks: Sequence[int] = range(6, 15),
    config: RegressionConfig | None = None,
) -> pl.DataFrame:
    """One row per (season, week, player, flag kind); unflagged players get kind 'none'."""
    scored = score(stats, rules)
    out = []
    for s in seasons:
        both = scored.filter(pl.col("season").is_in([s - 1, s]))
        cur = both.filter(pl.col("season") == s)
        for w in weeks:
            hist = both.filter((pl.col("season") == s - 1) | (pl.col("week") < w))
            rates = position_rates(norms_window(hist, s, w - 1), rules)
            report = build_report(hist, rates, s, w - 1, config)
            past = (
                cur.filter(pl.col("week") < w)
                .group_by("player_id")
                .agg(
                    pl.col("position").last(),
                    pl.col("fp").mean().alias("past_ppg"),
                    pl.len().alias("past_games"),
                )
            )
            future = (
                cur.filter(pl.col("week").is_between(w, w + 3))
                .group_by("player_id")
                .agg(pl.col("fp").mean().alias("future_ppg"), pl.len().alias("future_games"))
            )
            base = past.join(future, on="player_id", how="inner").filter(
                (pl.col("past_games") >= MIN_PAST_GAMES)
                & (pl.col("future_games") >= MIN_FUTURE_GAMES)
                & (pl.col("past_ppg") >= MIN_PAST_PPG)
            )
            flags = pl.DataFrame(
                [(f.player_id, f.kind, f.direction) for f in report.flags],
                schema={"player_id": pl.Utf8, "kind": pl.Utf8, "direction": pl.Int64},
                orient="row",
            ).unique(["player_id", "kind"])
            flagged = base.join(flags, on="player_id", how="inner")
            none = base.join(flags, on="player_id", how="anti").with_columns(
                pl.lit("none").alias("kind"), pl.lit(0, pl.Int64).alias("direction")
            )
            out.append(
                pl.concat([flagged, none.select(flagged.columns)]).with_columns(
                    pl.lit(s).alias("season"), pl.lit(w).alias("week")
                )
            )
    df = pl.concat(out)
    return df.with_columns(
        (pl.col("future_ppg") - pl.col("past_ppg")).alias("move"),
        (pl.col("past_ppg") / PPG_BUCKET).floor().cast(pl.Int64).alias("bucket"),
    )


def summarize(outcomes: pl.DataFrame) -> pl.DataFrame:
    """Support, raw hit rate, adjusted hit rate and lift per (kind, direction)."""
    expected = (
        outcomes.filter(pl.col("kind") == "none")
        .group_by("season", "week", "position", "bucket")
        .agg(pl.col("move").mean().alias("expected_move"))
    )
    flagged = outcomes.filter(pl.col("kind") != "none").join(
        expected, on=["season", "week", "position", "bucket"], how="left"
    )
    excess = (pl.col("move") - pl.col("expected_move").fill_null(0)) * pl.col("direction")
    return (
        flagged.group_by("kind", "direction")
        .agg(
            pl.len().alias("n"),
            ((pl.col("move") * pl.col("direction")) > 0).mean().alias("hit_raw"),
            (excess > 0).mean().alias("hit_adj"),
            excess.mean().alias("lift"),
        )
        .sort("kind", "direction")
    )
