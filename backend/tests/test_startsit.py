import dataclasses

import pytest

from signals import startsit as ss
from signals.team import RosMath
from tests.builders import schedule

SLOTS = ["QB", "RB", "WR", "FLEX"]


def P(name, pos, ppg, team="AAA"):
    return {"name": name, "position": pos, "ppg": ppg, "nfl_team": team}


@pytest.fixture
def players():
    return {
        "qb": P("QB", "QB", 20), "rb1": P("RB1", "RB", 15), "rb2": P("RB2", "RB", 9),
        "wr1": P("WR1", "WR", 14), "wr2": P("WR2", "WR", 12), "te": P("TE", "TE", 4),
    }  # fmt: skip


def test_real_lineup_vs_best(players):
    math = RosMath(players, schedule(["AAA"], weeks=17), 7, 17, SLOTS)
    plan = ss.plan_week(math, players, list(players), ["qb", "rb1", "wr1", "rb2"], 7)
    assert plan.current == ["qb", "rb1", "wr1", "rb2"]  # placed by fit_to_slots, in slot order
    assert plan.optimal == ["qb", "rb1", "wr1", "wr2"]  # WR2 (12) beats RB2 (9) in the FLEX
    assert plan.current_points == 58 and plan.optimal_points == 61
    assert plan.starters == {"qb", "rb1", "wr1", "wr2"}


def test_matchups_decide_this_week(players):
    sched = schedule(["AAA"], weeks=17)
    math = RosMath(players, sched, 7, 17, SLOTS, weekly={"rb2": {7: 16.0}, "wr2": {7: 8.0}})
    plan = ss.plan_week(math, players, list(players), ["qb", "rb1", "wr1", "wr2"], 7)
    assert plan.starters == {"qb", "rb1", "rb2", "wr1"} and plan.points["rb2"] == 16.0


def test_locked_starter_keeps_his_slot_and_locked_bench_stays_out(players):
    players = {
        **players,
        "rb2": {**players["rb2"], "nfl_team": "THU"},
        "wr2": {**players["wr2"], "nfl_team": "THU"},
    }
    sched = schedule(["AAA", "THU"], weeks=17)
    sched = dataclasses.replace(sched, completed=frozenset({("THU", 7)}))  # played Thursday
    math = RosMath(players, sched, 7, 17, SLOTS)
    locked = ss.locked_players(list(players), players, sched, 7)
    assert locked == {"rb2", "wr2"}
    plan = ss.plan_week(math, players, list(players), ["qb", "rb1", "wr1", "rb2"], 7, locked)
    assert plan.optimal[3] == "rb2"  # already played: keeps the FLEX, not swapped for the TE
    assert "wr2" not in plan.starters  # played from the bench: can't come in now
    assert plan.points["rb2"] == 0.0  # nothing left to score this week


def test_reserved_players_cant_start(players):
    math = RosMath(players, schedule(["AAA"], weeks=17), 7, 17, SLOTS)
    plan = ss.plan_week(math, players, list(players), [], 7, reserved={"wr2"})
    assert plan.current == [None, None, None, None]  # a manual team with no starters marked
    assert "wr2" not in plan.starters and plan.optimal[3] == "rb2"


def test_a_bye_leaves_the_slot_empty(players):
    players = {**players, "qb": {**players["qb"], "nfl_team": "BYE"}}
    sched = schedule(["AAA", "BYE"], weeks=17, byes={"BYE": 7})
    math = RosMath(players, sched, 7, 17, SLOTS)
    plan = ss.plan_week(math, players, list(players), ["qb", "rb1", "wr1", "wr2"], 7)
    assert plan.current[0] == "qb" and plan.optimal[0] is None  # nobody else can play QB
    assert plan.optimal_points == plan.current_points
