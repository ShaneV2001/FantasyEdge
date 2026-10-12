"""LeagueContext: everything the advisor endpoints need for one league, built once and cached.

Cache key = (league_id, league last_synced_at, latest data sync) so a refresh invalidates it.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime

import duckdb
import polars as pl

from app.errors import NotFound, NotReady
from db.conn import query_df
from ingest.market_values import MarketFormat, market_format_for
from projections.base import LeagueShape, ProjectionInputs, run
from projections.baseline import BaselineEngine
from projections.norms import norms_window, position_rates
from scoring.rules import describe, normalize, score
from signals.lineup import SKILL_POSITIONS
from signals.regression import RegressionReport, build_report
from signals.schedule import Schedule, build_schedule, fp_allowed_index, schedule_ease

log = logging.getLogger("ff_edge.context")

MATCHUP_POSITIONS = (*SKILL_POSITIONS, "K", "DEF")

ENGINE = BaselineEngine()
DEFAULT_PLAYOFF_START = 15


@dataclass
class LeagueRow:
    league_id: str
    platform: str
    external_id: str | None
    season: int
    name: str
    num_teams: int
    roster_positions: list[str]
    scoring_profile_id: str
    rules: dict[str, float]
    trade_deadline_week: int | None
    uses_faab: bool
    faab_budget: int | None
    playoff_week_start: int | None
    last_synced_at: datetime | None
    league_type: str = "redraft"

    @property
    def market_format(self) -> MarketFormat:
        return market_format_for(
            self.roster_positions, self.num_teams, normalize(self.rules)["rec"], self.league_type
        )

    @property
    def last_week(self) -> int:
        # Fantasy season ends with the playoffs: playoff start + 2 (3-week playoffs), capped at
        # week 18 (the last NFL regular-season week).
        return min(self.playoff_start + 2, 18)

    @property
    def playoff_start(self) -> int:
        return int(self.playoff_week_start or DEFAULT_PLAYOFF_START)

    @property
    def playoff_weeks(self) -> range:
        return range(self.playoff_start, self.last_week + 1)

    @property
    def playoff_label(self) -> str:
        first, last = self.playoff_weeks[0], self.playoff_weeks[-1]
        return f"week {first}" if first == last else f"weeks {first}-{last}"


@dataclass
class TeamRow:
    team_id: str
    league_id: str
    external_roster_id: str | None
    owner_name: str
    team_name: str
    is_mine: bool
    wins: int
    losses: int
    points_for: float
    faab_remaining: int | None
    player_ids: list[str] = field(default_factory=list)
    starters: list[str] = field(default_factory=list)
    slots: dict[str, str] = field(default_factory=dict)  # player_id -> starter|bench|ir|taxi


@dataclass
class LeagueContext:
    league: LeagueRow
    season: int
    week: int
    teams: list[TeamRow]
    players: dict[str, dict]  # player_id -> projection + info + market + regression summary
    schedule: Schedule
    regression: RegressionReport
    replacement_ppg: dict[str, float]
    market_source: str | None
    market_format: str
    market_stale: bool
    built_at: datetime
    # (opponent, position) -> fantasy points allowed vs league average (>1 = easier matchup)
    matchup: dict[tuple[str, str], float] = field(default_factory=dict)
    memo: dict = field(default_factory=dict)  # per-context derived results (e.g. trade ideas)

    @property
    def shape(self) -> LeagueShape:
        return LeagueShape(
            self.league.num_teams, tuple(self.league.roster_positions), self.league.last_week
        )

    @property
    def my_team(self) -> TeamRow | None:
        return next((t for t in self.teams if t.is_mine), None)

    def team(self, team_id: str) -> TeamRow:
        for t in self.teams:
            if t.team_id == team_id:
                return t
        raise NotFound("team", f"Team not found: {team_id}")

    @property
    def rostered(self) -> set[str]:
        return {p for t in self.teams for p in t.player_ids}

    def owner_of(self, player_id: str) -> TeamRow | None:
        return next((t for t in self.teams if player_id in t.player_ids), None)

    @property
    def deadline_passed(self) -> bool:
        d = self.league.trade_deadline_week
        return d is not None and self.week > d

    @property
    def scoring_label(self) -> str:
        return describe(self.league.rules)


# ───────── loading ─────────


def load_league(con: duckdb.DuckDBPyConnection, league_id: str) -> LeagueRow:
    row = con.execute(
        """SELECT l.*, s.rules FROM leagues l
           LEFT JOIN scoring_profiles s USING (scoring_profile_id) WHERE league_id = ?""",
        [league_id],
    ).pl()
    if row.is_empty():
        raise NotFound("league", f"League not found: {league_id}")
    r = row.row(0, named=True)
    return LeagueRow(
        league_id=r["league_id"],
        platform=r["platform"],
        external_id=r["external_id"],
        season=int(r["season"]),
        name=r["name"],
        num_teams=int(r["num_teams"]),
        roster_positions=json.loads(r["roster_positions"] or "[]"),
        scoring_profile_id=r["scoring_profile_id"],
        rules=normalize(json.loads(r["rules"]) if r["rules"] else {}),
        trade_deadline_week=r["trade_deadline_week"],
        uses_faab=bool(r["uses_faab"]),
        faab_budget=r["faab_budget"],
        playoff_week_start=r["playoff_week_start"],
        last_synced_at=r["last_synced_at"],
        league_type=r.get("league_type") or "redraft",
    )


def load_teams(con: duckdb.DuckDBPyConnection, league_id: str) -> list[TeamRow]:
    teams = query_df(con, "SELECT * FROM teams WHERE league_id = ? ORDER BY team_id", [league_id])
    spots = query_df(
        con,
        """SELECT r.* FROM roster_spots r JOIN teams t USING (team_id) WHERE t.league_id = ?""",
        [league_id],
    )
    out = []
    for t in teams.iter_rows(named=True):
        mine = spots.filter(pl.col("team_id") == t["team_id"])
        out.append(
            TeamRow(
                team_id=t["team_id"],
                league_id=t["league_id"],
                external_roster_id=t["external_roster_id"],
                owner_name=t["owner_name"] or "",
                team_name=t["team_name"] or t["owner_name"] or t["team_id"],
                is_mine=bool(t["is_mine"]),
                wins=t["wins"] or 0,
                losses=t["losses"] or 0,
                points_for=t["points_for"] or 0.0,
                faab_remaining=t["faab_remaining"],
                player_ids=mine["player_id"].to_list(),
                starters=mine.filter(pl.col("slot") == "starter")["player_id"].to_list(),
                slots=dict(mine.select("player_id", "slot").iter_rows()),
            )
        )
    return out


def current_week(schedule: Schedule) -> int:
    """First regular-season week that still has an unplayed game (season over → last week)."""
    for w in range(1, schedule.weeks + 1):
        if any(k[1] == w and k not in schedule.completed for k in schedule.games):
            return w
    return schedule.weeks


def _market(
    con: duckdb.DuckDBPyConnection, fmt: MarketFormat
) -> tuple[pl.DataFrame, str | None, str, bool]:
    """Latest snapshot for the league's format; falls back to any available format."""
    df = query_df(
        con,
        """SELECT * FROM market_values WHERE format = ?
           QUALIFY snapshot_date = max(snapshot_date) OVER ()""",
        [fmt.key],
    )
    fmt_used = fmt.key
    if df.is_empty():
        df = query_df(
            con,
            """SELECT * FROM market_values
               QUALIFY snapshot_date = max(snapshot_date) OVER ()
                   AND format = first(format ORDER BY format) OVER ()""",
        )
        fmt_used = df["format"][0] if df.height else fmt.key
    if df.is_empty():
        return df, None, fmt.key, True
    source = df["source"][0]
    stale = fmt_used != fmt.key or source != "fantasycalc"
    return df.unique("player_id"), source, fmt_used, stale


