"""Trade analyzer, idea generator and targeted finder.

The core yardstick is **rest-of-season starting-lineup points** (bye/injury-aware) for both teams,
so a trade is judged by what it does to each lineup, not by summing player values. Model value
(points above replacement) and market value (FantasyCalc) are shown alongside for context.

Two things make a deal real rather than theoretical:
- **Roster spots.** A 2-for-1 leaves the receiving team a player over its limit, so it must drop
  someone. We cut who a manager would: an extra K/DEF, then surplus depth at an over-stocked
  position, then the bench player with the lowest market value (our own projection where the
  market has no price); the loss counts against the deal.
- **Bye weeks.** Every remaining week is checked for both teams; a suggestion that leaves either
  team unable to fill a lineup slot in a week it can fill today is not offered.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from itertools import combinations

from signals.byes import RosterEntry, bye_grid
from signals.lineup import BENCH_BACKUPS, NON_STARTING, SKILL_POSITIONS, position_capacity
from signals.team import RosMath

ACCEPT_GAIN = 8.0
LEAN_GAIN = 2.0
# A deal is fair when each side gets at least (1 - FAIR_BAND) of the value it gives up, and a player
# at a position the receiving team is weak at counts NEED_PREMIUM more to it (both user settings).
FAIR_BAND = 0.15
NEED_PREMIUM = 0.10
# Every player in a deal is worth at least this share of its most valuable one: no waiver filler
# stacked up to "balance" a star.
MIN_PIECE = 0.10
# A player added only to even out the values is worth at most this share of the main player he
# balances (a throw-in, not a second target).
ADDON_SHARE = 0.5
GAP_STEP = 0.05  # value gaps within the same 5% rank as equal, so simpler deals win ties
MAX_PER_PARTNER = 2
MAX_PER_GIVE = 2
MAX_PER_RECEIVE = 1  # don't show the same target twice
PAGE_SIZE = 8
# Cutting a bench player who costs the lineup less than this many points per remaining week is
# free (bench depth); a user setting. Per week, so the same player is judged alike in week 2 and 16.
FREE_DROP_PPG = 0.5


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


@dataclass(frozen=True)
class Drop:
    """A player a team must release to stay at its roster limit, and why him."""

    player_id: str
    reason: str


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
    drops: list[Drop] = field(default_factory=list)  # forced by the roster limit
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
    # fair by value, their lineup gains, and no new short week (None: no partner modelled)
    partner_accepts: bool | None = None
    market_values_missing: bool = False  # no player has a price: drops went by projections only
    fair_value: bool | None = None  # within the fair band for both sides (None: can't be judged)
    market_gap: float | None = None  # MarketCheck.gap

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


@dataclass(frozen=True)
class Fairness:
    """How deals are judged by value. `needs` = each team's weak positions (team grades); a player
    there counts `need_premium` more to the team receiving him. `use_market`: market values, or
    our model value when the league has no market source."""

    band: float = FAIR_BAND
    need_premium: float = NEED_PREMIUM
    use_market: bool = True
    needs: Mapping[str, frozenset[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class MarketCheck:
    """One deal by value, from your side. `mine` / `theirs` = what a side gets (its need bonus
    included) per unit it gives up; `gap` = how far the worse-off side falls short of even."""

    give: tuple[str, ...]
    receive: tuple[str, ...]
    value_out: float
    value_in: float
    mine: float
    theirs: float
    gap: float
    no_filler: bool  # every player is worth at least MIN_PIECE of the best one in the deal
    fair: bool


def package_value(
    players: Mapping[str, Mapping],
    pids: Sequence[str],
    use_market: bool,
    needs: frozenset[str] = frozenset(),
    premium: float = 0.0,
) -> float | None:
    """Sum of trade values, with players at a `needs` position counted `premium` more. None when
    anyone has no value (e.g. no market price)."""
    total = 0.0
    for p in pids:
        v = trade_value(players, p, use_market)
        if not v:
            return None
        total += v * (1 + premium) if players[p].get("position") in needs else v
    return total


def market_check(
    players: Mapping[str, Mapping],
    give: Sequence[str],
    receive: Sequence[str],
    my_id: str,
    partner_id: str,
    fairness: Fairness,
) -> MarketCheck | None:
    """Is this deal fair by value for both sides? None when a side is empty or a player has no
    value to judge him by."""
    f = fairness
    out = package_value(players, give, f.use_market)
    inn = package_value(players, receive, f.use_market)
    if not out or not inn:
        return None
    mine = package_value(
        players, receive, f.use_market, f.needs.get(my_id, frozenset()), f.need_premium
    )
    theirs = package_value(
        players, give, f.use_market, f.needs.get(partner_id, frozenset()), f.need_premium
    )
    assert mine is not None and theirs is not None
    mine, theirs = mine / out, theirs / inn
    values = [trade_value(players, p, f.use_market) or 0.0 for p in (*give, *receive)]
    no_filler = min(values) >= MIN_PIECE * max(values)
    gap = max(0.0, 1 - min(mine, theirs))
    return MarketCheck(
        tuple(give), tuple(receive), out, inn, round(mine, 4), round(theirs, 4), round(gap, 4),
        no_filler, no_filler and gap <= f.band + 1e-9,
    )  # fmt: skip


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
SURPLUS = "more than your lineup can use"
BENCH_BY_MARKET = "lowest market value on your bench"
BENCH_BY_PROJECTION = "lowest value on your bench (our projection; no market price)"


def has_market_values(players: Mapping[str, Mapping]) -> bool:
    """Whether any player has a market price (none: the market source is missing or failed)."""
    return any(p.get("market_value") is not None for p in players.values())


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


@dataclass(frozen=True)
class DropCandidate:
    """Someone `choose_drops` could cut: the rule that makes him a candidate (extra, surplus,
    bench or cost) and the reason shown if he's the one."""

    player_id: str
    rule: str
    reason: str


