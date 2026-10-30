"""Waiver wire: which free agents help *your* lineup most, who you'd drop, and what to bid.

A pickup is judged like a one-sided trade: rest-of-season starting-lineup points (bye- and
injury-aware, via `RosMath`) with the free agent added, minus today's. When the roster is full the
player a manager would cut (`trade.choose_drops`: an extra K/DEF, surplus depth, or the
lowest-value bench player; never IR/taxi players) goes, and his loss counts
against the pickup, so the gain shown is the net gain.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from signals import trade as tr
from signals.team import RosMath

POSITIONS = ("QB", "RB", "WR", "TE", "K", "DEF")
CANDIDATES_PER_POS = 25  # best free agents by ppg that get the quick screen
SCORED_PER_POS = 8  # best of those (by gain before any drop) that get the full evaluation

FAAB_FULL_GAIN = 40.0  # ROS points of net gain that justify the full aggression share of budget
FAAB_AGGRESSION = 0.5  # share of remaining budget bid on a pickup worth FAAB_FULL_GAIN or more
FAAB_MIN_BID = 1
FAAB_RANGE = (0.75, 1.25)


@dataclass
class WaiverPick:
    player_id: str
    position: str
    gain: float  # net ROS lineup points: with him (and after any forced drop) minus today
    drop: str | None  # the player you'd release to make room (None: you have an open spot)
    weeks: int  # remaining weeks the gain is spread over
    fixes_weeks: list[int] = field(default_factory=list)  # short weeks he fills
    need: bool = False  # fixes a short week, or plays a position you need
    drop_reason: str | None = None  # why that player (see trade.choose_drops)

    @property
    def gain_per_week(self) -> float:
        return round(self.gain / self.weeks, 2) if self.weeks else 0.0


def _candidates(
    free_agents: Iterable[str], players: Mapping[str, Mapping], math: RosMath
) -> list[str]:
    """The top free agents at each position by rest-of-season points (byes and injuries counted,
    so a player out for the season doesn't take a shortlist spot)."""
    free_agents = list(free_agents)
    ros = {pid: sum(math.week_points(pid).values()) for pid in free_agents}
    by_pos: dict[str, list[str]] = {}
    for pid in free_agents:
        p = players.get(pid)
        if p and p.get("position") in POSITIONS and ros[pid] > 0:
            by_pos.setdefault(p["position"], []).append(pid)
    out: list[str] = []
    for pids in by_pos.values():
        pids.sort(key=lambda q: (-ros[q], q))
        out += pids[:CANDIDATES_PER_POS]
    return out


def rank_waivers(
    math: RosMath,
    players: Mapping[str, Mapping],
    team_id: str,
    roster: Sequence[str],
    free_agents: Iterable[str],
    rules: tr.RosterRules,
    viable_ppg: Mapping[str, float] | None = None,
    needs: Iterable[str] = (),
) -> list[WaiverPick]:
    """Free agents that raise your rest-of-season lineup, best net gain first."""
    roster = list(roster)
    base = math.ros_lineup_points(roster)
    weeks = math.end - math.start + 1
    # quick screen: gain with nobody dropped (an upper bound on the net gain)
    screened: dict[str, list[tuple[float, str]]] = {}
    for pid in _candidates(free_agents, players, math):
        raw = math.ros_lineup_points([*roster, pid]) - base
        if raw > 0.05:
            screened.setdefault(players[pid]["position"], []).append((raw, pid))
    short_before = (
        set(tr.short_weeks(roster, players, math, viable_ppg)) if viable_ppg is not None else set()
    )
    needs = set(needs)
    picks: list[WaiverPick] = []
    for pos, cands in screened.items():
        for _, pid in sorted(cands, key=lambda c: (-c[0], c[1]))[:SCORED_PER_POS]:
            after, cut = tr.roster_after(math, players, team_id, roster, [], [pid], rules)
            gain = round(math.ros_lineup_points(after) - base, 1)
            if gain <= 0:
                continue
            fixes: list[int] = []
            if viable_ppg is not None:
                fixes = sorted(short_before - set(tr.short_weeks(after, players, math, viable_ppg)))
            picks.append(
                WaiverPick(
                    pid, pos, gain, cut[0].player_id if cut else None, weeks, fixes,
                    need=bool(fixes) or pos in needs,
                    drop_reason=cut[0].reason if cut else None,
                )
            )  # fmt: skip
    picks.sort(key=lambda w: (-w.gain, w.player_id))
    return picks


def faab_bid(
    gain: float,
    remaining: int | None,
    full_gain: float = FAAB_FULL_GAIN,
    aggression: float = FAAB_AGGRESSION,
    min_bid: int = FAAB_MIN_BID,
) -> tuple[int, int, int] | None:
    """(low, suggested, high) FAAB bid for a pickup worth `gain` net ROS points.

    suggested = remaining x min(gain / full_gain, 1) x aggression, never below `min_bid` or above
    what's left; the range is 75%-125% of it, clamped the same way. None when there's no budget.
    """
    if remaining is None:
        return None
    if remaining <= 0:
        return (0, 0, 0)

    def clamp(x: float) -> int:
        return int(max(min(min_bid, remaining), min(round(x), remaining)))

    share = min(max(gain, 0.0) / full_gain, 1.0) if full_gain > 0 else 1.0
    bid = remaining * share * aggression
    return clamp(bid * FAAB_RANGE[0]), clamp(bid), clamp(bid * FAAB_RANGE[1])