UNPROJECTED_NOTE = "No projection: not in the local player database (run `tasks.py data`)."


def _add_unprojected(info: dict[str, dict], teams: list[TeamRow], columns: list[str]) -> None:
    """Rostered players we can't project (e.g. Sleeper IDs missing from `players`) still appear
    everywhere, at zero points, instead of silently vanishing from the roster."""
    missing = sorted({p for t in teams for p in t.player_ids if p not in info})
    if missing:
        log.warning("%d rostered player(s) have no projection: %s", len(missing), missing[:5])
    for pid in missing:
        row: dict = dict.fromkeys(columns)
        row |= {
            "player_id": pid,
            "name": f"Unknown player ({pid})",
            "position": "?",
            "method": "no_data",
            "availability_note": UNPROJECTED_NOTE,
            "regression_score": 0.0,
            "ease_next4": None,
            "ease_playoffs": None,
        }
        for col in ("ppg", "p10", "p90", "proj_ros_points", "next4_points", "ros_value_par",
                    "proj_next4_ppg", "replacement_ros"):  # fmt: skip
            row[col] = 0.0
        for col in ("games_played", "games_remaining"):
            row[col] = 0
        info[pid] = row


def build_context(con: duckdb.DuckDBPyConnection, league_id: str) -> LeagueContext:
    league = load_league(con, league_id)
    teams = load_teams(con, league_id)

    games = query_df(con, "SELECT * FROM nfl_games WHERE season = ?", [league.season])
    if games.is_empty():
        raise NotReady(
            f"No {league.season} NFL schedule in the local store — run `python tasks.py data`."
        )
    schedule = build_schedule(games, league.season)
    week = current_week(schedule)

    players = query_df(con, "SELECT * FROM players")
    stats = query_df(
        con,
        """SELECT s.*, p.position FROM player_week_stats s JOIN players p USING (player_id)
           WHERE s.season BETWEEN ? AND ?""",
        [league.season - 1, league.season],
    )
    if stats.is_empty():
        raise NotReady("No nflverse stats in the local store — run `python tasks.py data`.")
    scored = score(stats, league.rules)
    through = week  # games already final this week are included; unplayed ones don't exist yet

    shape = LeagueShape(league.num_teams, tuple(league.roster_positions), league.last_week)
    inputs = ProjectionInputs(scored, players, schedule, league.rules, league.season, week, shape)
    proj = run(ENGINE, inputs)

    rates = position_rates(norms_window(scored, league.season, through), league.rules)
    report = build_report(scored, rates, league.season, through)
    matchup = fp_allowed_index(scored, league.season, through)

    market, source, fmt_used, stale = _market(con, league.market_format)

    proj = proj.join(
        players.select(
            "player_id", "sleeper_id", "full_name", "birth_date", "years_exp", "depth_chart_order"
        ),
        on="player_id",
        how="left",
    ).join(
        market.select(
            "player_id",
            pl.col("value").alias("market_value"),
            pl.col("position_rank").alias("market_pos_rank"),
            pl.col("trend_30d").alias("market_trend_30d"),
        ),
        on="player_id",
        how="left",
    )
    # model rank vs market rank, compared within the market-covered player set at each position
    proj = proj.with_columns(
        pl.when(pl.col("market_value").is_not_null())
        .then(
            pl.col("ros_value_par")
            .rank("ordinal", descending=True)
            .over(["position", pl.col("market_value").is_not_null()])
        )
        .alias("model_pos_rank"),
        pl.when(pl.col("market_value").is_not_null())
        .then(
            pl.col("market_value")
            .rank("ordinal", descending=True)
            .over(["position", pl.col("market_value").is_not_null()])
        )
        .alias("market_rank_cov"),
    )
    tdoe = report.tdoe.select("player_id", "tdoe", "expected_td", "actual_td")
    proj = proj.join(tdoe, on="player_id", how="left")

    replacement_ppg = _replacement_ppg(proj, shape)
    info: dict[str, dict] = {}
    for r in proj.iter_rows(named=True):
        pid = r["player_id"]
        r["name"] = r.pop("full_name") or pid
        r["regression_score"] = report.score(pid)
        pos = r["position"]
        if pos in MATCHUP_POSITIONS:
            r["ease_next4"] = schedule_ease(
                schedule,
                matchup,
                r["nfl_team"],
                pos,
                range(week, min(week + 4, league.last_week + 1)),
            )
            r["ease_playoffs"] = schedule_ease(
                schedule, matchup, r["nfl_team"], pos, league.playoff_weeks
            )
        else:
            r["ease_next4"] = r["ease_playoffs"] = None
        info[pid] = r
    _add_unprojected(info, teams, proj.columns)

    return LeagueContext(
        league=league,
        season=league.season,
        week=week,
        teams=teams,
        players=info,
        schedule=schedule,
        regression=report,
        replacement_ppg=replacement_ppg,
        market_source=source,
        market_format=fmt_used,
        market_stale=stale,
        built_at=datetime.now(),
        matchup=matchup,
    )


