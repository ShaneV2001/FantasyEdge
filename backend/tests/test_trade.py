import pytest

from signals import advisor as adv
from signals import trade as tr
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
        players={k: v | {"signal": "sell"} for k, v in players.items()},
        profiles=team_profiles(rosters, players, SLOTS), byes=[], math=math, week=12,
        trade_deadline_week=11, trade_ideas=ideas, free_agents=None, regression_messages={},
    )  # fmt: skip
    feed = adv.build_feed(inp)
    assert not [a for a in feed if a.type in ("Trade", "Sell", "Buy")]
    inp.week = 10
    feed = adv.build_feed(inp)
    assert any(a.type == "Trade" for a in feed) and any(a.type == "Sell" for a in feed)
    assert all(a.urgency == "before_deadline" for a in feed if a.type in ("Trade", "Sell", "Buy"))


def test_trade_verdict_lines_are_parameters(league):
    players, rosters, math = league
    args = (math, players, ("A", rosters["A"]), ("B", rosters["B"]), ["a_rb4"], ["b_wr4"])
    assert evaluate(*args).verdict == "accept"  # A gains 78 ROS points (see test above)
    assert evaluate(*args, accept_gain=100.0, lean_gain=50.0).verdict == "lean_accept"
    assert evaluate(*args, accept_gain=1000.0, lean_gain=999.0).verdict == "neutral"


# ───────── roster spots, byes, paging, finder ─────────


def test_active_limit_counts_starters_and_bench_only():
    assert tr.active_limit(["QB", "RB", "FLEX", "BN", "BN", "IR", "TAXI"]) == 5
    assert tr.active_limit(["QB", "RB"]) is None  # no bench listed: no limit modelled


def test_two_for_one_forces_the_cheapest_drop(league):
    players, rosters, math = league
    rules = tr.RosterRules(active_limit=7)  # both teams are full at 7
    ev = evaluate(
        math, players, ("A", rosters["A"]), ("B", rosters["B"]),
        ["a_rb4"], ["b_wr3", "b_wr4"], rules=rules,
    )  # fmt: skip
    assert ev.me.drops == ["a_wr2"]  # benched after the trade, lowest value: costs no lineup points
    assert not set(ev.me.drops) & {"b_wr3", "b_wr4"}  # never the players just acquired
    assert ev.partner.drops == []  # B gives two, gets one
    assert any("drop A WR2" in r for r in ev.reasons)
    # the release counts against the deal
    assert ev.me.model_value_out == pytest.approx(
        players["a_rb4"]["ros_value_par"] + players["a_wr2"]["ros_value_par"]
    )


def test_reserved_players_use_ir_spots_until_they_run_out(league):
    players, rosters, math = league
    trade = (math, players, ("A", rosters["A"]), ("B", rosters["B"]), ["a_rb4"], ["b_wr3", "b_wr4"])
    # a_wr2 sits in A's one IR spot, so A has an open active spot: no drop
    ev = evaluate(
        *trade, rules=tr.RosterRules(active_limit=7, reserved=frozenset({"a_wr2"}), reserve_slots=1)
    )
    assert ev.me.drops == []
    # no IR spot for him: he uses an active spot after all, so A must drop someone (never him: he's injured)
    ev = evaluate(
        *trade, rules=tr.RosterRules(active_limit=6, reserved=frozenset({"a_wr2"}), reserve_slots=0)
    )
    # (A is already 1 over at 7 of 6; only the extra incoming player forces a release)
    assert len(ev.me.drops) == 1 and "a_wr2" not in ev.me.drops


