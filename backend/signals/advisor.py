"""Advisor feed: ranked, explainable actions for one team.

priority = urgency weight × impact × confidence weight — all constants below, nothing hidden.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from signals.byes import ByeWeekRow
from signals.lineup import SLOT_ELIGIBILITY, fit_to_slots
from signals.team import RosMath, TeamProfile
from signals.trade import TradeEvaluation
from signals.verdict import threshold as verdict_threshold

URGENCY_WEIGHT = {
    "this_week": 3.0,
    "before_byes": 2.2,
    "before_deadline": 1.6,
    "rest_of_season": 1.0,
}
CONFIDENCE_WEIGHT = {"high": 1.0, "medium": 0.75, "low": 0.5}

TOUGH_SCHEDULE = 0.92  # matchup index below this = tough
EASY_SCHEDULE = 1.08
BYE_HORIZON = 4  # weeks ahead to warn about danger weeks
WAIVER_MIN_GAIN = 1.5  # ppg over the player he'd replace
START_SIT_MIN_GAIN = 1.0


@dataclass
class Action:
    type: str  # Trade | Sell | Buy | Waiver | Lineup | Bye prep
    headline: str
    reasons: list[str]
    urgency: str
    confidence: str
    impact: float
    player_ids: list[str] = field(default_factory=list)
    team_id: str | None = None  # counterparty for Buy/Trade
    trade: TradeEvaluation | None = None

    @property
    def priority(self) -> float:
        return round(
            URGENCY_WEIGHT[self.urgency] * self.impact * CONFIDENCE_WEIGHT[self.confidence], 3
        )


@dataclass
class AdvisorInputs:
    my_team_id: str
    rosters: Mapping[str, Sequence[str]]
    team_names: Mapping[str, str]
    starters: Sequence[str]  # current (platform) starters; empty for manual leagues
    players: Mapping[str, Mapping]
    profiles: Mapping[str, TeamProfile]
    byes: Sequence[ByeWeekRow]
    math: RosMath
    week: int
    trade_deadline_week: int | None
    trade_ideas: Sequence[TradeEvaluation]
    free_agents: Sequence[str] | None  # None when the player pool is unknown (manual league)
    regression_messages: Mapping[str, list[str]]
    market_label: str = "Market"
    playoff_label: str = "weeks 15-17"


def _name(players: Mapping[str, Mapping], pid: str) -> str:
    return players.get(pid, {}).get("name", pid)


def deadline_passed(inp: AdvisorInputs) -> bool:
    d = inp.trade_deadline_week
    return d is not None and inp.week > d


def trade_urgency(inp: AdvisorInputs) -> str:
    return "before_deadline" if inp.trade_deadline_week is not None else "rest_of_season"


# ───────── generators ─────────


def lineup_actions(inp: AdvisorInputs) -> list[Action]:
    if not inp.starters:
        return []
    my = list(inp.rosters[inp.my_team_id])
    best = inp.math.lineup_for_week(my, inp.week)
    best_ids = best.starters
    current = [p for p in inp.starters if p in inp.players]
    pts = {p: inp.math.week_points(p)[inp.week] for p in my}
    actions = []
    benched_better = sorted((p for p in best_ids if p not in current), key=lambda p: -pts[p])
    sat = sorted((p for p in current if p not in best_ids), key=lambda p: pts[p])
    pos = {p: inp.players[p]["position"] for p in my if p in inp.players}
    lineup = list(current)
    pairs = []
    for add in benched_better:
        # swap only with a starter whose removal keeps the lineup legal (no RB-for-K swaps)
        for drop in sat:
            trial = [p for p in lineup if p != drop] + [add]
            if not fit_to_slots([(p, pos[p]) for p in trial], inp.math.slots)[1]:
                pairs.append((add, drop))
                sat.remove(drop)
                lineup = trial
                break
    for add, drop in pairs:
        gain = pts[add] - pts[drop]
        if gain < START_SIT_MIN_GAIN:
            continue
        a, d = inp.players[add], inp.players[drop]
        reasons = [f"Projected {pts[add]:.1f} vs {pts[drop]:.1f} points this week (+{gain:.1f})."]
        if not inp.math.schedule.has_game(d.get("nfl_team"), inp.week):
            reasons.append(f"{d['name']} is on bye in week {inp.week}.")
        elif d.get("injury_status"):
            reasons.append(f"{d['name']} is listed {d['injury_status']}.")
        if a.get("ease_next4") and a["ease_next4"] >= EASY_SCHEDULE:
            reasons.append(f"{a['name']} has a favourable matchup.")
        actions.append(
            Action("Lineup", f"Start {a['name']} over {d['name']}", reasons, "this_week",
                   "high" if gain >= 4 or pts[drop] == 0 else "medium", min(gain / 2, 5.0), [add, drop])
        )  # fmt: skip
    return actions


def bye_actions(inp: AdvisorInputs) -> list[Action]:
    actions = []
    for row in inp.byes:
        if not row.danger or row.weeks_away > BYE_HORIZON:
            continue
        lost = row.full_strength_points - row.lineup_points
        reasons = [
            f"{', '.join(row.danger_slots)} slot(s) can't be filled with a viable starter in week {row.week}"
            + (
                f" ({row.weeks_away} week{'s' if row.weeks_away != 1 else ''} away)."
                if row.weeks_away
                else " (this week)."
            ),
            f"Projected lineup {row.lineup_points:.1f} vs {row.full_strength_points:.1f} at full strength (−{lost:.1f}).",
        ]
        if row.starters_on_bye:
            reasons.append(f"On bye: {', '.join(row.starters_on_bye)}.")
        fa = _best_fa_for_slots(inp, row.danger_slots, row.week)
        pids = []
        if fa:
            reasons.append(
                f"Streamer: {_name(inp.players, fa)} ({inp.players[fa]['ppg']:.1f} ppg) is available."
            )
            pids.append(fa)
        urgency = "this_week" if row.weeks_away <= 1 else "before_byes"
        actions.append(
            Action("Bye prep", f"Week {row.week}: no viable {'/'.join(row.danger_slots)}", reasons,
                   urgency, "high", min(lost / 3, 5.0), pids)
        )  # fmt: skip
    return actions


def _slot_positions(labels: Sequence[str]) -> set[str]:
    rev = {"SFLEX": "SUPER_FLEX", "W/R": "WRRB_FLEX", "W/T": "REC_FLEX"}
    out: set[str] = set()
    for lab in labels:
        out |= SLOT_ELIGIBILITY.get(rev.get(lab, lab), frozenset())
    return out


def _best_fa_for_slots(inp: AdvisorInputs, labels: Sequence[str], week: int) -> str | None:
    if not inp.free_agents:
        return None
    positions = _slot_positions(labels)
    cands = [
        p for p in inp.free_agents
        if inp.players.get(p, {}).get("position") in positions
        and inp.math.schedule.has_game(inp.players[p].get("nfl_team"), week)
    ]  # fmt: skip
    return max(cands, key=lambda p: inp.players[p].get("ppg") or 0, default=None)


def _gap_confidence(p: Mapping) -> str:
    """How far past the buy/sell line the value gap is."""
    gap, implied = p.get("value_gap"), p.get("market_implied_points")
    if gap is None or not implied:
        return "low"
    ratio = abs(gap) / verdict_threshold(implied)
    return "high" if ratio >= 2 else "medium" if ratio >= 1.4 else "low"


def _gap_impact(p: Mapping) -> float:
    return min(abs(p.get("value_gap") or 0.0) / 15, 5.0)


def sell_actions(inp: AdvisorInputs) -> list[Action]:
    """Your players whose verdict is Sell: the market pays more than we project."""
    if deadline_passed(inp):
        return []
    actions = []
    for pid in inp.rosters[inp.my_team_id]:
        p = inp.players.get(pid)
        if not p or p.get("signal") != "sell":
            continue
        reasons = list(p.get("signal_reasons") or [])
        bye = p.get("bye_week")
        if bye is not None and inp.week <= bye <= inp.week + 3:
            reasons.append(f"Bye in week {bye} is coming up.")
        if p.get("ease_playoffs") and p["ease_playoffs"] <= TOUGH_SCHEDULE:
            reasons.append(
                f"Tough fantasy-playoff schedule, {inp.playoff_label} "
                f"(index {p['ease_playoffs']:.2f})."
            )
        actions.append(
            Action("Sell", f"Sell high on {p['name']}", reasons, trade_urgency(inp),
                   _gap_confidence(p), _gap_impact(p), [pid])
        )  # fmt: skip
    return actions


def buy_actions(inp: AdvisorInputs) -> list[Action]:
    """Other teams' players whose verdict is Buy, at positions you need."""
    if deadline_passed(inp):
        return []
    mine = inp.profiles.get(inp.my_team_id)
    needs = set(mine.needs) if mine else set()
    if not needs and mine:
        # no glaring hole: target the weakest graded position
        needs = {min(mine.grades.values(), key=lambda g: g.delta_pct).position}
    actions = []
    for tid, roster in inp.rosters.items():
        if tid == inp.my_team_id:
            continue
        prof = inp.profiles.get(tid)
        for pid in roster:
            p = inp.players.get(pid)
            if not p or p.get("signal") != "buy" or p.get("position") not in needs:
                continue
            reasons = list(p.get("signal_reasons") or [])
            reasons.append(f"Fills your weakest spot: {p['position']}.")
            if prof and p["position"] in prof.surplus:
                reasons.append(f"{inp.team_names[tid]} has {p['position']} depth to spare.")
            if p.get("ease_playoffs") and p["ease_playoffs"] >= EASY_SCHEDULE:
                reasons.append(
                    f"Easy fantasy-playoff schedule, {inp.playoff_label} "
                    f"(index {p['ease_playoffs']:.2f})."
                )
            actions.append(
                Action("Buy", f"Buy {p['name']} ({inp.team_names[tid]})", reasons,
                       trade_urgency(inp), _gap_confidence(p), _gap_impact(p), [pid], tid)
            )  # fmt: skip
    return actions


