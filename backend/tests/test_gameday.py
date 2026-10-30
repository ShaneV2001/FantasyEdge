"""Game-day alerts, kickoff locking and the injury-status change log."""

import dataclasses
from datetime import UTC, datetime, timedelta

import polars as pl

from ingest.run import status_changes
from signals import advisor as adv
from signals import gameday as gd
from signals import startsit as ss
from signals.schedule import build_schedule
from signals.team import RosMath
from tests.builders import schedule

SLOTS = ["QB", "RB", "WR", "FLEX"]
SUN = datetime(2026, 11, 1, 18, 0, tzinfo=UTC)  # 1:00 PM Eastern
SNF = datetime(2026, 11, 2, 1, 20, tzinfo=UTC)  # 8:20 PM Eastern


def P(name, pos, ppg, team="EAR", **kw):
    return {"name": name, "position": pos, "ppg": ppg, "nfl_team": team, **kw}


def _setup(players, starters, now=SUN - timedelta(hours=3)):
    sched = schedule(["EAR", "LATE"], weeks=17)
    sched = dataclasses.replace(sched, kickoffs={("EAR", 7): SUN, ("LATE", 7): SNF})
    math = RosMath(players, sched, 7, 17, SLOTS)
    locked = ss.locked_players(list(players), players, sched, 7, now)
    plan = ss.plan_week(math, players, list(players), starters, 7, locked)
    return plan, sched, now


def test_kickoff_locks_a_player_before_his_game_is_final():
    players = {"a": P("A", "RB", 10), "b": P("B", "RB", 10, team="LATE")}
    sched = dataclasses.replace(
        schedule(["EAR", "LATE"], weeks=17), kickoffs={("EAR", 7): SUN, ("LATE", 7): SNF}
    )
    assert ss.locked_players(list(players), players, sched, 7) == frozenset()  # no clock
    assert ss.locked_players(list(players), players, sched, 7, SUN - timedelta(minutes=1)) == set()
    assert ss.locked_players(list(players), players, sched, 7, SUN) == {"a"}
    assert ss.locked_players(list(players), players, sched, 7, SNF) == {"a", "b"}


def test_stale_results_dont_lock_everyone():
    """Days after the week's last game with no final scores, the local data is behind: fall back
    to locking only games known to be final."""
    players = {"a": P("A", "RB", 10)}
    sched = dataclasses.replace(
        schedule(["EAR", "LATE"], weeks=17), kickoffs={("EAR", 7): SUN, ("LATE", 7): SNF}
    )
    assert sched.live(7, SNF + timedelta(hours=11)) and not sched.live(7, SNF + timedelta(days=2))
    assert ss.locked_players(list(players), players, sched, 7, SNF + timedelta(days=2)) == set()
    assert not sched.live(8, SUN)  # no kickoffs known


def test_schedule_kickoffs_are_eastern_times():
    games = pl.DataFrame(
        {
            "season": [2026], "week": [7], "home_team": ["EAR"], "away_team": ["LATE"],
            "home_score": [None], "kickoff": [datetime(2026, 11, 1, 13, 0)],
        },
        schema_overrides={"home_score": pl.Int32},
    )  # fmt: skip
    s = build_schedule(games, 2026)
    assert s.kickoff("EAR", 7) == s.kickoff("LATE", 7) == SUN
    assert s.kickoff("EAR", 8) is None and s.kickoff(None, 7) is None


def test_questionable_starter_gets_a_pivot_and_a_late_hedge():
    players = {
        "qb": P("QB", "QB", 20),
        "q": P("Q Back", "RB", 15, team="LATE", injury_status="Questionable"),
        "early": P("Early Bench", "RB", 11),  # plays at 1:00, before the Q player's 8:20 game
        "late": P("Late Bench", "WR", 9, team="LATE"),  # can fill FLEX, plays at 8:20
        "wr": P("WR", "WR", 14),
        "rb": P("RB", "RB", 13),
    }
    plan, sched, now = _setup(players, ["qb", "rb", "wr", "q"])
    (a,) = gd.alerts(plan, players, sched, 7, now)
    assert (a.player_id, a.slot, a.severity, a.status) == ("q", "FLEX", "medium", "Questionable")
    assert a.pivot.player_id == "early" and a.late_pivot.player_id == "late"
    assert a.kickoff == SNF and "Q Back is listed Questionable." in a.reasons


