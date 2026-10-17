"""Season-ending injuries and the user's own availability what-ifs."""

from ingest.sleeper import parse_players
from projections.base import (
    SEASON_OUT,
    availability,
    availability_note,
    injury_detail,
    resolve_return_week,
    weekly_points,
)
from signals import trade as tr
from signals import waivers as wv
from signals.targets import week_cells
from signals.team import RosMath
from tests.builders import schedule
from tests.conftest import load_json


def test_torn_acl_on_ir_ends_the_season():
    assert resolve_return_week("IR", "Inactive", "Knee - ACL", "Surgery", 7) == (SEASON_OUT, "rule")
    assert resolve_return_week("IR", None, "Knee - ACL + MCL", None, 7)[0] == SEASON_OUT
    assert resolve_return_week("PUP", None, "Achilles", "Surgery", 7)[0] == SEASON_OUT
    assert resolve_return_week("Out", None, "Shoulder", "Out for the season", 7)[0] == SEASON_OUT


def test_other_injuries_keep_the_designation_rules():
    assert resolve_return_week("IR", None, "Undisclosed", None, 7) == (None, None)
    assert resolve_return_week("IR", None, "Knee - MCL", "Sprain", 7) == (None, None)
    assert resolve_return_week("Questionable", None, "Knee - ACL", None, 7) == (None, None)
    # back on the field: the old ACL note stays on his record but no longer matters
    assert resolve_return_week(None, "Active", "Knee - ACL", "Surgery", 7) == (None, None)
    assert resolve_return_week(None, None, None, None, 7) == (None, None)


def test_the_users_what_if_wins():
    assert resolve_return_week(None, None, None, None, 7, override_season=True) == (
        SEASON_OUT,
        "override",
    )
    assert resolve_return_week("IR", None, "Knee - ACL", None, 7, override_week=12) == (
        12,
        "override",
    )
    # a return week that has already arrived no longer applies
    assert resolve_return_week("IR", None, "Undisclosed", None, 12, override_week=12) == (
        None,
        None,
    )


def test_availability_follows_the_return_week():
    assert availability("IR", None, 9, 7, return_week=12) == 0.0
    assert availability("IR", None, 12, 7, return_week=12) == 1.0
    assert availability("IR", None, 17, 7, return_week=SEASON_OUT) == 0.0
    # without one, IR still means the default weeks out
    assert availability("IR", None, 10, 7) == 0.0 and availability("IR", None, 11, 7) == 1.0
    sched = schedule(["AAA"], weeks=17)
    pts = weekly_points(10.0, "AAA", "IR", None, sched, 7, 17, return_week=SEASON_OUT)
    assert sum(pts.values()) == 0


def test_notes_say_why():
    assert injury_detail("Knee - ACL", "Surgery") == "Knee - ACL, surgery"
    assert injury_detail(None, None) is None
    note = availability_note(
        "IR", None, return_week=SEASON_OUT, source="rule", detail="Knee - ACL, surgery"
    )
    assert note == "Out for the season (Knee - ACL, surgery)"
    assert (
        availability_note("IR", None, return_week=12, source="override")
        == "Out until week 12 (your what-if)"
    )
    assert availability_note(None, None, return_week=SEASON_OUT, source="override") == (
        "Out for the season (your what-if)"
    )


def test_week_cells_and_ros_math_use_it():
    sched = schedule(["AAA"], weeks=17)
    p = {"name": "X", "position": "RB", "ppg": 14.0, "nfl_team": "AAA", "injury_status": "IR"}
    cells = week_cells({**p, "return_week": SEASON_OUT}, sched, {}, 0.0, 7, 17)
    assert sum(c.points for c in cells) == 0
    cells = week_cells({**p, "return_week": 15}, sched, {}, 0.0, 7, 17)
    assert [c.week for c in cells if c.points > 0] == [15, 16, 17]
    math = RosMath({"x": {**p, "return_week": SEASON_OUT}}, sched, 7, 17, ["RB"])
    assert math.ros_lineup_points(["x"]) == 0


def test_season_out_free_agents_never_reach_waivers():
    sched = schedule(["AAA"], weeks=17)
    P = lambda n, pos, ppg, **kw: {"name": n, "position": pos, "ppg": ppg, "nfl_team": "AAA", **kw}  # noqa: E731
    players = {
        "rb1": P("RB1", "RB", 10), "rb2": P("RB2", "RB", 4),
        "done": P("ACL guy", "RB", 15, injury_status="IR", return_week=SEASON_OUT),
        "back": P("Back later", "RB", 15, injury_status="IR", return_week=14),
    }  # fmt: skip
    math = RosMath(players, sched, 7, 17, ["RB", "RB"])
    picks = wv.rank_waivers(math, players, "A", ["rb1", "rb2"], ["done", "back"], tr.RosterRules())
    assert [w.player_id for w in picks] == ["back"]
    # counted only from week 14: (15 - 4) x 4 weeks
    assert picks[0].gain == 44.0


def test_parse_players_keeps_injury_details():
    df = parse_players(load_json("sleeper_players.json"))
    row = df.filter(df["sleeper_id"] == "5859").row(0, named=True)  # A.J. Brown, IR
    assert row["injury_status"] == "IR"
    assert row["injury_body_part"] == "Ankle" and row["injury_notes"] == "Sprain"
