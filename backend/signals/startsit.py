"""This week's lineup: your real one, the best one, and what's locked.

Shared by My Team ("Best lineup"), the Advisor's start/sit cards and the Start/Sit planner so all
three always agree. Players whose game this week is already final are *locked*: a locked starter
keeps his slot (his points are banked) and a locked bench player can't come in. Players on IR or
taxi can't start. Everyone else competes for the remaining slots on this week's (matchup-adjusted)
projection.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

from signals.lineup import LineupPlayer, fit_to_slots, optimal_lineup
from signals.schedule import Schedule
from signals.team import RosMath


@dataclass
class WeekPlan:
    slots: list[str]
    current: list[str | None]  # your real lineup, one entry per slot (None = empty)
    optimal: list[str | None]  # the best lineup, same order
    points: dict[str, float]  # this week's projection for every roster player
    locked: frozenset[str]

    def total(self, lineup: Sequence[str | None]) -> float:
        return round(sum(self.points.get(p, 0.0) for p in lineup if p), 2)

    @property
    def current_points(self) -> float:
        return self.total(self.current)

    @property
    def optimal_points(self) -> float:
        return self.total(self.optimal)

    @property
    def starters(self) -> set[str]:
        return {p for p in self.optimal if p}


def locked_players(
    roster: Sequence[str], players: Mapping[str, Mapping], schedule: Schedule, week: int
) -> frozenset[str]:
    """Roster players whose game this week is already final."""
    out = set()
    for pid in roster:
        team = players.get(pid, {}).get("nfl_team")
        if schedule.has_game(team, week) and not schedule.plays(team, week):
            out.add(pid)
    return frozenset(out)


def plan_week(
    math: RosMath,
    players: Mapping[str, Mapping],
    roster: Sequence[str],
    starters: Sequence[str],
    week: int,
    locked: Collection[str] = (),
    reserved: Collection[str] = (),
) -> WeekPlan:
    slots = list(math.slots)
    pos = {p: players[p]["position"] for p in roster if p in players}
    points = {p: round(math.week_points(p)[week], 2) for p in pos}
    placed, _ = fit_to_slots([(p, pos[p]) for p in starters if p in pos], slots)
    current = [pid for _, pid in placed]
    locked = frozenset(p for p in locked if p in pos)
    fixed = {i: pid for i, pid in enumerate(current) if pid in locked}
    free = [i for i in range(len(slots)) if i not in fixed]
    cands = [
        LineupPlayer(p, pos[p], points[p])
        for p in pos
        if p not in locked and p not in reserved and points[p] > 0
    ]
    best = optimal_lineup(cands, [slots[i] for i in free])
    optimal: list[str | None] = [None] * len(slots)
    for i, pid in fixed.items():
        optimal[i] = pid
    for i, (_, lp) in zip(free, best.slots, strict=True):
        optimal[i] = lp.player_id if lp else None
    return WeekPlan(slots, current, optimal, points, locked)
