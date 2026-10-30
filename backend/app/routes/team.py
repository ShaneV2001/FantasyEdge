from __future__ import annotations

import logging
from typing import Literal

import duckdb
from fastapi import APIRouter, Depends, Query

from app.deps import get_clients, get_con, get_tuning, write_lock
from app.errors import AuthRequired
from app.schemas import models as m
from app.services import context, leagues, player, recap, views
from app.services.context import LeagueContext, get_context
from app.user_settings import UserSettings
from ingest.http import AuthRejected, SourceUnavailable
from ingest.run import Clients

router = APIRouter(prefix="/team", tags=["team"])
log = logging.getLogger("fantasyedge.api")


def refresh_if_stale(con: duckdb.DuckDBPyConnection, c: Clients, league_id: str) -> None:
    """Rosters are a cache of Sleeper/ESPN: loading (or switching to) a team re-pulls its league
    when the copy is older than `leagues.SYNC_MAX_AGE`. If the platform can't be reached, the
    cached rosters are used and the page says when they were last updated."""
    try:
        with write_lock:
            if leagues.ensure_synced(con, c, league_id):
                context.invalidate(league_id)
    except (SourceUnavailable, AuthRejected, AuthRequired) as exc:
        log.warning("roster refresh for %s failed, using the cached rosters: %s", league_id, exc)


def team_ctx(
    team_id: str,
    con: duckdb.DuckDBPyConnection = Depends(get_con),
    tuning: UserSettings = Depends(get_tuning),
    c: Clients = Depends(get_clients),
) -> LeagueContext:
    league_id = leagues.league_id_for_team(con, team_id)
    refresh_if_stale(con, c, league_id)
    ctx = get_context(con, league_id, tuning)
    ctx.team(team_id)  # 404 if the team vanished from the league
    return ctx


RosterView = Literal["current", "after"]
ROSTER_QUERY = Query(
    "current", description="after: as if your accepted ESPN trades had already gone through"
)


def view_ctx(
    ctx: LeagueContext, con: duckdb.DuckDBPyConnection, team_id: str, roster: RosterView
) -> tuple[LeagueContext, list]:
    """The league for this view: today's, or (for `after`, when the team has accepted trades
    waiting to process) a copy with those trades applied, plus the trades."""
    if roster == "after":
        rows = views.involves(leagues.pending_trades(con, ctx.league.league_id), team_id)
        if rows:
            return views.with_trades(ctx, rows), rows
    return ctx, []


@router.get("/{team_id}", response_model=m.TeamOut)
def get_team(
    team_id: str,
    roster: RosterView = ROSTER_QUERY,
    ctx: LeagueContext = Depends(team_ctx),
    con: duckdb.DuckDBPyConnection = Depends(get_con),
) -> m.TeamOut:
    """Roster with projections, ROS value, market value, flags and grades vs the league."""
    view, rows = view_ctx(ctx, con, team_id, roster)
    return views.team_view(view, team_id, len(rows), views.arriving(rows, team_id))


@router.get("/{team_id}/players", response_model=m.PlayersTableOut)
def get_players_table(
    team_id: str,
    q: str = Query("", max_length=60, description="Name search (accents and case ignored)"),
    pos: m.Position | None = None,
    nfl_team: str | None = Query(None, max_length=4, alias="team"),
    avail: m.Availability = Query("all", description="mine | other (another team) | fa"),
    sort: m.PlayerSort = "ros",
    dir: Literal["asc", "desc"] = "desc",
    page: int = Query(0, ge=0),
    size: int = Query(50, ge=10, le=100),
    ctx: LeagueContext = Depends(team_ctx),
) -> m.PlayersTableOut:
    """Every player with a projection: search, filter by position / NFL team / who has him,
    sort by PPG, ROS points, value, market value or verdict, paged on the server."""
    return views.players_table(
        ctx, team_id, q, pos, nfl_team, avail, sort, dir == "desc", page, size
    )


@router.get("/{team_id}/players/{player_id}", response_model=m.PlayerDetailOut)
def get_player(
    team_id: str,
    player_id: str,
    ctx: LeagueContext = Depends(team_ctx),
    con: duckdb.DuckDBPyConnection = Depends(get_con),
) -> m.PlayerDetailOut:
    """Bio, verdict, weekly statlines and projected-vs-actual points for one player."""
    flags = [views.flag_out(f) for f in ctx.regression.for_player(player_id)]
    override = con.execute(
        "SELECT out_for_season, return_week FROM player_availability WHERE player_id = ?",
        [player_id],
    ).fetchone()
    return player.player_detail(ctx, team_id, player_id, flags, override)


