"""ESPN scoring settings → our rules, checked against the points ESPN actually awarded."""

from __future__ import annotations

import polars as pl
import pytest

from scoring.espn import POSITION, from_espn, stat_line
from scoring.rules import score
from tests.conftest import load_json


@pytest.fixture(scope="module")
def league() -> dict:
    return load_json("espn_league.json")  # a real league, scrubbed (scripts/record_espn_fixture.py)


def test_recorded_league_rules(league):
    rules, unmodeled = from_espn(league["settings"]["scoringSettings"]["scoringItems"])
    # QB passing rules live only in per-position overrides in this league
    assert rules["pass_yd"] == pytest.approx(0.04) and rules["pass_td"] == 4
    assert rules["pass_int"] == -2 and rules["rec"] == 1 and rules["fum_lost"] == -2
    # exclusive ESPN brackets (300-399 = 2, 400+ = 4) become cumulative ones (2 + 2)
    assert rules["bonus_pass_yd_300"] == 2 and rules["bonus_pass_yd_400"] == 2
    assert rules["fgm_30_39"] == 3 and rules["fgm_50_59"] == 5 and rules["fgm_60p"] == 6
    assert rules["espn_pts_allow_0"] == 5 and rules["espn_pts_allow_46p"] == -5
    assert rules["pts_allow_0"] == 0  # Sleeper ranges are never used for an ESPN league
    assert "1-point safety" in unmodeled


def test_every_recorded_stat_line_scores_like_espn(league):
    rules, _ = from_espn(league["settings"]["scoringSettings"]["scoringItems"])
    rows, want = [], []
    for team in league["teams"]:
        for e in team["roster"]["entries"]:
            p = e["playerPoolEntry"]["player"]
            for s in p["stats"]:
                rows.append(stat_line(s["stats"], POSITION[p["defaultPositionId"]]))
                want.append((p["fullName"], s["scoringPeriodId"], s["appliedTotal"]))
    by_pos = {r["position"] for r in rows}
    assert {"QB", "RB", "WR", "TE", "K", "DEF"} <= by_pos  # all kinds of stat line are covered
    got = score(pl.DataFrame(rows, infer_schema_length=None), rules)["fp"].to_list()
    off = [(w, round(g, 2)) for w, g in zip(want, got, strict=True) if abs(g - w[2]) > 0.01]
    assert not off, off[:5]


def _item(stat_id: int, points: float = 0.0, **overrides: float) -> dict:
    return {
        "statId": stat_id,
        "points": points,
        "pointsOverrides": {k[1:]: v for k, v in overrides.items()},
    }


def test_te_premium_and_exclusive_bonuses():
    rules, unmodeled = from_espn(
        [
            _item(53, 1.0, p4=1.5),  # receptions: 1 PPR, TEs 1.5
            _item(56, 2.0),  # 100-199 receiving yards
            _item(57, 5.0),  # 200+ receiving yards
            _item(58, 0.25),  # targets: not modelled
        ]
    )
    assert rules["rec"] == 1.0 and rules["bonus_rec_te"] == 0.5 and rules["bonus_rec_rb"] == 0
    assert rules["bonus_rec_yd_100"] == 2.0 and rules["bonus_rec_yd_200"] == 3.0
    assert unmodeled == ["targets"]


def test_points_allowed_bracket_scoring():
    rules, _ = from_espn([_item(92, p16=1.0), _item(121, p16=0.0), _item(124, p16=-3.0)])
    lines = [stat_line({"120": pts}, "DEF") for pts in (17, 18, 40)]
    fp = score(pl.DataFrame(lines), rules)["fp"].to_list()
    assert fp == [1.0, 0.0, -3.0]


def test_empty_scoring_is_an_error():
    with pytest.raises(ValueError):
        from_espn([])
