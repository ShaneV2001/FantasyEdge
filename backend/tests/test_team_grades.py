from signals.team import full_strength_lineup, slot_strength, team_profiles

SLOTS = ["QB", "RB", "WR", "FLEX", "WRRB_FLEX", "K", "DEF"]


def P(pos, ppg):
    return {"position": pos, "ppg": ppg}


def _rosters():
    players = {}
    rosters = {}
    for t, base in (("A", 20.0), ("B", 10.0), ("C", 12.0)):
        ids = []
        for pos, extra in (("QB", 0), ("RB", 0), ("RB", -3), ("WR", 0), ("WR", -4), ("TE", -8),
                           ("K", -12), ("DEF", -12)):  # fmt: skip
            pid = f"{t}{pos}{len(ids)}"
            players[pid] = P(pos, max(base + extra, 1.0))
            ids.append(pid)
        rosters[t] = ids
    players["Bweak_k"] = P("K", 0.5)
    rosters["B"] = [p if not p.startswith("BK") else "Bweak_k" for p in rosters["B"]]
    return players, rosters


def test_flex_slots_are_measured_by_who_fills_them():
    players, rosters = _rosters()
    lu = full_strength_lineup(rosters["A"], players, SLOTS)
    flex = slot_strength(lu)
    assert set(flex) == {"FLEX", "W/R"}
    assert flex["FLEX"] + flex["W/R"] == sum(
        lp.points for slot, lp in lu.slots if slot in ("FLEX", "WRRB_FLEX") and lp
    )


def test_kickers_defenses_and_flex_are_graded_but_never_needs():
    players, rosters = _rosters()
    profs = team_profiles(rosters, players, SLOTS)
    b = profs["B"]
    assert {"K", "DEF", "FLEX", "W/R"} <= set(b.grades)
    assert b.grades["K"].rank == 3  # weakest kicker in the league
    assert profs["A"].grades["FLEX"].rank == 1
    assert not set(b.needs) & {"K", "DEF", "FLEX", "W/R"}
    assert set(b.needs) <= {"QB", "RB", "WR", "TE"}
