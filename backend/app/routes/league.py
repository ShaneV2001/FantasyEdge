from __future__ import annotations

import duckdb
from fastapi import APIRouter, Depends

from app.deps import get_clients, get_con, write_lock
from app.errors import NotReady
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
    """Look up a Sleeper user's leagues and teams for the current season (no full sync yet)."""
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


def _current_season(con: duckdb.DuckDBPyConnection, c: Clients) -> int:
    row = con.execute("SELECT max(season) FROM nfl_games").fetchone()
    return int(row[0]) if row and row[0] else c.settings.seasons[1]


@router.get("/espn/defaults", response_model=m.EspnDefaultsOut)
def espn_defaults(
    con: duckdb.DuckDBPyConnection = Depends(get_con), c: Clients = Depends(get_clients)
) -> m.EspnDefaultsOut:
    """League ID and whether cookies are set in the local .env (the cookies themselves stay put)."""
    return m.EspnDefaultsOut(
        league_id=c.settings.espn_league_id,
        cookies_in_env=bool(c.settings.espn_s2 and c.settings.espn_swid),
        season=_current_season(con, c),
    )


def _espn_response(con: duckdb.DuckDBPyConnection, choice, res) -> m.EspnConnectResponse:
    return m.EspnConnectResponse(
        league=m.LeagueChoiceOut(
            **{k: v for k, v in vars(choice).items() if k != "teams"},
            teams=[m.TeamChoiceOut(**vars(t)) for t in choice.teams],
        ),
        unmatched=[m.UnmatchedPlayerOut(**vars(p)) for p in res.unmatched],
        scoring_notes=res.scoring_notes,
        credentials=m.CredentialsOut(**leagues.masked_credentials(con, res.league_id)),
    )


@router.post("/espn/connect", response_model=m.EspnConnectResponse)
def connect_espn(
    body: m.EspnConnectRequest,
    con: duckdb.DuckDBPyConnection = Depends(get_con),
    c: Clients = Depends(get_clients),
) -> m.EspnConnectResponse:
    """Connect an ESPN league (private leagues need the espn_s2 and SWID cookies, which are
    stored only in the local database). Data flows in from ESPN only; nothing is written there."""
    season = body.season or _current_season(con, c)
    with write_lock:
        choice, res = leagues.connect_espn(con, c, body.league_id, season, body.espn_s2, body.swid)
    context.invalidate(choice.league_id)
    return _espn_response(con, choice, res)


@router.get("/{league_id}/credentials", response_model=m.CredentialsOut)
def get_credentials(
    league_id: str, con: duckdb.DuckDBPyConnection = Depends(get_con)
) -> m.CredentialsOut:
    """Whether ESPN cookies are saved for this league (last 4 characters only)."""
    return m.CredentialsOut(**leagues.masked_credentials(con, league_id))


@router.put("/{league_id}/credentials", response_model=m.CredentialsOut)
def put_credentials(
    league_id: str,
    body: m.CredentialsRequest,
    con: duckdb.DuckDBPyConnection = Depends(get_con),
    c: Clients = Depends(get_clients),
) -> m.CredentialsOut:
    """Replace expired ESPN cookies. They're checked against ESPN before being saved."""
    with write_lock:
        leagues.replace_credentials(con, c, league_id, body.espn_s2, body.swid)
    context.invalidate(league_id)
    return m.CredentialsOut(**leagues.masked_credentials(con, league_id))


@router.post("/{league_id}/select-team", response_model=m.TeamRef)
def select_team(
    league_id: str,
    body: m.SelectTeamRequest,
    con: duckdb.DuckDBPyConnection = Depends(get_con),
    c: Clients = Depends(get_clients),
) -> m.TeamRef:
    """Pick your team; syncs the league's rosters, transactions and market values if needed."""
    with write_lock:
        leagues.ensure_synced(con, c, league_id)
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
        raise NotReady("No NFL schedule in the local store — run `python tasks.py data`.")
    with write_lock:
        league_id, team_id = leagues.create_manual(
            con,
            name=body.name,
            num_teams=body.num_teams,
            roster_positions=body.roster_positions,
            scoring=body.scoring,
            player_ids=body.player_ids,
            starters=body.starters,
            ir=body.ir,
            season=int(season),
            trade_deadline_week=body.trade_deadline_week,
            playoff_week_start=body.playoff_week_start,
        )
    return m.TeamRef(team_id=team_id, league_id=league_id)
