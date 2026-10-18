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


# ───────── how many players a position can usefully hold ─────────

ONE_FLEX = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"]
SUPERFLEX = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "SUPER_FLEX", "K", "DEF"]
BASE = [
    P("q1", "QB", 22), P("q2", "QB", 18), P("r1", "RB", 16), P("r2", "RB", 14),
    P("r3", "RB", 12), P("w1", "WR", 15), P("w2", "WR", 13), P("w3", "WR", 9),
    P("t1", "TE", 10), P("k", "K", 8), P("d", "DEF", 7),
]  # fmt: skip


def _capacity(players, slots, **kw):
    from signals.lineup import position_capacity

    return position_capacity(optimal_lineup(players, slots), **kw)


def _count(players, pos):
    return sum(p.position == pos for p in players)


def test_position_capacity():
    # 1-QB, 1-flex: the flex goes to RB3 (12 > WR3's 9), so it counts for RBs only; one backup
    # per skill position, none for K / DEF
    std = _capacity(BASE, ONE_FLEX)
    assert std == {"QB": 2, "RB": 4, "WR": 3, "TE": 2, "K": 1, "DEF": 1}
    # Superflex: the second QB takes SUPER_FLEX, so QBs get it and nobody else does
    sf = _capacity(BASE, SUPERFLEX)
    assert sf == {"QB": 3, "RB": 4, "WR": 3, "TE": 2, "K": 1, "DEF": 1}
    # the backup count is a setting; streamed positions never get one
    deep = _capacity(BASE, ONE_FLEX, backups=2)
    assert deep == {"QB": 3, "RB": 5, "WR": 4, "TE": 3, "K": 1, "DEF": 1}


def test_one_flex_counts_for_one_position_only():
    for players, flex_pos in [(BASE, "RB"), ([*BASE, P("w0", "WR", 30)], "WR")]:
        cap = _capacity(players, ONE_FLEX)
        dedicated = {"QB": 1, "RB": 2, "WR": 2, "TE": 1}
        extra = {pos: cap[pos] - dedicated[pos] - 1 for pos in dedicated}
        assert extra == {pos: int(pos == flex_pos) for pos in dedicated}


def test_an_empty_flex_counts_for_nobody():
    thin = [P("q1", "QB", 20), P("r1", "RB", 15), P("r2", "RB", 14), P("w1", "WR", 13),
            P("w2", "WR", 12), P("t1", "TE", 9)]  # fmt: skip
    cap = _capacity(thin, ONE_FLEX)
    assert (cap["RB"], cap["WR"], cap["TE"]) == (3, 3, 2)


def test_superflex_four_tes_are_a_surplus():
    # the old count gave TEs the TE slot, FLEX and SUPER_FLEX at once (+1 backup = 4)
    players = [*BASE, P("t2", "TE", 8), P("t3", "TE", 6), P("t4", "TE", 5)]
    cap = _capacity(players, SUPERFLEX)
    assert _count(players, "TE") == 4 and cap["TE"] == 2


def test_superflex_six_rbs_are_a_surplus():
    # the old count gave RBs both RB slots, FLEX and SUPER_FLEX (+2 backups = 6)
    players = [*BASE, P("r4", "RB", 11), P("r5", "RB", 10), P("r6", "RB", 9)]
    cap = _capacity(players, SUPERFLEX)
    assert _count(players, "RB") == 6 and cap["RB"] == 4
