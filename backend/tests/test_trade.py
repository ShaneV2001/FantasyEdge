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


def test_acquire_for_builds_packages_for_one_target(league):
    players, rosters, math = league
    found = tr.acquire_for(
        math, players, ("A", rosters["A"]), ("B", rosters["B"]), "b_wr1",
        rules=tr.RosterRules(active_limit=7),
    )  # fmt: skip
    assert found
    sizes = set()
    for ev in found:
        assert ev.me.receives == ["b_wr1"]  # always the target, nothing else
        assert set(ev.me.gives) <= set(rosters["A"]) and 1 <= len(ev.me.gives) <= 2
        assert ev.me.lineup_delta > 0
        sizes.add(len(ev.me.gives))
    assert sizes == {1, 2}  # 1-for-1 and 2-for-1 packages both considered
    order = [ev.partner_accepts for ev in found]
    assert order == sorted(order, key=lambda a: not a)
    with pytest.raises(ValueError):
        tr.acquire_for(math, players, ("A", rosters["A"]), ("B", rosters["B"]), "a_rb1")


def test_shopping_one_player(league):
    players, rosters, math = league
    found = tr.find_for(math, players, ("A", rosters["A"]), {"B": rosters["B"]}, ["a_rb4"], "ANY")
    assert found and all(ev.me.gives == ["a_rb4"] for ev in found)


def test_shortlists_keep_deals_both_teams_like(league):
    """Even when only one package per size gets the full evaluation, it's a mutually good one if
    any exists (it used to be whichever helped *you* most, which the other team usually hates)."""
    players, rosters, math = league
    full = tr.acquire_for(
        math, players, ("A", rosters["A"]), ("B", rosters["B"]), "b_wr1", shortlist=50
    )
    assert any(ev.partner_accepts for ev in full)  # a deal B likes exists
    tight = tr.acquire_for(
        math, players, ("A", rosters["A"]), ("B", rosters["B"]), "b_wr1", shortlist=1
    )
    assert tight and tight[0].partner_accepts
    assert tr._shortlist_key(10, 2) < tr._shortlist_key(30, -5)  # mutual beats one-sided
    assert tr._shortlist_key(10, 8) < tr._shortlist_key(9, 8)  # then the better deal


# ───────── who gets cut when a roster overflows ─────────

DROP_SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"]


def _drop_league(**extra):
    players = {
        "qb": P("QB1", "QB", 20, market=4000), "rb1": P("RB1", "RB", 16, market=8000),
        "rb2": P("RB2", "RB", 14, market=7000), "wr1": P("WR1", "WR", 15, market=8000),
        "wr2": P("WR2", "WR", 13, market=6000), "te": P("TE1", "TE", 10, market=3000),
        "flex": P("RB3", "RB", 12, market=5000), "k": P("K1", "K", 8, market=None),
        "def": P("DEF1", "DEF", 7, market=None),
        # bench: a young receiver the market loves vs a waiver-level back, both barely play. One
        # backup each at RB and WR (the flex goes to RB3), so neither is surplus depth
        "ladd": P("Ladd", "WR", 6, market=5500), "scrub": P("Scrub", "RB", 6.5, market=300),
        **extra,
    }  # fmt: skip
    math = RosMath(players, schedule(["AAA"], weeks=17), 7, 17, DROP_SLOTS)
    return players, math


def test_valuable_bench_player_outlasts_waiver_fodder():
    players, math = _drop_league()
    (drop,) = tr.choose_drops(math, players, list(players), set(), 1)
    assert drop.player_id == "scrub"  # the old rule cut by lineup points and model value
    assert drop.reason == "lowest market value on your bench"


def test_an_extra_kicker_or_defense_goes_first():
    players, math = _drop_league(
        k2=P("K2", "K", 7.5, market=None), def2=P("DEF2", "DEF", 6, market=None)
    )
    drops = tr.choose_drops(math, players, list(players), set(), 2)
    assert {(d.player_id, d.reason) for d in drops} == {
        ("k2", "extra kicker"),
        ("def2", "extra defense"),
    }  # both extras go before the valuable bench receiver