def _replacement_ppg(proj: pl.DataFrame, shape: LeagueShape) -> dict[str, float]:
    from projections.base import replacement_ranks

    out = {}
    for pos, n in replacement_ranks(shape).items():
        ppg = proj.filter(pl.col("position") == pos)["ppg"].sort(descending=True)
        out[pos] = float(ppg[n - 1]) if ppg.len() >= n else 0.0
    return out


# ───────── cache ─────────

_cache: dict[str, tuple[tuple, LeagueContext]] = {}
_lock = threading.Lock()


def _version(con: duckdb.DuckDBPyConnection, league_id: str) -> tuple:
    lsync = con.execute(
        "SELECT last_synced_at FROM leagues WHERE league_id = ?", [league_id]
    ).fetchone()
    dsync = con.execute(
        "SELECT max(last_synced_at) FROM sync_log WHERE source NOT LIKE 'league:%'"
    ).fetchone()
    roster_n = con.execute(
        "SELECT count(*), max(synced_at) FROM roster_spots r JOIN teams t USING (team_id) WHERE t.league_id = ?",
        [league_id],
    ).fetchone()
    return (lsync[0] if lsync else None, dsync[0] if dsync else None, roster_n)


def get_context(con: duckdb.DuckDBPyConnection, league_id: str) -> LeagueContext:
    key = _version(con, league_id)
    with _lock:
        hit = _cache.get(league_id)
        if hit and hit[0] == key:
            return hit[1]
        ctx = build_context(con, league_id)
        _cache[league_id] = (key, ctx)
        return ctx


def invalidate(league_id: str | None = None) -> None:
    with _lock:
        if league_id is None:
            _cache.clear()
        else:
            _cache.pop(league_id, None)
