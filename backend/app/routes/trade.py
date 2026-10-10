from __future__ import annotations

import duckdb
from fastapi import APIRouter, Depends, Query

from app.deps import get_con
from app.schemas import models as m
from app.services import leagues, views
from app.services.context import get_context

router = APIRouter(prefix="/trade", tags=["trade"])


@router.post("/evaluate", response_model=m.TradeOut)
def evaluate(
    body: m.TradeEvaluateRequest, con: duckdb.DuckDBPyConnection = Depends(get_con)
) -> m.TradeOut:
    """Score a trade by its effect on both teams' rest-of-season starting lineups."""
    ctx = get_context(con, leagues.league_id_for_team(con, body.team_id))
    return views.evaluate_trade(ctx, body.team_id, body.give, body.receive)


@router.get("/suggest", response_model=m.TradeSuggestOut)
def suggest(
    team_id: str = Query(...), con: duckdb.DuckDBPyConnection = Depends(get_con)
) -> m.TradeSuggestOut:
    """1-for-1 and 2-for-1 ideas where both lineups gain (hidden after the trade deadline)."""
    ctx = get_context(con, leagues.league_id_for_team(con, team_id))
    ctx.team(team_id)
    return views.suggest_view(ctx, team_id)