@pytest.mark.parametrize("def2_ppg", [5.0, 3.0])  # covers a bye for real points, or a few
def test_a_backup_defense_covering_a_bye_outlasts_a_free_4th_qb(def2_ppg):
    # the starting D/ST is on bye this week, so the second one plays now; the 4th QB never will
    players, _ = _drop_league(
        **{"def": P("DEF1", "DEF", 7, team="BYE", market=None)},
        def2=P("DEF2", "DEF", def2_ppg, market=None),
        qb2=P("QB2", "QB", 15, market=2000),
        qb3=P("QB3", "QB", 14, market=1500),
        qb4=P("QB4", "QB", 13, market=700),
    )
    sched = schedule(["AAA", "BYE"], weeks=17, byes={"BYE": 7})
    math = RosMath(players, sched, 7, 17, DROP_SLOTS)
    (drop,) = tr.choose_drops(math, players, list(players), set(), 1)
    assert (drop.player_id, drop.reason) == ("qb4", "4th QB, more than your lineup can use")


def test_surplus_depth_goes_before_other_bench_players():
    # a 1-QB league can use 2 QBs: the 4th goes before any bench receiver
    players, math = _drop_league(
        qb2=P("QB2", "QB", 15, market=2000), qb3=P("QB3", "QB", 14, market=1500),
        qb4=P("QB4", "QB", 13, market=1200),
    )  # fmt: skip
    first, second = tr.choose_drops(math, players, list(players), set(), 2)
    assert (first.player_id, first.reason) == ("qb4", "4th QB, more than your lineup can use")
    assert (second.player_id, second.reason) == ("qb3", "3rd QB, more than your lineup can use")


def test_starters_and_new_arrivals_are_never_cut_while_bench_exists():
    players, math = _drop_league()
    drops = tr.choose_drops(math, players, list(players), {"scrub"}, 1)
    assert [d.player_id for d in drops] == ["ladd"]  # just-acquired scrub stays; starters stay
    starters_only = [p for p in players if p not in ("ladd", "scrub")]
    (drop,) = tr.choose_drops(math, players, starters_only, set(), 1)
    assert drop.reason == "costs your lineup the least"


@pytest.mark.parametrize(
    "backups, why",
    [(1, "5th RB, more than your lineup can use"), (2, "lowest market value on your bench")],
)
def test_trade_card_says_who_is_dropped_and_why(backups, why):
    # receiving B2 makes 5 RBs: one more than 2 RB slots + the flex + 1 backup (the default
    # setting), but fine for a manager who keeps 2 backups
    players, math = _drop_league(
        b1=P("B1", "WR", 16, market=9000), b2=P("B2", "RB", 15, market=9000)
    )
    mine = [p for p in players if p not in ("b1", "b2")]
    ev = tr.evaluate(
        math, players, ("A", mine), ("B", ["b1", "b2"]), ["wr2"], ["b1", "b2"],
        rules=tr.RosterRules(active_limit=len(mine), bench_backups=backups),
    )  # fmt: skip
    assert ev.me.drops == ["scrub"] and ev.me.drop_reasons == [why]
    assert any(f"drop Scrub ({why})" in r for r in ev.reasons)


def test_picking_up_a_kicker_drops_the_old_kicker_not_a_bench_player():
    # the new kicker covers the old one's bye; the old one still costs a few points, but he's the
    # dead weight now, not the bench receiver
    players, _ = _drop_league(
        **{"k": P("K1", "K", 8, team="BYE", market=None)}, k_new=P("K2", "K", 7.8, market=None)
    )
    math = RosMath(players, schedule(["AAA", "BYE"], weeks=17, byes={"BYE": 9}), 7, 17, DROP_SLOTS)
    (drop,) = tr.choose_drops(math, players, list(players), {"k_new"}, 1)
    assert (drop.player_id, drop.reason) == ("k", "extra kicker")


SF_DROP_SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "SUPER_FLEX", "K", "DEF"]


