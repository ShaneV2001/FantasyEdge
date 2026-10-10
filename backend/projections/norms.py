"""Positional league-average rates used by usage-implied projections and regression flags.

Population = every player-week of the prior season plus the current season through the as-of
week. Stat rows only exist for completed games, so nothing unplayed (or later) leaks in.
"""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl

from scoring.rules import normalize


@dataclass(frozen=True)
class PositionRates:
    position: str
    fp_per_target: float  # non-TD receiving points per target
    fp_per_carry: float  # non-TD rushing points per carry
    fp_per_att: float  # non-TD passing points per attempt
    rz_td_rate: float  # rush+rec TDs per red-zone opportunity
    nonrz_td_rate: float  # rush+rec TDs per non-red-zone opportunity
    pass_td_rate: float  # passing TDs per attempt


def norms_window(stats: pl.DataFrame, season: int, through_week: int) -> pl.DataFrame:
    return stats.filter(
        (pl.col("season") == season - 1)
        | ((pl.col("season") == season) & (pl.col("week") <= through_week))
    )


def _safe(num: float, den: float) -> float:
    return float(num) / float(den) if den else 0.0


def position_rates(window: pl.DataFrame, rules: dict[str, float]) -> dict[str, PositionRates]:
    r = normalize(rules)
    bonus = {"TE": r["bonus_rec_te"], "RB": r["bonus_rec_rb"], "WR": r["bonus_rec_wr"]}
    out: dict[str, PositionRates] = {}
    for pos in ("QB", "RB", "WR", "TE"):
        d = window.filter(pl.col("position") == pos).fill_null(0)
        if d.is_empty():
            out[pos] = PositionRates(pos, 0, 0, 0, 0, 0, 0)
            continue
        s = d.select(
            pl.col("targets").sum(),
            pl.col("receptions").sum(),
            pl.col("rec_yds").sum(),
            pl.col("carries").sum(),
            pl.col("rush_yds").sum(),
            pl.col("pass_att").sum(),
            pl.col("pass_yds").sum(),
            pl.col("pass_cmp").sum(),
            pl.col("interceptions").sum(),
            pl.col("pass_td").sum(),
            (pl.col("rush_td") + pl.col("rec_td")).sum().alias("td"),
            pl.col("rz_td").sum(),
            (pl.col("rz_carries") + pl.col("rz_targets")).sum().alias("rz_opp"),
        ).row(0, named=True)
        rec_fp = s["receptions"] * (r["rec"] + bonus.get(pos, 0.0)) + s["rec_yds"] * r["rec_yd"]
        rush_fp = s["rush_yds"] * r["rush_yd"] + s["carries"] * r["rush_att"]
        pass_fp = (
            s["pass_yds"] * r["pass_yd"]
            + s["interceptions"] * r["pass_int"]
            + s["pass_cmp"] * r["pass_cmp"]
        )
        nonrz_opp = s["targets"] + s["carries"] - s["rz_opp"]
        is_qb = pos == "QB"  # trick-play passes by skill players would otherwise skew usage
        out[pos] = PositionRates(
            position=pos,
            fp_per_target=_safe(rec_fp, s["targets"]),
            fp_per_carry=_safe(rush_fp, s["carries"]),
            fp_per_att=_safe(pass_fp, s["pass_att"]) if is_qb else 0.0,
            rz_td_rate=_safe(s["rz_td"], s["rz_opp"]),
            nonrz_td_rate=_safe(s["td"] - s["rz_td"], nonrz_opp),
            pass_td_rate=_safe(s["pass_td"], s["pass_att"]) if is_qb else 0.0,
        )
    return out


def expected_td_expr(rates: dict[str, PositionRates]) -> pl.Expr:
    """Expected rushing+receiving TDs for a row from its opportunity locations."""
    rz = pl.col("rz_carries").fill_null(0) + pl.col("rz_targets").fill_null(0)
    nonrz = pl.col("carries").fill_null(0) + pl.col("targets").fill_null(0) - rz
    expr = pl.lit(0.0)
    for pos, pr in rates.items():
        expr = (
            pl.when(pl.col("position") == pos)
            .then(rz * pr.rz_td_rate + nonrz * pr.nonrz_td_rate)
            .otherwise(expr)
        )
    return expr
