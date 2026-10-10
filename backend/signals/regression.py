"""Regression report: TD over expected, efficiency outliers, usage vs production mismatch.

direction = +1 → production likely to improve (buy-low); -1 → likely to cool off (sell-high).
Every flag carries a plain-English message with the numbers behind it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import polars as pl

from projections.norms import PositionRates

TDOE_THRESHOLD = 2.0
Z_THRESHOLD = 1.5
USAGE_SHIFT = 0.04  # 4 percentage points of team opportunity share
USAGE_WINDOW = 4
MIN_NORM_POPULATION = 12

FLAG_WEIGHTS = {"td_over_expected": 1.0, "efficiency": 0.75, "usage_mismatch": 1.0}
FLAG_SCALES = {
    "td_over_expected": TDOE_THRESHOLD,
    "efficiency": Z_THRESHOLD,
    "usage_mismatch": USAGE_SHIFT,
}


@dataclass
class RegressionFlag:
    player_id: str
    kind: str  # td_over_expected | efficiency | usage_mismatch
    metric: str
    direction: int
    value: float
    message: str
    numbers: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class EfficiencyMetric:
    key: str
    label: str
    positions: tuple[str, ...]
    num: str
    den: str
    min_sample: int
    sample_label: str
    fmt: str = "{:.1f}"


EFFICIENCY_METRICS = (
    EfficiencyMetric("ypc", "yards per carry", ("RB",), "rush_yds", "carries", 30, "carries"),
    EfficiencyMetric("ypt", "yards per target", ("RB", "WR", "TE"), "rec_yds", "targets", 20, "targets"),
    EfficiencyMetric(
        "catch_rate", "catch rate", ("RB", "WR", "TE"), "receptions", "targets", 20, "targets", "{:.0%}"
    ),
    EfficiencyMetric(
        "fp_per_opp", "fantasy points per opportunity", ("RB", "WR", "TE"), "fp", "opps", 30,
        "opportunities", "{:.2f}",
    ),
    EfficiencyMetric(
        "fp_per_dropback", "fantasy points per dropback", ("QB",), "fp", "qb_plays", 60,
        "plays", "{:.2f}",
    ),
)  # fmt: skip


def season_totals(stats: pl.DataFrame, season: int, through_week: int) -> pl.DataFrame:
    """Per-player totals for one season through `through_week` (stats must carry fp + position)."""
    d = stats.filter((pl.col("season") == season) & (pl.col("week") <= through_week)).fill_null(0)
    return (
        d.group_by("player_id")
        .agg(
            pl.col("position").last(),
            pl.len().alias("games"),
            *[
                pl.col(c).sum()
                for c in (
                    "fp",
                    "carries",
                    "rush_yds",
                    "rush_td",
                    "targets",
                    "receptions",
                    "rec_yds",
                    "rec_td",
                    "pass_att",
                    "pass_td",
                    "rz_carries",
                    "rz_targets",
                    "gl_carries",
                    "rz_td",
                )
            ],
        )  # fmt: skip
        .with_columns(
            (pl.col("carries") + pl.col("targets")).alias("opps"),
            (pl.col("pass_att") + pl.col("carries")).alias("qb_plays"),
            (pl.col("rz_carries") + pl.col("rz_targets")).alias("rz_opps"),
            (pl.col("rush_td") + pl.col("rec_td")).alias("td"),
        )
    )


# ───────── TD over expected ─────────


def td_over_expected(totals: pl.DataFrame, rates: dict[str, PositionRates]) -> pl.DataFrame:
    """Adds expected_td / tdoe columns (rush+rec TDs for skill players, passing TDs for QBs)."""
    rows = []
    for r in totals.iter_rows(named=True):
        pr = rates.get(r["position"])
        if pr is None:
            continue
        if r["position"] == "QB":
            actual = r["pass_td"]
            expected = r["pass_att"] * pr.pass_td_rate
        else:
            actual = r["td"]
            nonrz = r["opps"] - r["rz_opps"]
            expected = r["rz_opps"] * pr.rz_td_rate + nonrz * pr.nonrz_td_rate
        rows.append({"player_id": r["player_id"], "actual_td": actual, "expected_td": expected})
    df = pl.DataFrame(
        rows, schema={"player_id": pl.Utf8, "actual_td": pl.Int64, "expected_td": pl.Float64}
    )
    return totals.join(df, on="player_id", how="left").with_columns(
        (pl.col("actual_td") - pl.col("expected_td")).alias("tdoe")
    )


def tdoe_flags(with_tdoe: pl.DataFrame, threshold: float = TDOE_THRESHOLD) -> list[RegressionFlag]:
    flags = []
    for r in with_tdoe.filter(pl.col("tdoe").abs() >= threshold).iter_rows(named=True):
        actual, exp, tdoe = r["actual_td"], r["expected_td"], r["tdoe"]
        if r["position"] == "QB":
            basis = f"{actual} passing TDs on {r['pass_att']} attempts"
        else:
            basis = (
                f"{actual} TDs on {r['rz_opps']} red-zone touches ({r['opps']} total opportunities)"
            )
        if tdoe > 0:
            msg = f"{basis}; expected ~{exp:.1f}. Likely to slow down."
        else:
            msg = f"Only {basis}; expected ~{exp:.1f}. Due to bounce back."
        flags.append(
            RegressionFlag(
                r["player_id"],
                "td_over_expected",
                "tdoe",
                -1 if tdoe > 0 else 1,
                round(tdoe, 2),
                msg,
                {"actual_td": actual, "expected_td": round(exp, 2), "rz_opps": r["rz_opps"]},
            )
        )
    return flags


# ───────── efficiency outliers ─────────


def _metric_frame(totals: pl.DataFrame, m: EfficiencyMetric) -> pl.DataFrame:
    return totals.filter(
        pl.col("position").is_in(m.positions) & (pl.col(m.den) >= m.min_sample)
    ).with_columns((pl.col(m.num) / pl.col(m.den)).alias("metric"))


def positional_norms(
    current: pl.DataFrame, prior: pl.DataFrame | None, m: EfficiencyMetric
) -> dict[str, tuple[float, float, int]]:
    """position → (mean, sd, n). Falls back to last season when this season's sample is thin."""
    out = {}
    for pos in m.positions:
        cur = _metric_frame(current, m).filter(pl.col("position") == pos)["metric"]
        src = cur
        if cur.len() < MIN_NORM_POPULATION and prior is not None:
            src = _metric_frame(prior, m).filter(pl.col("position") == pos)["metric"]
        if src.len() >= 3 and (src.std() or 0) > 0:
            out[pos] = (float(src.mean()), float(src.std()), src.len())
    return out


