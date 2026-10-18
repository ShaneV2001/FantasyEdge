"""Trade analyzer, idea generator and targeted finder.

The core yardstick is **rest-of-season starting-lineup points** (bye/injury-aware) for both teams,
so a trade is judged by what it does to each lineup, not by summing player values. Model value
(points above replacement) and market value (FantasyCalc) are shown alongside for context.

Two things make a deal real rather than theoretical:
- **Roster spots.** A 2-for-1 leaves the receiving team a player over its limit, so it must drop
  someone. We cut who a manager would: an extra K/DEF, then surplus depth at an over-stocked
  position, then the bench player with the lowest market value; the loss counts against the deal.
- **Bye weeks.** Every remaining week is checked for both teams; a suggestion that leaves either
  team unable to fill a lineup slot in a week it can fill today is not offered.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from itertools import combinations

from signals.byes import RosterEntry, bye_grid
from signals.lineup import BENCH_BACKUPS, NON_STARTING, position_capacity
from signals.team import RosMath

ACCEPT_GAIN = 8.0
LEAN_GAIN = 2.0
MARKET_BAND = (0.7, 1.45)  # acceptable value ratio (received / given) for suggested deals
MAX_PER_PARTNER = 2
MAX_PER_GIVE = 2
MAX_PER_RECEIVE = 1  # don't show the same target twice
PAGE_SIZE = 8
# Cutting a bench player who costs the lineup less than this many points per remaining week is
# free (bench depth); a user setting. Per week, so the same player is judged alike in week 2 and 16.
FREE_DROP_PPG = 0.5
SKILL = ("QB", "RB", "WR", "TE")


@dataclass(frozen=True)
class RosterRules:
    """Roster-size limits. `active_limit` = starting + bench spots (None: no limit modelled);
    `reserved` = players on IR / taxi anywhere in the league, who can sit in one of a team's
    `reserve_slots` instead of an active spot (an injured player traded to you goes on your IR if
    you have room there; otherwise he takes an active spot). `bench_backups` = bench depth worth
    keeping per skill position when choosing forced drops (`position_capacity`); `free_drop_ppg` =
    lineup points per remaining week under which cutting a bench player counts as free."""

    active_limit: int | None = None
    reserved: frozenset[str] = frozenset()
    reserve_slots: int = 0
    bench_backups: int = BENCH_BACKUPS
    free_drop_ppg: float = FREE_DROP_PPG


def active_limit(roster_positions: Sequence[str]) -> int | None:
    """Starting + bench spots (IR and taxi don't count). None when the league lists no bench."""
    if "BN" not in roster_positions:
        return None
    return sum(1 for s in roster_positions if s not in NON_STARTING or s == "BN")


def reserve_slots(roster_positions: Sequence[str]) -> int:
    return sum(1 for s in roster_positions if s in ("IR", "TAXI"))


def active_count(pids: Sequence[str], rules: RosterRules) -> int:
    """Players using an active spot: everyone but the reserved ones that fit in reserve slots."""
    reserved = sum(1 for p in pids if p in rules.reserved)
    return len(pids) - min(reserved, rules.reserve_slots)


@dataclass
class WeekPoints:
    week: int
    before: float
    after: float


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
    drops: list[str] = field(default_factory=list)  # forced by the roster limit
    drop_reasons: list[str] = field(default_factory=list)  # why each one, aligned with `drops`
    new_short_weeks: list[int] = field(
        default_factory=list
    )  # can't fill a slot after, could before
    fixed_short_weeks: list[int] = field(default_factory=list)
    weekly: list[WeekPoints] = field(default_factory=list)

    @property
    def lineup_delta(self) -> float:
        return round(self.lineup_after - self.lineup_before, 2)


@dataclass
class TradeEvaluation:
    me: TradeSide
    partner: TradeSide | None  # None = hypothetical trade (players not on a league roster)
    verdict: str  # accept | lean_accept | neutral | decline
    headline: str
    reasons: list[str]
    danger_weeks_before: int | None = None
    danger_weeks_after: int | None = None
    score: float = 0.0
    tags: list[str] = field(default_factory=list)
    partner_accepts: bool | None = None  # would their lineup gain too (None: no partner modelled)

    @property
    def key(self) -> tuple:
        return (
            self.partner.team_id if self.partner else None,
            tuple(sorted(self.me.gives)),
            tuple(sorted(self.me.receives)),
        )


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


def _entries(pids: Iterable[str], players: Mapping[str, Mapping]) -> list[RosterEntry]:
    return [
        RosterEntry(p, players[p].get("name", p), players[p]["position"], players[p].get("nfl_team"),
                    players[p].get("ppg") or 0.0, players[p].get("injury_status"), players[p].get("status"),
                    players[p].get("return_week"))
        for p in pids
        if p in players
    ]  # fmt: skip


def short_weeks(
    pids: Sequence[str],
    players: Mapping[str, Mapping],
    math: RosMath,
    viable_ppg: Mapping[str, float],
) -> dict[int, list[str]]:
    """Remaining weeks where a lineup slot can't be filled by a viable starter -> those slots."""
    rows = bye_grid(
        _entries(pids, players), math.slots, math.schedule, math.start, math.end,
        dict(viable_ppg), math.inj,
    )  # fmt: skip
    return {r.week: r.danger_slots for r in rows if r.danger}


def danger_weeks(
    pids: Sequence[str],
    players: Mapping[str, Mapping],
    math: RosMath,
    viable_ppg: Mapping[str, float],
) -> int:
    return len(short_weeks(pids, players, math, viable_ppg))


STREAMED = {"K": "kicker", "DEF": "defense"}


@dataclass(frozen=True)
class Drop:
    player_id: str
    reason: str


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def choose_drops(
    math: RosMath,
    players: Mapping[str, Mapping],
    roster: Sequence[str],
    keep: set[str],
    n: int,
    backups: int = BENCH_BACKUPS,
    free_ppg: float = FREE_DROP_PPG,
) -> list[Drop]:
    """The `n` players a manager would cut, one at a time (counts are redone after each):

    1. dead weight: an extra kicker or defense (more than the lineup can start, whatever he
       costs: nobody carries two kickers), or surplus depth at an over-stocked position
       (`position_capacity` of this week's lineup with `backups` bench players per skill
       position, e.g. a 3rd QB in a 1-QB league) that the lineup barely needs. A cut
       that costs nothing (< 1 point) goes before one that costs a little;
    2. otherwise the bench player who is free to drop (not in this week's starting lineup, and
       cutting him costs the lineup < `free_ppg` points per remaining week, byes he covers
       included) with the lowest market value, so a valuable young bench player outlasts waiver
       fodder;
    3. if everyone starts, whoever costs the lineup the least.
    Players in `keep` (just acquired) are never cut.
    """
    current = list(roster)
    out: list[Drop] = []
    weeks = max(math.end - math.start + 1, 1)  # no weeks left: nobody costs anything

    def pos(p: str) -> str:
        return players.get(p, {}).get("position", "?")

    def market(p: str) -> float:
        return players.get(p, {}).get("market_value") or 0.0

    def points(p: str) -> float:
        return sum(math.week_points(p).values())

    for _ in range(n):
        cands = [p for p in current if p not in keep]
        if not cands:
            break
        count = Counter(pos(p) for p in current)
        lineup = math.lineup_for_week(current, math.start)
        capacity = position_capacity(lineup, backups)
        base = math.ros_lineup_points(current)
        cost = {p: base - math.ros_lineup_points([q for q in current if q != p]) for p in cands}
        # bench depth: not starting this week, and barely missed in the weeks left
        free = [p for p in cands if p not in lineup.starters and cost[p] / weeks < free_ppg]
        streamed = [
            p for p in cands if pos(p) in STREAMED and count[pos(p)] > capacity.get(pos(p), 0)
        ]
        surplus = [
            p for p in free
            if pos(p) in ("QB", "RB", "WR", "TE") and count[pos(p)] > capacity.get(pos(p), 0)
        ]  # fmt: skip
        # dead weight first: an extra K/DEF (whatever it costs: nobody carries two kickers) or
        # surplus depth; a cut that costs nothing (< 1 point) before one that costs a little
        dead = {q: 0 for q in streamed} | {q: 1 for q in surplus}
        if dead:
            p = min(
                (cost[q] >= 1.0, t, round(cost[q], 1) if t == 0 else market(q), points(q), q)
                for q, t in dead.items()
            )[-1]
            if dead[p] == 0:
                drop = Drop(p, f"extra {STREAMED[pos(p)]}")
            else:
                drop = Drop(p, f"{_ordinal(count[pos(p)])} {pos(p)}, more than your lineup can use")
        elif free:
            p = min(free, key=lambda q: (market(q), points(q), q))
            drop = Drop(p, "lowest market value on your bench")
        else:
            p = min(cands, key=lambda q: (round(cost[q], 2), market(q), q))
            drop = Drop(p, "costs your lineup the least")
        out.append(drop)
        current.remove(drop.player_id)
    return out


def roster_after(
    math: RosMath,
    players: Mapping[str, Mapping],
    team_id: str,
    roster: Sequence[str],
    out: Sequence[str],
    incoming: Sequence[str],
    rules: RosterRules,
) -> tuple[list[str], list[Drop]]:
    """(roster after the trade and any forced drops, the drops with why each was chosen)."""
    after = [p for p in roster if p not in out] + list(incoming)
    if rules.active_limit is None:
        return after, []
    # a team already over the limit (platform quirk) isn't forced below where it is today
    excess = active_count(after, rules) - max(rules.active_limit, active_count(roster, rules))
    if excess <= 0:
        return after, []
    droppable = [p for p in after if p not in rules.reserved]
    drops = choose_drops(
        math, players, droppable, set(incoming), excess, rules.bench_backups, rules.free_drop_ppg
    )
    gone = {d.player_id for d in drops}
    return [p for p in after if p not in gone], drops


def _name(players: Mapping[str, Mapping], pids: Sequence[str]) -> str:
    return " + ".join(players.get(p, {}).get("name", p) for p in pids)


def _drop_text(players: Mapping[str, Mapping], side: TradeSide) -> str:
    return " and ".join(
        f"{players.get(p, {}).get('name', p)} ({why})"
        for p, why in zip(side.drops, side.drop_reasons, strict=False)
    )


def _weeks_text(weeks: Sequence[int]) -> str:
    ws = sorted(weeks)
    return f"week {ws[0]}" if len(ws) == 1 else "weeks " + ", ".join(str(w) for w in ws)


def _side(
    math: RosMath,
    players: Mapping[str, Mapping],
    team_id: str,
    roster: Sequence[str],
    gives: Sequence[str],
    receives: Sequence[str],
    rules: RosterRules,
    viable_ppg: Mapping[str, float] | None,
) -> TradeSide:
    after, cut = roster_after(math, players, team_id, roster, gives, receives, rules)
    drops = [d.player_id for d in cut]
    side = TradeSide(
        team_id, list(gives), list(receives),
        math.ros_lineup_points(roster), math.ros_lineup_points(after),
        (_sum(players, gives, "ros_value_par") or 0.0) , _sum(players, receives, "ros_value_par") or 0.0,
        _sum(players, gives, "market_value"), _sum(players, receives, "market_value"),
        drops=drops,
        drop_reasons=[d.reason for d in cut],
        weekly=[
            WeekPoints(w, round(math.week_lineup_points(roster, w), 1),
                       round(math.week_lineup_points(after, w), 1))
            for w in range(math.start, math.end + 1)
        ],
    )  # fmt: skip
    if drops:  # a released player's value leaves the team too
        side.model_value_out += _sum(players, drops, "ros_value_par") or 0.0
    if viable_ppg is not None:
        before_short = short_weeks(roster, players, math, viable_ppg)
        after_short = short_weeks(after, players, math, viable_ppg)
        side.new_short_weeks = sorted(set(after_short) - set(before_short))
        side.fixed_short_weeks = sorted(set(before_short) - set(after_short))
    return side


def evaluate(
    math: RosMath,
    players: Mapping[str, Mapping],
    my_team: tuple[str, Sequence[str]],
    partner: tuple[str, Sequence[str]] | None,
    give: Sequence[str],
    receive: Sequence[str],
    viable_ppg: Mapping[str, float] | None = None,
    market_label: str = "Market",
    accept_gain: float = ACCEPT_GAIN,
    lean_gain: float = LEAN_GAIN,
    rules: RosterRules | None = None,
) -> TradeEvaluation:
    """Score a trade for both sides; with partner=None only your side is computed
    (a hypothetical deal, e.g. for a manual team or a player from another league)."""
    rules = rules or RosterRules()
    my_id, my_roster = my_team
    if not set(give) <= set(my_roster):
        raise ValueError("you can only give players on your roster")
    if set(receive) & set(my_roster):
        raise ValueError("you already have a player you're trying to receive")
    if partner is not None and not set(receive) <= set(partner[1]):
        raise ValueError("you can only receive players on the partner's roster")

    me = _side(math, players, my_id, my_roster, give, receive, rules, viable_ppg)
    them = None
    if partner is not None:
        them = _side(math, players, partner[0], partner[1], receive, give, rules, viable_ppg)

    d = me.lineup_delta
    if d >= accept_gain:
        verdict = "accept"
    elif d >= lean_gain:
        verdict = "lean_accept"
    elif d > -lean_gain:
        verdict = "neutral"
    else:
        verdict = "decline"

    mine_txt = f"Your starting lineup {'gains' if d >= 0 else 'loses'} {abs(d):.1f} projected points rest of season"
    if them is not None:
        theirs = (
            f"theirs {'gains' if them.lineup_delta >= 0 else 'loses'} {abs(them.lineup_delta):.1f}"
        )
        reasons = [f"{mine_txt}; {theirs}."]
    else:
        reasons = [f"{mine_txt} (hypothetical trade: the other side isn't modelled)."]
    if me.drops:
        reasons.append(
            f"You'd have to drop {_drop_text(players, me)} to make room (already counted above)."
        )
    if them is not None and them.drops:
        reasons.append(f"They'd have to drop {_drop_text(players, them)} to make room.")
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
        after = before + len(me.new_short_weeks) - len(me.fixed_short_weeks)
        if me.fixed_short_weeks:
            reasons.append(f"Fixes your lineup holes in {_weeks_text(me.fixed_short_weeks)}.")
        if me.new_short_weeks:
            reasons.append(
                f"Leaves your lineup short in {_weeks_text(me.new_short_weeks)} (byes or injuries)."
            )
        if them is not None and them.new_short_weeks:
            reasons.append(
                f"Leaves their lineup short in {_weeks_text(them.new_short_weeks)}, which makes a yes less likely."
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
    accepts = None if them is None else them.lineup_delta > 0 and not them.new_short_weeks
    return TradeEvaluation(
        me, them, verdict, headline, reasons, before, after, score=d, partner_accepts=accepts
    )


# ───────── idea generator ─────────


def _tradeable(players: Mapping[str, Mapping], pids: Sequence[str], use_market: bool) -> list[str]:
    return [
        p
        for p in pids
        if p in players and players[p]["position"] in SKILL and trade_value(players, p, use_market)
    ]


def candidate_trades(
    math: RosMath,
    players: Mapping[str, Mapping],
    my_team: tuple[str, Sequence[str]],
    others: Mapping[str, Sequence[str]],
    *,
    use_market: bool = True,
    min_gain: float = 1.0,
    max_evals_per_partner: int = 150,
    keep_per_partner: int = MAX_PER_PARTNER * 6,
    viable_ppg: Mapping[str, float] | None = None,
    rules: RosterRules | None = None,
    market_label: str = "Market",
    accept_gain: float = ACCEPT_GAIN,
    lean_gain: float = LEAN_GAIN,
) -> list[TradeEvaluation]:
    """Every 1-for-1 and 2-for-1 (both directions) deal where *both* lineups gain after forced
    drops, and neither team is left short in a week it can fill today; best first."""
    my_id, my_roster = my_team
    mine = _tradeable(players, my_roster, use_market)
    my_base = math.ros_lineup_points(my_roster)
    results: list[TradeEvaluation] = []

    for their_id, their_roster in others.items():
        theirs = _tradeable(players, their_roster, use_market)
        their_base = math.ros_lineup_points(their_roster)
        packages: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
            ((a,), (b,)) for a in mine for b in theirs
        ]
        packages += [(g, (b,)) for g in combinations(mine, 2) for b in theirs]
        packages += [((a,), r) for a in mine for r in combinations(theirs, 2)]
        scored = []
        for g, r in packages:
            vg = sum(trade_value(players, p, use_market) or 0 for p in g)
            vr = sum(trade_value(players, p, use_market) or 0 for p in r)
            if not vg or not (MARKET_BAND[0] <= vr / vg <= MARKET_BAND[1]):
                continue
            scored.append((abs(1 - vr / vg), g, r))
        scored.sort(key=lambda x: x[0])
        # quick screen without drops or bye checks, then the full evaluation for the best few
        hits = []
        for _, g, r in scored[:max_evals_per_partner]:
            md = math.ros_lineup_points([p for p in my_roster if p not in g] + list(r)) - my_base
            td = (
                math.ros_lineup_points([p for p in their_roster if p not in r] + list(g))
                - their_base
            )
            if md >= min_gain and td >= min_gain:
                hits.append((md, td, g, r))
        hits.sort(key=lambda x: -(min(x[0], x[1]) + 0.5 * x[0]))
        for _, _, g, r in hits[:keep_per_partner]:
            ev = evaluate(
                math, players, my_team, (their_id, their_roster), g, r,
                viable_ppg=viable_ppg, market_label=market_label,
                accept_gain=accept_gain, lean_gain=lean_gain, rules=rules,
            )  # fmt: skip
            assert ev.partner is not None
            md, td = ev.me.lineup_delta, ev.partner.lineup_delta
            if (
                md < min_gain
                or td < min_gain
                or ev.me.new_short_weeks
                or ev.partner.new_short_weeks
            ):
                continue
            ev.score = round(min(md, td) + 0.5 * md, 2)
            ev.tags = [f"{len(g)}-for-{len(r)}"]
            ev.headline = f"Give {_name(players, g)} for {_name(players, r)}"
            results.append(ev)

    results.sort(key=lambda e: -e.score)
    return results


def _pick_diverse(pool: list[TradeEvaluation], limit: int) -> list[TradeEvaluation]:
    """Best first, but at most 2 per partner / per player given, and each target once."""
    picked: list[TradeEvaluation] = []
    per_partner: dict[str, int] = {}
    per_give: dict[str, int] = {}
    per_receive: dict[str, int] = {}
    for ev in pool:
        pid = ev.partner.team_id if ev.partner else ""
        if per_partner.get(pid, 0) >= MAX_PER_PARTNER:
            continue
        if any(per_give.get(p, 0) >= MAX_PER_GIVE for p in ev.me.gives):
            continue
        if any(per_receive.get(p, 0) >= MAX_PER_RECEIVE for p in ev.me.receives):
            continue
        picked.append(ev)
        per_partner[pid] = per_partner.get(pid, 0) + 1
        for p in ev.me.gives:
            per_give[p] = per_give.get(p, 0) + 1
        for p in ev.me.receives:
            per_receive[p] = per_receive.get(p, 0) + 1
        if len(picked) >= limit:
            break
    return picked


def paginate(
    candidates: list[TradeEvaluation], page: int, limit: int = PAGE_SIZE
) -> tuple[list[TradeEvaluation], bool]:
    """Page `page` of diverse ideas; each page only uses deals no earlier page showed.
    Returns (ideas, has_more)."""
    remaining = list(candidates)
    shown: list[TradeEvaluation] = []
    for _ in range(page + 1):
        shown = _pick_diverse(remaining, limit)
        if not shown:  # caps exhausted: take what's left in order
            shown = remaining[:limit]
        keys = {ev.key for ev in shown}
        remaining = [ev for ev in remaining if ev.key not in keys]
        if not shown:
            break
    return shown, bool(remaining)


def suggest(
    math: RosMath,
    players: Mapping[str, Mapping],
    my_team: tuple[str, Sequence[str]],
    others: Mapping[str, Sequence[str]],
    *,
    use_market: bool = True,
    limit: int = PAGE_SIZE,
    min_gain: float = 1.0,
    max_evals_per_partner: int = 150,
    market_label: str = "Market",
    accept_gain: float = ACCEPT_GAIN,
    lean_gain: float = LEAN_GAIN,
    viable_ppg: Mapping[str, float] | None = None,
    rules: RosterRules | None = None,
) -> list[TradeEvaluation]:
    """The first page of mutually beneficial ideas (see `candidate_trades`)."""
    cands = candidate_trades(
        math, players, my_team, others, use_market=use_market, min_gain=min_gain,
        max_evals_per_partner=max_evals_per_partner, viable_ppg=viable_ppg, rules=rules,
        market_label=market_label, accept_gain=accept_gain, lean_gain=lean_gain,
    )  # fmt: skip
    return paginate(cands, 0, limit)[0]


# ───────── targeted finder ─────────


def _shortlist_key(my_gain: float, their_gain: float) -> tuple[bool, float]:
    """Sort key for the quick screen (before drops and bye checks): deals both lineups like
    first, best for both (then you); then the rest by your gain."""
    if their_gain > 0:
        return (False, -(min(my_gain, their_gain) + 0.5 * my_gain))
    return (True, -my_gain)


def find_for(
    math: RosMath,
    players: Mapping[str, Mapping],
    my_team: tuple[str, Sequence[str]],
    others: Mapping[str, Sequence[str]],
    give: Sequence[str],
    want_position: str,
    receive_count: int = 1,
    *,
    limit: int = 10,
    per_partner: int = MAX_PER_PARTNER,
    shortlist_per_partner: int = 8,
    viable_ppg: Mapping[str, float] | None = None,
    rules: RosterRules | None = None,
    market_label: str = "Market",
    accept_gain: float = ACCEPT_GAIN,
    lean_gain: float = LEAN_GAIN,
) -> list[TradeEvaluation]:
    """ "I'll give these players for a <position>": every team's players at that position (or
    pairs, for 2 back), deals that improve your lineup only. Deals their lineup also likes come
    first; the rest are marked as unlikely to be accepted."""
    my_id, my_roster = my_team
    if not give or not set(give) <= set(my_roster):
        raise ValueError("pick players from your roster to give")
    positions = set(SKILL) if want_position == "ANY" else {want_position}
    my_after_give = [p for p in my_roster if p not in give]
    my_base = math.ros_lineup_points(my_roster)
    found: list[TradeEvaluation] = []
    for their_id, their_roster in others.items():
        pool = [p for p in their_roster if players.get(p, {}).get("position") in positions]
        packages = [tuple(c) for c in combinations(pool, receive_count)]
        their_base = math.ros_lineup_points(their_roster)
        quick = []
        for r in packages:
            md = math.ros_lineup_points(my_after_give + list(r)) - my_base
            if md > 0:
                td = math.ros_lineup_points([p for p in their_roster if p not in r] + list(give))
                quick.append((_shortlist_key(md, td - their_base), r))
        quick.sort(key=lambda x: x[0])
        evs = []
        for _, r in quick[:shortlist_per_partner]:
            ev = evaluate(
                math, players, my_team, (their_id, their_roster), give, r,
                viable_ppg=viable_ppg, market_label=market_label,
                accept_gain=accept_gain, lean_gain=lean_gain, rules=rules,
            )  # fmt: skip
            if ev.me.lineup_delta <= 0:
                continue
            assert ev.partner is not None
            ev.headline = f"Give {_name(players, give)} for {_name(players, r)}"
            ev.tags = [f"{len(give)}-for-{len(r)}"]
            if not ev.partner_accepts:
                loss = -ev.partner.lineup_delta
                ev.reasons.insert(
                    1,
                    f"Their lineup would lose {loss:.1f} points, so they're unlikely to accept as is."
                    if loss > 0
                    else "Their lineup gains nothing (or a week goes short), so they're unlikely to accept as is.",
                )
            ev.score = ev.me.lineup_delta
            evs.append(ev)
        evs.sort(key=lambda e: (not e.partner_accepts, -e.score))
        found += evs[:per_partner]
    found.sort(key=lambda e: (not e.partner_accepts, -e.score))
    return found[:limit]


def acquire_for(
    math: RosMath,
    players: Mapping[str, Mapping],
    my_team: tuple[str, Sequence[str]],
    owner: tuple[str, Sequence[str]],
    target: str,
    *,
    max_give: int = 2,
    limit: int = 10,
    shortlist: int = 10,
    use_market: bool = True,
    viable_ppg: Mapping[str, float] | None = None,
    rules: RosterRules | None = None,
    market_label: str = "Market",
    accept_gain: float = ACCEPT_GAIN,
    lean_gain: float = LEAN_GAIN,
) -> list[TradeEvaluation]:
    """ "What would it take to get him?": packages of 1..`max_give` of your players for `target`
    that improve your lineup. Deals his team's lineup also likes come first."""
    my_id, my_roster = my_team
    owner_id, owner_roster = owner
    if target not in owner_roster:
        raise ValueError("that player isn't on the other team's roster")
    mine = _tradeable(players, my_roster, use_market)
    my_base = math.ros_lineup_points(my_roster)
    found: list[TradeEvaluation] = []
    their_base = math.ros_lineup_points(owner_roster)
    their_after_out = [p for p in owner_roster if p != target]
    for n in range(1, max_give + 1):
        quick = []
        for g in combinations(mine, n):
            md = math.ros_lineup_points([p for p in my_roster if p not in g] + [target]) - my_base
            if md > 0:
                td = math.ros_lineup_points(their_after_out + list(g)) - their_base
                quick.append((_shortlist_key(md, td), g))
        quick.sort(key=lambda x: x[0])
        for _, g in quick[:shortlist]:
            ev = evaluate(
                math, players, my_team, (owner_id, owner_roster), g, [target],
                viable_ppg=viable_ppg, market_label=market_label,
                accept_gain=accept_gain, lean_gain=lean_gain, rules=rules,
            )  # fmt: skip
            if ev.me.lineup_delta <= 0:
                continue
            assert ev.partner is not None
            ev.headline = f"Give {_name(players, g)} for {_name(players, [target])}"
            ev.tags = [f"{len(g)}-for-1"]
            if not ev.partner_accepts:
                loss = -ev.partner.lineup_delta
                ev.reasons.insert(
                    1,
                    f"Their lineup would lose {loss:.1f} points, so they're unlikely to accept as is."
                    if loss > 0
                    else "Their lineup gains nothing (or a week goes short), so they're unlikely to accept as is.",
                )
            ev.score = ev.me.lineup_delta
            found.append(ev)
    # mutually good deals first; among those, the ones that leave your lineup best off
    found.sort(key=lambda e: (not e.partner_accepts, -e.score))
    return found[:limit]
