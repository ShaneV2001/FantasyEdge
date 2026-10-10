import polars as pl

from ingest.nflverse import red_zone_from_pbp, transform_schedule
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
