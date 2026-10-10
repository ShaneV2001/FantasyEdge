from signals.lineup import LineupPlayer, optimal_lineup, starting_slots


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
