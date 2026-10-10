import pytest

from scoring.rules import HALF_PPR, PRESETS, describe, from_sleeper, profile_id
from tests.builders import stat_row, stats_frame
from tests.conftest import load_json

LINE = dict(receptions=6, rec_yds=80, rec_td=1, carries=2, rush_yds=10, fumbles_lost=1)


@pytest.mark.parametrize(
    "preset, expected",
    [("standard", 8 + 6 + 1 - 2), ("half_ppr", 3 + 8 + 6 + 1 - 2), ("ppr", 6 + 8 + 6 + 1 - 2)],
)
def test_receiver_line_under_presets(preset, expected):
    df = stats_frame([stat_row("w", "WR", 2026, 1, **LINE)], PRESETS[preset])
    assert df["fp"][0] == pytest.approx(expected)


def test_qb_line_half_ppr():
    df = stats_frame(
        [
            stat_row(
                "q", "QB", 2026, 1, pass_yds=300, pass_td=2, interceptions=1, rush_yds=20, two_pt=1
            )
        ]
    )
    assert df["fp"][0] == pytest.approx(12 + 8 - 1 + 2 + 2)


def test_te_premium_bonus_only_for_tes():
    rules = HALF_PPR | {"bonus_rec_te": 0.5}
    df = stats_frame(
        [stat_row("t", "TE", 2026, 1, receptions=4), stat_row("w", "WR", 2026, 1, receptions=4)],
        rules,
    )
    assert df["fp"].to_list() == pytest.approx([4.0, 2.0])


def test_from_sleeper_and_profile_id_stable():
    rules = from_sleeper(load_json("sleeper_league.json")["scoring_settings"])
    assert rules["rec"] == 0.5 and rules["pass_td"] == 4
    assert describe(rules) == "Half PPR"
    assert profile_id(rules) == profile_id(dict(HALF_PPR))
    assert profile_id(PRESETS["ppr"]) != profile_id(HALF_PPR)
