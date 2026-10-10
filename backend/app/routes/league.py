from __future__ import annotations

import duckdb
from fastapi import APIRouter, Depends

from app.deps import get_clients, get_con, write_lock
from app.schemas import models as m
from app.services import context, leagues
from ingest.run import Clients

router = APIRouter(prefix="/league", tags=["league"])


@router.post("/connect", response_model=m.ConnectResponse)
def connect_league(
    body: m.ConnectRequest,
    con: duckdb.DuckDBPyConnection = Depends(get_con),
    c: Clients = Depends(get_clients),
) -> m.ConnectResponse:
    """Look up a Sleeper user's leagues for the current season and sync each one."""
    with write_lock:
        choices = leagues.connect_sleeper(con, c, body.username)
    for ch in choices:
        context.invalidate(ch.league_id)
    return m.ConnectResponse(
        username=body.username,
        leagues=[
            m.LeagueChoiceOut(
                **{k: v for k, v in vars(ch).items() if k != "teams"},
                teams=[m.TeamChoiceOut(**vars(t)) for t in ch.teams],
            )
            for ch in choices
        ],
    )


@router.post("/{league_id}/select-team", response_model=m.TeamRef)
def select_team(
    league_id: str, body: m.SelectTeamRequest, con: duckdb.DuckDBPyConnection = Depends(get_con)
) -> m.TeamRef:
    with write_lock:
        team_id = leagues.select_team(con, league_id, body.external_roster_id)
    context.invalidate(league_id)
    return m.TeamRef(team_id=team_id, league_id=league_id)


@router.post("/manual", response_model=m.TeamRef)
def manual_league(
    body: m.ManualLeagueRequest, con: duckdb.DuckDBPyConnection = Depends(get_con)
) -> m.TeamRef:
    """Create a league from a hand-entered roster (works for any platform)."""
    season = con.execute("SELECT max(season) FROM nfl_games").fetchone()[0]
    if season is None:
        raise context.NotReady("No NFL schedule in the local store — run `python tasks.py data`.")
    with write_lock:
        league_id, team_id = leagues.create_manual(
            con,
            name=body.name,
            num_teams=body.num_teams,
            roster_positions=body.roster_positions,
            scoring=body.scoring,
            player_ids=body.player_ids,
            season=int(season),
            trade_deadline_week=body.trade_deadline_week,
        )
    return m.TeamRef(team_id=team_id, league_id=league_id)