@pytest.mark.parametrize(
    "extra, cut",
    [
        (dict(te2=P("TE2", "TE", 8, market=3000), te3=P("TE3", "TE", 6, market=2000),
              te4=P("TE4", "TE", 5, market=900)), ("te4", "4th TE")),
        (dict(rb4=P("RB4", "RB", 11, market=3000), rb5=P("RB5", "RB", 10, market=2000),
              rb6=P("RB6", "RB", 9, market=900)), ("rb6", "6th RB")),
    ],
)  # fmt: skip
def test_superflex_surplus_counts_each_flex_once(extra, cut):
    # the flex goes to RB3 and SUPER_FLEX to the 2nd QB, so TEs can use 1 slot and RBs 3 (+1
    # backup each): a 4th TE or a 6th RB is surplus, and goes before the cheap bench receiver
    players = {
        "qb": P("QB1", "QB", 20, market=4000), "qb2": P("QB2", "QB", 16, market=3000),
        "rb1": P("RB1", "RB", 16, market=8000), "rb2": P("RB2", "RB", 14, market=7000),
        "rb3": P("RB3", "RB", 12, market=5000), "wr1": P("WR1", "WR", 15, market=8000),
        "wr2": P("WR2", "WR", 13, market=6000), "scrub": P("Scrub", "WR", 6, market=400),
        "te": P("TE1", "TE", 10, market=3000), "k": P("K1", "K", 8, market=None),
        "def": P("DEF1", "DEF", 7, market=None), **extra,
    }  # fmt: skip
    math = RosMath(players, schedule(["AAA"], weeks=17), 7, 17, SF_DROP_SLOTS)
    (drop,) = tr.choose_drops(math, players, list(players), set(), 1)
    assert (drop.player_id, drop.reason) == (cut[0], f"{cut[1]}, more than your lineup can use")


# ───────── free to drop: lineup points per remaining week ─────────


def test_a_starting_flex_is_never_free_late_in_the_season():
    # week 16 of 17: cutting the FLEX (RB3) costs only 2 x 2 = 4 ROS points (Scrub fills in, 2 ppg
    # worse), under the old 5-point cutoff. But he starts this week, so he's never free to drop
    players, _ = _drop_league(
        flex=P("RB3", "RB", 12, market=100), scrub=P("Scrub", "RB", 10, market=300)
    )
    math = RosMath(players, schedule(["AAA"], weeks=17), 16, 17, DROP_SLOTS)
    (drop,) = tr.choose_drops(math, players, list(players), set(), 1)
    assert (drop.player_id, drop.reason) == ("scrub", "lowest market value on your bench")


def test_a_starter_is_never_free_even_with_a_backup_almost_as_good():
    # week 7: Scrub is 0.2 ppg worse than the FLEX (RB3), so cutting RB3 costs 0.2 a week, under
    # the 0.5 line. He still starts this week, so the cheap bench player goes, not him
    players, math = _drop_league(
        flex=P("RB3", "RB", 12, market=100), scrub=P("Scrub", "RB", 11.8, market=300)
    )
    (drop,) = tr.choose_drops(math, players, list(players), set(), 1)
    assert (drop.player_id, drop.reason) == ("scrub", "lowest market value on your bench")


def test_bench_player_costing_under_half_a_point_a_week_is_free_early():
    # week 2: Ladd covers WR2's bye (week 9) for 6.4 points, the only points he'll ever score for
    # us: 6.4 / 16 weeks = 0.4 a week, so he's free to drop (the old 5-point cutoff kept him)
    players, _ = _drop_league(
        wr2=P("WR2", "WR", 13, team="BYE", market=6000), ladd=P("Ladd", "WR", 6.4, market=200)
    )
    math = RosMath(players, schedule(["AAA", "BYE"], weeks=17, byes={"BYE": 9}), 2, 17, DROP_SLOTS)
    (drop,) = tr.choose_drops(math, players, list(players), set(), 1)
    assert (drop.player_id, drop.reason) == ("ladd", "lowest market value on your bench")