def _lowest(cands: Sequence[DropCandidate], key: Callable[[str], tuple]) -> DropCandidate | None:
    return min(cands, key=lambda c: key(c.player_id)) if cands else None


def choose_drops(
    math: RosMath,
    players: Mapping[str, Mapping],
    roster: Sequence[str],
    keep: set[str],
    n: int,
    backups: int = BENCH_BACKUPS,
    free_ppg: float = FREE_DROP_PPG,
) -> list[Drop]:
    """The `n` players a manager would cut, one at a time (counts are redone after each).

    Dead weight is an extra kicker or defense (more than the lineup can start, whatever he
    costs: nobody carries two kickers) or surplus depth at an over-stocked position
    (`position_capacity` of this week's lineup with `backups` bench players per skill position,
    e.g. a 3rd QB in a 1-QB league) who is free to drop: not in this week's starting lineup, and
    cutting him costs the lineup < `free_ppg` points per remaining week, byes he covers included.
    Each cut is the first pass that finds someone:

    1. dead weight that costs nothing (< 1 point): an extra K/DEF (the cheapest), then surplus
       depth (the lowest value);
    2. dead weight that costs a little, in the same order (e.g. a 2nd D/ST covering a bye);
    3. the free-to-drop bench player with the lowest market value, so a valuable young bench
       player outlasts waiver fodder;
    4. whoever costs the lineup the least (e.g. everyone starts).
    A missing market price is not a price of 0: when one of the players being compared has none,
    they're all compared by our rest-of-season value (`ros_value_par`) instead. When no player
    has a price at all, pass 3 is skipped (nothing to rank the bench by but the lineup cost).
    Players in `keep` (just acquired) are never cut.
    """
    current = list(roster)
    out: list[Drop] = []
    weeks = max(math.end - math.start + 1, 1)  # no weeks left: nobody costs anything
    priced = has_market_values(players)

    def pos(p: str) -> str:
        return players.get(p, {}).get("position", "?")

    def market(p: str) -> float | None:
        return players.get(p, {}).get("market_value")

    def ours(p: str) -> float:
        return players.get(p, {}).get("ros_value_par") or 0.0

    def by_value(group: Sequence[str]) -> tuple[Callable[[str], float], bool]:
        """How to rank `group` by value: (key, whether it's our projection, not the market)."""
        prices = {q: market(q) for q in group}
        if priced and all(v is not None for v in prices.values()):
            return lambda q: prices[q] or 0.0, False
        return ours, True

    def points(p: str) -> float:
        return sum(math.week_points(p).values())

    def next_cut(cands: list[str]) -> DropCandidate:
        """The first pass (see above) that finds someone among `cands`, for `current`."""
        count = Counter(pos(p) for p in current)
        lineup = math.lineup_for_week(current, math.start)
        capacity = position_capacity(lineup, backups)
        base = math.ros_lineup_points(current)
        cost = {p: base - math.ros_lineup_points([q for q in current if q != p]) for p in cands}

        def over(p: str) -> bool:
            return count[pos(p)] > capacity.get(pos(p), 0)

        # bench depth: not starting this week, and barely missed in the weeks left
        free = [p for p in cands if p not in lineup.starters and cost[p] / weeks < free_ppg]
        extras = [
            DropCandidate(p, "extra", f"extra {STREAMED[pos(p)]}")
            for p in cands
            if pos(p) in STREAMED and over(p)
        ]
        surplus = [
            DropCandidate(p, "surplus", f"{_ordinal(count[pos(p)])} {pos(p)}, {SURPLUS}")
            for p in free
            if pos(p) in SKILL_POSITIONS and over(p)
        ]
        surplus_value = by_value([c.player_id for c in surplus])[0]
        bench_value, projected = by_value(free)
        why = BENCH_BY_PROJECTION if projected else BENCH_BY_MARKET
        bench = [DropCandidate(p, "bench", why) for p in free] if priced else []
        anyone = [DropCandidate(p, "cost", "costs your lineup the least") for p in cands]
        anyone_value = by_value(cands)[0]

        def light(c: DropCandidate) -> bool:
            return cost[c.player_id] < 1.0

        def cheapest(p: str) -> tuple:
            return (round(cost[p], 1), points(p), p)

        def least_surplus(p: str) -> tuple:
            return (surplus_value(p), points(p), p)

        pick = (
            _lowest([c for c in extras if light(c)], cheapest)  # 1. dead weight, costs nothing
            or _lowest([c for c in surplus if light(c)], least_surplus)
            or _lowest([c for c in extras if not light(c)], cheapest)  # 2. costs a little
            or _lowest([c for c in surplus if not light(c)], least_surplus)
            or _lowest(bench, lambda p: (bench_value(p), points(p), p))  # 3. free bench
            or _lowest(anyone, lambda p: (round(cost[p], 2), anyone_value(p), p))  # 4. the rest
        )
        assert pick is not None  # `anyone` is never empty
        return pick

    for _ in range(n):
        cands = [p for p in current if p not in keep]
        if not cands:
            break
        pick = next_cut(cands)
        out.append(Drop(pick.player_id, pick.reason))
        current.remove(pick.player_id)
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
        f"{players.get(d.player_id, {}).get('name', d.player_id)} ({d.reason})" for d in side.drops
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
    after, drops = roster_after(math, players, team_id, roster, gives, receives, rules)
    side = TradeSide(
        team_id, list(gives), list(receives),
        math.ros_lineup_points(roster), math.ros_lineup_points(after),
        (_sum(players, gives, "ros_value_par") or 0.0) , _sum(players, receives, "ros_value_par") or 0.0,
        _sum(players, gives, "market_value"), _sum(players, receives, "market_value"),
        drops=drops,
        weekly=[
            WeekPoints(w, round(math.week_lineup_points(roster, w), 1),
                       round(math.week_lineup_points(after, w), 1))
            for w in range(math.start, math.end + 1)
        ],
    )  # fmt: skip
    if drops:  # a released player's value leaves the team too
        side.model_value_out += _sum(players, [d.player_id for d in drops], "ros_value_par") or 0.0
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
    fairness: Fairness | None = None,
) -> TradeEvaluation:
    """Score a trade for both sides; with partner=None only your side is computed
    (a hypothetical deal, e.g. for a manual team or a player from another league)."""
    rules = rules or RosterRules()
    fairness = fairness or Fairness()
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
    check = (
        market_check(players, give, receive, my_id, partner[0], fairness)
        if partner is not None
        else market_check(players, give, receive, my_id, "", fairness)
    )
    if check is not None:
        label = market_label if fairness.use_market else "Model"
        if check.fair:
            fair = "fair by value"
        elif check.mine < check.theirs:
            fair = f"you overpay: you get {check.mine:.0%} of what you give"
        else:
            fair = f"they'd get {check.theirs:.0%} of what they give"
        reasons.append(
            f"{label} value: you give {check.value_out:,.0f}, get {check.value_in:,.0f} ({fair})."
        )
        if them is not None and not check.fair and check.theirs < check.mine:
            reasons.insert(
                1, "They'd give up far more value than they get, so they'd likely say no."
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
    fair = None if check is None else check.fair
    accepts = (
        None
        if them is None
        else them.lineup_delta > 0 and not them.new_short_weeks and fair is not False
    )
    return TradeEvaluation(
        me, them, verdict, headline, reasons, before, after, score=d, partner_accepts=accepts,
        market_values_missing=not has_market_values(players), fair_value=fair,
        market_gap=None if check is None else check.gap,
    )  # fmt: skip


# ───────── idea generator ─────────


def _tradeable(players: Mapping[str, Mapping], pids: Sequence[str], use_market: bool) -> list[str]:
    return [
        p
        for p in pids
        if p in players
        and players[p]["position"] in SKILL_POSITIONS
        and trade_value(players, p, use_market)
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
    fairness: Fairness | None = None,
) -> list[TradeEvaluation]:
    """Every 1-for-1 and 2-for-1 (both directions) deal that's fair by value (`market_check`) and
    where *both* lineups gain after forced drops, and neither team is left short in a week it can
    fill today; best first."""
    fairness = fairness or Fairness(use_market=use_market)
    my_id, my_roster = my_team
    mine = _tradeable(players, my_roster, fairness.use_market)
    my_base = math.ros_lineup_points(my_roster)
    results: list[TradeEvaluation] = []

    for their_id, their_roster in others.items():
        theirs = _tradeable(players, their_roster, fairness.use_market)
        their_base = math.ros_lineup_points(their_roster)
        packages: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
            ((a,), (b,)) for a in mine for b in theirs
        ]
        packages += [(g, (b,)) for g in combinations(mine, 2) for b in theirs]
        packages += [((a,), r) for a in mine for r in combinations(theirs, 2)]
        scored = []
        for g, r in packages:
            check = market_check(players, g, r, my_id, their_id, fairness)
            if check is not None and check.fair:
                scored.append((check.gap, g, r))
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
                accept_gain=accept_gain, lean_gain=lean_gain, rules=rules, fairness=fairness,
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
    fairness: Fairness | None = None,
) -> list[TradeEvaluation]:
    """The first page of mutually beneficial ideas (see `candidate_trades`)."""
    cands = candidate_trades(
        math, players, my_team, others, use_market=use_market, min_gain=min_gain,
        max_evals_per_partner=max_evals_per_partner, viable_ppg=viable_ppg, rules=rules,
        market_label=market_label, accept_gain=accept_gain, lean_gain=lean_gain, fairness=fairness,
    )  # fmt: skip
    return paginate(cands, 0, limit)[0]


