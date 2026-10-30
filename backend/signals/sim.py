"""Head-to-head odds: one week's win probability and the season's playoff odds.

A team's score in a week is modelled as normal. The mean is its lineup's projected points; the
variance is the sum of its starters' per-game variances, taken from each player's p10–p90 band
(sd = (p90 − p10) / 2.563) and scaled by that week's projection (matchup, injury). Points from
games already final are banked with no variance. Starters are treated as independent.

Playoff odds play out the rest of the regular season `sims` times (seeded, so the same inputs
always give the same odds) and seed teams by wins, then points for. Divisions aren't modelled.
"""

from __future__ import annotations

import math
import random
from collections import Counter
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field

BAND_Z = 2 * 1.2816  # p10 to p90 is ±1.2816 sd
SIMS = 5000


@dataclass(frozen=True)
class TeamWeek:
    mean: float
    sd: float


def player_sd(p: Mapping, week_points: float) -> float:
    """A player's sd for one week: his per-game band scaled by that week's projection."""
    ppg, p10, p90 = p.get("ppg") or 0.0, p.get("p10"), p.get("p90")
    if ppg <= 0 or p10 is None or p90 is None or week_points <= 0:
        return 0.0
    return max(p90 - p10, 0.0) / BAND_Z * (week_points / ppg)


def team_week(
    starters: Collection[str],
    points: Mapping[str, float],
    players: Mapping[str, Mapping],
    banked: Mapping[str, float] | None = None,
) -> TeamWeek:
    """`points`: each starter's projection for the week; `banked`: actual points of starters
    whose game is final (they replace the projection and add no variance)."""
    banked = banked or {}
    mean, var = 0.0, 0.0
    for p in starters:
        if p in banked:
            mean += banked[p]
            continue
        pts = points.get(p, 0.0)
        mean += pts
        var += player_sd(players.get(p, {}), pts) ** 2
    return TeamWeek(round(mean, 2), round(math.sqrt(var), 2))


def win_prob(a: TeamWeek, b: TeamWeek) -> float:
    """P(a outscores b)."""
    sd = math.hypot(a.sd, b.sd)
    if sd == 0:
        return 1.0 if a.mean > b.mean else 0.0 if a.mean < b.mean else 0.5
    return 0.5 * (1 + math.erf((a.mean - b.mean) / (sd * math.sqrt(2))))


@dataclass(frozen=True)
class Record:
    wins: int
    losses: int
    points_for: float


@dataclass
class Odds:
    team_id: str
    playoffs: float  # share of sims making the playoffs
    seeds: list[float] = field(default_factory=list)  # share finishing 1st, 2nd, ... (all teams)
    wins: float = 0.0  # mean final wins
    losses: float = 0.0


def season_odds(
    records: Mapping[str, Record],
    games: Sequence[tuple[int, str, str]],
    weeks: Mapping[tuple[int, str], TeamWeek],
    playoff_teams: int,
    sims: int = SIMS,
    seed: int = 0,
) -> dict[str, Odds]:
    """Play out the remaining `games` (week, team, opponent; each pair once) from `records`."""
    teams = sorted(records)
    n = len(teams)
    rng = random.Random(seed)
    made = dict.fromkeys(teams, 0)
    seeds = {t: [0] * n for t in teams}
    wins_total = dict.fromkeys(teams, 0)
    left = Counter(t for _, a, b in games for t in (a, b))  # games still to play per team
    draws = [(a, b, weeks.get((w, a)), weeks.get((w, b))) for w, a, b in games]
    for _ in range(sims):
        wins = {t: records[t].wins for t in teams}
        pf = {t: records[t].points_for for t in teams}
        for a, b, wa, wb in draws:
            sa = rng.gauss(wa.mean, wa.sd) if wa else 0.0
            sb = rng.gauss(wb.mean, wb.sd) if wb else 0.0
            pf[a] += sa
            pf[b] += sb
            wins[a if sa > sb else b] += 1
        order = sorted(teams, key=lambda t: (-wins[t], -pf[t]))
        for i, t in enumerate(order):
            seeds[t][i] += 1
            if i < playoff_teams:
                made[t] += 1
            wins_total[t] += wins[t]
    out = {}
    for t in teams:
        mean_wins = wins_total[t] / sims
        out[t] = Odds(
            t,
            round(made[t] / sims, 4),
            [round(s / sims, 4) for s in seeds[t]],
            round(mean_wins, 2),
            round(records[t].losses + left[t] - (mean_wins - records[t].wins), 2),
        )
    return out
