"""Team-level math shared by trades, grades and the advisor.

`RosMath` turns per-player weekly projections into rest-of-season *starting lineup* points for any
set of players (bye- and injury-aware), memoised so trade search stays fast.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from projections.base import DEFAULT_INJURY, InjuryAssumptions, weekly_points
from signals.lineup import (
    SKILL_POSITIONS,
    SLOT_ELIGIBILITY,
    Lineup,
    LineupPlayer,
    optimal_lineup,
    slot_label,
)
from signals.schedule import Schedule


class RosMath:
    def __init__(
        self,
        players: Mapping[str, Mapping],
        schedule: Schedule,
        start_week: int,
        end_week: int,
        slots: Sequence[str],
        inj: InjuryAssumptions = DEFAULT_INJURY,
        weekly: Mapping[str, Mapping[int, float]] | None = None,
    ):
        """`weekly`: per-player week -> points to use instead of the flat ppg (e.g. this week's
        matchup-adjusted projections); players missing from it fall back to ppg x availability."""
        self.players = players
        self.weekly = weekly or {}
        self.inj = inj
        self.schedule = schedule
        self.start, self.end = start_week, end_week
        self.slots = list(slots)
        self._weekly: dict[str, dict[int, float]] = {}
        self._memo: dict[tuple, float] = {}

    def week_points(self, pid: str) -> dict[int, float]:
        if pid not in self._weekly:
            p = self.players.get(pid)
            if pid in self.weekly:
                given, team = self.weekly[pid], (p or {}).get("nfl_team")
                self._weekly[pid] = {
                    w: given.get(w, 0.0) if self.schedule.plays(team, w) else 0.0
                    for w in range(self.start, self.end + 1)
                }
            elif p is None:
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
                    self.inj,
                    p.get("return_week"),
                )
        return self._weekly[pid]

    def _pos(self, pid: str) -> str:
        p = self.players.get(pid)
        return p["position"] if p else "?"

    def lineup_for_week(self, pids: Iterable[str], week: int) -> Lineup:
        avail = [LineupPlayer(p, self._pos(p), self.week_points(p).get(week, 0.0)) for p in pids]
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
#
# Position strength = the team's best players at a position, weighted by how many lineup spots that
# position fills: dedicated slots count fully, plus the position's typical share of FLEX /
# SUPER_FLEX slots (e.g. RB with 2 RB slots + 1 FLEX = top-2 RBs + 0.45 x the 3rd RB). This avoids
# crediting a position for whoever happens to win the FLEX spot, and rewards real depth.
# Letters compare a position group with what a typical team in a league this size starts there:
# in a 10-team league the benchmark RB1 is the average of the 10 best RBs, the RB2 the average of
# the next 10, and so on (weighted like the group itself). A >= 10% above it, B >= even, C >= 10%
# below, D >= 20% below, F lower. Rank and z-score against the league are kept for context. A
# z-score curve (the old letters) stretched a balanced league's small gaps into D's and F's.

FLEX_SHARES: dict[str, dict[str, float]] = {
    "FLEX": {"RB": 0.45, "WR": 0.45, "TE": 0.10},
    "WRRB_FLEX": {"RB": 0.5, "WR": 0.5},
    "REC_FLEX": {"WR": 0.8, "TE": 0.2},
    "SUPER_FLEX": {"QB": 0.9, "RB": 0.05, "WR": 0.05},
}
OVERALL = "ALL"
# K and DEF are graded too (dedicated slots only); needs/surplus stay skill-position only.
GRADED_POSITIONS = (*SKILL_POSITIONS, "K", "DEF")


GRADE_CUTS = ((1.10, "A"), (1.00, "B"), (0.90, "C"), (0.80, "D"))


def grade_from_ratio(ratio: float) -> str:
    """Letter for a group's points / the typical team's points at that spot."""
    for cut, letter in GRADE_CUTS:
        if ratio >= cut - 1e-9:
            return letter
    return "F"


def tier_averages(
    players: Mapping[str, Mapping], num_teams: int, depth: Mapping[str, int]
) -> dict[str, list[float]]:
    """Per position, the average ppg of each tier of `num_teams` players, best tier first: what a
    typical team's 1st, 2nd, ... best player there scores when talent is split evenly."""
    out: dict[str, list[float]] = {}
    for pos, n in depth.items():
        vals = sorted(
            (
                p.get("ppg") or 0.0
                for p in players.values()
                if p.get("position") == pos and (p.get("ppg") or 0) > 0
            ),
            reverse=True,
        )
        tiers = []
        for k in range(n):
            chunk = vals[num_teams * k : num_teams * (k + 1)]
            tiers.append(sum(chunk) / len(chunk) if chunk else 0.0)
        out[pos] = tiers
    return out


