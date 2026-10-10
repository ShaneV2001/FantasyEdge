"""Team-level math shared by trades, grades and the advisor.

`RosMath` turns per-player weekly projections into rest-of-season *starting lineup* points for any
set of players (bye- and injury-aware), memoised so trade search stays fast.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from projections.base import weekly_points
from signals.lineup import SKILL_POSITIONS, Lineup, LineupPlayer, optimal_lineup
from signals.schedule import Schedule


class RosMath:
    def __init__(
        self,
        players: Mapping[str, Mapping],
        schedule: Schedule,
        start_week: int,
        end_week: int,
        slots: Sequence[str],
    ):
        self.players = players
        self.schedule = schedule
        self.start, self.end = start_week, end_week
        self.slots = list(slots)
        self._weekly: dict[str, dict[int, float]] = {}
        self._memo: dict[tuple, float] = {}

    def week_points(self, pid: str) -> dict[int, float]:
        if pid not in self._weekly:
            p = self.players.get(pid)
            if p is None:
                self._weekly[pid] = dict.fromkeys(range(self.start, self.end + 1), 0.0)
            else:
                self._weekly[pid] = weekly_points(
                    p.get("ppg") or 0.0,
                    p.get("nfl_team"),
                    p.get("injury_status"),
                    p.get("status"),
                    self.schedule,
                    self.start,
                    self.end,
                )
        return self._weekly[pid]

    def _pos(self, pid: str) -> str:
        p = self.players.get(pid)
        return p["position"] if p else "?"

    def lineup_for_week(self, pids: Iterable[str], week: int) -> Lineup:
        avail = [LineupPlayer(p, self._pos(p), self.week_points(p)[week]) for p in pids]
        return optimal_lineup([a for a in avail if a.points > 0], self.slots)

    def week_lineup_points(self, pids: Iterable[str], week: int) -> float:
        pts = tuple(
            sorted(
                (p, round(self.week_points(p)[week], 3))
                for p in pids
                if self.week_points(p)[week] > 0
            )
        )
        if pts not in self._memo:
            players = [LineupPlayer(p, self._pos(p), v) for p, v in pts]
            self._memo[pts] = optimal_lineup(players, self.slots).points
        return self._memo[pts]

    def ros_lineup_points(self, pids: Iterable[str]) -> float:
        pids = list(pids)
        return sum(self.week_lineup_points(pids, w) for w in range(self.start, self.end + 1))


# ───────── grades, needs & surplus ─────────


def _grade(delta: float) -> str:
    if delta >= 0.15:
        return "A"
    if delta >= 0.05:
        return "B"
    if delta > -0.05:
        return "C"
    if delta > -0.15:
        return "D"
    return "F"


@dataclass
class PositionGrade:
    position: str
    points: float
    league_avg: float
    rank: int
    teams: int
    grade: str
    delta_pct: float


@dataclass
class TeamProfile:
    team_id: str
    grades: dict[str, PositionGrade]
    starters: list[str]
    needs: list[str] = field(default_factory=list)
    surplus: list[str] = field(default_factory=list)
    starter_points: float = 0.0


def full_strength_lineup(
    pids: Iterable[str], players: Mapping[str, Mapping], slots: Sequence[str]
) -> Lineup:
    pool = [
        LineupPlayer(p, players[p]["position"], players[p].get("ppg") or 0.0)
        for p in pids
        if p in players
    ]
    return optimal_lineup(pool, slots)


def team_profiles(
    rosters: Mapping[str, list[str]], players: Mapping[str, Mapping], slots: Sequence[str]
) -> dict[str, TeamProfile]:
    """Position strength (starter PPG by player position) graded vs league average,
    plus needs (weak starters) and surplus (bench players who would start elsewhere)."""
    lineups = {t: full_strength_lineup(p, players, slots) for t, p in rosters.items()}
    pos_points = {
        t: {
            pos: sum(lp.points for _, lp in lu.slots if lp and lp.position == pos)
            for pos in SKILL_POSITIONS
        }
        for t, lu in lineups.items()
    }
    starter_ppg: dict[str, list[float]] = {pos: [] for pos in SKILL_POSITIONS}
    for lu in lineups.values():
        for _, lp in lu.slots:
            if lp and lp.position in starter_ppg:
                starter_ppg[lp.position].append(lp.points)
    median = {pos: sorted(v)[len(v) // 2] if v else 0.0 for pos, v in starter_ppg.items()}

    n = len(rosters)
    out: dict[str, TeamProfile] = {}
    for t, pts in pos_points.items():
        grades = {}
        for pos in SKILL_POSITIONS:
            vals = sorted((pp[pos] for pp in pos_points.values()), reverse=True)
            avg = sum(vals) / n if n else 0.0
            delta = (pts[pos] - avg) / avg if avg else 0.0
            grades[pos] = PositionGrade(
                pos,
                round(pts[pos], 2),
                round(avg, 2),
                vals.index(pts[pos]) + 1,
                n,
                _grade(delta),
                round(delta, 3),
            )
        lu = lineups[t]
        starters = [lp.player_id for _, lp in lu.slots if lp]
        bench = [p for p in rosters[t] if p not in starters and p in players]
        needs = [
            pos for pos in SKILL_POSITIONS
            if grades[pos].grade in ("D", "F") or (n >= 6 and grades[pos].rank > n * 2 / 3)
        ]  # fmt: skip
        surplus = sorted(
            {
                players[p]["position"]
                for p in bench
                if players[p]["position"] in median
                and (players[p].get("ppg") or 0) >= median[players[p]["position"]] * 0.85
            }
        )
        out[t] = TeamProfile(
            t, grades, starters, needs, [s for s in surplus if s not in needs], round(lu.points, 2)
        )
    return out
