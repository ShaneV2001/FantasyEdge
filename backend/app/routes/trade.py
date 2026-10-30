from __future__ import annotations

import duckdb
from fastapi import APIRouter, Depends, Query

from app.deps import get_con, get_tuning
from app.schemas import models as m
from app.services import leagues, views
from app.services.context import get_context
from app.user_settings import UserSettings

router = APIRouter(prefix="/trade", tags=["trade"])


@router.post("/evaluate", response_model=m.TradeOut)
def evaluate_trade(
    body: m.TradeEvaluateRequest,
    con: duckdb.DuckDBPyConnection = Depends(get_con),
    tuning: UserSettings = Depends(get_tuning),
) -> m.TradeOut:
    """Score a trade by its effect on both teams' rest-of-season starting lineups."""
    ctx = get_context(con, leagues.league_id_for_team(con, body.team_id), tuning)
    return views.evaluate_trade(ctx, body.team_id, body.give, body.receive)


@router.post("/outlook", response_model=m.TradeOutlookOut)
def trade_outlook(
    body: m.TradeEvaluateRequest,
    con: duckdb.DuckDBPyConnection = Depends(get_con),
    tuning: UserSettings = Depends(get_tuning),
) -> m.TradeOutlookOut:
    """Each remaining week's best lineup for both teams, before and after the trade: who fills
    in for players on bye or hurt, and the slots left empty."""
    ctx = get_context(con, leagues.league_id_for_team(con, body.team_id), tuning)
    return views.outlook_view(ctx, body.team_id, body.give, body.receive)


@router.get("/suggest", response_model=m.TradeSuggestOut)
def suggest_trades(
    team_id: str = Query(...),
    page: int = Query(0, ge=0, le=50, description="0 = best ideas; each page shows new deals"),
    con: duckdb.DuckDBPyConnection = Depends(get_con),
    tuning: UserSettings = Depends(get_tuning),
) -> m.TradeSuggestOut:
    """1-for-1 and 2-for-1 ideas where both lineups gain after any forced drops, and neither team
    is left short in a week it can fill today (hidden after the trade deadline)."""
    ctx = get_context(con, leagues.league_id_for_team(con, team_id), tuning)
    ctx.team(team_id)
    return views.suggest_view(ctx, team_id, page)


@router.post("/find", response_model=m.TradeFindOut)
def find_trades(
    body: m.TradeFindRequest,
    con: duckdb.DuckDBPyConnection = Depends(get_con),
    tuning: UserSettings = Depends(get_tuning),
) -> m.TradeFindOut:
    """ "Trade these players for a RB": deals across the league that improve your lineup, the ones
    the other team should like first."""
    ctx = get_context(con, leagues.league_id_for_team(con, body.team_id), tuning)
    return views.find_view(ctx, body.team_id, body.give, body.want_position, body.receive_count)