def test_injured_player_received_needs_an_ir_spot(league):
    players, rosters, math = league
    # b_wr4 is on B's IR; A's single IR spot is already used by a_wr2 -> b_wr4 takes an active spot
    rules = tr.RosterRules(active_limit=6, reserved=frozenset({"a_wr2", "b_wr4"}), reserve_slots=1)
    ev = evaluate(
        math, players, ("A", rosters["A"]), ("B", rosters["B"]), ["a_rb4"], ["b_wr4"], rules=rules
    )
    assert ev.me.drops == []  # one in, one out: same number of active players
    ev = evaluate(
        math, players, ("A", rosters["A"]), ("B", rosters["B"]), [], ["b_wr4"], rules=rules
    )
    assert len(ev.me.drops) == 1  # nothing out, and his IR spot is taken: someone must go
    assert ev.partner.drops == []


def test_trade_that_creates_a_bye_hole_is_flagged(league):
    players, rosters, _ = league
    players = players | {"b_qb2": P("B QB2", "QB", 19, team="ZZZ")}  # his team is off in week 9
    rosters = rosters | {"B": rosters["B"] + ["b_qb2"]}
    math = RosMath(players, schedule(["AAA", "ZZZ"], weeks=17, byes={"ZZZ": 9}), 5, 17, SLOTS)
    viable = {"QB": 10.0, "RB": 5.0, "WR": 5.0, "TE": 5.0}
    ev = evaluate(
        math, players, ("A", rosters["A"]), ("B", rosters["B"]),
        ["a_qb"], ["b_qb2"], viable_ppg=viable,
    )  # fmt: skip
    assert ev.me.new_short_weeks == [9]  # A's only QB would now be on bye in week 9
    assert any("Leaves your lineup short in week 9" in r for r in ev.reasons)
    assert ev.partner.new_short_weeks == []  # B keeps b_qb for week 9
    week9 = next(w for w in ev.me.weekly if w.week == 9)
    assert week9.after < week9.before


def test_ideas_never_leave_a_team_short(league):
    players, rosters, math = league
    viable = {"QB": 10.0, "RB": 5.0, "WR": 5.0, "TE": 5.0}
    cands = tr.candidate_trades(
        math, players, ("A", rosters["A"]), {"B": rosters["B"]},
        viable_ppg=viable, rules=tr.RosterRules(active_limit=7),
    )  # fmt: skip
    assert cands
    for ev in cands:
        assert not ev.me.new_short_weeks and not ev.partner.new_short_weeks
        assert ev.me.lineup_delta >= 1 and ev.partner.lineup_delta >= 1
        assert len(ev.me.weekly) == 13 and len(ev.partner.weekly) == 13


def test_pages_show_new_ideas(league):
    players, rosters, math = league
    cands = tr.candidate_trades(math, players, ("A", rosters["A"]), {"B": rosters["B"]})
    seen = set()
    page, more = 0, True
    while more and page < 20:
        ideas, more = tr.paginate(cands, page, limit=2)
        keys = {ev.key for ev in ideas}
        assert not keys & seen  # nothing repeats across pages
        seen |= keys
        page += 1
    assert seen == {ev.key for ev in cands}  # every idea is reachable
    assert tr.paginate(cands, 99, limit=2) == ([], False)


def test_finder_looks_for_the_position_you_want(league):
    players, rosters, math = league
    found = tr.find_for(
        math, players, ("A", rosters["A"]), {"B": rosters["B"]}, ["a_rb3", "a_rb4"], "WR", 1,
        rules=tr.RosterRules(active_limit=7),
    )  # fmt: skip
    assert found
    for ev in found:
        assert ev.me.gives == ["a_rb3", "a_rb4"]
        assert all(players[p]["position"] == "WR" for p in ev.me.receives)
        assert all(p in rosters["B"] for p in ev.me.receives)
        assert ev.me.lineup_delta > 0
    order = [ev.partner_accepts for ev in found]
    assert order == sorted(order, key=lambda a: not a)  # deals they'd accept come first
    pairs = tr.find_for(math, players, ("A", rosters["A"]), {"B": rosters["B"]}, ["a_rb1"], "WR", 2)
    assert all(len(ev.me.receives) == 2 for ev in pairs)
    with pytest.raises(ValueError):
        tr.find_for(math, players, ("A", rosters["A"]), {"B": rosters["B"]}, ["b_wr1"], "RB")
