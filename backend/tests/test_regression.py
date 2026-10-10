import polars as pl
import pytest

from projections.norms import PositionRates
from signals.regression import (
    EFFICIENCY_METRICS,
    RegressionReport,
    efficiency_flags,
    season_totals,
    td_over_expected,
    tdoe_flags,
    usage_flags,
    usage_trends,
)
from tests.builders import stat_row, stats_frame

RATES = {
    "RB": PositionRates("RB", 1.0, 0.45, 0, rz_td_rate=0.2, nonrz_td_rate=0.02, pass_td_rate=0),
    "WR": PositionRates("WR", 1.4, 0.5, 0, rz_td_rate=0.2, nonrz_td_rate=0.02, pass_td_rate=0),
    "QB": PositionRates("QB", 0, 0.4, 0.3, 0.1, 0.01, pass_td_rate=0.045),
}


def _totals(rows):
    return season_totals(stats_frame(rows), 2026, 99)


# ───────── TD over expected ─────────


def test_tdoe_hot_player_flags_cool_off():
    # 9 RZ touches + 40 other carries; 6 TDs. expected = 9*0.2 + 40*0.02 = 2.6 → +3.4
    rows = [stat_row("hot", "RB", 2026, 1, carries=49, rz_carries=9, rush_td=6, rz_td=5)]
    t = td_over_expected(_totals(rows), RATES)
    r = t.row(0, named=True)
    assert r["expected_td"] == pytest.approx(2.6)
    assert r["tdoe"] == pytest.approx(3.4)
    (flag,) = tdoe_flags(t)
    assert flag.direction == -1
    assert "6 TDs on 9 red-zone touches" in flag.message and "~2.6" in flag.message
    assert "slow down" in flag.message


def test_tdoe_cold_player_flags_bounce_back():
    rows = [stat_row("cold", "RB", 2026, 1, carries=60, rz_carries=15, rush_td=1, rz_td=1)]
    (flag,) = tdoe_flags(td_over_expected(_totals(rows), RATES))  # expected 3.9 → -2.9
    assert flag.direction == 1 and "bounce back" in flag.message


def test_tdoe_threshold_is_inclusive_and_quiet_below():
    exact = [stat_row("x", "WR", 2026, 1, targets=10, rz_targets=10, rec_td=4, rz_td=4)]  # 4-2=+2
    near = [stat_row("y", "WR", 2026, 1, targets=10, rz_targets=10, rec_td=3, rz_td=3)]  # +1
    assert len(tdoe_flags(td_over_expected(_totals(exact), RATES))) == 1
    assert tdoe_flags(td_over_expected(_totals(near), RATES)) == []


def test_qb_tdoe_uses_passing():
    rows = [stat_row("q", "QB", 2026, 1, pass_att=100, pass_td=9)]  # expected 4.5
    (flag,) = tdoe_flags(td_over_expected(_totals(rows), RATES))
    assert flag.value == pytest.approx(4.5) and "passing TDs" in flag.message


# ───────── efficiency z-scores ─────────


def _rb_population(n=14, ypc_outlier=None, outlier_carries=40):
    rows = []
    for i in range(n):
        ypc = 4.0 + 0.1 * (i % 5 - 2)  # 3.8..4.2
        rows.append(stat_row(f"rb{i}", "RB", 2026, 1, carries=40, rush_yds=int(40 * ypc)))
    if ypc_outlier is not None:
        rows.append(
            stat_row(
                "out",
                "RB",
                2026,
                1,
                carries=outlier_carries,
                rush_yds=int(outlier_carries * ypc_outlier),
            )
        )
    return _totals(rows)


def test_efficiency_outlier_flagged_with_direction():
    flags, z = efficiency_flags(_rb_population(ypc_outlier=6.5), None)
    out = [f for f in flags if f.player_id == "out" and f.metric == "ypc"]
    assert len(out) == 1 and out[0].direction == -1 and out[0].value >= 1.5
    assert "yards per carry vs RB norm" in out[0].message
    assert z.filter(pl.col("metric") == "ypc").height == 15


def test_efficiency_min_sample_enforced():
    flags, z = efficiency_flags(_rb_population(ypc_outlier=9.0, outlier_carries=12), None)
    assert not [f for f in flags if f.player_id == "out"]
    assert "out" not in z["player_id"].to_list()


def test_efficiency_falls_back_to_prior_norms_when_thin():
    thin_current = _rb_population(n=3, ypc_outlier=6.5)
    prior = _rb_population(n=14)
    flags, _ = efficiency_flags(thin_current, prior)
    assert any(f.player_id == "out" and f.metric == "ypc" for f in flags)


def test_metric_minimums_match_spec():
    mins = {m.key: m.min_sample for m in EFFICIENCY_METRICS}
    assert mins["ypc"] == 30 and mins["ypt"] == 20 and mins["catch_rate"] == 20


# ───────── usage vs production ─────────


def _usage_rows(pid, my_opps, my_fp_yards, team="AAA"):
    rows = []
    for w, (opps, yds) in enumerate(zip(my_opps, my_fp_yards, strict=True), start=1):
        rows.append(stat_row(pid, "WR", 2026, w, team, targets=opps, rec_yds=yds))
        rows.append(stat_row(f"{pid}_mate", "WR", 2026, w, team, targets=40 - opps))
    return rows


def test_usage_up_points_down_is_positive():
    rows = _usage_rows("riser", [6, 6, 12, 12], [90, 90, 40, 40])
    trends = usage_trends(stats_frame(rows), 2026, 4)
    (flag,) = [f for f in usage_flags(trends) if f.player_id == "riser"]
    assert flag.direction == 1
    assert "up from 15% to 30%" in flag.message


def test_usage_down_points_up_is_negative():
    rows = _usage_rows("faller", [12, 12, 6, 6], [40, 40, 90, 90])
    (flag,) = [
        f for f in usage_flags(usage_trends(stats_frame(rows), 2026, 4)) if f.player_id == "faller"
    ]
    assert flag.direction == -1


def test_usage_requires_three_games():
    rows = _usage_rows("short", [6, 12], [90, 40])
    assert (
        usage_trends(stats_frame(rows), 2026, 4).filter(pl.col("player_id") == "short").is_empty()
    )


def test_report_score_sign():
    from signals.regression import RegressionFlag

    rep = RegressionReport(
        [
            RegressionFlag("p", "td_over_expected", "tdoe", -1, 3.0, ""),
            RegressionFlag("p", "usage_mismatch", "usage_down_points_up", -1, -0.05, ""),
        ],
        pl.DataFrame(),
        pl.DataFrame(),
        pl.DataFrame(),
    )
    assert rep.score("p") < -2
    assert rep.score("nobody") == 0
