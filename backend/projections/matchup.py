"""Matchup-adjusted projections: scale an engine's per-game output by this week's opponent.

Used by the backtest to choose how much each projection should follow the matchup
(`MATCHUP_ALPHA` and `signals.matchup_factors`) and by the player page for past weeks; the
matchup model is built from the same history the engine sees, so the target week never leaks in.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import polars as pl

from projections.base import ProjectionEngine, ProjectionInputs
from signals.matchup_factors import FactorWeights, build_matchup_model


@dataclass(frozen=True)
class MatchupAdjusted:
    engine: ProjectionEngine
    weights: FactorWeights = field(default_factory=FactorWeights)

    @property
    def run_id(self) -> str:
        return f"{self.engine.run_id}+matchup"

    def per_game(self, inputs: ProjectionInputs) -> pl.DataFrame:
        base = self.engine.per_game(inputs)
        if not any(self.weights.alpha.values()) and not any(self.weights.vegas.values()):
            return base
        teams = dict(inputs.players.select("player_id", "nfl_team").iter_rows())
        positions = dict(inputs.players.select("player_id", "position").iter_rows())
        model = build_matchup_model(
            inputs.stats, inputs.schedule, teams, inputs.rules, inputs.season, inputs.week - 1,
            self.weights,
        )  # fmt: skip
        w = inputs.week
        mult = {
            pid: model.multiplier(
                pid,
                positions.get(pid) or "",
                teams.get(pid),
                inputs.schedule.opponent(teams.get(pid), w),
                w,
            )  # fmt: skip
            for pid in base["player_id"].to_list()
        }
        m = pl.col("player_id").replace_strict(mult, default=1.0, return_dtype=pl.Float64)
        return base.with_columns((pl.col(c) * m).round(2) for c in ("ppg", "p10", "p90"))