def position_weights(slots: Sequence[str]) -> dict[str, list[float]]:
    """Per position: weight for the 1st, 2nd, ... best player (1.0 per dedicated slot + flex share)."""
    dedicated = dict.fromkeys(GRADED_POSITIONS, 0)
    share = dict.fromkeys(GRADED_POSITIONS, 0.0)
    for slot in slots:
        if slot in dedicated:
            dedicated[slot] += 1
        for pos, f in FLEX_SHARES.get(slot, {}).items():
            share[pos] += f
    out = {}
    for pos in GRADED_POSITIONS:
        w = [1.0] * dedicated[pos]
        extra = round(share[pos], 4)
        while extra > 1e-9:
            w.append(min(1.0, extra))
            extra -= 1.0
        if w:
            out[pos] = w
    return out


def position_strength(
    pids: Iterable[str], players: Mapping[str, Mapping], weights: Mapping[str, list[float]]
) -> dict[str, float]:
    pids = list(pids)
    out = {}
    for pos, w in weights.items():
        ppg = sorted(
            (
                players[p].get("ppg") or 0.0
                for p in pids
                if p in players and players[p]["position"] == pos
            ),
            reverse=True,
        )
        out[pos] = sum(wi * v for wi, v in zip(w, ppg, strict=False))
    return out


@dataclass
class PositionGrade:
    position: str
    points: float
    league_avg: float
    rank: int
    teams: int
    grade: str
    delta_pct: float
    z: float = 0.0
    benchmark: float = 0.0  # a typical team's points here in a league this size
    vs_benchmark: float = 0.0  # points / benchmark - 1


@dataclass
class TeamProfile:
    team_id: str
    grades: dict[str, PositionGrade]
    starters: list[str]
    needs: list[str] = field(default_factory=list)
    surplus: list[str] = field(default_factory=list)
    starter_points: float = 0.0
    overall: PositionGrade | None = None


def full_strength_lineup(
    pids: Iterable[str], players: Mapping[str, Mapping], slots: Sequence[str]
) -> Lineup:
    pool = [
        LineupPlayer(p, players[p]["position"], players[p].get("ppg") or 0.0)
        for p in pids
        if p in players
    ]
    return optimal_lineup(pool, slots)


def grade_value(
    label: str, value: float, field_values: list[float], benchmark: float
) -> PositionGrade:
    """Grade one value against the typical team (`benchmark`); rank and z against the whole
    field (which includes the team itself)."""
    n = len(field_values)
    mean = sum(field_values) / n if n else 0.0
    var = sum((v - mean) ** 2 for v in field_values) / (n - 1) if n > 1 else 0.0
    sd = var**0.5
    z = (value - mean) / sd if sd > 1e-9 else 0.0
    rank = 1 + sum(1 for v in field_values if v > value + 1e-9)
    delta = (value - mean) / mean if mean else 0.0
    ratio = value / benchmark if benchmark > 0 else 1.0
    return PositionGrade(
        label,
        round(value, 2),
        round(mean, 2),
        rank,
        n,
        grade_from_ratio(ratio),
        round(delta, 3),
        round(z, 2),
        round(benchmark, 2),
        round(ratio - 1, 3),
    )


def benchmarks(
    slots: Sequence[str], tiers: Mapping[str, list[float]], weights: Mapping[str, list[float]]
) -> tuple[dict[str, float], dict[str, float]]:
    """(per position, per flex slot label) points a typical team gets there. A flex slot's
    typical filler is each position's next tier after its dedicated slots, by `FLEX_SHARES`."""
    pos_bench = {
        pos: sum(wk * (tiers.get(pos, [])[k] if k < len(tiers.get(pos, [])) else 0.0)
                 for k, wk in enumerate(w))
        for pos, w in weights.items()
    }  # fmt: skip
    dedicated = {pos: sum(1 for s in slots if s == pos) for pos in GRADED_POSITIONS}
    used = dict.fromkeys(GRADED_POSITIONS, 0)  # flex tiers already taken by earlier flex slots
    flex: dict[str, float] = {}
    for slot in slots:
        shares = FLEX_SHARES.get(slot)
        if not shares:
            continue
        pts = 0.0
        for pos, share in shares.items():
            k = dedicated[pos] + used[pos]
            t = tiers.get(pos, [])
            pts += share * (t[k] if k < len(t) else 0.0)
            used[pos] += 1
        label = slot_label(slot)
        flex[label] = flex.get(label, 0.0) + pts
    return pos_bench, flex


