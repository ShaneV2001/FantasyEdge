import polars as pl
import pytest

from scoring.rules import DEFAULTS, HALF_PPR, PRESETS, describe, from_sleeper, normalize, profile_id
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
    assert {k: rules[k] for k in HALF_PPR} == HALF_PPR  # offense matches half PPR exactly…
    assert rules["xpm"] == 0 and rules["sack"] == 0  # …and unlisted K/DEF keys score nothing
    assert profile_id(rules) == profile_id(dict(rules))
    assert profile_id(PRESETS["ppr"]) != profile_id(HALF_PPR)


def _fp(rules, **stats):
    pos = stats.pop("position", "WR")
    return stats_frame([stat_row("x", pos, 2026, 1, **stats)], rules)["fp"][0]


def test_sleeper_missing_keys_score_zero():
    # A league that lists no reception points is standard scoring, not half PPR.
    rules = from_sleeper({"rec_yd": 0.1, "rec_td": 6})
    assert rules["rec"] == 0 and rules["pass_td"] == 0
    assert _fp(rules, receptions=5, rec_yds=50) == pytest.approx(5.0)


def test_empty_sleeper_settings_fall_back_to_half_ppr():
    assert from_sleeper({}) == DEFAULTS


def test_full_default_settings_match_half_ppr():
    rules = from_sleeper(load_json("sleeper_scoring_full.json"))
    assert profile_id(rules) == profile_id(HALF_PPR)


@pytest.mark.parametrize(
    "rule, stats, expected",
    [
        ({"rec_fd": 0.5}, dict(rec_fd=4), 2.0),
        ({"rush_fd": 1}, dict(position="RB", rush_fd=3), 3.0),
        ({"pass_fd": 0.25}, dict(position="QB", pass_fd=8), 2.0),
        ({"pass_int_td": -2}, dict(position="QB", interceptions=1, pass_int_td=1), -2.0),
        ({"pass_sack": -0.5}, dict(position="QB", sacks_taken=4), -2.0),
        ({"fum": -1}, dict(fumbles=2, fumbles_lost=1), -2.0),
        ({"pass_inc": -0.5, "pass_att": 0.1}, dict(position="QB", pass_att=30, pass_cmp=20), -2.0),
        ({"bonus_rush_yd_100": 3}, dict(position="RB", rush_yds=99), 0.0),
        ({"bonus_rush_yd_100": 3, "bonus_rush_yd_200": 3}, dict(position="RB", rush_yds=210), 6.0),
        ({"bonus_rec_yd_100": 2}, dict(rec_yds=100), 2.0),
        ({"bonus_pass_yd_300": 2, "bonus_pass_yd_400": 3}, dict(position="QB", pass_yds=301), 2.0),
        ({"bonus_pass_cmp_25": 1}, dict(position="QB", pass_cmp=25, pass_att=30), 1.0),
        ({"bonus_rush_rec_yd_100": 2}, dict(position="RB", rush_yds=60, rec_yds=45), 2.0),
        ({"pass_2pt": 2}, dict(position="QB", two_pt=1, pass_2pt=1), 2.0),
        ({"rec_2pt": 2, "rush_2pt": 1}, dict(two_pt=1, rec_2pt=1), 2.0),
    ],
)
def test_each_extra_rule(rule, stats, expected):
    only = dict.fromkeys(DEFAULTS, 0.0) | rule  # isolate the rule under test
    assert _fp(only, **stats) == pytest.approx(expected)


def test_legacy_two_pt_profile_and_rows():
    old = normalize({"two_pt": 3.0})
    assert old["pass_2pt"] == old["rush_2pt"] == old["rec_2pt"] == 3.0
    # rows ingested before the split only carry two_pt: scored at the rush/rec rate
    assert _fp(HALF_PPR, two_pt=1) == pytest.approx(2.0)


def test_score_tolerates_rows_without_new_columns():
    from scoring.rules import score
    from tests.conftest import load_parquet

    stats = (
        load_parquet("player_week_stats.parquet")
        .head(50)
        .with_columns(pl.lit("WR").alias("position"))
    )
    assert score(stats, HALF_PPR)["fp"].null_count() == 0


def _k_or_def(rules, position, **stats):
    return stats_frame([stat_row("x", position, 2026, 1, **stats)], rules)["fp"][0]


def test_kicker_line_with_sleeper_defaults():
    # 2 short FGs (3 each), one 45-yarder (4), one 52-yarder (5), a miss (-1), 3 PATs (3), 1 missed PAT
    pts = _k_or_def(HALF_PPR, "K", fgm_20_29=1, fgm_30_39=1, fgm_40_49=1, fgm_50_59=1,
                    fgmiss=1, xpm=3, xpmiss=1)  # fmt: skip
    assert pts == pytest.approx(3 + 3 + 4 + 5 - 1 + 3 - 1)


def test_kicker_distance_scoring():
    rules = dict.fromkeys(DEFAULTS, 0.0) | {"fgm_yds": 0.1, "fgm": 1.0, "fgm_60p": 2.0}
    assert _k_or_def(rules, "K", fgm_30_39=1, fgm_60p=1, fgm_yds=95) == pytest.approx(9.5 + 2 + 2)


@pytest.mark.parametrize(
    "pts_allow, bracket_pts",
    [(0, 10), (1, 7), (6, 7), (7, 4), (13, 4), (14, 1), (20, 1), (21, 0), (27, 0), (28, -1),
     (34, -1), (35, -4), (52, -4)],
)  # fmt: skip
def test_points_allowed_brackets(pts_allow, bracket_pts):
    assert _k_or_def(HALF_PPR, "DEF", pts_allow=pts_allow, yds_allow=320) == bracket_pts


def test_defense_line_and_yards_brackets():
    rules = HALF_PPR | {"yds_allow_300_349": -1.0}
    pts = _k_or_def(rules, "DEF", def_sack=3, def_int=2, def_fum_rec=1, def_td=1, def_safe=1,
                    def_blk_kick=1, def_st_td=1, pts_allow=10, yds_allow=310)  # fmt: skip
    assert pts == pytest.approx(3 + 4 + 2 + 6 + 2 + 2 + 6 + 4 - 1)


def test_brackets_only_apply_to_recorded_defense_games():
    # a WR (or a DEF row without a score) never earns shutout points
    assert _k_or_def(HALF_PPR, "WR") == 0
    assert _k_or_def(HALF_PPR, "DEF", def_sack=2) == 2
