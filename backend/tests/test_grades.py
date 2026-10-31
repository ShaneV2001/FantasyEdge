from types import SimpleNamespace

import polars as pl
import pytest

from app.services import views
from signals.team import (
    benchmarks,
    grade_from_ratio,
    grade_value,
    position_strength,
    position_weights,
    simulate_league,
    team_profiles,
    tier_averages,
)

STD = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"]


def P(pos, ppg, par=None):
    return {
        "position": pos,
        "ppg": ppg,
        "ros_value_par": par if par is not None else ppg,
        "name": pos,
    }


def test_position_weights_include_flex_shares():
    w = position_weights(STD)
    assert w["QB"] == [1.0]
    assert w["RB"] == [1.0, 1.0, 0.45]
    assert w["WR"] == [1.0, 1.0, 0.45]
    assert w["TE"] == [1.0, 0.1]
    sf = position_weights(["QB", "RB", "WR", "SUPER_FLEX"])
    assert sf["QB"] == [1.0, 0.9]
    two_flex = position_weights(["RB", "FLEX", "FLEX"])
    assert two_flex["RB"] == [1.0, 0.9]


def test_position_strength_not_skewed_by_who_plays_flex():
    # Same WRs on both teams; team A's 3rd RB is better, so a RB wins FLEX there.
    players = {
        "a_rb1": P("RB", 15), "a_rb2": P("RB", 14), "a_rb3": P("RB", 13),
        "b_rb1": P("RB", 15), "b_rb2": P("RB", 14), "b_rb3": P("RB", 5),
        "a_wr1": P("WR", 16), "a_wr2": P("WR", 12), "a_wr3": P("WR", 10),
        "b_wr1": P("WR", 16), "b_wr2": P("WR", 12), "b_wr3": P("WR", 10),
    }  # fmt: skip
    w = position_weights(STD)
    a = position_strength([p for p in players if p.startswith("a")], players, w)
    b = position_strength([p for p in players if p.startswith("b")], players, w)
    assert a["WR"] == pytest.approx(b["WR"])  # identical receivers → identical WR strength
    assert a["RB"] > b["RB"]  # A's RB depth is credited
    assert a["WR"] == pytest.approx(16 + 12 + 0.45 * 10)


@pytest.mark.parametrize(
    "ratio, letter",
    [(1.25, "A"), (1.10, "A"), (1.05, "B"), (1.00, "B"), (0.95, "C"), (0.90, "C"),
     (0.85, "D"), (0.80, "D"), (0.79, "F")],
)  # fmt: skip
def test_grade_cutoffs(ratio, letter):
    assert grade_from_ratio(ratio) == letter


def test_grade_value_is_vs_the_typical_team_with_league_rank_kept():
    g = grade_value("RB", 30, [10, 20, 30], benchmark=29)
    assert g.grade == "B" and g.benchmark == 29
    g = grade_value("RB", 30, [10, 20, 30], benchmark=26)
    assert g.grade == "A" and g.vs_benchmark == pytest.approx(30 / 26 - 1, abs=1e-3)
    assert g.rank == 1 and g.teams == 3 and g.z == pytest.approx(1.0)  # still ranked vs the league
    assert grade_value("RB", 30, [30], benchmark=0).grade == "B"  # nothing to compare: even


def test_tiers_are_the_league_sized_slices_of_the_player_pool():
    players = {f"rb{i}": P("RB", 30 - i) for i in range(25)}  # 30, 29, ... 6
    tiers = tier_averages(players, num_teams=10, depth={"RB": 3})
    assert tiers["RB"] == [pytest.approx(25.5), pytest.approx(15.5), pytest.approx(8.0)]


def _league(n_teams, spread):
    """`n_teams` teams whose players differ by `spread` ppg per team step."""
    players, rosters = {}, {}
    for t in range(n_teams):
        ids = []
        for pos, base in (("QB", 18), ("RB", 12), ("RB", 10), ("WR", 12), ("WR", 10), ("TE", 8)):
            pid = f"t{t}_{pos}_{len(ids)}"
            players[pid] = P(pos, base + (t - n_teams / 2) * spread)
            ids.append(pid)
        rosters[f"T{t}"] = ids
    return players, rosters


