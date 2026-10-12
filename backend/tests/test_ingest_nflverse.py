import polars as pl

from ingest.nflverse import (
    build_player_week_stats,
    pick_sixes_from_pbp,
    red_zone_from_pbp,
    transform_kicker_stats,
    transform_schedule,
    transform_team_defense,
)
from tests.conftest import load_parquet


def _pbp(rows):
    base = {
        "season_type": "REG",
        "season": 2026,
        "week": 1,
        "two_point_attempt": 0,
        "rush_attempt": 0,
        "pass_attempt": 0,
        "sack": 0,
        "rusher_player_id": None,
        "receiver_player_id": None,
        "rush_touchdown": 0,
        "pass_touchdown": 0,
    }
    return pl.DataFrame([base | r for r in rows])


def test_red_zone_counts_and_tds():
    pbp = _pbp(
        [
            {"yardline_100": 15, "rush_attempt": 1, "rusher_player_id": "A"},
            {"yardline_100": 3, "rush_attempt": 1, "rusher_player_id": "A", "rush_touchdown": 1},
            {"yardline_100": 45, "rush_attempt": 1, "rusher_player_id": "A", "rush_touchdown": 1},
            {"yardline_100": 10, "pass_attempt": 1, "receiver_player_id": "A", "pass_touchdown": 1},
            {"yardline_100": 8, "pass_attempt": 1, "receiver_player_id": "B"},
            # sacks and two-point tries are not opportunities
            {"yardline_100": 8, "pass_attempt": 1, "sack": 1, "receiver_player_id": "B"},
            {"yardline_100": 2, "rush_attempt": 1, "rusher_player_id": "A", "two_point_attempt": 1},
        ]
    )
    out = {r["player_id"]: r for r in red_zone_from_pbp(pbp).iter_rows(named=True)}
    assert out["A"]["rz_carries"] == 2
    assert out["A"]["gl_carries"] == 1
    assert out["A"]["rz_targets"] == 1
    assert out["A"]["rz_td"] == 2  # the 45-yard TD is not a red-zone TD
    assert out["B"]["rz_targets"] == 1 and out["B"]["rz_carries"] == 0


def test_schedule_has_one_bye_per_team():
    games = load_parquet("nfl_games.parquet").filter(pl.col("season") == 2025)
    assert set(games["home_team"]) == set(games["away_team"])
    assert "LAR" in set(games["home_team"]) and "LA" not in set(games["home_team"])
    weeks = sorted(games["week"].unique().to_list())
    assert weeks[0] == 1 and weeks[-1] == 18
    # every team plays 17 of 18 weeks
    for team in games["home_team"].unique().to_list():
        played = games.filter((pl.col("home_team") == team) | (pl.col("away_team") == team))
        assert played["week"].n_unique() == 17


def test_transform_schedule_filters_postseason():
    raw = pl.DataFrame(
        {
            "game_id": ["g1", "g2"],
            "season": [2026, 2026],
            "game_type": ["REG", "WC"],
            "week": [1, 19],
            "gameday": ["2026-09-10", "2027-01-10"],
            "gametime": ["20:20", "13:00"],
            "home_team": ["LA", "KC"],
            "away_team": ["SF", "BUF"],
            "home_score": [None, None],
            "away_score": [None, None],
        }
    )
    out = transform_schedule(raw)
    assert out.height == 1 and out["home_team"][0] == "LAR"


def test_pick_sixes_charge_the_passer():
    pbp = pl.DataFrame(
        {
            "season_type": ["REG", "REG", "REG", "POST"],
            "season": [2026] * 4,
            "week": [1, 1, 2, 19],
            "interception": [1, 1, 0, 1],
            "return_touchdown": [1, 0, 1, 1],
            "passer_player_id": ["Q", "Q", "Q", "Q"],
        }
    )
    out = pick_sixes_from_pbp(pbp)
    assert out.select("player_id", "week", "pass_int_td").rows() == [("Q", 1, 1)]


