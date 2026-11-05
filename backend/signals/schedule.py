"""NFL schedule helpers: byes, remaining games, opponents, and opponent strength vs position."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import cached_property
from zoneinfo import ZoneInfo

import polars as pl

REG_SEASON_WEEKS = 18
EASTERN = ZoneInfo("America/New_York")  # nflverse game times
LIVE_GRACE = timedelta(hours=12)  # after a week's last kickoff, its games should be final

# How far a matchup moves a weekly projection: points × (1 + α × (index − 1)). α = 0 means the
# schedule is ignored for that position. Chosen per position by `python -m models.run
# tune-matchups` (walk-forward, tuned on earlier seasons and checked on the latest).
# 2025 holdout, next-week MAE at chosen α vs α=0: QB 6.46/6.49, RB 4.08/4.09, WR 3.72/3.72,
# K 3.77/3.79, DEF 4.18/4.30 (weekly Spearman 0.12 → 0.23). TE: matchups didn't help.
# QB and RB now meet the opponent by stat component (`signals.matchup_factors`), where
# `tune-factors` chose α 0.5 (QB) and 0.25 (RB) for that blend.
MATCHUP_ALPHA: dict[str, float] = {
    "QB": 0.5, "RB": 0.25, "WR": 0.25, "TE": 0.0, "K": 0.25, "DEF": 0.75,
}  # fmt: skip


@dataclass(frozen=True)
class Schedule:
    season: int
    weeks: int
    games: dict[tuple[str, int], str]  # (team, week) -> opponent
    byes: dict[str, int]  # team -> bye week
    completed: frozenset[tuple[str, int]] = frozenset()  # (team, week) games already final
    # (team, week) -> kickoff (UTC). nflverse times are US/Eastern; missing when unknown.
    kickoffs: Mapping[tuple[str, int], datetime] = field(default_factory=dict)
    # (team, week) -> the team's implied points from the betting lines; missing until posted
    implied: Mapping[tuple[str, int], float] = field(default_factory=dict)

    def kickoff(self, team: str | None, week: int) -> datetime | None:
        return self.kickoffs.get((team, week)) if team else None

    @cached_property
    def _last_kickoff(self) -> dict[int, datetime]:
        out: dict[int, datetime] = {}
        for (_, week), k in self.kickoffs.items():
            out[week] = max(out.get(week, k), k)
        return out

    def live(self, week: int, now: datetime) -> bool:
        """True until `LIVE_GRACE` after the week's last kickoff. Past that, an unfinished game
        means the local results are out of date, not that the game is still on."""
        last = self._last_kickoff.get(week)
        return last is not None and now <= last + LIVE_GRACE

    def started(self, team: str | None, week: int, now: datetime) -> bool:
        """True once the team's game this week is final, or has kicked off in a live week."""
        if team is None or (team, week) not in self.games:
            return False
        if (team, week) in self.completed:
            return True
        k = self.kickoff(team, week)
        return k is not None and k <= now and self.live(week, now)

    def plays(self, team: str | None, week: int) -> bool:
        """True if the team has a game this week that has not been played yet."""
        return (
            team is not None and (team, week) in self.games and (team, week) not in self.completed
        )

    def has_game(self, team: str | None, week: int) -> bool:
        return team is not None and (team, week) in self.games

    def opponent(self, team: str | None, week: int) -> str | None:
        return self.games.get((team, week)) if team else None

    def bye(self, team: str | None) -> int | None:
        return self.byes.get(team) if team else None

    def remaining_games(self, team: str | None, start: int, end: int) -> list[int]:
        return [w for w in range(start, end + 1) if self.plays(team, w)]


def build_schedule(games: pl.DataFrame, season: int) -> Schedule:
    """A team's bye is the regular-season week in which it has no game row."""
    g = games.filter(pl.col("season") == season)
    if "kickoff" not in g.columns:
        g = g.with_columns(pl.lit(None, pl.Datetime).alias("kickoff"))
    for c in ("spread_line", "total_line"):
        if c not in g.columns:
            g = g.with_columns(pl.lit(None, pl.Float64).alias(c))
    matchups: dict[tuple[str, int], str] = {}
    completed: set[tuple[str, int]] = set()
    kickoffs: dict[tuple[str, int], datetime] = {}
    implied: dict[tuple[str, int], float] = {}
    for home, away, week, score, kick, spread, total in g.select(
        "home_team", "away_team", "week", "home_score", "kickoff", "spread_line", "total_line"
    ).iter_rows():
        matchups[(home, week)] = away
        matchups[(away, week)] = home
        if spread is not None and total is not None:  # nflverse: spread > 0 = home favoured
            implied[(home, week)] = (total + spread) / 2
            implied[(away, week)] = (total - spread) / 2
        if score is not None:
            completed |= {(home, week), (away, week)}
        if kick is not None:
            utc = kick.replace(tzinfo=EASTERN).astimezone(UTC)
            kickoffs[(home, week)] = kickoffs[(away, week)] = utc
    weeks = int(g["week"].max()) if g.height else REG_SEASON_WEEKS
    played: dict[str, set[int]] = defaultdict(set)
    for team, week in matchups:
        played[team].add(week)
    byes = {}
    for team, ws in played.items():
        missing = [w for w in range(1, weeks + 1) if w not in ws]
        if missing:
            byes[team] = missing[0]
    return Schedule(season, weeks, matchups, byes, frozenset(completed), kickoffs, implied)