# ───────── targeted finder ─────────


@dataclass
class Offers:
    """Fair deals, best first. When none survive, `closest` is the package nearest to even by value
    (for a "no fair package" note) and `fair_found` says whether fair ones existed but none helped
    your lineup."""

    ideas: list[TradeEvaluation]
    closest: MarketCheck | None = None
    fair_found: int = 0


def offer_rank(ev: TradeEvaluation) -> tuple:
    """Deals their lineup also likes first; then the most even by value (gaps within the same
    GAP_STEP count as equal); then the simplest (fewest players); then your gain."""
    return (
        not ev.partner_accepts,
        int((ev.market_gap or 0.0) / GAP_STEP),
        len(ev.me.gives) + len(ev.me.receives),
        -ev.me.lineup_delta,
    )


def _varied(
    evs: list[TradeEvaluation], limit: int, side: str = "gives", per_player: int = 3
) -> list[TradeEvaluation]:
    """Best first, but each package on the side that varies (`gives` when shopping for one target,
    `receives` when the give is fixed) only once, and no player there in more than `per_player`
    deals, so the list isn't ten versions of one offer."""
    picked: list[TradeEvaluation] = []
    seen: set[frozenset[str]] = set()
    uses: dict[str, int] = {}
    for ev in sorted(evs, key=offer_rank):
        pkg = frozenset(getattr(ev.me, side))
        if pkg in seen or any(uses.get(p, 0) >= per_player for p in pkg):
            continue
        picked.append(ev)
        seen.add(pkg)
        for p in pkg:
            uses[p] = uses.get(p, 0) + 1
        if len(picked) >= limit:
            break
    return picked