def test_a_balanced_league_grades_b_and_c_not_a_to_f():
    """The old z-score curve gave a league of near-equal teams the full A-F spread."""
    players, rosters = _league(10, spread=0.05)
    profs = team_profiles(rosters, players, ["QB", "RB", "RB", "WR", "WR", "TE"])
    for p in profs.values():
        assert p.overall.grade in ("B", "C") and p.grades["RB"].grade in ("B", "C")
    assert profs["T9"].overall.rank == 1 and profs["T0"].overall.rank == 10


def test_a_spread_out_league_still_separates_strong_and_weak():
    players, rosters = _league(12, spread=0.5)
    profs = team_profiles(rosters, players, ["QB", "RB", "RB", "WR", "WR", "TE"])
    assert profs["T11"].overall.grade == "A" and profs["T0"].overall.grade in ("D", "F")


def test_flex_benchmark_uses_the_next_tier_after_dedicated_slots():
    slots = ["RB", "WR", "FLEX"]
    tiers = {"RB": [20, 12, 8], "WR": [18, 11, 7], "TE": [9, 5, 3]}
    pos, flex = benchmarks(slots, tiers, position_weights(slots))
    assert flex["FLEX"] == pytest.approx(0.45 * 12 + 0.45 * 11 + 0.10 * 9)
    assert pos["RB"] == pytest.approx(20 + 0.45 * 12)


def test_simulated_league_respects_size_and_caps():
    players = {f"qb{i}": P("QB", 20 - i * 0.1) for i in range(30)}
    players |= {f"rb{i}": P("RB", 18 - i * 0.1) for i in range(60)}
    players |= {f"wr{i}": P("WR", 17 - i * 0.1) for i in range(70)}
    players |= {f"te{i}": P("TE", 12 - i * 0.1) for i in range(30)}
    players |= {
        f"k{i}": P("K", 8, par=50) for i in range(20)
    }  # inflated value: must still be capped
    players |= {f"d{i}": P("DEF", 7, par=50) for i in range(20)}
    roster_positions = STD + ["BN"] * 6 + ["IR"]
    sim = simulate_league(
        players, exclude={"qb0", "rb0"}, num_teams=11, roster_positions=roster_positions
    )
    assert len(sim) == 11
    for ids in sim.values():
        assert len(ids) == 15  # 9 starters + 6 bench (IR not drafted)
        pos = [players[p]["position"] for p in ids]
        assert pos.count("K") == 1 and pos.count("DEF") == 1 and pos.count("QB") <= 2
    drafted = {p for ids in sim.values() for p in ids}
    assert not drafted & {"qb0", "rb0"}
    assert len(drafted) == 11 * 15


def test_grade_only_limits_output():
    players = {"a": P("QB", 20), "b": P("QB", 10)}
    profs = team_profiles({"me": ["a"], "sim": ["b"]}, players, ["QB"], grade_only=["me"])
    assert list(profs) == ["me"] and profs["me"].grades["QB"].rank == 1


def _ctx(players, rows, k=6):
    stats = pl.DataFrame(
        rows, schema={"player_id": pl.Utf8, "season": pl.Int64, "fp": pl.Float64}, orient="row"
    )
    return SimpleNamespace(
        players=players,
        stats=stats,
        season=2026,
        memo={},
        tuning=SimpleNamespace(grade_prod_games=k),
    )


def test_grades_blend_the_projection_with_this_seasons_production():
    players = {
        "hot": P("RB", 10.0),  # producing 16 a game
        "new": P("RB", 12.0),  # no games yet: projection only
        "gone": P("RB", 20.0) | {"return_week": 99},  # out for the season
    }
    rows = [("hot", 2026, 16.0)] * 6 + [("hot", 2025, 2.0), ("gone", 2026, 20.0)]
    g = views.graded_players(_ctx(players, rows))
    assert g["hot"]["ppg"] == pytest.approx(13.0)  # 6 games, k=6: half and half (2025 ignored)
    assert g["new"]["ppg"] == 12.0 and g["gone"]["ppg"] == 0.0
    assert players["hot"]["ppg"] == 10.0  # the projection itself is untouched
    assert views.graded_players(_ctx(players, rows, k=0))["hot"]["ppg"] == 16.0  # production only
