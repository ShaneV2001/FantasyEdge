"""Search the baseline weights and regression-flag thresholds against the backtest.

Parameters are chosen on the training seasons only and then checked on a held-out season, so the
reported improvement is not just the search fitting noise.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from itertools import product

import polars as pl

from models.backtest import metrics, walk_forward
from models.regression_eval import flag_outcomes, summarize
from projections.baseline import BaselineEngine
from signals.regression import RegressionConfig
from signals.schedule import Schedule

WEIGHT_STEP = 0.1
SHRINK_OPTIONS = (2, 4, 6, 8)
THRESHOLDS = {
    "td_over_expected": ("tdoe_threshold", (1.0, 1.5, 2.0, 2.5, 3.0)),
    "efficiency": ("z_threshold", (1.0, 1.25, 1.5, 1.75, 2.0)),
    "usage_mismatch": ("usage_shift", (0.02, 0.03, 0.04, 0.05, 0.06)),
}
MIN_FLAGS = 30


def relevant_mae4(engine, stats, schedules, rules, seasons) -> float:
    m = metrics(walk_forward(engine, stats, schedules, rules, seasons), relevant_only=True)
    return float(m.filter(pl.col("position") == "ALL")["mae_4"][0])


def weight_grid() -> list[BaselineEngine]:
    steps = round(1 / WEIGHT_STEP)
    out = []
    for i, j, shrink in product(range(steps + 1), range(steps + 1), SHRINK_OPTIONS):
        if i + j > steps:
            continue
        w_l3, w_season = i / steps, j / steps
        w_usage = round(1 - w_l3 - w_season, 10)
        if w_l3 + w_season == 0:  # usage alone can't project K/DEF or usage-less players
            continue
        out.append(BaselineEngine(w_l3, w_season, w_usage, shrink))
    return out


@dataclass
class WeightResult:
    best: BaselineEngine
    train_best: float
    train_default: float
    valid_best: float
    valid_default: float

    @property
    def improves(self) -> bool:
        return self.valid_best < self.valid_default


def tune_weights(
    stats: pl.DataFrame,
    schedules: Mapping[int, Schedule],
    rules: dict[str, float],
    train: Sequence[int],
    valid: Sequence[int],
) -> WeightResult:
    default = BaselineEngine()
    scored = [(relevant_mae4(e, stats, schedules, rules, train), e) for e in weight_grid()]
    train_best, best = min(scored, key=lambda t: t[0])
    return WeightResult(
        best,
        train_best,
        relevant_mae4(default, stats, schedules, rules, train),
        relevant_mae4(best, stats, schedules, rules, valid),
        relevant_mae4(default, stats, schedules, rules, valid),
    )


def _excess(summary: pl.DataFrame, kind: str) -> tuple[float, int]:
    """Total excess PPG (lift × flags) over both directions of one flag kind, and flag count."""
    rows = summary.filter(pl.col("kind") == kind)
    return float((rows["lift"] * rows["n"]).sum()), int(rows["n"].sum())


def tune_thresholds(
    stats: pl.DataFrame,
    rules: dict[str, float],
    train: Sequence[int],
    valid: Sequence[int],
) -> list[dict]:
    """Per flag kind: the threshold with the most total excess PPG on train, checked on valid.

    Each kind's threshold only changes its own flags, so kinds are searched independently.
    """
    default = RegressionConfig()
    out = []
    for kind, (field, options) in THRESHOLDS.items():
        trials = []
        for value in options:
            cfg = replace(default, **{field: value})
            excess, n = _excess(summarize(flag_outcomes(stats, rules, train, config=cfg)), kind)
            if n >= MIN_FLAGS:
                trials.append((excess, value))
        best_value = max(trials)[1] if trials else getattr(default, field)
        valid_scores = {
            label: _excess(
                summarize(
                    flag_outcomes(stats, rules, valid, config=replace(default, **{field: v}))
                ),
                kind,
            )
            for label, v in (("default", getattr(default, field)), ("best", best_value))
        }
        out.append(
            {
                "kind": kind,
                "field": field,
                "default": getattr(default, field),
                "best": best_value,
                "train": {v: round(e, 1) for e, v in trials},
                "valid_default": valid_scores["default"],
                "valid_best": valid_scores["best"],
            }
        )
    return out