def test_weekly_stats_split_two_pointers_and_first_downs():
    raw = pl.DataFrame(
        {
            "season_type": ["REG"], "position": ["QB"], "player_id": ["Q"], "season": [2026],
            "week": [1], "game_id": ["g"], "team": ["LA"], "opponent_team": ["SF"],
            "attempts": [30], "completions": [20], "passing_yards": [250], "passing_tds": [2],
            "passing_interceptions": [1], "carries": [3], "rushing_yards": [12],
            "rushing_tds": [0], "targets": [0], "receptions": [0], "receiving_yards": [0],
            "receiving_tds": [0], "receiving_air_yards": [0], "target_share": [None],
            "air_yards_share": [None], "wopr": [None], "rushing_fumbles_lost": [0],
            "receiving_fumbles_lost": [0], "sack_fumbles_lost": [1], "passing_2pt_conversions": [1],
            "rushing_2pt_conversions": [1], "receiving_2pt_conversions": [0], "passing_epa": [1.0],
            "rushing_epa": [0.0], "receiving_epa": [0.0], "passing_first_downs": [11],
            "rushing_first_downs": [1], "receiving_first_downs": [0], "rushing_fumbles": [0],
            "receiving_fumbles": [0], "sack_fumbles": [2], "sacks_suffered": [3],
            "passing_air_yards": [310], "passing_yards_after_catch": [120],
            "receiving_yards_after_catch": [0],
        }
    )  # fmt: skip
    row = build_player_week_stats(raw, None, None).row(0, named=True)
    assert row["team"] == "LAR"
    assert (row["pass_2pt"], row["rush_2pt"], row["two_pt"]) == (1, 1, 2)
    assert (row["pass_fd"], row["rush_fd"], row["sacks_taken"], row["fumbles"]) == (11, 1, 3, 2)
    assert row["pass_int_td"] == 0
    assert (row["pass_air_yards"], row["pass_yac"], row["rec_yac"]) == (310, 120, 0)


def test_weekly_stats_without_yac_columns_are_null():
    raw = pl.DataFrame(
        {
            "season_type": ["REG"], "position": ["WR"], "player_id": ["W"], "season": [2026],
            "week": [1], "game_id": ["g"], "team": ["KC"], "opponent_team": ["LV"],
            "attempts": [0], "completions": [0], "passing_yards": [0], "passing_tds": [0],
            "passing_interceptions": [0], "carries": [0], "rushing_yards": [0],
            "rushing_tds": [0], "targets": [8], "receptions": [6], "receiving_yards": [70],
            "receiving_tds": [1], "receiving_air_yards": [60], "target_share": [0.25],
            "air_yards_share": [0.3], "wopr": [0.58], "rushing_fumbles_lost": [0],
            "receiving_fumbles_lost": [0], "sack_fumbles_lost": [0], "passing_2pt_conversions": [0],
            "rushing_2pt_conversions": [0], "receiving_2pt_conversions": [0], "passing_epa": [0.0],
            "rushing_epa": [0.0], "receiving_epa": [2.5],
        }
    )  # fmt: skip
    row = build_player_week_stats(raw, None, None).row(0, named=True)
    assert row["rec_yac"] is None and row["pass_yac"] is None and row["pass_air_yards"] is None


def test_kicker_transform_maps_sleeper_terms():
    raw = pl.DataFrame(
        {
            "season_type": ["REG", "REG"], "position": ["K", "WR"], "player_id": ["k1", "w1"],
            "season": [2026, 2026], "week": [3, 3], "game_id": ["g", "g"],
            "team": ["LA", "LA"], "opponent_team": ["SF", "SF"],
            "fg_made_40_49": [2, 0], "fg_made_60_": [1, 0], "fg_missed": [1, 0],
            "fg_made_distance": [152, 0], "pat_made": [3, 0], "pat_missed": [0, 0],
        }
    )  # fmt: skip
    out = transform_kicker_stats(raw)
    assert out.height == 1
    row = out.row(0, named=True)
    assert row["team"] == "LAR" and row["opponent"] == "SF"
    assert (row["fgm_40_49"], row["fgm_60p"], row["fgmiss"], row["fgm_yds"], row["xpm"]) == (
        2, 1, 1, 152, 3,
    )  # fmt: skip
    assert row["fgm_0_19"] == 0  # column absent in this release → 0


def test_team_defense_joins_opponent_score_and_yards():
    team = pl.DataFrame(
        {
            "season_type": ["REG", "REG"], "season": [2026, 2026], "week": [1, 1],
            "game_id": ["g1", "g1"], "team": ["LA", "SF"], "opponent_team": ["SF", "LA"],
            "def_sacks": [4, 1], "def_interceptions": [1, 0], "fumble_recovery_opp": [1, 0],
            "def_tds": [1, 0], "special_teams_tds": [0, 1], "def_safeties": [0, 0],
            "def_fg_blocks": [1, 0], "def_punt_blocks": [0, 0], "def_pat_blocks": [0, 0],
            "passing_yards": [250, 180], "sack_yards_lost": [5, 30], "rushing_yards": [120, 60],
        }
    )  # fmt: skip
    games = pl.DataFrame(
        {"season": [2026], "week": [1], "home_team": ["LAR"], "away_team": ["SF"],
         "home_score": [27], "away_score": [10]}
    )  # fmt: skip
    rows = {r["player_id"]: r for r in transform_team_defense(team, games).iter_rows(named=True)}
    rams = rows["sl:LAR"]
    assert rams["pts_allow"] == 10  # SF scored 10
    assert rams["yds_allow"] == 180 - 30 + 60  # SF's net yards
    assert (rams["def_sack"], rams["def_int"], rams["def_td"], rams["def_blk_kick"]) == (4, 1, 1, 1)
    assert rows["sl:SF"]["pts_allow"] == 27 and rows["sl:SF"]["def_st_td"] == 1
