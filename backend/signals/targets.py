"""Schedule-driven buy targets: who projects best each upcoming week and over the rest of season.

Each week's projection is the player's per-game projection × expected availability × the
matchup multiplier for that week's opponent (`signals.schedule.matchup_multiplier`, with each
position's backtest-tuned strength). Byes and games already played count 0. The neutral
projection (no matchup adjustment) is kept alongside so the schedule's effect is visible.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from projections.base import DEFAULT_INJURY, InjuryAssumptions, availability
from signals.schedule import Schedule, matchup_multiplier

POSITIONS = ("QB", "RB", "WR", "TE", "K", "DEF")
TOP_N = 10
UPCOMING_CELLS = 4  # opponents shown on a rest-of-season row


@dataclass(frozen=True)
class WeekCell:
    week: int
    opponent: str | None  # None on a bye
    index: float | None  # opponent's points-allowed index for the position (>1 easier)
    points: float
    neutral: float


@dataclass
class TargetRow:
    player_id: str
    position: str
    points: float
    neutral_points: float
    games: int
    avg_index: float | None
    cells: list[WeekCell] = field(default_factory=list)

    @property
    def schedule_delta(self) -> float:
        return round(self.points - self.neutral_points, 2)


def week_cells(
    player: Mapping,
    schedule: Schedule,
    index: Mapping[tuple[str, str], float],
    alpha: float,
    start: int,
    end: int,
    inj: InjuryAssumptions = DEFAULT_INJURY,
) -> list[WeekCell]:
    team, pos = player.get("nfl_team"), player.get("position") or ""
    ppg = float(player.get("ppg") or 0.0)
    cells = []
    for w in range(start, end + 1):
        opp = schedule.opponent(team, w)
        if not schedule.plays(team, w):  # bye, or this week's game is already final
            cells.append(WeekCell(w, opp, None, 0.0, 0.0))
            continue
        base = ppg * availability(player.get("injury_status"), player.get("status"), w, start, inj)
        mult = matchup_multiplier(index, opp, pos, alpha)
        cells.append(
            WeekCell(w, opp, round(index.get((opp, pos), 1.0), 3), round(base * mult, 2),
                     round(base, 2))
        )  # fmt: skip
    return cells


def all_cells(
    players: Mapping[str, Mapping],
    schedule: Schedule,
    index: Mapping[tuple[str, str], float],
    alpha: Mapping[str, float],
    start: int,
    end: int,
    inj: InjuryAssumptions = DEFAULT_INJURY,
) -> dict[str, list[WeekCell]]:
    """Week-by-week matchup-adjusted projections for every player (computed once per context)."""
    return {
        pid: week_cells(
            p, schedule, index, alpha.get(p.get("position") or "", 0.0), start, end, inj
        )
        for pid, p in players.items()
    }


def ros_points(cells: list[WeekCell]) -> float:
    return round(sum(c.points for c in cells), 2)


def rank_targets(
    players: Mapping[str, Mapping],
    cells: Mapping[str, list[WeekCell]],
    start: int,
    end: int,
    positions: Iterable[str] = POSITIONS,
    top: int = TOP_N,
) -> dict[str, dict]:
    """{position: {"ros": [TargetRow…], "weekly": {week: [TargetRow…]}}}, best first."""
    out: dict[str, dict] = {}
    for pos in positions:
        pids = [pid for pid, p in players.items() if p.get("position") == pos and pid in cells]
        ros = [ros_row(pid, pos, cells[pid]) for pid in pids]
        ros.sort(key=lambda r: (-r.points, r.player_id))
        weekly: dict[int, list[TargetRow]] = {}
        for i, w in enumerate(range(start, end + 1)):
            rows = []
            for pid in pids:
                c = cells[pid][i]
                if c.index is None:
                    continue
                rows.append(TargetRow(pid, pos, c.points, c.neutral, 1, c.index, [c]))
            rows.sort(key=lambda r: (-r.points, r.player_id))
            weekly[w] = rows[:top]
        out[pos] = {"ros": ros[:top], "weekly": weekly}
    return out


def ros_row(pid: str, pos: str, cells: list[WeekCell]) -> TargetRow:
    """Rest-of-season summary: total, neutral total, games, average opponent, next opponents."""
    played = [c for c in cells if c.index is not None]
    return TargetRow(
        pid, pos,
        ros_points(cells),
        round(sum(c.neutral for c in cells), 2),
        len(played),
        round(sum(c.index for c in played) / len(played), 3) if played else None,
        [c for c in cells if c.opponent is not None][:UPCOMING_CELLS],
    )  # fmt: skip