@router.get("/{team_id}/players/{player_id}/trades", response_model=m.PlayerTradesOut)
def get_player_trades(
    team_id: str,
    player_id: str,
    want: Literal["QB", "RB", "WR", "TE", "ANY"] = Query(
        "ANY", description="When he's yours: the position you want back"
    ),
    ctx: LeagueContext = Depends(team_ctx),
) -> m.PlayerTradesOut:
    """Trades built around one player: if he's yours, deals that give him away (1 or 2 players
    back); if he's on another team, packages of 1-2 of your players for him. Deals the other
    lineup also likes come first."""
    return views.player_trades_view(ctx, team_id, player_id, want)


@router.get("/{team_id}/buy-targets", response_model=m.BuyTargetsOut)
def get_buy_targets(team_id: str, ctx: LeagueContext = Depends(team_ctx)) -> m.BuyTargetsOut:
    """Players the market undervalues vs our projection (buy), and your overvalued ones (sell)."""
    return views.buy_targets_view(ctx, team_id)


@router.get("/{team_id}/rankings", response_model=m.RankingsOut)
def get_rankings(
    team_id: str,
    top: int = Query(10, ge=5, le=50, description="Players per position (10, 15, 20, 30 …)"),
    ctx: LeagueContext = Depends(team_ctx),
) -> m.RankingsOut:
    """Top N per position by schedule-adjusted points, for each upcoming week and the rest of
    the season (all players; owner labeled)."""
    return views.rankings_view(ctx, team_id, top)


@router.get("/{team_id}/startsit", response_model=m.StartSitOut)
def get_startsit(
    team_id: str,
    week: int | None = Query(None, ge=1, le=18, description="Default: this week"),
    ctx: LeagueContext = Depends(team_ctx),
) -> m.StartSitOut:
    """Your real lineup and the best lineup for a week (matchup-adjusted projections), with the
    positions each slot accepts and who is locked (game already final) or on IR. Read-only: the
    planner never changes your lineup on the platform."""
    return views.startsit_view(ctx, team_id, week)


@router.get("/{team_id}/waivers", response_model=m.WaiversOut)
def get_waivers(
    team_id: str,
    ctx: LeagueContext = Depends(team_ctx),
    con: duckdb.DuckDBPyConnection = Depends(get_con),
) -> m.WaiversOut:
    """Free agents ranked by net rest-of-season gain to your starting lineup (after the best
    drop), with a FAAB bid range, plus Sleeper's most-added players of the last 24 hours."""
    trending = con.execute(
        """SELECT player_id, count, fetched_at FROM trending
           WHERE kind = 'add' AND lookback_hours = 24 ORDER BY count DESC"""
    ).fetchall()
    return views.waivers_view(ctx, team_id, trending)


@router.get("/{team_id}/advice", response_model=m.AdviceOut)
def get_advice(
    team_id: str,
    roster: RosterView = ROSTER_QUERY,
    ctx: LeagueContext = Depends(team_ctx),
    con: duckdb.DuckDBPyConnection = Depends(get_con),
) -> m.AdviceOut:
    """Ranked advisor feed (Offer / Trade / Sell / Buy / Waiver / Lineup / Bye prep) + team
    grades."""
    view, rows = view_ctx(ctx, con, team_id, roster)
    if rows:
        return views.advice_view(view, team_id, len(rows))
    league_id = ctx.league.league_id
    return views.advice_view(
        ctx,
        team_id,
        accepted=leagues.pending_trades(con, league_id),
        offers=leagues.trade_offers(con, league_id),
    )


@router.get("/{team_id}/regression", response_model=m.RegressionOut)
def get_regression(
    team_id: str,
    roster: RosterView = ROSTER_QUERY,
    ctx: LeagueContext = Depends(team_ctx),
    con: duckdb.DuckDBPyConnection = Depends(get_con),
) -> m.RegressionOut:
    """TD over expected, efficiency outliers and usage/production mismatches."""
    return views.regression_view(view_ctx(ctx, con, team_id, roster)[0], team_id)


@router.get("/{team_id}/byes", response_model=m.ByesOut)
def get_byes(team_id: str, ctx: LeagueContext = Depends(team_ctx)) -> m.ByesOut:
    """Week × lineup-slot grid of remaining byes with danger weeks."""
    return views.byes_view(ctx, team_id)