def _addons(
    players: Mapping[str, Mapping], pool: Sequence[str], main: Sequence[str], use_market: bool
) -> list[str]:
    """Players from `pool` small enough to be a throw-in next to `main` (ADDON_SHARE)."""
    top = max((trade_value(players, p, use_market) or 0.0) for p in main)
    return [p for p in pool if (trade_value(players, p, use_market) or 0.0) <= ADDON_SHARE * top]


def _closest(checks: Iterable[MarketCheck]) -> MarketCheck | None:
    return min((c for c in checks if c.no_filler), key=lambda c: c.gap, default=None)


def _shop(
    math: RosMath,
    players: Mapping[str, Mapping],
    my_team: tuple[str, Sequence[str]],
    partner: tuple[str, Sequence[str]],
    packages: Iterable[tuple[tuple[str, ...], tuple[str, ...]]],
    fairness: Fairness,
    shortlist: int,
    quick_limit: int,
    **eval_kwargs,
) -> tuple[list[TradeEvaluation], list[MarketCheck]]:
    """Value-check every (give, receive) package with one partner, lineup-check the most even fair
    ones (your lineup must gain), then fully evaluate the best `shortlist`. Returns (deals that
    still improve your lineup after drops, every value check)."""
    my_id, my_roster = my_team
    their_id, their_roster = partner
    checks = [
        c for g, r in packages if (c := market_check(players, g, r, my_id, their_id, fairness))
    ]
    fair = sorted((c for c in checks if c.fair), key=lambda c: c.gap)
    my_base = math.ros_lineup_points(my_roster)
    their_base = math.ros_lineup_points(their_roster)
    quick = []
    for c in fair[:quick_limit]:
        md = math.ros_lineup_points([p for p in my_roster if p not in c.give] + list(c.receive))
        if md - my_base <= 0:
            continue
        td = math.ros_lineup_points([p for p in their_roster if p not in c.receive] + list(c.give))
        quick.append(((td - their_base <= 0, c.gap, my_base - md), c))
    quick.sort(key=lambda x: x[0])
    evs = []
    for _, c in quick[:shortlist]:
        ev = evaluate(
            math, players, my_team, partner, c.give, c.receive, fairness=fairness, **eval_kwargs
        )
        if ev.me.lineup_delta <= 0:
            continue
        assert ev.partner is not None
        ev.headline = f"Give {_name(players, c.give)} for {_name(players, c.receive)}"
        ev.tags = [f"{len(c.give)}-for-{len(c.receive)}"]
        if not ev.partner_accepts:
            loss = -ev.partner.lineup_delta
            ev.reasons.insert(
                1,
                f"Fair by value, but their lineup would lose {loss:.1f} points, so they may say no."
                if loss > 0
                else "Fair by value, but their lineup gains nothing (or a week goes short), so they may say no.",
            )
        ev.score = ev.me.lineup_delta
        evs.append(ev)
    return evs, checks


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
    quick_limit: int = 40,
    viable_ppg: Mapping[str, float] | None = None,
    rules: RosterRules | None = None,
    market_label: str = "Market",
    accept_gain: float = ACCEPT_GAIN,
    lean_gain: float = LEAN_GAIN,
    fairness: Fairness | None = None,
) -> Offers:
    """ "I'll give these players for a <position>": every team's players at that position (or
    pairs, for 2 back), fair by value and improving your lineup. When the values don't line up,
    one more player evens them out: one of yours if you'd be short, one of theirs if you'd
    overpay. Deals their lineup also likes come first, then the most even."""
    fairness = fairness or Fairness()
    my_id, my_roster = my_team
    if not give or not set(give) <= set(my_roster):
        raise ValueError("pick players from your roster to give")
    positions = set(SKILL_POSITIONS) if want_position == "ANY" else {want_position}
    give = tuple(give)
    my_extras = [p for p in _tradeable(players, my_roster, fairness.use_market) if p not in give]
    found: list[TradeEvaluation] = []
    checks: list[MarketCheck] = []
    common = dict(
        viable_ppg=viable_ppg, rules=rules, market_label=market_label,
        accept_gain=accept_gain, lean_gain=lean_gain,
    )  # fmt: skip
    use = fairness.use_market
    for their_id, their_roster in others.items():
        theirs = _tradeable(players, their_roster, use)
        pool = [p for p in theirs if players[p]["position"] in positions]
        packages: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
        for r in combinations(pool, receive_count):
            packages.append((give, r))
            packages += [((*give, x), r) for x in _addons(players, my_extras, give, use)]
            others_r = [p for p in theirs if p not in r]
            packages += [(give, (*r, x)) for x in _addons(players, others_r, r, use)]
        evs, cs = _shop(
            math, players, my_team, (their_id, their_roster), packages, fairness,
            shortlist_per_partner, quick_limit, **common,
        )  # fmt: skip
        found += _varied(evs, per_partner, side="receives")
        checks += cs
    ideas = sorted(found, key=offer_rank)[:limit]
    return Offers(ideas, None if ideas else _closest(checks), sum(1 for c in checks if c.fair))


