"""Lineup slot eligibility and an optimal-lineup solver.

Greedy over slots from most to least restrictive, picking the best eligible remaining player.
For nested flex structures (QB/RB/WR/TE ⊂ FLEX ⊂ SUPER_FLEX) this is optimal.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

SLOT_ELIGIBILITY: dict[str, frozenset[str]] = {
    "QB": frozenset({"QB"}),
    "RB": frozenset({"RB"}),
    "WR": frozenset({"WR"}),
    "TE": frozenset({"TE"}),
    "K": frozenset({"K"}),
    "DEF": frozenset({"DEF"}),
    "FLEX": frozenset({"RB", "WR", "TE"}),
    "WRRB_FLEX": frozenset({"RB", "WR"}),
    "REC_FLEX": frozenset({"WR", "TE"}),
    "SUPER_FLEX": frozenset({"QB", "RB", "WR", "TE"}),
}
NON_STARTING = {"BN", "IR", "TAXI"}
SKILL_POSITIONS = ("QB", "RB", "WR", "TE")


def starting_slots(roster_positions: Iterable[str]) -> list[str]:
    return [s for s in roster_positions if s in SLOT_ELIGIBILITY]


def slot_label(slot: str) -> str:
    return {"SUPER_FLEX": "SFLEX", "WRRB_FLEX": "W/R", "REC_FLEX": "W/T"}.get(slot, slot)


@dataclass(frozen=True)
class LineupPlayer:
    player_id: str
    position: str
    points: float


@dataclass
class Lineup:
    slots: list[tuple[str, LineupPlayer | None]]

    @property
    def points(self) -> float:
        return sum(p.points for _, p in self.slots if p is not None)

    @property
    def starters(self) -> set[str]:
        return {p.player_id for _, p in self.slots if p is not None}


def _slot_order(slots: Sequence[str]) -> list[int]:
    return sorted(range(len(slots)), key=lambda i: (len(SLOT_ELIGIBILITY[slots[i]]), i))


def optimal_lineup(players: Iterable[LineupPlayer], slots: Sequence[str]) -> Lineup:
    pool = sorted(players, key=lambda p: -p.points)
    used: set[str] = set()
    filled: list[LineupPlayer | None] = [None] * len(slots)
    for i in _slot_order(slots):
        elig = SLOT_ELIGIBILITY[slots[i]]
        for p in pool:
            if p.player_id not in used and p.position in elig:
                filled[i] = p
                used.add(p.player_id)
                break
    return Lineup(list(zip(slots, filled, strict=True)))


def lineup_points(
    points: Mapping[str, float], positions: Mapping[str, str], slots: Sequence[str]
) -> float:
    """Fast path: best lineup points from {player_id: points} (players with 0 points still fill)."""
    players = [LineupPlayer(pid, positions[pid], pts) for pid, pts in points.items()]
    return optimal_lineup(players, slots).points


def fit_to_slots(
    players: Sequence[tuple[str, str]], slots: Sequence[str]
) -> tuple[list[tuple[str, str | None]], list[str]]:
    """Place chosen starters (player_id, position) into lineup slots, ignoring points.

    Slots are filled most-restrictive first, each taking the eligible player who fits the fewest
    slot types (so a QB isn't wasted on SUPER_FLEX while a RB could go there). Returns the slot
    assignment and any players that could not be placed.
    """
    reach = {pos: sum(pos in elig for elig in SLOT_ELIGIBILITY.values()) for pos in SKILL_POSITIONS}
    remaining = list(players)
    assigned: list[tuple[str, str | None]] = [(s, None) for s in slots]
    for i in _slot_order(slots):
        elig = SLOT_ELIGIBILITY[slots[i]]
        cands = [p for p in remaining if p[1] in elig]
        if not cands:
            continue
        pick = min(cands, key=lambda p: reach.get(p[1], 1))
        remaining.remove(pick)
        assigned[i] = (slots[i], pick[0])
    return assigned, [p[0] for p in remaining]
