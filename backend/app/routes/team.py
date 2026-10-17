from __future__ import annotations

from typing import Literal

import duckdb
from fastapi import APIRouter, Depends, Query

from app.deps import get_con, get_tuning, write_lock
from app.schemas import models as m
from app.services import context, leagues, player, views
from app.services.context import LeagueContext, get_context
from app.user_settings import UserSettings

router = APIRouter(prefix="/team", tags=["team"])


def team_ctx(
    team_id: str,
    con: duckdb.DuckDBPyConnection = Depends(get_con),
    tuning: UserSettings = Depends(get_tuning),
) -> LeagueContext:
    ctx = get_context(con, leagues.league_id_for_team(con, team_id), tuning)
    ctx.team(team_id)  # 404 if the team vanished from the league
    return ctx


@router.get("/{team_id}", response_model=m.TeamOut)
def get_team(team_id: str, ctx: LeagueContext = Depends(team_ctx)) -> m.TeamOut:
    """Roster with projections, ROS value, market value, flags and grades vs the league."""
    return views.team_view(ctx, team_id)


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
    team_id: str, player_id: str, ctx: LeagueContext = Depends(team_ctx)
) -> m.PlayerDetailOut:
    """Bio, verdict, weekly statlines and projected-vs-actual points for one player."""
    flags = [views.flag_out(f) for f in ctx.regression.for_player(player_id)]
    return player.player_detail(ctx, team_id, player_id, flags)


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


@router.get("/{team_id}/advice", response_model=m.AdviceOut)
def get_advice(team_id: str, ctx: LeagueContext = Depends(team_ctx)) -> m.AdviceOut:
    """Ranked advisor feed (Trade / Sell / Buy / Waiver / Lineup / Bye prep) + team grades."""
    return views.advice_view(ctx, team_id)


@router.get("/{team_id}/regression", response_model=m.RegressionOut)
def get_regression(team_id: str, ctx: LeagueContext = Depends(team_ctx)) -> m.RegressionOut:
    """TD over expected, efficiency outliers and usage/production mismatches."""
    return views.regression_view(ctx, team_id)


@router.get("/{team_id}/byes", response_model=m.ByesOut)
def get_byes(team_id: str, ctx: LeagueContext = Depends(team_ctx)) -> m.ByesOut:
    """Week × lineup-slot grid of remaining byes with danger weeks."""
    return views.byes_view(ctx, team_id)


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