@pytest.mark.parametrize("start", [2, 16])
@pytest.mark.parametrize("ladd_ppg, cut", [(0.8, "ladd"), (1.2, "scrub")])
def test_the_same_cost_per_week_gives_the_same_drop_any_week(start, ladd_ppg, cut):
    # WR2 is out every odd week, so Ladd (the only other WR) starts half the remaining weeks: in
    # week 2 and week 16 alike he costs ladd_ppg / 2 a week. 0.4 is under the 0.5 line (free: the
    # cheapest on the market goes); 0.6 isn't (he stays, and Scrub goes)
    players, _ = _drop_league(ladd=P("Ladd", "WR", ladd_ppg, market=200))
    wr2_out_odd_weeks = {"wr2": {w: 0.0 if w % 2 else 13.0 for w in range(1, 18)}}
    math = RosMath(
        players, schedule(["AAA"], weeks=17), start, 17, DROP_SLOTS, weekly=wr2_out_odd_weeks
    )
    (drop,) = tr.choose_drops(math, players, list(players), set(), 1)
    assert drop.player_id == cut


def test_a_bench_wr_covering_three_byes_is_not_free():
    # weeks 2-17: Ladd fills in for three receivers' byes, 3 x 6 = 18 points over 16 weeks (1.1 a
    # week), so he isn't free; Scrub (a backup QB who never plays) is, and goes though the market
    # likes him more
    players = {
        "qb": P("QB1", "QB", 20, market=4000), "rb1": P("RB1", "RB", 16, market=8000),
        "rb2": P("RB2", "RB", 14, market=7000), "te": P("TE1", "TE", 10, market=3000),
        "wr1": P("WR1", "WR", 15, team="B5", market=8000),
        "wr2": P("WR2", "WR", 13, team="B7", market=6000),
        "flex": P("WR3", "WR", 12, team="B9", market=5000),
        "k": P("K1", "K", 8, market=None), "def": P("DEF1", "DEF", 7, market=None),
        "ladd": P("Ladd", "WR", 6, market=100), "scrub": P("Scrub", "QB", 5, market=300),
    }  # fmt: skip
    sched = schedule(["AAA", "B5", "B7", "B9"], weeks=17, byes={"B5": 5, "B7": 7, "B9": 9})
    math = RosMath(players, sched, 2, 17, DROP_SLOTS)
    (drop,) = tr.choose_drops(math, players, list(players), set(), 1)
    assert (drop.player_id, drop.reason) == ("scrub", "lowest market value on your bench")
    # with Scrub gone too, Ladd is the cheapest cut, but as a cost, not as free bench depth
    (drop,) = tr.choose_drops(math, players, [p for p in players if p != "scrub"], set(), 1)
    assert (drop.player_id, drop.reason) == ("ladd", "costs your lineup the least")


def test_free_drop_line_is_a_setting():
    players, _ = _drop_league(
        wr2=P("WR2", "WR", 13, team="BYE", market=6000), ladd=P("Ladd", "WR", 6.4, market=200)
    )
    math = RosMath(players, schedule(["AAA", "BYE"], weeks=17, byes={"BYE": 9}), 2, 17, DROP_SLOTS)
    # 0.4 a week is free at the default 0.5 line, but not for a manager who sets it to 0.3
    (drop,) = tr.choose_drops(math, players, list(players), set(), 1, free_ppg=0.3)
    assert drop.player_id == "scrub"
    assert tr.RosterRules().free_drop_ppg == tr.FREE_DROP_PPG == 0.5


def test_no_weeks_left_does_not_break_drops():
    players, _ = _drop_league()
    math = RosMath(players, schedule(["AAA"], weeks=17), 18, 17, DROP_SLOTS)
    assert len(tr.choose_drops(math, players, list(players), set(), 1)) == 1


# ───────── missing market values ─────────


def _unpriced(p):
    return p | {"market_value": None}


@pytest.mark.parametrize(
    "rookie_par, cut", [(40, "scrub"), (20, "rookie")]
)  # our projection likes him more than Scrub, or less
def test_a_rookie_with_no_market_price_is_judged_by_our_projection(rookie_par, cut):
    # the market has no price for the rookie: that's not a price of 0, so the bench is compared by
    # our rest-of-season value instead (Scrub: 6.5 ppg x 5 = 32.5)
    players, math = _drop_league(ladd=_unpriced(P("Rookie", "WR", 6, par=rookie_par)))
    players["rookie"] = players.pop("ladd")
    (drop,) = tr.choose_drops(math, players, list(players), set(), 1)
    assert (drop.player_id, drop.reason) == (
        cut,
        "lowest value on your bench (our projection; no market price)",
    )


