import polars as pl
import pytest

from models.regression_eval import summarize
from signals.regression import RegressionConfig


def _row(kind, direction, move, bucket=3):
    return {
        "season": 2026, "week": 6, "position": "WR", "bucket": bucket,
        "kind": kind, "direction": direction, "move": move,
    }  # fmt: skip


def test_lift_is_measured_against_similar_unflagged_players():
    rows = [
        _row("none", 0, -2.0),
        _row("none", 0, -4.0),  # similar players fell 3 PPG on average
        _row("td_over_expected", -1, -5.0),  # fell 2 more than expected → lift +2
        _row("td_over_expected", -1, -2.0),  # fell 1 less than expected → lift −1
        _row("efficiency", 1, 1.0),  # rose 4 vs expected −3 → lift +4
    ]
    s = {
        (r["kind"], r["direction"]): r for r in summarize(pl.DataFrame(rows)).iter_rows(named=True)
    }
    tdoe = s[("td_over_expected", -1)]
    assert tdoe["n"] == 2
    assert tdoe["hit_raw"] == 1.0  # both declined…
    assert tdoe["hit_adj"] == 0.5  # …but only one beyond what similar players did
    assert tdoe["lift"] == pytest.approx(0.5)
    assert s[("efficiency", 1)]["lift"] == pytest.approx(4.0)


def test_config_thresholds_reach_the_report():
    cfg = RegressionConfig(tdoe_threshold=1.0, z_threshold=1.0, usage_shift=0.02)
    assert cfg.scales == {"td_over_expected": 1.0, "efficiency": 1.0, "usage_mismatch": 0.02}
