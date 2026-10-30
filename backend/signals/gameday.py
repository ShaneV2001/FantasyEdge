"""Game-day alerts: starters who might not play this week, and who to put in instead.

Injury statuses come from Sleeper (refreshed with the player list); practice reports from the
nflverse injury report. A starter whose game has kicked off is locked and never flagged.

The pivot is the best bench player who can fill the same slot. For a Questionable or Doubtful
starter, if that bench player kicks off *earlier*, you'd have to decide before inactives are
announced (about 90 minutes before kickoff), so a backup who plays at the same time or later is
offered as a hedge.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from datetime import datetime

from signals.lineup import SLOT_ELIGIBILITY
from signals.schedule import Schedule
from signals.startsit import WeekPlan

# Sleeper injury_status / nflverse report_status -> how likely he sits
STATUS_SEVERITY = {
    "Out": "out", "IR": "out", "PUP": "out", "NFI": "out", "Sus": "out", "COV": "out",
    "Doubtful": "high", "Questionable": "medium",
}  # fmt: skip
SEVERITY_ORDER = {"out": 0, "high": 1, "medium": 2, "low": 3}
UNCERTAIN = ("high", "medium")  # he may or may not play: worth a hedge


def practice_label(raw: str | None) -> str | None:
    """nflverse's practice participation text, shortened: DNP / Limited / Full."""
    if not raw:
        return None
    low = raw.lower()
    if low.startswith("did not"):
        return "DNP"
    if low.startswith("limited"):
        return "Limited"
    if low.startswith("full"):
        return "Full"
    return raw


@dataclass(frozen=True)
class Pivot:
    player_id: str
    points: float
    kickoff: datetime | None


@dataclass
class Alert:
    player_id: str
    slot: str
    severity: str  # out | high | medium | low
    status: str  # Out, Doubtful, Questionable, Bye, or a practice report
    points: float  # this week's projection (already discounted for the status)
    kickoff: datetime | None
    reasons: list[str] = field(default_factory=list)
    pivot: Pivot | None = None  # best bench replacement for the slot
    late_pivot: Pivot | None = None  # best bench replacement kicking off no earlier than him
    free_agent: Pivot | None = None  # best free agent for the slot, when he beats the bench


def _status(
    p: Mapping, practice: tuple[str | None, str | None] | None
) -> tuple[str | None, str | None]:
    """(severity, label) from the stronger of Sleeper's status and the official report."""
    best: tuple[str | None, str | None] = (None, None)
    for raw in (p.get("injury_status"), practice[0] if practice else None):
        sev = STATUS_SEVERITY.get(raw or "")
        if sev and (best[0] is None or SEVERITY_ORDER[sev] < SEVERITY_ORDER[best[0]]):
            best = (sev, raw)
    if best[0] is None and practice and practice_label(practice[1]) == "DNP":
        best = ("low", "Missed practice")
    return best


def _best(
    cands: list[str],
    points: Mapping[str, float],
    players: Mapping[str, Mapping],
    schedule: Schedule,
    week: int,
) -> Pivot | None:
    best = max(cands, key=points.__getitem__, default=None)
    if best is None:
        return None
    return Pivot(
        best, round(points[best], 2), schedule.kickoff(players[best].get("nfl_team"), week)
    )


def alerts(
    plan: WeekPlan,
    players: Mapping[str, Mapping],
    schedule: Schedule,
    week: int,
    now: datetime,
    practice: Mapping[str, tuple[str | None, str | None]] | None = None,
    reserved: Collection[str] = (),
    free_agents: Mapping[str, float] | None = None,
) -> list[Alert]:
    """Alerts for this week's starters, most serious first. `practice` is player id ->
    (report status, practice participation); `free_agents` is player id -> this week's points."""
    practice = practice or {}
    in_lineup = {p for p in plan.current if p}
    out: list[Alert] = []
    for slot, pid in zip(plan.slots, plan.current, strict=True):
        if not pid or pid in plan.locked or pid not in players:
            continue
        p = players[pid]
        team = p.get("nfl_team")
        kick = schedule.kickoff(team, week)
        if team and schedule.started(team, week, now):
            continue
        if not schedule.has_game(team, week):
            sev, label = "out", "Bye"
        else:
            sev, label = _status(p, practice.get(pid))
        if sev is None or label is None:
            continue
        a = Alert(pid, slot, sev, label, plan.points.get(pid, 0.0), kick)
        prac = practice_label((practice.get(pid) or (None, None))[1])
        if label == "Bye":
            a.reasons.append(f"{p['name']} is on bye in week {week}.")
        else:
            a.reasons.append(f"{p['name']} is listed {label}.")
        if prac and label != "Missed practice":
            a.reasons.append(f"Latest practice report: {prac}.")
        detail = p.get("injury_detail")
        if detail and label != "Bye":
            a.reasons.append(f"Injury: {detail}.")

        eligible = SLOT_ELIGIBILITY.get(slot, frozenset())
        bench = [
            b
            for b in plan.points
            if b not in in_lineup
            and b not in plan.locked
            and b not in reserved
            and players.get(b, {}).get("position") in eligible
            and plan.points[b] > 0
            and _status(players[b], practice.get(b))[0] not in ("out", "high")
        ]

        a.pivot = _best(bench, plan.points, players, schedule, week)
        if sev in UNCERTAIN and a.pivot and kick and a.pivot.kickoff and a.pivot.kickoff < kick:
            later = [
                b
                for b in bench
                if (k := schedule.kickoff(players[b].get("nfl_team"), week)) and k >= kick
            ]
            a.late_pivot = _best(later, plan.points, players, schedule, week)
        if free_agents:
            fas = [
                f
                for f, pts in free_agents.items()
                if pts > 0 and players.get(f, {}).get("position") in eligible
                and _status(players[f], practice.get(f))[0] not in ("out", "high")
                and not schedule.started(players[f].get("nfl_team"), week, now)
            ]  # fmt: skip
            fa = _best(fas, free_agents, players, schedule, week)
            if fa and fa.points > (a.pivot.points if a.pivot else 0.0):
                a.free_agent = fa
        out.append(a)
    out.sort(key=lambda a: (SEVERITY_ORDER[a.severity], -a.points))
    return out