def test_out_bye_and_practice_alerts_sorted_by_severity():
    players = {
        "qb": P("QB", "QB", 20, team="BYE"),
        "rb": P("RB", "RB", 13, injury_status="Out"),
        "wr": P("WR", "WR", 14),
        "flex": P("Flex", "WR", 12),
        "bench": P("Bench", "RB", 8),
        "hurt": P("Hurt Bench", "RB", 9, injury_status="Doubtful"),
    }
    sched = schedule(["EAR", "BYE"], weeks=17, byes={"BYE": 7})
    math = RosMath(players, sched, 7, 17, SLOTS)
    plan = ss.plan_week(math, players, list(players), ["qb", "rb", "wr", "flex"], 7)
    practice = {"wr": (None, "Did Not Participate In Practice")}
    alerts = gd.alerts(plan, players, sched, 7, SUN - timedelta(days=2), practice=practice)
    assert [(a.player_id, a.severity, a.status) for a in alerts] == [
        ("qb", "out", "Bye"), ("rb", "out", "Out"), ("wr", "low", "Missed practice"),
    ]  # fmt: skip
    assert alerts[0].pivot is None  # no other QB
    assert alerts[1].pivot.player_id == "bench"  # the Doubtful bench RB isn't a pivot


def test_official_report_can_raise_severity_and_free_agents_beat_a_thin_bench():
    players = {
        "qb": P("QB", "QB", 20),
        "rb": P("RB", "RB", 13, injury_status="Questionable"),
        "wr": P("WR", "WR", 14),
        "flex": P("Flex", "WR", 12),
        "bench": P("Bench", "RB", 3),
        "fa": P("Free Agent", "RB", 10),
    }
    plan, sched, now = _setup(
        {k: v for k, v in players.items() if k != "fa"}, ["qb", "rb", "wr", "flex"]
    )
    practice = {"rb": ("Doubtful", "Limited Participation in Practice")}
    (a,) = gd.alerts(plan, players, sched, 7, now, practice=practice, free_agents={"fa": 10.0})
    assert (a.severity, a.status) == ("high", "Doubtful")
    assert "Latest practice report: Limited." in a.reasons
    assert a.pivot.player_id == "bench" and a.free_agent.player_id == "fa"


def test_no_alert_once_his_game_kicked_off():
    players = {
        "qb": P("QB", "QB", 20),
        "rb": P("RB", "RB", 13, injury_status="Questionable"),
        "wr": P("WR", "WR", 14),
        "flex": P("Flex", "WR", 12),
    }
    plan, sched, now = _setup(players, ["qb", "rb", "wr", "flex"], now=SUN + timedelta(minutes=5))
    assert gd.alerts(plan, players, sched, 7, now) == []


def test_advisor_turns_alerts_into_cards_without_repeating_a_lineup_swap():
    alert = gd.Alert("rb", "RB", "out", "Out", 0.0, SUN, ["RB is listed Out."],
                     pivot=gd.Pivot("bench", 8.0, SUN))  # fmt: skip
    minor = gd.Alert("wr", "WR", "low", "Missed practice", 14.0, SUN, [])
    players = {"rb": P("RB", "RB", 13), "bench": P("Bench", "RB", 8), "wr": P("WR", "WR", 14)}
    math = RosMath(players, schedule(["EAR"], weeks=17), 7, 17, SLOTS)
    inp = adv.AdvisorInputs(
        my_team_id="A", rosters={"A": list(players)}, team_names={"A": "A"}, starters=[],
        players=players, profiles={}, byes=[], math=math, week=7, trade_deadline_week=None,
        trade_ideas=[], free_agents=None, regression_messages={}, alerts=[alert, minor],
    )  # fmt: skip
    (card,) = adv.alert_actions(inp)
    assert card.type == "Injury" and card.headline == "RB won't play"
    assert (
        card.player_ids == ["rb", "bench"]
        and "Best bench option: Bench (8.0 projected)." in card.reasons
    )
    assert adv.alert_actions(inp, skip={"rb"}) == []


def test_status_changes_are_logged_only_when_they_change():
    old = pl.DataFrame(
        {"player_id": ["a", "b", "c"], "injury_status": ["Questionable", None, "Out"]}
    )
    new = pl.DataFrame(
        {"player_id": ["a", "b", "c", "d"], "injury_status": ["Out", "Questionable", "Out", "Out"]}
    )
    rows = status_changes(old, new).sort("player_id")
    assert rows.select("player_id", "status").rows() == [("a", "Out"), ("b", "Questionable")]
    assert status_changes(pl.DataFrame(), new).is_empty()  # first refresh logs nothing
