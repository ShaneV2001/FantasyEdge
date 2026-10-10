"""Trade analyzer + finder.

The core yardstick is **rest-of-season starting-lineup points** (bye/injury-aware) for both teams,
so a trade is judged by what it does to each lineup, not by summing player values. Model value
(points above replacement) and market value (FantasyCalc) are shown alongside for context.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from itertools import combinations

from signals.byes import RosterEntry, bye_grid
from signals.team import RosMath

ACCEPT_GAIN = 8.0
LEAN_GAIN = 2.0
MARKET_BAND = (0.7, 1.45)  # acceptable value ratio (received / given) for suggested deals
MAX_PER_PARTNER = 2
MAX_PER_GIVE = 2
MAX_PER_RECEIVE = 1  # don't show the same target twice


@dataclass
class TradeSide:
    team_id: str
    gives: list[str]
    receives: list[str]
    lineup_before: float
    lineup_after: float
    model_value_out: float
    model_value_in: float
    market_value_out: float | None
    market_value_in: float | None

    @property
    def lineup_delta(self) -> float:
        return round(self.lineup_after - self.lineup_before, 2)


@dataclass
class TradeEvaluation:
    me: TradeSide
    partner: TradeSide
    verdict: str  # accept | lean_accept | neutral | decline
    headline: str
    reasons: list[str]
    danger_weeks_before: int | None = None
    danger_weeks_after: int | None = None
    score: float = 0.0
    tags: list[str] = field(default_factory=list)


def _sum(players: Mapping[str, Mapping], pids: Sequence[str], key: str) -> float | None:
    vals = [players.get(p, {}).get(key) for p in pids]
    if any(v is None for v in vals):
        return None
    return float(sum(vals))


def trade_value(players: Mapping[str, Mapping], pid: str, use_market: bool) -> float | None:
    p = players.get(pid)
    if p is None:
        return None
    if use_market:
        return p.get("market_value")
    return max(p.get("ros_value_par") or 0.0, 0.0) + 1.0


def danger_weeks(
    pids: Sequence[str],
    players: Mapping[str, Mapping],
    math: RosMath,
    viable_ppg: Mapping[str, float],
) -> int:
    entries = [
        RosterEntry(p, players[p].get("name", p), players[p]["position"], players[p].get("nfl_team"),
                    players[p].get("ppg") or 0.0, players[p].get("injury_status"), players[p].get("status"))
        for p in pids
        if p in players
    ]  # fmt: skip
    rows = bye_grid(entries, math.slots, math.schedule, math.start, math.end, dict(viable_ppg))
    return sum(1 for r in rows if r.danger)


def _name(players: Mapping[str, Mapping], pids: Sequence[str]) -> str:
    return " + ".join(players.get(p, {}).get("name", p) for p in pids)


def evaluate(
    math: RosMath,
    players: Mapping[str, Mapping],
    my_team: tuple[str, Sequence[str]],
    partner: tuple[str, Sequence[str]],
    give: Sequence[str],
    receive: Sequence[str],
    viable_ppg: Mapping[str, float] | None = None,
    market_label: str = "Market",
) -> TradeEvaluation:
    my_id, my_roster = my_team
    their_id, their_roster = partner
    if not set(give) <= set(my_roster):
        raise ValueError("you can only give players on your roster")
    if not set(receive) <= set(their_roster):
        raise ValueError("you can only receive players on the partner's roster")

    my_after = [p for p in my_roster if p not in give] + list(receive)
    their_after = [p for p in their_roster if p not in receive] + list(give)
    me = TradeSide(
        my_id, list(give), list(receive),
        math.ros_lineup_points(my_roster), math.ros_lineup_points(my_after),
        _sum(players, give, "ros_value_par") or 0.0, _sum(players, receive, "ros_value_par") or 0.0,
        _sum(players, give, "market_value"), _sum(players, receive, "market_value"),
    )  # fmt: skip
    them = TradeSide(
        their_id, list(receive), list(give),
        math.ros_lineup_points(their_roster), math.ros_lineup_points(their_after),
        me.model_value_in, me.model_value_out, me.market_value_in, me.market_value_out,
    )  # fmt: skip

    d = me.lineup_delta
    if d >= ACCEPT_GAIN:
        verdict = "accept"
    elif d >= LEAN_GAIN:
        verdict = "lean_accept"
    elif d > -LEAN_GAIN:
        verdict = "neutral"
    else:
        verdict = "decline"

    reasons = [
        f"Your starting lineup {'gains' if d >= 0 else 'loses'} {abs(d):.1f} projected points "
        f"rest of season; theirs {'gains' if them.lineup_delta >= 0 else 'loses'} {abs(them.lineup_delta):.1f}."
    ]
    reasons.append(
        f"Model value (points above replacement): you give {me.model_value_out:.0f}, get {me.model_value_in:.0f}."
    )
    if me.market_value_out and me.market_value_in is not None:
        ratio = me.market_value_in / me.market_value_out
        fair = (
            "fair by market"
            if 0.85 <= ratio <= 1.18
            else ("you win on market value" if ratio > 1.18 else "you overpay by market value")
        )
        reasons.append(
            f"{market_label} value: you give {me.market_value_out:,.0f}, get {me.market_value_in:,.0f} ({fair})."
        )

    before = after = None
    if viable_ppg is not None:
        before = danger_weeks(my_roster, players, math, viable_ppg)
        after = danger_weeks(my_after, players, math, viable_ppg)
        if after < before:
            reasons.append(f"Fixes {before - after} bye/injury danger week(s) on your roster.")
        elif after > before:
            reasons.append(
                f"Creates {after - before} new bye/injury danger week(s) on your roster."
            )
    byes = [players.get(p, {}).get("bye_week") for p in receive]
    upcoming = [b for b in byes if b is not None and b >= math.start]
    if receive and not upcoming:
        reasons.append("Incoming player bye is already behind them.")

    headline = {
        "accept": "Accept: clear lineup upgrade",
        "lean_accept": "Lean accept: modest lineup upgrade",
        "neutral": "Neutral: roughly even for your lineup",
        "decline": "Decline: weakens your lineup",
    }[verdict]
    return TradeEvaluation(me, them, verdict, headline, reasons, before, after, score=d)


def suggest(
    math: RosMath,
    players: Mapping[str, Mapping],
    my_team: tuple[str, Sequence[str]],
    others: Mapping[str, Sequence[str]],
    *,
    use_market: bool = True,
    limit: int = 8,
    min_gain: float = 1.0,
    max_evals_per_partner: int = 150,
    market_label: str = "Market",
) -> list[TradeEvaluation]:
    """1-for-1 and 2-for-1 (both directions) deals where *both* lineups gain ROS points."""
    my_id, my_roster = my_team
    skill = {"QB", "RB", "WR", "TE"}

    def tradeable(pids: Sequence[str]) -> list[str]:
        return [
            p
            for p in pids
            if p in players
            and players[p]["position"] in skill
            and trade_value(players, p, use_market)
        ]

    mine = tradeable(my_roster)
    my_base = math.ros_lineup_points(my_roster)
    results: list[TradeEvaluation] = []

    for their_id, their_roster in others.items():
        theirs = tradeable(their_roster)
        their_base = math.ros_lineup_points(their_roster)
        packages: list[tuple[float, tuple[str, ...], tuple[str, ...]]] = []
        for g, r in [((a,), (b,)) for a in mine for b in theirs]:
            packages.append((0, g, r))
        for g in combinations(mine, 2):
            for b in theirs:
                packages.append((0, g, (b,)))
        for a in mine:
            for r in combinations(theirs, 2):
                packages.append((0, (a,), r))
        scored = []
        for _, g, r in packages:
            vg = sum(trade_value(players, p, use_market) or 0 for p in g)
            vr = sum(trade_value(players, p, use_market) or 0 for p in r)
            if not vg or not (MARKET_BAND[0] <= vr / vg <= MARKET_BAND[1]):
                continue
            scored.append((abs(1 - vr / vg), g, r))
        scored.sort(key=lambda x: x[0])
        partner_hits = []
        for _, g, r in scored[:max_evals_per_partner]:
            my_after = [p for p in my_roster if p not in g] + list(r)
            their_after = [p for p in their_roster if p not in r] + list(g)
            md = math.ros_lineup_points(my_after) - my_base
            td = math.ros_lineup_points(their_after) - their_base
            if md >= min_gain and td >= min_gain:
                partner_hits.append((md, td, g, r))
        partner_hits.sort(key=lambda x: -(min(x[0], x[1]) + 0.5 * x[0]))
        for md, td, g, r in partner_hits[: MAX_PER_PARTNER * 3]:
            ev = evaluate(
                math, players, my_team, (their_id, their_roster), g, r, market_label=market_label
            )
            ev.score = round(min(md, td) + 0.5 * md, 2)
            ev.tags = [f"{len(g)}-for-{len(r)}"]
            ev.headline = f"Give {_name(players, g)} for {_name(players, r)}"
            results.append(ev)

    results.sort(key=lambda e: -e.score)
    picked: list[TradeEvaluation] = []
    per_partner: dict[str, int] = {}
    per_give: dict[str, int] = {}
    per_receive: dict[str, int] = {}
    for ev in results:
        if per_partner.get(ev.partner.team_id, 0) >= MAX_PER_PARTNER:
            continue
        if any(per_give.get(p, 0) >= MAX_PER_GIVE for p in ev.me.gives):
            continue
        if any(per_receive.get(p, 0) >= MAX_PER_RECEIVE for p in ev.me.receives):
            continue
        picked.append(ev)
        per_partner[ev.partner.team_id] = per_partner.get(ev.partner.team_id, 0) + 1
        for p in ev.me.gives:
            per_give[p] = per_give.get(p, 0) + 1
        for p in ev.me.receives:
            per_receive[p] = per_receive.get(p, 0) + 1
        if len(picked) >= limit:
            break
    return picked