def efficiency_flags(
    totals: pl.DataFrame,
    prior_totals: pl.DataFrame | None,
    z_threshold: float = Z_THRESHOLD,
) -> tuple[list[RegressionFlag], pl.DataFrame]:
    """Returns flags plus a long frame of every computed z-score (player_id, metric, z)."""
    flags: list[RegressionFlag] = []
    zs = []
    for m in EFFICIENCY_METRICS:
        norms = positional_norms(totals, prior_totals, m)
        for r in _metric_frame(totals, m).iter_rows(named=True):
            if r["position"] not in norms:
                continue
            mean, sd, _ = norms[r["position"]]
            z = (r["metric"] - mean) / sd
            zs.append({"player_id": r["player_id"], "metric": m.key, "z": z})
            if abs(z) < z_threshold:
                continue
            trend = "Expect it to drift down." if z > 0 else "Expect it to improve."
            msg = (
                f"{m.fmt.format(r['metric'])} {m.label} vs {r['position']} norm "
                f"{m.fmt.format(mean)} (z = {z:+.1f}, {r[m.den]} {m.sample_label}). {trend}"
            )
            flags.append(
                RegressionFlag(
                    r["player_id"],
                    "efficiency",
                    m.key,
                    -1 if z > 0 else 1,
                    round(z, 2),
                    msg,
                    {"value": round(r["metric"], 3), "norm": round(mean, 3), "sample": r[m.den]},
                )
            )
    z_df = pl.DataFrame(zs, schema={"player_id": pl.Utf8, "metric": pl.Utf8, "z": pl.Float64})
    return flags, z_df


# ───────── usage vs production ─────────


