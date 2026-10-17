from signals import advisor as adv
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