def test_priced_benches_still_go_by_market():
    players, math = _drop_league(ladd=P("Ladd", "WR", 6, market=5500, par=1))
    (drop,) = tr.choose_drops(math, players, list(players), set(), 1)
    assert (drop.player_id, drop.reason) == ("scrub", "lowest market value on your bench")


def test_surplus_without_a_price_is_judged_by_our_projection():
    # 4 QBs in a 1-QB league: the unpriced one isn't the 4th to go just for having no price
    players, math = _drop_league(
        qb2=P("QB2", "QB", 15, market=2000, par=10), qb3=P("QB3", "QB", 14, market=1500, par=5),
        qb4=_unpriced(P("QB4", "QB", 13, par=60)),
    )  # fmt: skip
    (drop,) = tr.choose_drops(math, players, list(players), set(), 1)
    assert (drop.player_id, drop.reason) == ("qb3", "4th QB, more than your lineup can use")


def _no_market(players):
    return {k: _unpriced(v) for k, v in players.items()}


def test_with_no_market_values_anywhere_no_reason_mentions_the_market():
    players, _ = _drop_league(b1=P("B1", "WR", 16), b2=P("B2", "RB", 15))
    players = _no_market(players)
    math = RosMath(players, schedule(["AAA"], weeks=17), 7, 17, DROP_SLOTS)
    assert not tr.has_market_values(players)
    mine = [p for p in players if p not in ("b1", "b2")]
    ev = tr.evaluate(
        math, players, ("A", mine), ("B", ["b1", "b2"]), ["wr2"], ["b1", "b2"],
        rules=tr.RosterRules(active_limit=len(mine), bench_backups=2),
    )  # fmt: skip
    # no market rule: whoever costs the lineup least goes (three bench players cost nothing; Ladd
    # has the lowest projection of them)
    assert ev.me.drops == ["ladd"] and ev.me.drop_reasons == ["costs your lineup the least"]
    assert ev.market_values_missing
    assert not any("market" in r.lower() for r in ev.reasons + ev.me.drop_reasons)
    # every rule, one cut at a time: extra kicker, surplus QB, then lowest cost
    players = _no_market(
        _drop_league(k2=P("K2", "K", 7.5), qb2=P("QB2", "QB", 15), qb3=P("QB3", "QB", 14))[0]
    )
    math = RosMath(players, schedule(["AAA"], weeks=17), 7, 17, DROP_SLOTS)
    drops = tr.choose_drops(math, players, list(players), set(), 4)
    assert [d.reason for d in drops] == [
        "extra kicker",
        "3rd QB, more than your lineup can use",
        "costs your lineup the least",
        "costs your lineup the least",
    ]


def test_market_values_flag_is_off_when_the_league_has_prices(league):
    players, rosters, math = league
    ev = evaluate(math, players, ("A", rosters["A"]), ("B", rosters["B"]), ["a_rb4"], ["b_wr4"])
    assert tr.has_market_values(players) and not ev.market_values_missing


@pytest.mark.parametrize("ir_spots", [1, 0])  # in an IR spot, or over the IR limit
def test_a_player_on_ir_is_never_dropped(ir_spots):
    # the injured receiver has no price and the lowest projection: he'd be the first cut otherwise
    players, math = _drop_league(hurt=_unpriced(P("Hurt", "WR", 0, par=0)))
    roster = [p for p in players if p != "scrub"]
    rules = tr.RosterRules(
        active_limit=len(roster) - ir_spots, reserved=frozenset({"hurt"}), reserve_slots=ir_spots
    )
    after, drops = tr.roster_after(math, players, "A", roster, [], ["scrub"], rules)
    assert len(drops) == 1 and drops[0].player_id != "hurt" and "hurt" in after
