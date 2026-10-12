import polars as pl
import pytest

from projections.base import LeagueShape, ProjectionInputs
from projections.baseline import BaselineEngine
from projections.matchup import MatchupAdjusted
from scoring.rules import HALF_PPR
from signals.schedule import Schedule, fp_allowed_index, matchup_multiplier
from tests.builders import stat_row, stats_frame


def test_multiplier():
    idx = {("KC", "DEF"): 1.4, ("NYJ", "DEF"): 0.6}
    assert matchup_multiplier(idx, "KC", "DEF", 0.0) == 1.0
    assert matchup_multiplier(idx, "KC", "DEF", 1.0) == pytest.approx(1.4)
    assert matchup_multiplier(idx, "NYJ", "DEF", 0.5) == pytest.approx(0.8)
    assert matchup_multiplier(idx, None, "DEF", 1.0) == 1.0  # bye / unknown opponent
    assert matchup_multiplier(idx, "BUF", "DEF", 1.0) == 1.0  # no data → neutral


def test_index_covers_kickers_and_defenses():
    rows = [
        stat_row("sl:AAA", "DEF", 2026, 1, "AAA", opponent="BBB", def_sack=6),
        stat_row("sl:CCC", "DEF", 2026, 1, "CCC", opponent="DDD", def_sack=2),
        stat_row("k1", "K", 2026, 1, "AAA", opponent="BBB", xpm=4),
        stat_row("k2", "K", 2026, 1, "CCC", opponent="DDD", xpm=2),
    ]
    idx = fp_allowed_index(stats_frame(rows), 2026, 1)
    assert idx[("BBB", "DEF")] > 1 > idx[("DDD", "DEF")]  # BBB's offense is the easier matchup
    assert idx[("BBB", "K")] > 1 > idx[("DDD", "K")]


def _schedule(week_opponents):
    games = {}
    for (team, week), opp in week_opponents.items():
        games[(team, week)] = opp
        games[(opp, week)] = team
    return Schedule(2026, 18, games, {})


def test_wrapper_uses_only_history_and_this_weeks_opponent():
    # Two receivers, identical history; next week one faces the soft defense SOFT.
    rows = []
    for w in range(1, 5):
        rows += [
            stat_row("a", "WR", 2026, w, "AAA", opponent="X", rec_yds=80),
            stat_row("b", "WR", 2026, w, "BBB", opponent="Y", rec_yds=80),
            stat_row("z", "WR", 2026, w, "ZZZ", opponent="SOFT", rec_yds=200),  # SOFT leaks yards
            stat_row("y", "WR", 2026, w, "YYY", opponent="HARD", rec_yds=10),
        ]
    # a week-5 blowup against HARD must not leak into the week-5 projection
    rows.append(stat_row("y", "WR", 2026, 5, "YYY", opponent="HARD", rec_yds=400))
    stats = stats_frame(rows)
    hist = stats.filter(pl.col("week") < 5)
    players = pl.DataFrame(
        {"player_id": ["a", "b"], "position": ["WR", "WR"], "nfl_team": ["AAA", "BBB"],
         "injury_status": [None, None], "status": [None, None]}
    )  # fmt: skip
    sched = _schedule({("AAA", 5): "SOFT", ("BBB", 5): "HARD"})
    inp = ProjectionInputs(hist, players, sched, HALF_PPR, 2026, 5, LeagueShape())
    base = {r[0]: r[1] for r in BaselineEngine().per_game(inp).select("player_id", "ppg").rows()}
    adj = MatchupAdjusted(BaselineEngine(), {"WR": 1.0}).per_game(inp)
    got = {r[0]: r[1] for r in adj.select("player_id", "ppg").rows()}
    assert base["a"] == base["b"]
    assert got["a"] > base["a"] > got["b"]
    assert MatchupAdjusted(BaselineEngine(), {"WR": 0.0}).per_game(inp)["ppg"].to_list() == (
        BaselineEngine().per_game(inp)["ppg"].to_list()
    )
