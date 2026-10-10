import pytest

from signals.team import (
    grade_from_z,
    grade_value,
    position_strength,
    position_weights,
    simulate_league,
    team_profiles,
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
    "z, letter",
    [
        (1.2, "A"),
        (1.0, "A"),
        (0.5, "B"),
        (0.0, "C"),
        (-0.34, "C"),
        (-0.5, "D"),
        (-1.0, "D"),
        (-1.5, "F"),
    ],
)
def test_grade_cutoffs(z, letter):
    assert grade_from_z(z) == letter


def test_grade_value_rank_z_and_single_team():
    g = grade_value("RB", 30, [10, 20, 30])
    assert g.rank == 1 and g.teams == 3 and g.z == pytest.approx(1.0) and g.grade == "A"
    solo = grade_value("RB", 30, [30])
    assert solo.grade == "C" and solo.z == 0.0  # nothing to compare against


def test_grades_spread_evenly_in_a_realistic_league():
    # 12 teams with linearly spaced strength → z-score letters give a sensible spread (no 1/3 F's)
    players, rosters = {}, {}
    for t in range(12):
        ids = []
        for pos, base in (("QB", 18), ("RB", 12), ("RB", 10), ("WR", 12), ("WR", 10), ("TE", 8)):
            pid = f"t{t}_{pos}_{len(ids)}"
            players[pid] = P(pos, base + t * 0.5)
            ids.append(pid)
        rosters[f"T{t}"] = ids
    profs = team_profiles(rosters, players, ["QB", "RB", "RB", "WR", "WR", "TE"])
    letters = [p.grades["RB"].grade for p in profs.values()]
    assert letters.count("F") <= 2 and letters.count("A") <= 2
    assert profs["T11"].overall.grade == "A" and profs["T0"].overall.grade == "F"
    assert profs["T11"].overall.rank == 1


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
