"""Lineup slot eligibility and an optimal-lineup solver.

When every pair of slot eligibility sets is nested or disjoint (QB/RB/WR/TE ⊂ FLEX ⊂ SUPER_FLEX),
filling slots from most to least restrictive with the best eligible remaining player is optimal.
Overlapping-but-not-nested flexes (W/R next to W/T) break that, so those lineups are solved
exactly as an assignment problem.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

SKILL_POSITIONS = ("QB", "RB", "WR", "TE")
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
    "SUPER_FLEX": frozenset(SKILL_POSITIONS),
}
NON_STARTING = {"BN", "IR", "TAXI"}
# Bench depth worth keeping at each skill position beyond the slots it fills (byes, injuries); a
# user setting. Kickers and defenses are streamed, so a second one is dead weight.
BENCH_BACKUPS = 1


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


def position_capacity(lineup: Lineup, backups: int = BENCH_BACKUPS) -> dict[str, int]:
    """How many players at each position a roster can usefully hold, given its best lineup: the
    position's dedicated slots, plus each flex slot once, for the position of the player the lineup
    puts there (an empty flex counts for nobody), plus `backups` at QB/RB/WR/TE (none for K/DEF).
    So in a Superflex league whose 2nd QB takes SUPER_FLEX, TEs don't also get credit for it."""
    cap = dict.fromkeys((*SKILL_POSITIONS, "K", "DEF"), 0)
    for slot, player in lineup.slots:
        if slot in cap:  # dedicated slot: counts even when nobody can fill it this week
            cap[slot] += 1
        elif player is not None:
            cap[player.position] += 1
    for pos in SKILL_POSITIONS:
        cap[pos] += backups
    return cap


def _slot_order(slots: Sequence[str]) -> list[int]:
    return sorted(range(len(slots)), key=lambda i: (len(SLOT_ELIGIBILITY[slots[i]]), i))


def _is_laminar(slots: Sequence[str]) -> bool:
    sets = list({SLOT_ELIGIBILITY[s] for s in slots})
    return all(a <= b or b <= a or not (a & b) for i, a in enumerate(sets) for b in sets[i + 1 :])


def optimal_lineup(players: Iterable[LineupPlayer], slots: Sequence[str]) -> Lineup:
    pool = sorted(players, key=lambda p: -p.points)
    if not _is_laminar(slots):
        return _assignment_lineup(pool, slots)
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


_INELIGIBLE = 1e9
_FILL_BONUS = 1e-6  # prefer starting a 0-point player over leaving a slot empty


def _assignment_lineup(pool: Sequence[LineupPlayer], slots: Sequence[str]) -> Lineup:
    """Exact max-points lineup via the Hungarian algorithm (slots × candidates + empty seats)."""
    # Only a position's top-k players can start, k = number of slots that accept it.
    room = {
        pos: sum(pos in SLOT_ELIGIBILITY[s] for s in slots) for pos in {p.position for p in pool}
    }
    cands: list[LineupPlayer] = []
    for p in pool:  # sorted best first
        if room.get(p.position, 0) > 0:
            cands.append(p)
            room[p.position] -= 1
    n = len(slots)
    cost = [
        [
            -(p.points + _FILL_BONUS) if p.position in SLOT_ELIGIBILITY[s] else _INELIGIBLE
            for p in cands
        ]
        + [0.0] * n  # one "leave empty" seat per slot
        for s in slots
    ]
    cols = _hungarian(cost)
    filled = [cands[c] if c < len(cands) else None for c in cols]
    return Lineup(list(zip(slots, filled, strict=True)))


def _hungarian(cost: Sequence[Sequence[float]]) -> list[int]:
    """Min-cost assignment of every row to a distinct column (rows <= cols). O(rows² · cols)."""
    n, m = len(cost), len(cost[0])
    inf = float("inf")
    u, v = [0.0] * (n + 1), [0.0] * (m + 1)
    match, way = [0] * (m + 1), [0] * (m + 1)  # match[col] = row (1-based), 0 = free
    for row in range(1, n + 1):
        match[0], j0 = row, 0
        minv, used = [inf] * (m + 1), [False] * (m + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = match[j0], inf, 0
            for j in range(1, m + 1):
                if not used[j]:
                    cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j], way[j] = cur, j0
                    if minv[j] < delta:
                        delta, j1 = minv[j], j
            for j in range(m + 1):
                if used[j]:
                    u[match[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if match[j0] == 0:
                break
        while j0:
            j1 = way[j0]
            match[j0] = match[j1]
            j0 = j1
    out = [0] * n
    for j in range(1, m + 1):
        if match[j]:
            out[match[j] - 1] = j - 1
    return out


def lineup_points(
    points: Mapping[str, float], positions: Mapping[str, str], slots: Sequence[str]
) -> float:
    """Fast path: best lineup points from {player_id: points} (players with 0 points still fill)."""
    players = [LineupPlayer(pid, positions[pid], pts) for pid, pts in points.items()]
    return optimal_lineup(players, slots).points


def fit_to_slots(
    players: Sequence[tuple[str, str]],
    slots: Sequence[str],
    points: Mapping[str, float] | None = None,
) -> tuple[list[tuple[str, str | None]], list[str]]:
    """Place chosen starters (player_id, position) into lineup slots.

    Slots are filled most-restrictive first, each taking the eligible player who fits the fewest
    slot types (so a QB isn't wasted on SUPER_FLEX while a RB could go there), then the one with
    the most `points`: your best WR takes the WR slot and the next one the FLEX. Returns the slot
    assignment and any players that could not be placed.
    """
    reach = {pos: sum(pos in elig for elig in SLOT_ELIGIBILITY.values()) for pos in SKILL_POSITIONS}
    pts = points or {}
    remaining = list(players)
    assigned: list[tuple[str, str | None]] = [(s, None) for s in slots]
    for i in _slot_order(slots):
        elig = SLOT_ELIGIBILITY[slots[i]]
        cands = [p for p in remaining if p[1] in elig]
        if not cands:
            continue
        pick = min(cands, key=lambda p: (reach.get(p[1], 1), -pts.get(p[0], 0.0)))
        remaining.remove(pick)
        assigned[i] = (slots[i], pick[0])
    return assigned, [p[0] for p in remaining]