@router.get("/{team_id}/pending-trades", response_model=m.PendingTradesOut)
def get_pending_trades(
    team_id: str,
    ctx: LeagueContext = Depends(team_ctx),
    con: duckdb.DuckDBPyConnection = Depends(get_con),
) -> m.PendingTradesOut:
    """Trades you accepted on ESPN that are waiting to process, and your lineups once they do."""
    league_id = ctx.league.league_id
    row = con.execute(
        "SELECT trade_review_hours FROM leagues WHERE league_id = ?", [league_id]
    ).fetchone()
    return views.pending_view(
        ctx, team_id, leagues.pending_trades(con, league_id), row[0] if row else None
    )


@router.get("/{team_id}/alerts", response_model=m.GamedayOut)
def get_gameday_alerts(
    team_id: str,
    ctx: LeagueContext = Depends(team_ctx),
    con: duckdb.DuckDBPyConnection = Depends(get_con),
) -> m.GamedayOut:
    """Starters this week who might not play (injury status, practice, bye), each with the bench
    player or free agent to start instead. Games already kicked off are skipped."""
    changes = context.status_changes(con, ctx.team(team_id).player_ids)
    return views.gameday_view(ctx, team_id, changes)


@router.get("/{team_id}/matchup", response_model=m.MatchupOut)
def get_matchup(
    team_id: str,
    ctx: LeagueContext = Depends(team_ctx),
    con: duckdb.DuckDBPyConnection = Depends(get_con),
) -> m.MatchupOut:
    """This week's head-to-head matchup with your win chance, the standings with playoff odds,
    and your week-by-week schedule."""
    return views.matchup_view(ctx, team_id, leagues.matchups(con, ctx.league.league_id))


@router.get("/{team_id}/recap", response_model=m.RecapOut)
def get_recap(
    team_id: str,
    week: int | None = Query(None, ge=1, le=18, description="Default: the last completed week"),
    ctx: LeagueContext = Depends(team_ctx),
    con: duckdb.DuckDBPyConnection = Depends(get_con),
) -> m.RecapOut:
    """A played week looked back on: your lineup vs the best you could have set and vs the one
    FantasyEdge's projections would have picked, plus how the projections held up this season."""
    return recap.recap_view(ctx, team_id, leagues.matchups(con, ctx.league.league_id), week)


@router.get("/{team_id}/trade-offers", response_model=m.TradeOffersOut)
def get_trade_offers(
    team_id: str,
    ctx: LeagueContext = Depends(team_ctx),
    con: duckdb.DuckDBPyConnection = Depends(get_con),
) -> m.TradeOffersOut:
    """Open ESPN trade offers sent to you (or by you), each graded by the trade analyzer."""
    return views.offers_view(ctx, team_id, leagues.trade_offers(con, ctx.league.league_id))


@router.delete("/{team_id}", response_model=m.ForgetOut)
def forget_team(team_id: str, con: duckdb.DuckDBPyConnection = Depends(get_con)) -> m.ForgetOut:
    """Delete a manual team, or forget a Sleeper/ESPN league (with its saved ESPN login) from
    FantasyEdge. Nothing changes on Sleeper or ESPN; connect again any time."""
    league_id = leagues.league_id_for_team(con, team_id)
    with write_lock:
        platform, n = leagues.forget_league(con, league_id)
    context.invalidate(league_id)
    return m.ForgetOut(league_id=league_id, platform=platform, teams_removed=n)


@router.patch("/{team_id}", response_model=m.TeamRef)
def rename_team(
    team_id: str, body: m.RenameTeamRequest, con: duckdb.DuckDBPyConnection = Depends(get_con)
) -> m.TeamRef:
    """Rename a manual team."""
    with write_lock:
        league_id = leagues.rename_team(con, team_id, body.name)
    context.invalidate(league_id)
    return m.TeamRef(team_id=team_id, league_id=league_id)


@router.put("/{team_id}/roster", response_model=m.TeamRef)
def update_roster(
    team_id: str, body: m.ManualLeagueRequest, con: duckdb.DuckDBPyConnection = Depends(get_con)
) -> m.TeamRef:
    """Edit a manual team: name, scoring, league size, lineup/bench/IR depth and players."""
    with write_lock:
        league_id, _ = leagues.update_manual(
            con,
            team_id,
            name=body.name,
            num_teams=body.num_teams,
            roster_positions=body.roster_positions,
            scoring=body.scoring,
            player_ids=body.player_ids,
            starters=body.starters,
            ir=body.ir,
            trade_deadline_week=body.trade_deadline_week,
            playoff_week_start=body.playoff_week_start,
        )
    context.invalidate(league_id)
    return m.TeamRef(team_id=team_id, league_id=league_id)
