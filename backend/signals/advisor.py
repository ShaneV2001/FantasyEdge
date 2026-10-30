"""Advisor feed: ranked, explainable actions for one team.

priority = urgency weight × impact × confidence weight — all constants below, nothing hidden.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from signals.byes import ByeWeekRow
from signals.lineup import SLOT_ELIGIBILITY, fit_to_slots
from signals.startsit import WeekPlan, plan_week
from signals.team import RosMath, TeamProfile
from signals.trade import TradeEvaluation
from signals.verdict import GAP_MIN_POINTS, GAP_MIN_SHARE
from signals.verdict import threshold as verdict_threshold
from signals.waivers import WaiverPick

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
    type: str  # Offer | Trade | Sell | Buy | Waiver | Lineup | Bye prep
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
    waivers: Sequence[WaiverPick] = ()  # ranked pickups (signals.waivers), best net gain first
    week_plan: WeekPlan | None = None  # this week's real vs best lineup (signals.startsit)
    # players in a trade both sides already accepted: no point suggesting them again
    in_trades: frozenset[str] = frozenset()
    # open offers other teams sent you: (proposing team id, the analyzer's evaluation)
    offers: Sequence[tuple[str, TradeEvaluation]] = ()
    market_label: str = "Market"
    playoff_label: str = "weeks 15-17"
    waiver_min_gain: float = WAIVER_MIN_GAIN
    start_sit_min_gain: float = START_SIT_MIN_GAIN
    easy_schedule: float = EASY_SCHEDULE
    tough_schedule: float = TOUGH_SCHEDULE
    gap_min_points: float = GAP_MIN_POINTS
    gap_min_share: float = GAP_MIN_SHARE


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
    plan = inp.week_plan or plan_week(inp.math, inp.players, my, inp.starters, inp.week)
    best_ids, pts = plan.starters, plan.points
    current = [p for p in inp.starters if p in inp.players]
    actions = []
    benched_better = sorted((p for p in best_ids if p not in current), key=lambda p: -pts[p])
    # a starter whose game is already final can't be benched
    sat = sorted(
        (p for p in current if p not in best_ids and p not in plan.locked), key=lambda p: pts[p]
    )
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
        if gain < inp.start_sit_min_gain:
            continue
        a, d = inp.players[add], inp.players[drop]
        reasons = [f"Projected {pts[add]:.1f} vs {pts[drop]:.1f} points this week (+{gain:.1f})."]
        if not inp.math.schedule.has_game(d.get("nfl_team"), inp.week):
            reasons.append(f"{d['name']} is on bye in week {inp.week}.")
        elif d.get("injury_status"):
            reasons.append(f"{d['name']} is listed {d['injury_status']}.")
        if a.get("ease_next4") and a["ease_next4"] >= inp.easy_schedule:
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
        pids = _best_fa_for_slots(inp, row.danger_slots, row.week)
        if pids:
            picks = ", ".join(
                f"{_name(inp.players, p)} ({inp.players[p]['position']}, "
                f"{inp.players[p]['ppg']:.1f} ppg)"
                for p in pids
            )
            reasons.append(f"Available to stream: {picks}.")
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


def _best_fa_for_slots(inp: AdvisorInputs, labels: Sequence[str], week: int) -> list[str]:
    """The best free agent playing that week for each short slot (a WR *and* a DEF, not just
    whichever scores more). Week points already count byes and injuries, so a player out for the
    season (or still on IR that week) is never suggested."""
    if not inp.free_agents:
        return []
    picks: list[str] = []
    for label in labels:
        positions = _slot_positions([label])
        cands = [
            p for p in inp.free_agents
            if p not in picks
            and inp.players.get(p, {}).get("position") in positions
            and inp.math.week_points(p).get(week, 0.0) > 0
        ]  # fmt: skip
        best = max(cands, key=lambda p: inp.math.week_points(p).get(week, 0.0), default=None)
        if best:
            picks.append(best)
    return picks


def _gap_confidence(p: Mapping, inp: AdvisorInputs) -> str:
    """How far past the buy/sell line the value gap is."""
    gap, implied = p.get("value_gap"), p.get("market_implied_points")
    if gap is None or not implied:
        return "low"
    t = verdict_threshold(implied, inp.gap_min_points, inp.gap_min_share)
    if t <= 0:
        return "high"  # any nonzero gap is past a zero line
    ratio = abs(gap) / t
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
        if not p or p.get("signal") != "sell" or pid in inp.in_trades:
            continue
        reasons = list(p.get("signal_reasons") or [])
        bye = p.get("bye_week")
        if bye == inp.week:
            reasons.append(f"On bye this week (week {bye}).")
        elif bye is not None and inp.week < bye <= inp.week + 3:
            reasons.append(f"Bye in week {bye} is coming up.")
        if p.get("ease_playoffs") and p["ease_playoffs"] <= inp.tough_schedule:
            reasons.append(
                f"Tough fantasy-playoff schedule, {inp.playoff_label} "
                f"(index {p['ease_playoffs']:.2f})."
            )
        actions.append(
            Action("Sell", f"Sell high on {p['name']}", reasons, trade_urgency(inp),
                   _gap_confidence(p, inp), _gap_impact(p), [pid])
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
        skill = [g for pos, g in mine.grades.items() if pos in ("QB", "RB", "WR", "TE")]
        needs = {min(skill, key=lambda g: g.delta_pct).position} if skill else set()
    actions = []
    for tid, roster in inp.rosters.items():
        if tid == inp.my_team_id:
            continue
        prof = inp.profiles.get(tid)
        for pid in roster:
            p = inp.players.get(pid)
            if (
                not p
                or p.get("signal") != "buy"
                or p.get("position") not in needs
                or pid in inp.in_trades
            ):
                continue
            reasons = list(p.get("signal_reasons") or [])
            reasons.append(f"Fills your weakest spot: {p['position']}.")
            if prof and p["position"] in prof.surplus:
                reasons.append(f"{inp.team_names[tid]} has {p['position']} depth to spare.")
            if p.get("ease_playoffs") and p["ease_playoffs"] >= inp.easy_schedule:
                reasons.append(
                    f"Easy fantasy-playoff schedule, {inp.playoff_label} "
                    f"(index {p['ease_playoffs']:.2f})."
                )
            actions.append(
                Action("Buy", f"Buy {p['name']} ({inp.team_names[tid]})", reasons,
                       trade_urgency(inp), _gap_confidence(p, inp), _gap_impact(p), [pid], tid)
            )  # fmt: skip
    return actions


def trade_actions(inp: AdvisorInputs, top: int = 3) -> list[Action]:
    if deadline_passed(inp):
        return []
    out = []
    ideas = [ev for ev in inp.trade_ideas if not inp.in_trades & {*ev.me.gives, *ev.me.receives}]
    for ev in ideas[:top]:
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


OFFER_HEADLINE = {
    "accept": "accept it",
    "lean_accept": "worth accepting",
    "neutral": "a coin flip",
    "decline": "decline it",
}


def offer_actions(inp: AdvisorInputs) -> list[Action]:
    """Offers waiting on your answer, graded like any trade. A bad offer is as worth knowing
    about as a good one, so impact has a floor."""
    out = []
    for proposer, ev in inp.offers:
        gain = ev.me.lineup_delta
        team = inp.team_names.get(proposer, proposer)
        out.append(
            Action("Offer", f"Offer from {team}: {OFFER_HEADLINE.get(ev.verdict, ev.verdict)}",
                   [ev.headline, *ev.reasons[:3]], "this_week", "high",
                   min(max(abs(gain) / 4, 1.5), 5.0), [*ev.me.gives, *ev.me.receives], proposer, ev)
        )  # fmt: skip
    return out


WAIVER_ACTIONS = 3


def waiver_actions(inp: AdvisorInputs) -> list[Action]:
    """The best pickups from the waiver ranking (same numbers as the Waivers page): one per
    position, only when the net gain per week clears the threshold."""
    actions: list[Action] = []
    seen: set[str] = set()
    for w in inp.waivers:
        if len(actions) >= WAIVER_ACTIONS:
            break
        if w.position in seen or w.gain_per_week < inp.waiver_min_gain:
            continue
        seen.add(w.position)
        b = inp.players[w.player_id]
        reasons = [
            f"Adds {w.gain:.0f} rest-of-season points to your starting lineup "
            f"({w.gain_per_week:.1f} a week), projecting {b.get('ppg') or 0:.1f} ppg."
        ]
        if w.fixes_weeks:
            weeks = ", ".join(str(x) for x in w.fixes_weeks)
            reasons.append(
                f"Fills a lineup hole in week{'s' if len(w.fixes_weeks) > 1 else ''} {weeks}."
            )
        reasons += inp.regression_messages.get(w.player_id, [])[:1]
        if w.drop:
            reasons.append(
                f"Drop {_name(inp.players, w.drop)}: the player your lineup misses least "
                "(already counted in the gain)."
            )
        actions.append(
            Action("Waiver", f"Add {b['name']} ({w.position})", reasons, "this_week",
                   "high" if w.gain_per_week >= 4 else "medium" if w.gain_per_week >= 2.5 else "low",
                   min(w.gain_per_week, 5.0), [w.player_id] + ([w.drop] if w.drop else []))
        )  # fmt: skip
    return actions


def build_feed(inp: AdvisorInputs, limit: int = 10) -> list[Action]:
    actions = (
        offer_actions(inp)
        + lineup_actions(inp)
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
