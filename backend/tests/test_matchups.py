"""Head-to-head parsing (Sleeper, ESPN) and the win / playoff-odds model."""

from ingest import espn as es
from ingest import sleeper as sl
from signals import sim


def test_win_prob_is_even_for_equal_teams_and_clear_for_a_big_favourite():
    a = sim.TeamWeek(110, 20)
    assert sim.win_prob(a, a) == 0.5
    assert sim.win_prob(sim.TeamWeek(140, 15), sim.TeamWeek(95, 15)) > 0.95
    assert sim.win_prob(sim.TeamWeek(80, 0), sim.TeamWeek(90, 0)) == 0.0  # all final
    p = sim.win_prob(sim.TeamWeek(120, 20), sim.TeamWeek(110, 20))
    assert abs(p + sim.win_prob(sim.TeamWeek(110, 20), sim.TeamWeek(120, 20)) - 1) < 1e-12


def test_team_week_banks_final_games_and_scales_spread_with_the_projection():
    players = {"a": {"ppg": 10, "p10": 4, "p90": 16}, "b": {"ppg": 10, "p10": 4, "p90": 16}}
    full = sim.team_week(["a", "b"], {"a": 10, "b": 10}, players)
    assert full.mean == 20 and abs(full.sd - (2 * (12 / sim.BAND_Z) ** 2) ** 0.5) < 0.01
    half = sim.team_week(["a"], {"a": 5}, players)  # e.g. Questionable: half the points
    assert abs(half.sd - 12 / sim.BAND_Z / 2) < 0.01
    banked = sim.team_week(["a", "b"], {"a": 10, "b": 10}, players, banked={"a": 23.4})
    assert banked.mean == 33.4 and banked.sd == sim.team_week(["b"], {"b": 10}, players).sd


def test_season_odds_are_seeded_and_add_up():
    records = {t: sim.Record(2, 2, 400.0) for t in "ABCD"}
    games = [(5, "A", "B"), (5, "C", "D"), (6, "A", "C"), (6, "B", "D")]
    strong = sim.TeamWeek(150, 10)
    weak = sim.TeamWeek(80, 10)
    weeks = {(w, t): (strong if t == "A" else weak) for w in (5, 6) for t in "ABCD"}
    odds = sim.season_odds(records, games, weeks, playoff_teams=2, sims=2000, seed=1)
    assert odds == sim.season_odds(records, games, weeks, 2, sims=2000, seed=1)
    assert odds["A"].playoffs == 1.0 and odds["A"].seeds[0] == 1.0 and odds["A"].wins == 4.0
    assert abs(sum(o.playoffs for o in odds.values()) - 2) < 1e-9
    assert all(abs(sum(o.seeds) - 1) < 1e-9 for o in odds.values())
    assert odds["A"].losses == 2.0  # no losses added


def test_sleeper_matchups_pair_by_matchup_id():
    raw = [
        {"roster_id": 1, "matchup_id": 7, "points": 101.5, "starters": ["a", "0", "b"],
         "players_points": {"a": 60, "b": 41.5, "c": 3}},
        {"roster_id": 2, "matchup_id": 7, "points": 99.0, "starters": [], "players_points": None},
        {"roster_id": 3, "matchup_id": None, "points": 0},
    ]  # fmt: skip
    one, two, three = sl.parse_matchups(4, raw)
    assert (one.week, one.team, one.opponent, one.points) == (4, "1", "2", 101.5)
    assert one.starters == ["a", "b"] and one.player_points["c"] == 3.0  # "0" = empty slot
    assert two.opponent == "1" and two.player_points == {}
    assert three.opponent is None


def _side(team, total, entries=None):
    side = {"teamId": team, "totalPoints": total}
    if entries is not None:
        side["rosterForCurrentScoringPeriod"] = {
            "entries": [
                {"playerId": p, "lineupSlotId": slot, "playerPoolEntry": {"appliedStatTotal": pts}}
                for p, slot, pts in entries
            ]
        }
    return side


def test_espn_schedule_keeps_the_regular_season_both_ways():
    raw = {
        "schedule": [
            {"matchupPeriodId": 1, "playoffTierType": "NONE", "home": _side(1, 120.0), "away": _side(2, 99.5)},
            {"matchupPeriodId": 2, "playoffTierType": "NONE", "home": _side(3, 0.0)},  # a bye
            {"matchupPeriodId": 15, "playoffTierType": "WINNERS_BRACKET", "home": _side(1, 0), "away": _side(3, 0)},
        ]
    }  # fmt: skip
    rows = es.parse_schedule(raw)
    assert [(m.week, m.team, m.opponent, m.points) for m in rows] == [
        (1, "1", "2", 120.0), (1, "2", "1", 99.5), (2, "3", None, 0.0),
    ]  # fmt: skip


def test_espn_boxscore_starters_and_live_score():
    entries = [
        (11, 2, 20.0),
        (12, 4, 15.5),
        (13, es.BENCH, 30.0),
        (14, es.IR, 0.0),
        (-16012, 16, 7.0),
    ]
    raw = {
        "schedule": [
            {"matchupPeriodId": 8, "home": _side(1, 10.0, entries), "away": _side(2, 0.0, [])},
            {"matchupPeriodId": 7, "home": _side(3, 1.0, [(1, 2, 1.0)]), "away": _side(4, 2.0, [])},
        ]
    }
    one, two = es.parse_boxscore(raw, 8)
    assert one.starters == ["11", "12", "-16012"] and one.player_points["13"] == 30.0
    assert one.points == 42.5  # starters' live points, not the lagging totalPoints
    assert two.starters == [] and two.points == 0.0 and two.opponent == "1"
