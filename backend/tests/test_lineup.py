import random

import pytest

from signals.lineup import SLOT_ELIGIBILITY, LineupPlayer, optimal_lineup, starting_slots


def P(pid, pos, pts):
    return LineupPlayer(pid, pos, pts)


def test_starting_slots_drop_bench_ir_taxi():
    assert starting_slots(["QB", "RB", "FLEX", "BN", "IR", "TAXI", "SUPER_FLEX"]) == [
        "QB",
        "RB",
        "FLEX",
        "SUPER_FLEX",
    ]


def test_flex_gets_best_leftover():
    players = [
        P("r1", "RB", 15),
        P("r2", "RB", 12),
        P("w1", "WR", 14),
        P("w2", "WR", 11),
        P("t1", "TE", 9),
    ]
    lu = optimal_lineup(players, ["RB", "WR", "TE", "FLEX"])
    assigned = {slot: p.player_id for slot, p in lu.slots}
    assert assigned == {"RB": "r1", "WR": "w1", "TE": "t1", "FLEX": "r2"}
    assert lu.points == 50


def test_superflex_prefers_second_qb_when_better():
    players = [P("q1", "QB", 22), P("q2", "QB", 18), P("r1", "RB", 15), P("w1", "WR", 12)]
    lu = optimal_lineup(players, ["SUPER_FLEX", "QB", "RB", "FLEX"])
    assigned = {slot: p.player_id for slot, p in lu.slots}
    assert assigned["QB"] == "q1" and assigned["SUPER_FLEX"] == "q2"
    assert assigned["FLEX"] == "w1"


def test_restrictive_slots_filled_first():
    # If FLEX were filled first it would steal the only TE-eligible... ensure TE slot still gets t1.
    players = [P("t1", "TE", 30), P("w1", "WR", 5)]
    lu = optimal_lineup(players, ["FLEX", "TE"])
    assigned = {slot: p.player_id for slot, p in lu.slots}
    assert assigned == {"FLEX": "w1", "TE": "t1"}


def test_empty_slot_when_no_eligible():
    lu = optimal_lineup([P("w1", "WR", 10)], ["QB", "WR"])
    assert lu.slots[0][1] is None and lu.points == 10


def test_overlapping_flexes_are_solved_exactly():
    # Greedy fills W/R with the WR and is left with the TE for W/T (21); best is 35.
    players = [P("w", "WR", 20), P("r", "RB", 15), P("t", "TE", 1)]
    lu = optimal_lineup(players, ["WRRB_FLEX", "REC_FLEX"])
    assert lu.points == 35
    assert {slot: p.player_id for slot, p in lu.slots} == {"WRRB_FLEX": "r", "REC_FLEX": "w"}


def test_assignment_leaves_slots_empty_when_nobody_fits():
    lu = optimal_lineup([P("w", "WR", 10)], ["WRRB_FLEX", "REC_FLEX", "K"])
    assert lu.points == 10
    assert sum(p is None for _, p in lu.slots) == 2


def _brute_force(players, slots):
    best = 0.0

    def go(i, used, total):
        nonlocal best
        if i == len(slots):
            best = max(best, total)
            return
        go(i + 1, used, total)  # leave empty
        for p in players:
            if p.player_id not in used and p.position in SLOT_ELIGIBILITY[slots[i]]:
                go(i + 1, used | {p.player_id}, total + p.points)

    go(0, frozenset(), 0.0)
    return best


@pytest.mark.parametrize("seed", range(150))
def test_matches_brute_force(seed):
    rng = random.Random(seed)
    kinds = ["QB", "RB", "WR", "TE", "FLEX", "WRRB_FLEX", "REC_FLEX", "SUPER_FLEX"]
    slots = [rng.choice(kinds) for _ in range(rng.randint(1, 4))]
    players = [
        P(f"p{i}", rng.choice(["QB", "RB", "WR", "TE"]), float(rng.randint(0, 30)))
        for i in range(rng.randint(1, 7))
    ]
    assert optimal_lineup(players, slots).points == pytest.approx(_brute_force(players, slots))


def test_position_capacity():
    from signals.lineup import position_capacity

    std = position_capacity(["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"])
    assert std == {"QB": 2, "RB": 5, "WR": 5, "TE": 3, "K": 1, "DEF": 1}
    sf = position_capacity(["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "SUPER_FLEX"])
    assert sf["QB"] == 3 and sf["K"] == 0 and sf["DEF"] == 0
