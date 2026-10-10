import pytest

from app.services.leagues import assign_roster_slots
from signals.lineup import fit_to_slots

POS = {
    "qb1": "QB", "qb2": "QB", "rb1": "RB", "rb2": "RB", "rb3": "RB",
    "wr1": "WR", "wr2": "WR", "wr3": "WR", "te1": "TE", "k1": "K", "d1": "DEF",
}  # fmt: skip
STD = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"]


def roster(bench: int, ir: int = 0) -> list[str]:
    return STD + ["BN"] * bench + ["IR"] * ir


def test_fit_to_slots_uses_flex_and_superflex():
    slots = ["QB", "RB", "WR", "FLEX", "SUPER_FLEX"]
    assigned, unplaced = fit_to_slots(
        [("qb1", "QB"), ("qb2", "QB"), ("rb1", "RB"), ("rb2", "RB"), ("wr1", "WR")], slots
    )
    assert unplaced == []
    by_slot = dict(assigned)
    assert by_slot["QB"] in ("qb1", "qb2") and by_slot["SUPER_FLEX"] in ("qb1", "qb2")
    assert by_slot["FLEX"] in ("rb1", "rb2")


def test_fit_to_slots_reports_overflow():
    _, unplaced = fit_to_slots([("qb1", "QB"), ("qb2", "QB")], ["QB", "FLEX"])
    assert unplaced == ["qb2"]


def test_bench_depth_is_configurable():
    ids = list(POS)  # 11 players
    slots = assign_roster_slots(roster(bench=2), POS, ids, [], [])
    assert set(slots.values()) == {"bench"}  # no starters chosen → we pick the lineup
    with pytest.raises(ValueError, match="only 9 starting \\+ 1 bench"):
        assign_roster_slots(roster(bench=1), POS, ids, [], [])


def test_starters_bench_and_ir_assignment():
    ids = list(POS)
    starters = ["qb1", "rb1", "rb2", "wr1", "wr2", "te1", "rb3", "k1", "d1"]
    out = assign_roster_slots(roster(bench=1, ir=1), POS, ids, starters, ["qb2"])
    assert out["rb3"] == "starter"  # FLEX
    assert out["qb2"] == "ir"
    assert out["wr3"] == "bench"


def test_starter_that_does_not_fit_is_rejected():
    ids = list(POS)
    starters = ["qb1", "qb2", "rb1", "rb2", "wr1", "wr2", "te1", "k1", "d1"]  # 2 QBs, 1 QB slot
    with pytest.raises(ValueError, match="qb2 \\(QB\\)"):
        assign_roster_slots(roster(bench=4), POS, ids, starters, [])


def test_bench_overflow_with_starters_is_rejected():
    ids = list(POS)
    # 11 players fit 9 starting + 2 bench spots overall, but with only 1 starter marked,
    # the other 10 would all need bench spots
    with pytest.raises(ValueError, match="10 bench players but only 2 bench"):
        assign_roster_slots(roster(bench=2), POS, ids, ["qb1"], [])


@pytest.mark.parametrize(
    "positions, msg",
    [(["QB", "BN", "XX"], "unknown roster slot"), (["BN", "BN"], "at least one starting slot")],
)
def test_bad_roster_shapes(positions, msg):
    with pytest.raises(ValueError, match=msg):
        assign_roster_slots(positions, POS, ["qb1"], [], [])


def test_ir_limits_and_overlaps():
    with pytest.raises(ValueError, match="IR spot"):
        assign_roster_slots(roster(bench=2, ir=0), POS, ["qb1", "qb2"], [], ["qb2"])
    with pytest.raises(ValueError, match="both starting and on IR"):
        assign_roster_slots(roster(bench=2, ir=1), POS, ["qb1"], ["qb1"], ["qb1"])
    with pytest.raises(ValueError, match="twice"):
        assign_roster_slots(roster(bench=2), POS, ["qb1", "qb1"], [], [])