def opportunity_share(stats: pl.DataFrame) -> pl.DataFrame:
    """Per player-game share of team targets+carries."""
    d = stats.with_columns(
        (pl.col("targets").fill_null(0) + pl.col("carries").fill_null(0)).alias("opps")
    )
    team = d.group_by("team", "season", "week").agg(pl.col("opps").sum().alias("team_opps"))
    return d.join(team, on=["team", "season", "week"]).with_columns(
        (pl.col("opps") / pl.col("team_opps")).alias("opp_share")
    )


def usage_trends(
    stats: pl.DataFrame, season: int, through_week: int, window: int = USAGE_WINDOW
) -> pl.DataFrame:
    d = opportunity_share(
        stats.filter((pl.col("season") == season) & (pl.col("week") <= through_week))
    ).filter(pl.col("position").is_in(["RB", "WR", "TE"]))
    recent = d.sort("week").group_by("player_id").tail(window)
    half = window // 2
    return (
        recent.sort("week")
        .group_by("player_id")
        .agg(
            pl.len().alias("n"),
            pl.col("opp_share").head(half).mean().alias("share_early"),
            pl.col("opp_share").tail(half).mean().alias("share_late"),
            pl.col("fp").head(half).mean().alias("fp_early"),
            pl.col("fp").tail(half).mean().alias("fp_late"),
            pl.col("opp_share").alias("share_series"),
            pl.col("fp").alias("fp_series"),
        )
        .filter(pl.col("n") >= 3)
        .with_columns((pl.col("share_late") - pl.col("share_early")).alias("share_change"))
    )


def usage_flags(trends: pl.DataFrame, shift: float = USAGE_SHIFT) -> list[RegressionFlag]:
    flags = []
    for r in trends.iter_rows(named=True):
        dshare, fe, fl = r["share_change"], r["fp_early"], r["fp_late"]
        nums = {
            "share_early": round(r["share_early"], 3),
            "share_late": round(r["share_late"], 3),
            "fp_early": round(fe, 1),
            "fp_late": round(fl, 1),
            "games": r["n"],
        }
        se, sl = r["share_early"] * 100, r["share_late"] * 100
        if dshare >= shift and fl <= fe:
            msg = (
                f"Opportunity share up from {se:.0f}% to {sl:.0f}% over the last {r['n']} games "
                f"while points went {fe:.1f} → {fl:.1f}. Production should catch up."
            )
            flags.append(
                RegressionFlag(
                    r["player_id"],
                    "usage_mismatch",
                    "usage_up_points_down",
                    1,
                    round(dshare, 3),
                    msg,
                    nums,
                )
            )
        elif dshare <= -shift and fl >= fe:
            msg = (
                f"Opportunity share down from {se:.0f}% to {sl:.0f}% over the last {r['n']} games "
                f"but points held at {fe:.1f} → {fl:.1f}. Hard to sustain on shrinking usage."
            )
            flags.append(
                RegressionFlag(
                    r["player_id"],
                    "usage_mismatch",
                    "usage_down_points_up",
                    -1,
                    round(dshare, 3),
                    msg,
                    nums,
                )
            )
    return flags


# ───────── report ─────────


@dataclass
class RegressionReport:
    flags: list[RegressionFlag]
    tdoe: pl.DataFrame  # per player season totals + expected_td/tdoe
    efficiency_z: pl.DataFrame
    usage: pl.DataFrame

    def for_player(self, player_id: str) -> list[RegressionFlag]:
        return [f for f in self.flags if f.player_id == player_id]

    def score(self, player_id: str) -> float:
        """Signed strength: >0 expect better production, <0 expect worse."""
        s = 0.0
        for f in self.for_player(player_id):
            mag = min(abs(f.value) / FLAG_SCALES[f.kind], 2.0)  # 1.0 at threshold, capped at 2
            s += f.direction * FLAG_WEIGHTS[f.kind] * mag
        return round(s, 2)


def build_report(
    stats: pl.DataFrame, rates: dict[str, PositionRates], season: int, through_week: int
) -> RegressionReport:
    totals = season_totals(stats, season, through_week)
    prior = season_totals(stats, season - 1, 99)
    with_tdoe = td_over_expected(totals, rates)
    eff_flags, z_df = efficiency_flags(totals, prior if prior.height else None)
    trends = usage_trends(stats, season, through_week)
    flags = tdoe_flags(with_tdoe) + eff_flags + usage_flags(trends)
    return RegressionReport(flags, with_tdoe, z_df, trends)
