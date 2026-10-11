import polars as pl
import pytest

from ingest.nflverse import STATS_COLUMNS
from models.backtest import metrics, metrics_json, walk_forward
from projections.baseline import BaselineEngine
from projections.simple import Last3Engine, SeasonPpgEngine
from scoring.rules import HALF_PPR
from tests.builders import schedule, stat_row

TEAMS = ["AAA", "BBB"]


def _frame(rows):
    return pl.DataFrame(rows, infer_schema_length=None).select([*STATS_COLUMNS, "position"])


def _season_rows():
    # 2025: steady 10-point receiver. 2026: 10 points weeks 1-4, then 100 from week 5 on.
    rows = [stat_row("A", "WR", 2025, w, "AAA", rec_yds=100) for w in range(1, 18)]
    rows += [stat_row("A", "WR", 2026, w, "AAA", rec_yds=100) for w in range(1, 5)]
    rows += [stat_row("A", "WR", 2026, w, "AAA", rec_yds=1000) for w in range(5, 10)]
    rows += [stat_row("B", "WR", 2026, w, "BBB", rec_yds=50) for w in range(1, 10)]
    return _frame(rows)


@pytest.fixture
def schedules():
    return {2026: schedule(TEAMS, weeks=18)}


@pytest.mark.parametrize("engine", [BaselineEngine(), SeasonPpgEngine(), Last3Engine()])
def test_projections_never_see_the_target_week(engine, schedules):
    preds = walk_forward(engine, _season_rows(), schedules, HALF_PPR, [2026], weeks=[5])
    a = preds.filter(pl.col("player_id") == "A").row(0, named=True)
    assert a["actual_1"] == pytest.approx(100.0)
    assert a["ppg"] < 20  # only the 10-point history was visible


def test_actuals_cover_played_games_in_the_horizon(schedules):
    preds = walk_forward(Last3Engine(), _season_rows(), schedules, HALF_PPR, [2026], weeks=[3])
    a = preds.filter(pl.col("player_id") == "A").row(0, named=True)
    # weeks 3,4 score 10 and weeks 5,6 score 100
    assert a["actual_4"] == pytest.approx(55.0)
    assert a["season"] == 2026 and a["week"] == 3 and a["engine"] == "last3"


def test_players_without_history_or_without_a_game_are_not_scored(schedules):
    rows = _season_rows().vstack(_frame([stat_row("C", "WR", 2026, 5, "AAA", rec_yds=70)]))
    preds = walk_forward(BaselineEngine(), rows, schedules, HALF_PPR, [2026], weeks=[5, 12])
    assert "C" not in preds["player_id"].to_list()  # first game is the target week
    assert preds["week"].unique().to_list() == [5]  # nobody played week 12


def test_metrics_by_hand():
    preds = pl.DataFrame(
        {
            "position": ["WR"] * 5 + ["RB"],
            "season": [2026] * 6,
            "week": [1] * 6,
            "ppg": [10.0, 8.0, 6.0, 4.0, 2.0, 5.0],
            "p10": [5.0, 4.0, 3.0, 2.0, 1.0, 1.0],
            "p90": [15.0, 12.0, 9.0, 6.0, 3.0, 6.0],
            "actual_1": [12.0, 9.0, 10.0, 3.0, 0.0, 9.0],
            "actual_4": [10.0, 8.0, 6.0, 4.0, 2.0, 5.0],
            "relevant": [True, True, True, False, False, True],
        }
    )
    m = {r["position"]: r for r in metrics(preds).iter_rows(named=True)}
    wr = m["WR"]
    assert wr["n"] == 5
    assert wr["mae_1"] == pytest.approx((2 + 1 + 4 + 1 + 2) / 5)
    assert wr["mae_4"] == 0
    assert wr["coverage"] == pytest.approx(3 / 5)  # 10 > 9 and 0 < 1 fall outside
    assert wr["spearman"] == pytest.approx(0.9)  # ranks 1,3,2,4,5 vs 1..5
    assert m["RB"]["spearman"] is None  # a 1-player group gives no rank correlation
    assert m["ALL"]["n"] == 6
    rel = {r["position"]: r for r in metrics(preds, relevant_only=True).iter_rows(named=True)}
    assert rel["WR"]["n"] == 3
    assert set(metrics_json(preds)) == {"all", "relevant"}
