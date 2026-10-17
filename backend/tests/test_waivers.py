import pytest

from signals import trade as tr
from signals import waivers as wv
from signals.team import RosMath
from tests.builders import schedule

SLOTS = ["QB", "RB", "WR", "FLEX"]


def P(name, pos, ppg, team="AAA", par=None):
    return {
        "name": name,
        "position": pos,
        "ppg": ppg,
        "nfl_team": team,
        "ros_value_par": par if par is not None else ppg * 5,
        "bye_week": None,
    }


@pytest.fixture
def setup():
    players = {
        "qb": P("QB", "QB", 18), "rb1": P("RB1", "RB", 15), "rb2": P("RB2", "RB", 6),
        "wr1": P("WR1", "WR", 14), "wr2": P("WR2", "WR", 5), "bench_te": P("TE", "TE", 2),
        # free agents
        "fa_rb": P("FA RB", "RB", 12), "fa_wr": P("FA WR", "WR", 9), "fa_qb": P("FA QB", "QB", 10),
        "fa_bad": P("FA scrub", "WR", 1),
    }  # fmt: skip
    roster = ["qb", "rb1", "rb2", "wr1", "wr2", "bench_te"]
    math = RosMath(players, schedule(["AAA"], weeks=17), 8, 17, SLOTS)
    return players, roster, math


FAS = ["fa_rb", "fa_wr", "fa_qb", "fa_bad"]


def test_ranked_by_net_gain_with_the_cheapest_drop(setup):
    players, roster, math = setup
    rules = tr.RosterRules(active_limit=6)  # full: every pickup forces a drop
    picks = wv.rank_waivers(math, players, "A", roster, FAS, rules)
    assert [w.player_id for w in picks] == ["fa_rb", "fa_wr"]  # QB backup and the scrub don't help
    rb = picks[0]
    assert rb.drop == "bench_te"  # costs the lineup nothing
    # FA RB (12) replaces RB2 (6) in the FLEX: +6 a week for 10 weeks
    assert rb.gain == pytest.approx(60.0) and rb.gain_per_week == pytest.approx(6.0)
    assert picks[1].gain == pytest.approx(30.0)  # FA WR (9) over RB2 (6) in the FLEX: +3 a week


def test_net_gain_counts_the_drop_when_it_hurts(setup):
    players, _, _ = setup
    players = {**players, "rb1": {**players["rb1"], "nfl_team": "BBB"}}  # RB1 on bye in week 10
    math = RosMath(players, schedule(["AAA", "BBB"], weeks=17, byes={"BBB": 10}), 8, 17, SLOTS)
    roster = ["qb", "rb1", "wr1", "rb2"]  # four starters, no bench
    pick = wv.rank_waivers(math, players, "A", roster, ["fa_wr"], tr.RosterRules(active_limit=4))[0]
    # FA WR (9) beats RB2 (6) in the FLEX: +3 a week for 9 weeks. RB2 must go, so in week 10
    # the RB slot he'd have filled sits empty: the net gain is 30, not the 36 a free spot would give
    assert pick.drop == "rb2"
    assert pick.gain == pytest.approx(30.0)
    raw = math.ros_lineup_points([*roster, "fa_wr"]) - math.ros_lineup_points(roster)
    assert raw == pytest.approx(36.0)


def test_no_drop_with_an_open_roster_spot(setup):
    players, roster, math = setup
    picks = wv.rank_waivers(math, players, "A", roster, FAS, tr.RosterRules(active_limit=8))
    assert picks and all(w.drop is None for w in picks)
    picks = wv.rank_waivers(math, players, "A", roster, FAS, tr.RosterRules())  # no limit modelled
    assert all(w.drop is None for w in picks)


def test_reserved_players_are_never_dropped(setup):
    players, roster, math = setup
    rules = tr.RosterRules(active_limit=5, reserved=frozenset({"bench_te"}), reserve_slots=0)
    # bench_te sits on IR but there's no IR slot: he uses an active spot, yet can't be released
    rb = wv.rank_waivers(math, players, "A", roster, FAS, rules)[0]
    assert rb.drop not in (None, "bench_te")


def test_short_weeks_and_needs(setup):
    players, roster, math = setup
    players = {**players, "qb": {**players["qb"], "nfl_team": "BBB"}}
    math = RosMath(players, schedule(["AAA", "BBB"], weeks=17, byes={"BBB": 10}), 8, 17, SLOTS)
    picks = wv.rank_waivers(
        math, players, "A", roster, FAS, tr.RosterRules(), viable_ppg={"QB": 5.0}, needs=["WR"]
    )
    qb = next(w for w in picks if w.player_id == "fa_qb")
    assert qb.fixes_weeks == [10] and qb.need  # covers the starting QB's bye
    assert next(w for w in picks if w.player_id == "fa_wr").need  # WR is a need
    assert not next(w for w in picks if w.player_id == "fa_rb").need


def test_candidates_are_the_best_by_ppg_at_each_position(monkeypatch, setup):
    players, roster, math = setup
    many = {f"wr{i}": P(f"WR {i}", "WR", 6 + i * 0.1) for i in range(40)}
    players = {**players, **many}
    math = RosMath(players, schedule(["AAA"], weeks=17), 8, 17, SLOTS)
    monkeypatch.setattr(wv, "CANDIDATES_PER_POS", 5)
    picks = wv.rank_waivers(math, players, "A", roster, list(many), tr.RosterRules())
    assert picks[0].player_id == "wr39"  # the best one survives the screen
    assert {w.player_id for w in picks} <= {f"wr{i}" for i in range(35, 40)}


def test_faab_bid():
    # half the budget at the full-bid gain; proportional below it
    assert wv.faab_bid(40, 100, 40, 0.5, 1) == (38, 50, 62)
    assert wv.faab_bid(10, 100, 40, 0.5, 1) == (9, 12, 16)
    assert wv.faab_bid(400, 100, 40, 1.0, 1) == (75, 100, 100)  # never more than you have
    assert wv.faab_bid(0.5, 100, 40, 0.5, 2) == (2, 2, 2)  # minimum bid
    assert wv.faab_bid(10, 1, 40, 0.5, 3) == (1, 1, 1)  # min bid can't exceed what's left
    assert wv.faab_bid(10, 0, 40, 0.5, 1) == (0, 0, 0)  # broke
    assert wv.faab_bid(10, None) is None  # not a FAAB league
