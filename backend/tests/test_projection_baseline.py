import polars as pl
import pytest

from projections.base import LeagueShape, ProjectionInputs, replacement_ranks, run
from projections.baseline import BaselineEngine, history_before
from scoring.rules import HALF_PPR
from tests.builders import schedule, stat_row, stats_frame


def _players(rows):
    return pl.DataFrame(
        rows,
        schema={
            "player_id": pl.Utf8,
            "position": pl.Utf8,
            "nfl_team": pl.Utf8,
            "injury_status": pl.Utf8,
            "status": pl.Utf8,
        },
        orient="row",
    )


def _wr_games(pid, team, season, weeks, rec_yds):
    return [
        stat_row(pid, "WR", season, w, team, targets=8, receptions=5, rec_yds=y)
        for w, y in zip(weeks, rec_yds, strict=True)
    ]


@pytest.fixture
def inputs():
    rows = _wr_games("A", "AAA", 2025, range(1, 18), [60] * 17)
    rows += _wr_games("A", "AAA", 2026, [1, 2, 3, 4, 5, 6], [50, 50, 50, 100, 100, 100])
    rows += _wr_games("B", "BBB", 2026, [1, 2, 3, 4, 5, 6], [40] * 6)
    rows += [
        stat_row("A", "WR", 2026, 9, "AAA", receptions=20, rec_yds=400)
    ]  # future: must be ignored
    players = _players(
        [("A", "WR", "AAA", None, "Active"), ("B", "WR", "BBB", "IR", "Injured Reserve"),
         ("K1", "K", "AAA", None, "Active")]
    )  # fmt: skip
    sched = schedule(["AAA", "BBB"], byes={"AAA": 10, "BBB": 7}, completed_through=6)
    return ProjectionInputs(
        stats_frame(rows), players, sched, HALF_PPR, 2026, 7, LeagueShape(num_teams=2, last_week=17)
    )


def test_history_excludes_future_weeks(inputs):
    h = history_before(inputs.stats, 2026, 7)
    assert h.filter((pl.col("season") == 2026) & (pl.col("week") > 7)).is_empty()


def test_weighted_ppg_formula(inputs):
    df = BaselineEngine().per_game(inputs)
    a = df.filter(pl.col("player_id") == "A").row(0, named=True)
    # L3 = 2.5 + 10 = 12.5 ; season (6 games, no shrink) = mean(7.5x3, 12.5x3) = 10
    assert a["l3_ppg"] == pytest.approx(12.5)
    assert a["season_ppg"] == pytest.approx(10.0)
    assert a["ppg"] == pytest.approx(0.5 * 12.5 + 0.3 * 10 + 0.2 * a["usage_ppg"], abs=0.02)
    assert a["p10"] < a["ppg"] < a["p90"]


def test_ros_skips_future_bye(inputs):
    df = run(BaselineEngine(), inputs)
    a = df.filter(pl.col("player_id") == "A").row(0, named=True)
    # weeks 7..17 = 11 weeks, minus the week-10 bye
    assert a["games_remaining"] == 10
    assert a["proj_ros_points"] == pytest.approx(a["ppg"] * 10, abs=0.05)
    assert a["bye_week"] == 10 and a["bye_upcoming"]


def test_ir_player_misses_weeks_and_k_gets_default(inputs):
    df = run(BaselineEngine(), inputs)
    b = df.filter(pl.col("player_id") == "B").row(0, named=True)
    # IR → out weeks 7-10; BBB bye (wk 7) already inside that window → plays 11..17
    assert b["games_remaining"] == 7
    assert "IR" in b["availability_note"]
    k = df.filter(pl.col("player_id") == "K1").row(0, named=True)
    assert k["ppg"] == 8.0 and k["method"] == "default"


def test_replacement_ranks_count_flex_shares():
    ranks = replacement_ranks(
        LeagueShape(10, ("QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "SUPER_FLEX", "BN"))
    )
    # QB: (1 + 0.9 SFLEX) x 10 = 19 starters -> replacement is the 20th QB
    assert ranks["QB"] == 20
    assert ranks["RB"] == 26  # (2 + 0.45 + 0.05) x 10 = 25 starters
    assert ranks["TE"] == 12  # (1 + 0.10) x 10 = 11 starters
    assert "K" not in ranks
