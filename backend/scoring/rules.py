"""League scoring rules → fantasy points for player_week_stats rows.

Rules use Sleeper's key names so a league's `scoring_settings` maps 1:1.
"""

from __future__ import annotations

import hashlib
import json

import polars as pl

HALF_PPR: dict[str, float] = {
    "pass_yd": 0.04,
    "pass_td": 4.0,
    "pass_int": -1.0,
    "pass_cmp": 0.0,
    "rush_yd": 0.1,
    "rush_td": 6.0,
    "rush_att": 0.0,
    "rec": 0.5,
    "rec_yd": 0.1,
    "rec_td": 6.0,
    "bonus_rec_rb": 0.0,
    "bonus_rec_wr": 0.0,
    "bonus_rec_te": 0.0,
    "fum_lost": -2.0,
    "two_pt": 2.0,
}

PRESETS: dict[str, dict[str, float]] = {
    "half_ppr": HALF_PPR,
    "ppr": HALF_PPR | {"rec": 1.0},
    "standard": HALF_PPR | {"rec": 0.0},
}


def from_sleeper(scoring_settings: dict[str, float] | None) -> dict[str, float]:
    """Pick the keys we model from Sleeper settings; anything missing keeps the half-PPR default."""
    s = scoring_settings or {}
    rules = {k: float(s.get(k, v)) for k, v in HALF_PPR.items() if k != "two_pt"}
    rules["two_pt"] = float(s.get("rush_2pt", s.get("rec_2pt", HALF_PPR["two_pt"])))
    return rules


def normalize(rules: dict[str, float] | None) -> dict[str, float]:
    return HALF_PPR | {k: float(v) for k, v in (rules or {}).items() if k in HALF_PPR}


def profile_id(rules: dict[str, float]) -> str:
    canon = json.dumps(normalize(rules), sort_keys=True)
    return hashlib.sha1(canon.encode()).hexdigest()[:12]


def ppr_value(rules: dict[str, float]) -> float:
    return normalize(rules)["rec"]


def describe(rules: dict[str, float]) -> str:
    rec = normalize(rules)["rec"]
    return {1.0: "PPR", 0.5: "Half PPR", 0.0: "Standard"}.get(rec, f"{rec:g} PPR")


def _c(name: str) -> pl.Expr:
    return pl.col(name).fill_null(0)


def points_expr(rules: dict[str, float]) -> pl.Expr:
    """Fantasy points for one player-week row (needs `position` for TE/RB/WR reception bonuses)."""
    r = normalize(rules)
    rec_bonus = (
        pl.when(pl.col("position") == "TE")
        .then(r["bonus_rec_te"])
        .when(pl.col("position") == "RB")
        .then(r["bonus_rec_rb"])
        .when(pl.col("position") == "WR")
        .then(r["bonus_rec_wr"])
        .otherwise(0.0)
    )
    return (
        _c("pass_yds") * r["pass_yd"]
        + _c("pass_td") * r["pass_td"]
        + _c("interceptions") * r["pass_int"]
        + _c("pass_cmp") * r["pass_cmp"]
        + _c("rush_yds") * r["rush_yd"]
        + _c("rush_td") * r["rush_td"]
        + _c("carries") * r["rush_att"]
        + _c("receptions") * (r["rec"] + rec_bonus)
        + _c("rec_yds") * r["rec_yd"]
        + _c("rec_td") * r["rec_td"]
        + _c("fumbles_lost") * r["fum_lost"]
        + _c("two_pt") * r["two_pt"]
    )


def score(stats: pl.DataFrame, rules: dict[str, float]) -> pl.DataFrame:
    """Add `fp` (league-scored fantasy points). `stats` must include `position`."""
    return stats.with_columns(points_expr(rules).alias("fp"))


def td_points_expr(rules: dict[str, float]) -> pl.Expr:
    """Points that came from touchdowns (used to split production into TD / non-TD parts)."""
    r = normalize(rules)
    return _c("pass_td") * r["pass_td"] + _c("rush_td") * r["rush_td"] + _c("rec_td") * r["rec_td"]
