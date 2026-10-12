import pytest

from signals.schedule import Schedule
from signals.targets import all_cells, rank_targets, week_cells


def _schedule():
    # weeks 5-7: AAA plays SOFT, HARD, then has a bye; BBB plays HARD, SOFT, SOFT
    games = {("AAA", 5): "SOFT", ("AAA", 6): "HARD", ("BBB", 5): "HARD", ("BBB", 6): "SOFT",
             ("BBB", 7): "SOFT"}  # fmt: skip
    games |= {(o, w): t for (t, w), o in list(games.items())}
    return Schedule(2026, 18, games, {"AAA": 7})


INDEX = {("SOFT", "DEF"): 1.5, ("HARD", "DEF"): 0.5}


def P(team, ppg, pos="DEF", **kw):
    return {"nfl_team": team, "position": pos, "ppg": ppg} | kw


def test_cells_apply_matchup_bye_and_injury():
    cells = week_cells(P("AAA", 10), _schedule(), INDEX, 1.0, 5, 7)
    assert [(c.week, c.opponent, c.points, c.neutral) for c in cells] == [
        (5, "SOFT", 15.0, 10.0), (6, "HARD", 5.0, 10.0), (7, None, 0.0, 0.0),
    ]  # fmt: skip
    out = week_cells(P("AAA", 10, injury_status="Out"), _schedule(), INDEX, 1.0, 5, 6)
    assert out[0].points == 0 and out[1].points == 5.0  # out this week only


def test_rankings_per_week_and_rest_of_season():
    players = {"a": P("AAA", 10), "b": P("BBB", 10)}
    cells = all_cells(players, _schedule(), INDEX, {"DEF": 1.0}, 5, 7)
    r = rank_targets(players, cells, 5, 7, positions=["DEF"])["DEF"]
    assert [x.player_id for x in r["weekly"][5]] == ["a", "b"]
    assert [x.player_id for x in r["weekly"][6]] == ["b", "a"]
    assert [x.player_id for x in r["weekly"][7]] == ["b"]  # AAA is on bye
    ros = {x.player_id: x for x in r["ros"]}
    assert ros["b"].points == pytest.approx(5 + 15 + 15) and ros["b"].games == 3
    assert ros["a"].points == pytest.approx(15 + 5) and ros["a"].schedule_delta == 0
    assert ros["b"].schedule_delta == pytest.approx(35 - 30)
    assert r["ros"][0].player_id == "b"


def test_alpha_zero_ignores_schedule_and_top_n_caps():
    players = {f"p{i}": P("BBB", float(i)) for i in range(15)}
    cells = all_cells(players, _schedule(), INDEX, {"DEF": 0.0}, 5, 6)
    r = rank_targets(players, cells, 5, 6, positions=["DEF"])["DEF"]
    assert len(r["ros"]) == 10 and r["ros"][0].player_id == "p14"
    assert all(x.schedule_delta == 0 for x in r["ros"])