def allowed_index(
    df: pl.DataFrame,
    keys: list[str],
    value: str,
    season: int,
    through_week: int,
    prior_weight: float = 3.0,
    mean_weight: float | pl.Expr = 0.0,
) -> pl.DataFrame:
    """Opponent × `keys` → `value` allowed per game relative to the league average (`idx`).

    The current season is shrunk toward the prior season with `prior_weight` pseudo-games and,
    for noisy stats such as touchdowns, toward the league average with `mean_weight` more (a
    number, or an expression over `keys`). Returns opponent, keys, idx and rank (1 = allows the
    most).
    """
    keep = pl.col("opponent").is_not_null()
    for k in keys:
        keep &= pl.col(k).is_not_null()
    cur = df.filter((pl.col("season") == season) & (pl.col("week") <= through_week) & keep)
    prior = df.filter((pl.col("season") == season - 1) & keep)
    by = ["opponent", *keys]

    def per_game(d: pl.DataFrame) -> pl.DataFrame:
        return (
            d.group_by(*by, "week")
            .agg(pl.col(value).sum())
            .group_by(*by)
            .agg(pl.col(value).sum().alias("total"), pl.len().alias("games"))
        )

    c = per_game(cur).rename({"total": "cur_total", "games": "cur_games"})
    p = per_game(prior).with_columns((pl.col("total") / pl.col("games")).alias("prior_avg"))
    out = c.join(p.select(*by, "prior_avg"), on=by, how="full", coalesce=True)
    out = out.with_columns(pl.col("cur_total").fill_null(0), pl.col("cur_games").fill_null(0))
    pos_avg = out.group_by(keys).agg(
        (pl.col("cur_total").sum() / pl.col("cur_games").sum()).alias("pos_cur"),
        pl.col("prior_avg").mean().alias("pos_prior"),
    )
    out = out.join(pos_avg, on=keys).with_columns(
        pl.coalesce("prior_avg", "pos_prior", "pos_cur").alias("prior_avg")
    )
    mw = pl.lit(mean_weight) if isinstance(mean_weight, int | float) else mean_weight
    toward_mean = pl.when(mw > 0).then(mw * pl.coalesce("pos_prior", "pos_cur")).otherwise(0.0)
    out = out.with_columns(
        (
            (pl.col("cur_total") + prior_weight * pl.col("prior_avg") + toward_mean)
            / (pl.col("cur_games") + prior_weight + mw)
        ).alias("allowed")
    )
    league = out.group_by(keys).agg(pl.col("allowed").mean().alias("league_avg"))
    return (
        out.join(league, on=keys)
        .with_columns((pl.col("allowed") / pl.col("league_avg")).alias("idx"))
        .filter(pl.col("opponent").is_not_null() & pl.col("idx").is_finite())
        .with_columns(pl.col("idx").rank("ordinal", descending=True).over(keys).alias("rank"))
        .select(*by, "idx", "rank")
    )


def fp_allowed_index(
    scored: pl.DataFrame, season: int, through_week: int, prior_weight: float = 3.0
) -> dict[tuple[str, str], float]:
    """Opponent × position → fantasy points allowed per game relative to league average (1.0).

    >1 means the opponent gives up more than average (an easier matchup). For skill players and
    kickers the opponent is a defense; for team defenses (DEF rows) it is the offense they faced,
    so (KC, "DEF") is how many DEF points defenses score against KC. The current season is shrunk
    toward the prior season with `prior_weight` pseudo-games.
    """
    df = allowed_index(scored, ["position"], "fp", season, through_week, prior_weight)
    return {
        (o, pos): float(i) for o, pos, i in df.select("opponent", "position", "idx").iter_rows()
    }


def schedule_ease(
    sched: Schedule,
    index: dict[tuple[str, str], float],
    team: str | None,
    position: str,
    weeks: range | list[int],
) -> float | None:
    """Average matchup index over the given weeks (byes skipped). None if no games."""
    vals = [
        index.get((opp, position), 1.0)
        for w in weeks
        if (opp := sched.opponent(team, w)) is not None
    ]
    return sum(vals) / len(vals) if vals else None


def matchup_multiplier(
    index: Mapping[tuple[str, str], float], opponent: str | None, position: str, alpha: float
) -> float:
    """Scale for a player's per-game projection against `opponent` (1.0 = neutral)."""
    if opponent is None or alpha == 0:
        return 1.0
    return max(1.0 + alpha * (index.get((opponent, position), 1.0) - 1.0), 0.0)
