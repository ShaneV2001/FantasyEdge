"""Bye-week planner: week × lineup-slot grid, unfillable slots and danger weeks.

A slot is
  ok    — filled by a player projected at or above replacement level for his position,
  thin  — filled, but only by a below-replacement player,
  empty — nobody eligible is available.
A *danger week* is one where some slot is worse than it is at full strength (i.e. the bye or an
injury creates the hole), so a weak position all season doesn't flag every week.

For the grid, a cell is a *fill-in* when its player isn't one of the full-strength starters
(`replaces` names the starter who is out, `why` says bye or injury), and a *hole* when nobody can
fill a slot that is filled at full strength.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from projections.base import DEFAULT_INJURY, InjuryAssumptions, availability
from signals.lineup import LineupPlayer, optimal_lineup, slot_label
from signals.schedule import Schedule

STATUS_RANK = {"ok": 0, "thin": 1, "empty": 2}


@dataclass(frozen=True)
class RosterEntry:
    player_id: str
    name: str
    position: str
    nfl_team: str | None
    ppg: float
    injury_status: str | None = None
    status: str | None = None
    return_week: int | None = None  # first week back when known (projections.base.SEASON_OUT)


@dataclass
class SlotCell:
    slot: str
    label: str
    status: str
    player_id: str | None = None
    name: str | None = None
    position: str | None = None
    ppg: float | None = None
    replaces: str | None = None  # the full-strength starter this fill-in stands in for
    why: str | None = None  # "bye" or "injury": why that starter is out
    hole: bool = False  # empty this week, filled at full strength


@dataclass
class ByeWeekRow:
    week: int
    weeks_away: int
    cells: list[SlotCell]
    on_bye: list[str]  # names of rostered players on bye
    starters_on_bye: list[str]  # names of full-strength starters on bye
    danger: bool
    danger_slots: list[str] = field(default_factory=list)
    lineup_points: float = 0.0
    full_strength_points: float = 0.0


def _cells(
    roster: dict[str, RosterEntry],
    available: list[LineupPlayer],
    slots: list[str],
    viable_ppg: dict[str, float],
) -> tuple[list[SlotCell], float]:
    lineup = optimal_lineup(available, slots)
    cells = []
    for slot, lp in lineup.slots:
        if lp is None:
            cells.append(SlotCell(slot, slot_label(slot), "empty"))
            continue
        e = roster[lp.player_id]
        ok = e.ppg >= viable_ppg.get(e.position, 0.0)
        cells.append(
            SlotCell(
                slot,
                slot_label(slot),
                "ok" if ok else "thin",
                e.player_id,
                e.name,
                e.position,
                round(e.ppg, 2),
            )
        )
    return cells, lineup.points


def bye_grid(
    roster_entries: list[RosterEntry],
    slots: list[str],
    schedule: Schedule,
    start_week: int,
    end_week: int,
    viable_ppg: dict[str, float],
    inj: InjuryAssumptions = DEFAULT_INJURY,
) -> list[ByeWeekRow]:
    roster = {e.player_id: e for e in roster_entries}
    full = [LineupPlayer(e.player_id, e.position, e.ppg) for e in roster_entries]
    base_cells, base_pts = _cells(roster, full, slots, viable_ppg)
    base_starters = {c.player_id for c in base_cells if c.player_id}

    rows = []
    for w in range(start_week, end_week + 1):
        avail = []
        for e in roster_entries:
            if not schedule.has_game(e.nfl_team, w):
                continue
            a = availability(e.injury_status, e.status, w, start_week, inj, e.return_week)
            if a > 0:
                avail.append(LineupPlayer(e.player_id, e.position, e.ppg * a))
        cells, pts = _cells(roster, avail, slots, viable_ppg)
        _mark_changes(cells, base_cells, base_starters, roster, schedule, w)
        danger_slots = [
            c.label
            for c, b in zip(cells, base_cells, strict=True)
            if STATUS_RANK[c.status] > STATUS_RANK[b.status]
        ]
        on_bye = [e for e in roster_entries if schedule.bye(e.nfl_team) == w]
        rows.append(
            ByeWeekRow(
                week=w,
                weeks_away=w - start_week,
                cells=cells,
                on_bye=[e.name for e in on_bye],
                starters_on_bye=[e.name for e in on_bye if e.player_id in base_starters],
                danger=bool(danger_slots),
                danger_slots=danger_slots,
                lineup_points=round(pts, 2),
                full_strength_points=round(base_pts, 2),
            )
        )
    return rows


def _mark_changes(
    cells: list[SlotCell],
    base_cells: list[SlotCell],
    base_starters: set[str],
    roster: dict[str, RosterEntry],
    schedule: Schedule,
    week: int,
) -> None:
    """Tag this week's fill-ins with the full-strength starter each stands in for (same position
    first) and why he's out, and mark slots that are empty only this week."""
    starting = {c.player_id for c in cells if c.player_id}
    out = [roster[p] for p in base_starters if p not in starting]
    out.sort(key=lambda e: -e.ppg)

    def why(e: RosterEntry) -> str:
        return "bye" if not schedule.has_game(e.nfl_team, week) else "injury"

    # an empty slot names the starter it normally has, so a week's summary lists everyone out
    for c, b in zip(cells, base_cells, strict=True):
        c.hole = c.player_id is None and b.player_id is not None
        if c.hole and (starter := roster.get(b.player_id)) in out:
            out.remove(starter)
            c.replaces, c.why = starter.name, why(starter)
    for c in cells:
        if not c.player_id or c.player_id in base_starters or not out:
            continue
        starter = next((e for e in out if e.position == c.position), out[0])
        out.remove(starter)
        c.replaces, c.why = starter.name, why(starter)


def bye_overlap(team_byes: list[int | None], candidate_bye: int | None, start_week: int) -> int:
    """How many of the given starters share the candidate's (still upcoming) bye week."""
    if candidate_bye is None or candidate_bye < start_week:
        return 0
    return sum(1 for b in team_byes if b == candidate_bye)
