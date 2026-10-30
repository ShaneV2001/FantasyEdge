from types import SimpleNamespace

from signals import advisor as adv
from signals.startsit import plan_week
from signals.team import RosMath, team_profiles
from tests.builders import schedule

SLOTS = ["QB", "RB", "FLEX", "K"]


def P(name, pos, ppg, team="AAA"):
    return {"name": name, "position": pos, "ppg": ppg, "nfl_team": team, "bye_week": None}


def _inputs(players, roster, starters, sched, week=5):
    math = RosMath(players, sched, week, 17, SLOTS)
    rosters = {"A": roster}
    return adv.AdvisorInputs(
        my_team_id="A", rosters=rosters, team_names={"A": "A"}, starters=starters,
        players=players, profiles=team_profiles(rosters, players, SLOTS), byes=[], math=math,
        week=week, trade_deadline_week=None, trade_ideas=[], free_agents=None, regression_messages={},
    )  # fmt: skip


def test_lineup_swaps_stay_position_legal():
    players = {
        "qb": P("QB", "QB", 20),
        "rb1": P("RB One", "RB", 15),
        "rb2": P("RB Two", "RB", 6),
        "rb3": P("RB Three", "RB", 14),  # benched but better than rb2
        "k": P("Kicker", "K", 8, team="BYE"),  # kicker's team is on bye this week
    }
    sched = schedule(["AAA", "BYE"], weeks=17, byes={"BYE": 5})
    inp = _inputs(players, list(players), ["qb", "rb1", "rb2", "k"], sched)
    actions = adv.lineup_actions(inp)
    headlines = [a.headline for a in actions]
    assert "Start RB Three over RB Two" in headlines
    assert not any("Kicker" in h for h in headlines)  # no RB-for-K "swap"


def test_start_sit_uses_this_weeks_matchups():
    # two RBs with the same ppg: the matchup-adjusted week points decide who starts
    players = {
        "qb": P("QB", "QB", 20),
        "rb1": P("RB One", "RB", 15),
        "soft": P("Soft Matchup", "RB", 10),
        "tough": P("Tough Matchup", "RB", 10),
    }
    sched = schedule(["AAA"], weeks=17)
    inp = _inputs(players, list(players), ["qb", "rb1", "tough"], sched)
    assert adv.lineup_actions(inp) == []  # flat ppg: a tie, no swap worth suggesting
    weekly = {"soft": {5: 13.0}, "tough": {5: 7.5}}
    week_math = RosMath(players, sched, 5, 17, SLOTS, weekly=weekly)
    inp.week_plan = plan_week(week_math, players, list(players), ["qb", "rb1", "tough"], 5)
    (swap,) = adv.lineup_actions(inp)
    assert swap.headline == "Start Soft Matchup over Tough Matchup"
    assert "13.0 vs 7.5" in swap.reasons[0]


def test_weekly_points_override_flat_ppg():
    players = {"a": P("A", "RB", 10), "b": P("B", "RB", 10)}
    sched = schedule(["AAA"], weeks=17)
    math = RosMath(players, sched, 5, 7, ["RB"], weekly={"a": {5: 14.0, 6: 4.0}})
    assert math.week_points("a") == {5: 14.0, 6: 4.0, 7: 0.0}  # a missing week counts as 0
    assert math.week_points("b") == {5: 10.0, 6: 10.0, 7: 10.0}  # not given: ppg each week
    assert math.lineup_for_week(["a", "b"], 5).starters == {"a"}
    assert math.lineup_for_week(["a", "b"], 6).starters == {"b"}


def test_no_lineup_advice_without_starters():
    players = {"qb": P("QB", "QB", 20), "rb1": P("RB One", "RB", 15)}
    inp = _inputs(players, list(players), [], schedule(["AAA"], weeks=17))
    assert adv.lineup_actions(inp) == []


def test_sell_reason_names_the_league_playoff_weeks():
    p = P("Seller", "WR", 15) | {"signal": "sell", "ease_playoffs": 0.8}
    players = {"wr": p, "qb": P("QB", "QB", 20)}
    inp = _inputs(players, list(players), [], schedule(["AAA"], weeks=17))
    inp.playoff_label = "weeks 14-16"
    (sell,) = adv.sell_actions(inp)
    assert any("weeks 14-16" in r for r in sell.reasons)


def test_advisor_follows_the_verdict_not_raw_flags():
    flagged_fair = P("Flagged", "WR", 15) | {"regression_score": -2.5, "signal": "hold"}
    overvalued = P("Pricey", "WR", 12) | {
        "regression_score": 0.0,
        "signal": "sell",
        "signal_reasons": ["overvalued by 30 points."],
        "value_gap": -30.0,
        "market_implied_points": 150.0,
    }
    players = {"a": flagged_fair, "b": overvalued, "qb": P("QB", "QB", 20)}
    inp = _inputs(players, list(players), [], schedule(["AAA"], weeks=17))
    sells = adv.sell_actions(inp)
    assert [a.player_ids for a in sells] == [["b"]]
    assert sells[0].reasons[0] == "overvalued by 30 points." and sells[0].confidence == "high"


