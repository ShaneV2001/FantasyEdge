import pytest

from signals import advisor as adv
from signals.team import RosMath, team_profiles
from signals.trade import evaluate, suggest
from tests.builders import schedule

SLOTS = ["QB", "RB", "RB", "WR", "WR", "FLEX"]


def P(name, pos, ppg, team="AAA", market=None, par=None):
    return {
        "name": name,
        "position": pos,
        "ppg": ppg,
        "nfl_team": team,
        "market_value": market if market is not None else ppg * 300,
        "ros_value_par": par if par is not None else ppg * 5,
        "bye_week": None,
    }


@pytest.fixture
def league():
    players = {
        # Team A: RB-rich, WR-poor
        "a_qb": P("A QB", "QB", 18), "a_rb1": P("A RB1", "RB", 16), "a_rb2": P("A RB2", "RB", 14),
        "a_rb3": P("A RB3", "RB", 13), "a_rb4": P("A RB4", "RB", 12),
        "a_wr1": P("A WR1", "WR", 9), "a_wr2": P("A WR2", "WR", 6),
        # Team B: WR-rich, RB-poor
        "b_qb": P("B QB", "QB", 18), "b_rb1": P("B RB1", "RB", 8), "b_rb2": P("B RB2", "RB", 5),
        "b_wr1": P("B WR1", "WR", 16), "b_wr2": P("B WR2", "WR", 14), "b_wr3": P("B WR3", "WR", 13),
        "b_wr4": P("B WR4", "WR", 12),
    }  # fmt: skip
    rosters = {
        "A": [p for p in players if p.startswith("a_")],
        "B": [p for p in players if p.startswith("b_")],
    }
    math = RosMath(players, schedule(["AAA"], weeks=17), 5, 17, SLOTS)
    return players, rosters, math


def test_evaluate_is_consistent_for_both_sides(league):
    players, rosters, math = league
    ev = evaluate(math, players, ("A", rosters["A"]), ("B", rosters["B"]), ["a_rb4"], ["b_wr4"])
    # Both swap a bench surplus player for a starter at their weak spot; 13 weeks remain (5..17).
    # A: WR slots 9+6 -> 12+9 (+6/wk). B: RB slots 8+5 -> 12+8 (+7/wk).
    assert ev.me.lineup_delta == pytest.approx(6 * 13)
    assert ev.partner.lineup_delta == pytest.approx(7 * 13)
    assert ev.me.gives == ev.partner.receives == ["a_rb4"]
    assert ev.verdict == "accept"
    assert any("starting lineup gains" in r for r in ev.reasons)


def test_evaluate_rejects_players_not_owned(league):
    players, rosters, math = league
    with pytest.raises(ValueError):
        evaluate(math, players, ("A", rosters["A"]), ("B", rosters["B"]), ["b_wr1"], ["b_wr3"])


def test_bad_trade_is_declined(league):
    players, rosters, math = league
    ev = evaluate(math, players, ("A", rosters["A"]), ("B", rosters["B"]), ["a_rb1"], ["b_rb2"])
    assert ev.verdict == "decline" and ev.me.lineup_delta < 0


def test_suggest_only_returns_mutual_gains(league):
    players, rosters, math = league
    ideas = suggest(math, players, ("A", rosters["A"]), {"B": rosters["B"]})
    assert ideas
    for ev in ideas:
        assert ev.me.lineup_delta > 0 and ev.partner.lineup_delta > 0
    assert any(set(ev.me.gives) & {"a_rb3", "a_rb4"} for ev in ideas)


def test_suggest_respects_market_band(league):
    players, rosters, math = league
    players = {k: dict(v) for k, v in players.items()}
    for pid in ("b_wr1", "b_wr2", "b_wr3", "b_wr4"):
        players[pid]["market_value"] = 99999  # far too expensive for anything A has
    ideas = suggest(
        math.__class__(players, math.schedule, 5, 17, SLOTS),
        players,
        ("A", rosters["A"]),
        {"B": rosters["B"]},
    )
    assert not any(set(ev.me.receives) & {"b_wr1", "b_wr2", "b_wr3", "b_wr4"} for ev in ideas)


def test_team_profiles_find_needs_and_surplus(league):
    players, rosters, _ = league
    profs = team_profiles(rosters, players, SLOTS)
    assert "RB" in profs["A"].surplus and "WR" in profs["A"].needs
    assert profs["A"].grades["RB"].grade in ("A", "B")


def test_trade_advice_hidden_after_deadline(league):
    players, rosters, math = league
    ideas = suggest(math, players, ("A", rosters["A"]), {"B": rosters["B"]})
    inp = adv.AdvisorInputs(
        my_team_id="A", rosters=rosters, team_names={"A": "A", "B": "B"}, starters=[],
        players={k: v | {"regression_score": -3.0} for k, v in players.items()},
        profiles=team_profiles(rosters, players, SLOTS), byes=[], math=math, week=12,
        trade_deadline_week=11, trade_ideas=ideas, free_agents=None, regression_messages={},
    )  # fmt: skip
    feed = adv.build_feed(inp)
    assert not [a for a in feed if a.type in ("Trade", "Sell", "Buy")]
    inp.week = 10
    feed = adv.build_feed(inp)
    assert any(a.type == "Trade" for a in feed) and any(a.type == "Sell" for a in feed)
    assert all(a.urgency == "before_deadline" for a in feed if a.type in ("Trade", "Sell", "Buy"))
