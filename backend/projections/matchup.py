"""Matchup-adjusted projections: scale an engine's per-game output by this week's opponent.

Used by the backtest to choose how much each position's projection should follow the schedule
(`MATCHUP_ALPHA`); the opponent index is built from the same history the engine sees, so the
target week never leaks in.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

import polars as pl

from projections.base import ProjectionEngine, ProjectionInputs
from signals.schedule import fp_allowed_index, matchup_multiplier


@dataclass(frozen=True)
class MatchupAdjusted:
    engine: ProjectionEngine
    alpha: Mapping[str, float] = field(default_factory=dict)

    @property
    def run_id(self) -> str:
        return f"{self.engine.run_id}+matchup"

    def per_game(self, inputs: ProjectionInputs) -> pl.DataFrame:
        base = self.engine.per_game(inputs)
        if not any(self.alpha.values()):
            return base
        index = fp_allowed_index(inputs.stats, inputs.season, inputs.week - 1)
        teams = dict(inputs.players.select("player_id", "nfl_team").iter_rows())
        positions = dict(inputs.players.select("player_id", "position").iter_rows())
        mult = {
            pid: matchup_multiplier(
                index,
                inputs.schedule.opponent(teams.get(pid), inputs.week),
                positions.get(pid) or "",
                self.alpha.get(positions.get(pid) or "", 0.0),
            )
            for pid in base["player_id"].to_list()
        }
        m = pl.col("player_id").replace_strict(mult, default=1.0, return_dtype=pl.Float64)
        return base.with_columns((pl.col(c) * m).round(2) for c in ("ppg", "p10", "p90"))
