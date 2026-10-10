from __future__ import annotations

import duckdb
from fastapi import APIRouter, Depends

from app.deps import get_con
from app.schemas import models as m
from app.services import leagues, views
from app.services.context import LeagueContext, get_context

router = APIRouter(prefix="/team", tags=["team"])


def team_ctx(team_id: str, con: duckdb.DuckDBPyConnection = Depends(get_con)) -> LeagueContext:
    ctx = get_context(con, leagues.league_id_for_team(con, team_id))
    ctx.team(team_id)  # 404 if the team vanished from the league
    return ctx


@router.get("/{team_id}", response_model=m.TeamOut)
def get_team(team_id: str, ctx: LeagueContext = Depends(team_ctx)) -> m.TeamOut:
    """Roster with projections, ROS value, market value, flags and grades vs the league."""
    return views.team_view(ctx, team_id)


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
