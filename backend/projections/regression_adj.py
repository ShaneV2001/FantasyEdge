"""Fold regression flags into the projection: flagged sell-highs project lower, buy-lows higher.

    ppg += beta_sell × min(score, 0) + beta_buy × max(score, 0)

where `score` is the regression report's signed strength (≈ ±1 per flag at its threshold). The
flags are built from the same history the wrapped engine sees, so the backtest stays leak-free.
The betas are chosen by `python -m models.run tune-regression`.
"""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl

from projections.base import ProjectionEngine, ProjectionInputs
from projections.baseline import history_before
from projections.norms import norms_window, position_rates
from signals.regression import build_report


@dataclass(frozen=True)
class RegressionAdjusted:
    engine: ProjectionEngine
    beta_sell: float = 0.0
    beta_buy: float = 0.0

    @property
    def run_id(self) -> str:
        return (
            self.engine.run_id
            if not (self.beta_sell or self.beta_buy)
            else (f"{self.engine.run_id}+reg")
        )

    def scores(self, inputs: ProjectionInputs) -> dict[str, float]:
        hist = history_before(inputs.stats, inputs.season, inputs.week)
        rates = position_rates(norms_window(hist, inputs.season, inputs.week), inputs.rules)
        return build_report(hist, rates, inputs.season, inputs.week).scores()

    def per_game(self, inputs: ProjectionInputs) -> pl.DataFrame:
        base = self.engine.per_game(inputs)
        if not (self.beta_sell or self.beta_buy):
            return base
        scores = self.scores(inputs)
        shift = {
            pid: self.beta_sell * min(s, 0.0) + self.beta_buy * max(s, 0.0)
            for pid, s in scores.items()
        }
        d = pl.col("player_id").replace_strict(shift, default=0.0, return_dtype=pl.Float64)
        return base.with_columns(
            (pl.col("ppg") + d).clip(lower_bound=0).round(2).alias("ppg"),
            (pl.col("p10") + d).clip(lower_bound=0).round(2).alias("p10"),
            (pl.col("p90") + d).clip(lower_bound=0).round(2).alias("p90"),
        )