def test_start_sit_minimum_gain_is_a_setting():
    players = {
        "qb": P("QB", "QB", 20),
        "rb1": P("RB One", "RB", 15),
        "rb2": P("RB Two", "RB", 6),
        "rb3": P("RB Three", "RB", 14),
        "k": P("Kicker", "K", 8),
    }
    sched = schedule(["AAA"], weeks=17)
    inp = _inputs(players, list(players), ["qb", "rb1", "rb2", "k"], sched)
    assert any(a.headline == "Start RB Three over RB Two" for a in adv.lineup_actions(inp))
    inp.start_sit_min_gain = 100.0
    assert not adv.lineup_actions(inp)


def test_gap_confidence_follows_gap_settings_and_survives_zero():
    players = {"qb": P("QB", "QB", 20)}
    inp = _inputs(players, list(players), [], schedule(["AAA"], weeks=17))

    def conf(gap):
        return adv._gap_confidence({"value_gap": gap, "market_implied_points": 100.0}, inp)

    assert (conf(25.0), conf(15.0), conf(5.0)) == ("high", "medium", "low")
    inp.gap_min_points = 0.0
    inp.gap_min_share = 0.0
    assert conf(5.0) == "high"


def test_sell_reason_says_bye_is_this_week():
    seller = P("Seller", "WR", 15, team="BYE") | {"signal": "sell", "bye_week": 5}
    players = {"wr": seller, "qb": P("QB", "QB", 20)}
    sched = schedule(["AAA", "BYE"], weeks=17, byes={"BYE": 5})
    (sell,) = adv.sell_actions(_inputs(players, list(players), [], sched, week=5))
    assert "On bye this week (week 5)." in sell.reasons
    assert not any("coming up" in r for r in sell.reasons)


def test_bye_streamers_cover_every_short_slot():
    """A WR and a D/ST both on bye: suggest a WR *and* a D/ST, not just the higher scorer."""
    players = {
        "fa_wr": P("Stream WR", "WR", 11.4),
        "fa_wr_bye": P("Bye WR", "WR", 14.0, team="BYE"),
        "fa_def": P("Stream DEF", "DEF", 6.0),
        "qb": P("QB", "QB", 20),
    }
    sched = schedule(["AAA", "BYE"], weeks=17, byes={"BYE": 5})
    inp = _inputs(players, ["qb"], [], sched)
    inp.free_agents = ["fa_wr", "fa_wr_bye", "fa_def"]
    assert adv._best_fa_for_slots(inp, ["WR", "DEF"], 5) == ["fa_wr", "fa_def"]
    assert adv._best_fa_for_slots(inp, ["WR", "WR"], 5) == ["fa_wr"]  # no second healthy WR
    inp.free_agents = None
    assert adv._best_fa_for_slots(inp, ["WR"], 5) == []


def test_bye_streamers_skip_players_who_cant_play_that_week():
    """A free agent out for the season (or still on IR in that week) is never a streamer, however
    high his ppg was before the injury."""
    players = {
        "fa_out": P("Season Out", "RB", 14.4) | {"injury_status": "IR", "return_week": 99},
        "fa_back": P("Back Week 8", "RB", 13.0) | {"injury_status": "IR", "return_week": 8},
        "fa_rb": P("Healthy RB", "RB", 9.0),
        "qb": P("QB", "QB", 20),
    }
    sched = schedule(["AAA"], weeks=17)
    inp = _inputs(players, ["qb"], [], sched)
    inp.free_agents = ["fa_out", "fa_back", "fa_rb"]
    assert adv._best_fa_for_slots(inp, ["RB"], 6) == ["fa_rb"]
    assert adv._best_fa_for_slots(inp, ["RB"], 9) == ["fa_back"]


def test_players_in_an_accepted_trade_are_not_suggested_again():
    seller = P("Seller", "WR", 15) | {"signal": "sell", "value_gap": -30.0}
    players = {"wr": seller, "qb": P("QB", "QB", 20)}
    inp = _inputs(players, list(players), [], schedule(["AAA"], weeks=17))
    assert [a.player_ids for a in adv.sell_actions(inp)] == [["wr"]]
    inp.in_trades = frozenset({"wr"})
    assert adv.sell_actions(inp) == []


def _offer(verdict, gain):
    side = SimpleNamespace(lineup_delta=gain, gives=["wr"], receives=["rb"])
    return SimpleNamespace(me=side, verdict=verdict, headline="You gain 12 points.", reasons=["r1"])


def test_an_offer_gets_a_card_even_when_it_is_bad():
    players = {"wr": P("WR", "WR", 15), "qb": P("QB", "QB", 20)}
    inp = _inputs(players, list(players), [], schedule(["AAA"], weeks=17))
    inp.team_names = {"A": "A", "B": "Rivals"}
    inp.offers = [("B", _offer("accept", 12.0)), ("B", _offer("decline", -1.0))]
    good, bad = adv.offer_actions(inp)
    assert good.headline == "Offer from Rivals: accept it" and good.urgency == "this_week"
    assert good.reasons == ["You gain 12 points.", "r1"] and good.team_id == "B"
    assert bad.headline == "Offer from Rivals: decline it" and bad.impact == 1.5
    assert good.priority > bad.priority
