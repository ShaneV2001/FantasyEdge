from app.user_settings import UserSettings
from projections.base import DEFAULT_INJURY, InjuryAssumptions, availability, availability_note
from signals.targets import week_cells
from signals.team import RosMath
from tests.builders import schedule


def test_defaults_unchanged():
    assert availability("Questionable", None, 5, 5) == 0.85
    assert availability("Doubtful", None, 5, 5) == 0.25
    assert availability("Out", None, 5, 5) == 0.0
    assert availability(None, "IR", 8, 5) == 0.0 and availability(None, "IR", 9, 5) == 1.0
    assert availability_note("Questionable", None) == "Questionable this week (85% chance-weighted)"


def test_custom_assumptions():
    inj = InjuryAssumptions(questionable=0.5, doubtful=0.1, ir_weeks=1)
    assert availability("Questionable", None, 5, 5, inj) == 0.5
    assert availability("Questionable", None, 6, 5, inj) == 1.0  # only this week
    assert availability("Doubtful", None, 5, 5, inj) == 0.1
    assert availability(None, "IR", 5, 5, inj) == 0.0 and availability(None, "IR", 6, 5, inj) == 1.0
    assert (
        availability_note("Questionable", None, inj)
        == "Questionable this week (50% chance-weighted)"
    )
    assert availability_note(None, "IR", inj) == "On IR: assumed out 1 more weeks"


def test_user_settings_map_to_assumptions():
    s = UserSettings(play_chance_questionable=0.6, play_chance_doubtful=0.2, ir_weeks_out=3)
    assert s.injury == InjuryAssumptions(0.6, 0.2, 3)
    assert UserSettings().injury == DEFAULT_INJURY


def test_cells_and_ros_math_use_the_assumptions():
    sched = schedule(["AAA", "BBB"], weeks=17)
    p = {"nfl_team": "AAA", "position": "WR", "ppg": 10.0, "injury_status": "Questionable"}
    inj = InjuryAssumptions(questionable=0.5)
    assert week_cells(p, sched, {}, 0.0, 5, 5)[0].points == 8.5
    assert week_cells(p, sched, {}, 0.0, 5, 5, inj)[0].points == 5.0
    math = RosMath({"x": p}, sched, 5, 5, ["WR"], inj=inj)
    assert math.week_points("x")[5] == 5.0