def slot_strength(lineup: Lineup) -> dict[str, float]:
    """Points from each flex slot type in a full-strength lineup, keyed by its label (FLEX, SFLEX,
    W/R, W/T): how good the players filling your flex spots are."""
    out: dict[str, float] = {}
    for slot, lp in lineup.slots:
        if slot in FLEX_SHARES:
            label = slot_label(slot)
            out[label] = out.get(label, 0.0) + (lp.points if lp else 0.0)
    return out


def team_profiles(
    rosters: Mapping[str, list[str]],
    players: Mapping[str, Mapping],
    slots: Sequence[str],
    grade_only: Iterable[str] | None = None,
    num_teams: int | None = None,
) -> dict[str, TeamProfile]:
    """Grade every team (or only `grade_only`) by position and overall against a typical team in
    a `num_teams` league (default: as many as `rosters`), drawn from every player in `players`,
    and rank it against all `rosters`. Plus needs (weak positions) and surplus (bench players who
    would start for a typical team)."""
    weights = position_weights(slots)
    flex_count = sum(1 for s in slots if s in FLEX_SHARES)
    depth = {pos: len(w) + flex_count for pos, w in weights.items()}
    tiers = tier_averages(players, num_teams or len(rosters), depth)
    pos_bench, flex_bench = benchmarks(slots, tiers, weights)
    total_bench = sum(pos_bench.values())
    strength = {t: position_strength(p, players, weights) for t, p in rosters.items()}
    lineups = {t: full_strength_lineup(p, players, slots) for t, p in rosters.items()}
    totals = {t: lu.points for t, lu in lineups.items()}
    flex = {t: slot_strength(lu) for t, lu in lineups.items()}

    starter_ppg: dict[str, list[float]] = {pos: [] for pos in SKILL_POSITIONS}
    for lu in lineups.values():
        for _, lp in lu.slots:
            if lp and lp.position in starter_ppg:
                starter_ppg[lp.position].append(lp.points)
    median = {pos: sorted(v)[len(v) // 2] if v else 0.0 for pos, v in starter_ppg.items()}

    n = len(rosters)
    out: dict[str, TeamProfile] = {}
    for t in rosters if grade_only is None else grade_only:
        grades = {
            pos: grade_value(
                pos, strength[t][pos], [strength[x][pos] for x in rosters], pos_bench[pos]
            )
            for pos in weights
        }
        grades |= {
            label: grade_value(
                label, pts, [flex[x].get(label, 0.0) for x in rosters], flex_bench.get(label, 0.0)
            )
            for label, pts in flex[t].items()
        }
        overall = grade_value(OVERALL, totals[t], list(totals.values()), total_bench)
        lu = lineups[t]
        starters = [lp.player_id for _, lp in lu.slots if lp]
        bench = [p for p in rosters[t] if p not in starters and p in players]
        needs = [
            pos for pos, g in grades.items()
            if pos in SKILL_POSITIONS and (g.grade in ("D", "F") or (n >= 6 and g.rank > n * 2 / 3))
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
            t,
            grades,
            starters,
            needs,
            [s for s in surplus if s not in needs],
            round(lu.points, 2),
            overall,
        )
    return out


def simulate_league(
    players: Mapping[str, Mapping],
    exclude: Iterable[str],
    num_teams: int,
    roster_positions: Sequence[str],
) -> dict[str, list[str]]:
    """A typical league for benchmarking a manual team: snake draft of the rest of the player pool
    by rest-of-season value, with sensible caps (K/DEF only for their slots, limited QBs)."""
    slots = [s for s in roster_positions if s in SLOT_ELIGIBILITY]
    size = len([s for s in roster_positions if s != "IR"])
    taken = set(exclude)
    pool = sorted(
        (
            p
            for p, v in players.items()
            if p not in taken and v.get("position") in (*SKILL_POSITIONS, "K", "DEF")
        ),
        key=lambda p: -(players[p].get("ros_value_par") or 0.0),
    )
    caps = {
        "K": slots.count("K"),
        "DEF": slots.count("DEF"),
        "QB": slots.count("QB") + (2 if "SUPER_FLEX" in slots else 1),
    }
    teams: dict[str, list[str]] = {f"sim-{i + 1}": [] for i in range(num_teams)}
    order = list(teams)
    used: set[str] = set()
    for rnd in range(size):
        for t in order if rnd % 2 == 0 else list(reversed(order)):
            have = [players[p]["position"] for p in teams[t]]
            for p in pool:
                if p in used:
                    continue
                pos = players[p]["position"]
                if pos in caps and have.count(pos) >= caps[pos]:
                    continue
                teams[t].append(p)
                used.add(p)
                break
    return teams