def acquire_for(
    math: RosMath,
    players: Mapping[str, Mapping],
    my_team: tuple[str, Sequence[str]],
    owner: tuple[str, Sequence[str]],
    target: str,
    *,
    max_give: int = 3,
    limit: int = 10,
    shortlist: int = 15,
    quick_limit: int = 80,
    viable_ppg: Mapping[str, float] | None = None,
    rules: RosterRules | None = None,
    market_label: str = "Market",
    accept_gain: float = ACCEPT_GAIN,
    lean_gain: float = LEAN_GAIN,
    fairness: Fairness | None = None,
) -> Offers:
    """ "What would it take to get him?": packages of 1..`max_give` of your players for `target`,
    fair by value and improving your lineup. If you'd overpay, his team can add one more player to
    even it out. Deals his team's lineup also likes come first, then the most even."""
    fairness = fairness or Fairness()
    owner_id, owner_roster = owner
    if target not in owner_roster:
        raise ValueError("that player isn't on the other team's roster")
    mine = _tradeable(players, my_team[1], fairness.use_market)
    others_t = [p for p in _tradeable(players, owner_roster, fairness.use_market) if p != target]
    extras = _addons(players, others_t, (target,), fairness.use_market)
    packages: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
    for n in range(1, max_give + 1):
        for g in combinations(mine, n):
            packages.append((g, (target,)))
            packages += [(g, (target, x)) for x in extras]
    evs, checks = _shop(
        math, players, my_team, owner, packages, fairness, shortlist, quick_limit,
        viable_ppg=viable_ppg, rules=rules, market_label=market_label,
        accept_gain=accept_gain, lean_gain=lean_gain,
    )  # fmt: skip
    ideas = _varied(evs, limit)
    return Offers(ideas, None if ideas else _closest(checks), sum(1 for c in checks if c.fair))
