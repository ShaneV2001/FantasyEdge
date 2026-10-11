"""League scoring rules → fantasy points for player_week_stats rows.

Rules use Sleeper's key names so a league's `scoring_settings` maps 1:1. A Sleeper league scores
exactly what it lists (a missing key is worth 0 there); half-PPR defaults only fill in when no
settings are given at all (presets, manual leagues, old stored profiles).
"""

from __future__ import annotations

import hashlib
import json
import logging

import polars as pl

log = logging.getLogger("ff_edge.scoring")

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
    "pass_2pt": 2.0,
    "rush_2pt": 2.0,
    "rec_2pt": 2.0,
}

# Keys we model beyond the classic set; worth 0 unless a league (or custom dict) says otherwise.
EXTRA_KEYS: tuple[str, ...] = (
    "pass_att", "pass_inc", "pass_int_td", "pass_sack", "fum",
    "pass_fd", "rush_fd", "rec_fd",
    "bonus_pass_yd_300", "bonus_pass_yd_400", "bonus_pass_cmp_25",
    "bonus_rush_yd_100", "bonus_rush_yd_200", "bonus_rec_yd_100", "bonus_rec_yd_200",
    "bonus_rush_rec_yd_100", "bonus_rush_rec_yd_200",
)  # fmt: skip

DEFAULTS: dict[str, float] = HALF_PPR | dict.fromkeys(EXTRA_KEYS, 0.0)
RULE_KEYS: tuple[str, ...] = tuple(DEFAULTS)

PRESETS: dict[str, dict[str, float]] = {
    "half_ppr": HALF_PPR,
    "ppr": HALF_PPR | {"rec": 1.0},
    "standard": HALF_PPR | {"rec": 0.0},
}

# Stat columns the rules read; older stored rows may lack the newer ones (treated as 0).
STAT_COLUMNS: tuple[str, ...] = (
    "pass_att", "pass_cmp", "pass_yds", "pass_td", "interceptions", "pass_int_td", "sacks_taken",
    "carries", "rush_yds", "rush_td", "receptions", "rec_yds", "rec_td",
    "fumbles", "fumbles_lost", "pass_fd", "rush_fd", "rec_fd",
    "two_pt", "pass_2pt", "rush_2pt", "rec_2pt",
)  # fmt: skip

_warned: set[str] = set()


def _expand_legacy(rules: dict[str, float]) -> dict[str, float]:
    """Old profiles stored a single `two_pt` rate for every kind of two-point conversion."""
    if "two_pt" not in rules:
        return rules
    out = {k: v for k, v in rules.items() if k != "two_pt"}
    for k in ("pass_2pt", "rush_2pt", "rec_2pt"):
        out.setdefault(k, rules["two_pt"])
    return out


def from_sleeper(scoring_settings: dict[str, float] | None) -> dict[str, float]:
    """A Sleeper league's rules: every key we model, 0 where the league doesn't list it."""
    s = scoring_settings or {}
    if not s:
        return dict(DEFAULTS)
    unmodeled = sorted(k for k, v in s.items() if k not in DEFAULTS and v and k not in _warned)
    if unmodeled:
        _warned.update(unmodeled)
        log.info("scoring keys not modeled yet (ignored): %s", ", ".join(unmodeled))
    return {k: float(s.get(k, 0.0)) for k in RULE_KEYS}


def normalize(rules: dict[str, float] | None) -> dict[str, float]:
    known = {k: float(v) for k, v in _expand_legacy(dict(rules or {})).items() if k in DEFAULTS}
    return DEFAULTS | known


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


def _at_least(expr: pl.Expr, n: int) -> pl.Expr:
    return (expr >= n).cast(pl.Float64)


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
    # two-point conversions not attributed to a play type (rows ingested before the split)
    unattributed_2pt = (_c("two_pt") - _c("pass_2pt") - _c("rush_2pt") - _c("rec_2pt")).clip(0)
    scrimmage = _c("rush_yds") + _c("rec_yds")
    return (
        _c("pass_yds") * r["pass_yd"]
        + _c("pass_td") * r["pass_td"]
        + _c("interceptions") * r["pass_int"]
        + _c("pass_int_td") * r["pass_int_td"]
        + _c("pass_cmp") * r["pass_cmp"]
        + _c("pass_att") * r["pass_att"]
        + (_c("pass_att") - _c("pass_cmp")).clip(0) * r["pass_inc"]
        + _c("sacks_taken") * r["pass_sack"]
        + _c("pass_fd") * r["pass_fd"]
        + _c("rush_yds") * r["rush_yd"]
        + _c("rush_td") * r["rush_td"]
        + _c("carries") * r["rush_att"]
        + _c("rush_fd") * r["rush_fd"]
        + _c("receptions") * (r["rec"] + rec_bonus)
        + _c("rec_yds") * r["rec_yd"]
        + _c("rec_td") * r["rec_td"]
        + _c("rec_fd") * r["rec_fd"]
        + _c("fumbles") * r["fum"]
        + _c("fumbles_lost") * r["fum_lost"]
        + _c("pass_2pt") * r["pass_2pt"]
        + _c("rush_2pt") * r["rush_2pt"]
        + _c("rec_2pt") * r["rec_2pt"]
        + unattributed_2pt * r["rush_2pt"]
        + _at_least(_c("pass_yds"), 300) * r["bonus_pass_yd_300"]
        + _at_least(_c("pass_yds"), 400) * r["bonus_pass_yd_400"]
        + _at_least(_c("pass_cmp"), 25) * r["bonus_pass_cmp_25"]
        + _at_least(_c("rush_yds"), 100) * r["bonus_rush_yd_100"]
        + _at_least(_c("rush_yds"), 200) * r["bonus_rush_yd_200"]
        + _at_least(_c("rec_yds"), 100) * r["bonus_rec_yd_100"]
        + _at_least(_c("rec_yds"), 200) * r["bonus_rec_yd_200"]
        + _at_least(scrimmage, 100) * r["bonus_rush_rec_yd_100"]
        + _at_least(scrimmage, 200) * r["bonus_rush_rec_yd_200"]
    )


def with_stat_columns(stats: pl.DataFrame) -> pl.DataFrame:
    """Add any stat column the rules read but `stats` lacks (older rows/fixtures) as 0."""
    missing = [c for c in STAT_COLUMNS if c not in stats.columns]
    return stats.with_columns(pl.lit(0, pl.Int32).alias(c) for c in missing) if missing else stats


def score(stats: pl.DataFrame, rules: dict[str, float]) -> pl.DataFrame:
    """Add `fp` (league-scored fantasy points). `stats` must include `position`."""
    return with_stat_columns(stats).with_columns(points_expr(rules).alias("fp"))


def td_points_expr(rules: dict[str, float]) -> pl.Expr:
    """Points that came from touchdowns (used to split production into TD / non-TD parts)."""
    r = normalize(rules)
    return _c("pass_td") * r["pass_td"] + _c("rush_td") * r["rush_td"] + _c("rec_td") * r["rec_td"]
