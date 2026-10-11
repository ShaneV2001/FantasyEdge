"""Naive comparison engines for the backtest: any real projection has to beat these.

Both use the baseline's band math so p10–p90 coverage is comparable across engines.
"""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl

from projections.base import ProjectionInputs
from projections.baseline import add_band, history_aggs, history_frame


def _project(inputs: ProjectionInputs, ppg: pl.Expr, method: str) -> pl.DataFrame:
    agg = history_frame(inputs).group_by("player_id").agg(*history_aggs(inputs.season))
    agg = add_band(agg.with_columns(ppg.alias("ppg")).filter(pl.col("ppg").is_not_null()))
    return agg.select(
        "player_id", "ppg", "p10", "p90",
        pl.col("games_played").cast(pl.UInt32), pl.lit(method).alias("method"),
    )  # fmt: skip


@dataclass(frozen=True)
class SeasonPpgEngine:
    """This season's points per game so far, last season's before week 1 is played."""

    run_id: str = "season-ppg"

    def per_game(self, inputs: ProjectionInputs) -> pl.DataFrame:
        return _project(inputs, pl.col("cur_ppg").fill_null(pl.col("prior_ppg")), self.run_id)


@dataclass(frozen=True)
class Last3Engine:
    """Average of the player's last three games (reaching back into last season)."""

    run_id: str = "last3"

    def per_game(self, inputs: ProjectionInputs) -> pl.DataFrame:
        return _project(inputs, pl.col("l3_ppg"), self.run_id)