def trade_actions(inp: AdvisorInputs, top: int = 3) -> list[Action]:
    if deadline_passed(inp):
        return []
    out = []
    for ev in list(inp.trade_ideas)[:top]:
        gain = ev.me.lineup_delta
        conf = (
            "high"
            if gain >= 10 and ev.partner.lineup_delta >= 5
            else "medium"
            if gain >= 4
            else "low"
        )
        out.append(
            Action("Trade", f"Trade idea with {inp.team_names.get(ev.partner.team_id, ev.partner.team_id)}: {ev.headline}",
                   ev.reasons, trade_urgency(inp), conf, min(gain / 4, 5.0),
                   [*ev.me.gives, *ev.me.receives], ev.partner.team_id, ev)
        )  # fmt: skip
    return out


def waiver_actions(inp: AdvisorInputs) -> list[Action]:
    if not inp.free_agents:
        return []
    my = list(inp.rosters[inp.my_team_id])
    mine = inp.profiles.get(inp.my_team_id)
    starters = set(mine.starters) if mine else set()
    actions = []
    bench = [p for p in my if p in inp.players and p not in starters]
    drop = min(bench, key=lambda p: inp.players[p].get("ros_value_par") or 0, default=None)
    for pos in ("QB", "RB", "WR", "TE"):
        my_pos = [p for p in my if inp.players.get(p, {}).get("position") == pos]
        worst_starter = min(
            (inp.players[p].get("ppg") or 0 for p in my_pos if p in starters), default=0.0
        )
        fas = [p for p in inp.free_agents if inp.players.get(p, {}).get("position") == pos]
        best = max(fas, key=lambda p: inp.players[p].get("ros_value_par") or 0, default=None)
        if best is None:
            continue
        b = inp.players[best]
        gain = (b.get("ppg") or 0) - worst_starter
        if gain < WAIVER_MIN_GAIN:
            continue
        reasons = [
            f"Projects {b['ppg']:.1f} ppg vs your weakest {pos} starter at {worst_starter:.1f}."
        ]
        reasons += inp.regression_messages.get(best, [])[:1]
        if drop:
            reasons.append(
                f"Drop candidate: {_name(inp.players, drop)} (lowest rest-of-season value on your bench)."
            )
        actions.append(
            Action("Waiver", f"Add {b['name']} ({pos})", reasons, "this_week",
                   "medium" if gain >= 3 else "low", min(gain, 5.0), [best] + ([drop] if drop else []))
        )  # fmt: skip
    return actions


def build_feed(inp: AdvisorInputs, limit: int = 10) -> list[Action]:
    actions = (
        lineup_actions(inp)
        + bye_actions(inp)
        + trade_actions(inp)
        + sell_actions(inp)
        + buy_actions(inp)
        + waiver_actions(inp)
    )
    actions.sort(key=lambda a: -a.priority)
    # keep the feed varied: at most 3 of any one type
    picked, per_type = [], {}
    for a in actions:
        if per_type.get(a.type, 0) >= 3:
            continue
        picked.append(a)
        per_type[a.type] = per_type.get(a.type, 0) + 1
        if len(picked) >= limit:
            break
    return picked
