from __future__ import annotations

import logging

import duckdb
from fastapi import APIRouter, Depends, Query

from app.deps import get_clients, get_con, write_lock
from app.errors import NotFound
from app.schemas import models as m
from app.services import context, leagues
from ingest import run as jobs
from ingest.http import SourceUnavailable
from ingest.market_values import MarketFormat
from ingest.run import Clients

router = APIRouter(tags=["meta"])
log = logging.getLogger("fantasyedge.api")

ATTRIBUTION = [
    "League, roster, player and trending data from the Sleeper API (non-commercial use).",
    "ESPN league data read from fantasy.espn.com with your own login (read-only).",
    "NFL statistics, play-by-play, schedules and injuries from nflverse (CC-BY 4.0); FTN data CC-BY-SA 4.0.",
    "Market trade values from FantasyCalc; player ID crosswalk from DynastyProcess.",
    "FantasyEdge is not affiliated with Sleeper, ESPN, Yahoo, FantasyCalc, nflverse or the NFL.",
]


@router.get("/meta/status", response_model=m.StatusOut)
def get_status(con: duckdb.DuckDBPyConnection = Depends(get_con)) -> m.StatusOut:
    rows = con.execute(
        "SELECT source, last_synced_at, status, detail FROM sync_log ORDER BY source"
    ).fetchall()
    season = con.execute("SELECT max(season) FROM nfl_games").fetchone()[0]
    week = None
    if season is not None:
        games = con.execute("SELECT * FROM nfl_games WHERE season = ?", [season]).pl()
        from signals.schedule import build_schedule

        week = context.current_week(build_schedule(games, season))
    return m.StatusOut(
        season=season,
        week=week,
        sources=[
            m.SourceStatus(source=r[0], last_synced_at=r[1], status=r[2], detail=r[3]) for r in rows
        ],
        attribution=ATTRIBUTION,
    )


@router.post("/refresh", response_model=m.RefreshOut)
def refresh(
    body: m.RefreshRequest,
    con: duckdb.DuckDBPyConnection = Depends(get_con),
    c: Clients = Depends(get_clients),
) -> m.RefreshOut:
    """Re-pull league rosters/transactions (scope=league), market values, or everything."""
    detail: list[str] = []
    ok = True
    with write_lock:
        if body.scope in ("league", "all") and body.league_id:
            platform = con.execute(
                "SELECT platform, external_id FROM leagues WHERE league_id = ?", [body.league_id]
            ).fetchone()
            if platform is None:
                raise NotFound("league", f"League not found: {body.league_id}")
            if platform[0] == "sleeper":
                rosters = leagues.sync_sleeper_league(con, c, platform[1], force=True)
                detail.append(f"league: {len(rosters)} rosters synced")
            elif platform[0] == "espn":
                res = leagues.sync_espn_league(con, c, body.league_id, force=True)
                detail.append(f"league: {len(res.teams)} ESPN rosters synced")
            else:
                detail.append("league: manual league, nothing to sync")
        if body.scope in ("market", "all"):
            for fmt in _market_formats(con, body.league_id):
                try:
                    detail.append(f"market: {jobs.market_sync(con, c, fmt)}")
                except SourceUnavailable as exc:
                    ok = False
                    detail.append(f"market {fmt.key} failed: {exc.detail}")
        if body.scope == "all":
            for name, job in (
                ("players", jobs.players_sync),
                ("stats", jobs.stats_sync),
                ("trending", jobs.trending_sync),
            ):
                try:
                    detail.append(f"{name}: {job(con, c)}")
                except Exception as exc:  # keep going; report per-source
                    ok = False
                    log.exception("refresh %s failed", name)
                    detail.append(f"{name} failed: {exc}")
    context.invalidate(body.league_id if body.scope == "league" else None)
    synced = None
    if body.league_id:
        row = con.execute(
            "SELECT last_synced_at FROM leagues WHERE league_id = ?", [body.league_id]
        ).fetchone()
        synced = row[0] if row else None
    return m.RefreshOut(scope=body.scope, ok=ok, detail=detail, last_synced_at=synced)


def _market_formats(con: duckdb.DuckDBPyConnection, league_id: str | None) -> list[MarketFormat]:
    """The league's own market format, or every stored league's (default format if none)."""
    ids = (
        [league_id]
        if league_id
        else [r[0] for r in con.execute("SELECT league_id FROM leagues").fetchall()]
    )
    formats = {f.key: f for f in (context.load_league(con, i).market_format for i in ids)}
    return list(formats.values()) or [MarketFormat()]


@router.get("/players", response_model=list[m.PlayerRef], tags=["players"])
def search_players(
    q: str = Query("", max_length=60),
    pos: str | None = Query(None, pattern="^(QB|RB|WR|TE|K|DEF)$"),
    limit: int = Query(20, ge=1, le=100),
    con: duckdb.DuckDBPyConnection = Depends(get_con),
) -> list[m.PlayerRef]:
    """Player search (used by manual team entry). Full players table arrives in phase 3."""
    sql = """SELECT player_id, full_name AS name, position, nfl_team FROM players
             WHERE (? = '' OR lower(full_name) LIKE '%' || lower(?) || '%')
               AND (? IS NULL OR position = ?)
               AND (nfl_team IS NOT NULL)
             ORDER BY (SELECT max(value) FROM market_values mv WHERE mv.player_id = players.player_id) DESC NULLS LAST,
                      full_name
             LIMIT ?"""
    rows = con.execute(sql, [q, q, pos, pos, limit]).fetchall()
    return [m.PlayerRef(player_id=r[0], name=r[1], position=r[2], nfl_team=r[3]) for r in rows]
