"""Search the baseline weights and regression-flag thresholds against the backtest.

Parameters are chosen on the training seasons only and then checked on a held-out season, so the
reported improvement is not just the search fitting noise.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from itertools import product

import polars as pl

from models.backtest import POSITIONS, metrics, walk_forward
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


MATCHUP_ALPHAS = (0.0, 0.25, 0.5, 0.75, 1.0)


def matchup_table(
    stats: pl.DataFrame,
    schedules: Mapping[int, Schedule],
    rules: dict[str, float],
    seasons: Sequence[int],
) -> pl.DataFrame:
    """Next-week MAE and Spearman per (alpha, position), all projected players who played.

    A position's multiplier only touches that position's rows, so one run per alpha (applied to
    every position at once) covers all positions.
    """
    from projections.matchup import MatchupAdjusted

    out = []
    for a in MATCHUP_ALPHAS:
        engine = MatchupAdjusted(BaselineEngine(), dict.fromkeys(POSITIONS, a))
        m = metrics(walk_forward(engine, stats, schedules, rules, seasons))
        out.append(m.select("position", "mae_1", "spearman").with_columns(pl.lit(a).alias("alpha")))
    return pl.concat(out).filter(pl.col("position") != "ALL")


def tune_matchups(
    stats: pl.DataFrame,
    schedules: Mapping[int, Schedule],
    rules: dict[str, float],
    train: Sequence[int],
    valid: Sequence[int],
) -> list[dict]:
    """Per position: alpha with the lowest train MAE, kept only if the holdout improves too."""
    tr = matchup_table(stats, schedules, rules, train)
    va = matchup_table(stats, schedules, rules, valid)
    rows = []
    for pos in POSITIONS:
        t = tr.filter(pl.col("position") == pos).sort("alpha")
        v = va.filter(pl.col("position") == pos).sort("alpha")
        if t.is_empty():
            continue
        best = float(t.sort("mae_1")["alpha"][0])
        v_at = dict(zip(v["alpha"].to_list(), v["mae_1"].to_list(), strict=True))
        keep = best if v_at.get(best, float("inf")) < v_at.get(0.0, float("inf")) else 0.0
        rows.append(
            {
                "position": pos,
                "train": dict(zip(t["alpha"].to_list(), t["mae_1"].to_list(), strict=True)),
                "valid": v_at,
                "valid_rho": dict(zip(v["alpha"].to_list(), v["spearman"].to_list(), strict=True)),
                "best_train": best,
                "chosen": keep,
            }
        )
    return rows


REG_BETA_SELL = (0.0, 0.25, 0.5, 0.75, 1.0)
REG_BETA_BUY = (0.0, 0.25, 0.5)


def tune_regression(
    stats: pl.DataFrame,
    schedules: Mapping[int, Schedule],
    rules: dict[str, float],
    train: Sequence[int],
    valid: Sequence[int],
) -> dict:
    """(beta_sell, beta_buy) with the lowest train 4-week MAE (fantasy-relevant), with holdout."""
    from projections.regression_adj import RegressionAdjusted

    grid = {
        (s, b): relevant_mae4(
            RegressionAdjusted(BaselineEngine(), s, b), stats, schedules, rules, train
        )
        for s in REG_BETA_SELL
        for b in REG_BETA_BUY
    }
    best = min(grid, key=grid.get)
    valid_default = relevant_mae4(BaselineEngine(), stats, schedules, rules, valid)
    valid_best = relevant_mae4(
        RegressionAdjusted(BaselineEngine(), *best), stats, schedules, rules, valid
    )
    return {
        "train": grid,
        "best": best,
        "valid_default": valid_default,
        "valid_best": valid_best,
        "chosen": best if valid_best < valid_default else (0.0, 0.0),
    }
