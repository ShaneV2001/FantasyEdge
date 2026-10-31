from __future__ import annotations

import logging
from datetime import UTC, datetime

import duckdb
from fastapi import APIRouter, Depends, Query

from app.config import Settings
from app.deps import get_ai_settings, get_clients, get_con, write_lock
from app.errors import InvalidInput, NotFound
from app.schemas import models as m
from app.services import context, freshness, leagues
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


def _current_week(con: duckdb.DuckDBPyConnection) -> tuple[int | None, int | None]:
    season = con.execute("SELECT max(season) FROM nfl_games").fetchone()[0]
    if season is None:
        return None, None
    from signals.schedule import build_schedule

    games = con.execute("SELECT * FROM nfl_games WHERE season = ?", [season]).pl()
    return season, context.current_week(build_schedule(games, season))


@router.put(
    "/players/{player_id}/availability", response_model=m.PlayerAvailabilityOut, tags=["players"]
)
def set_player_availability(
    player_id: str,
    body: m.PlayerAvailabilityIn,
    con: duckdb.DuckDBPyConnection = Depends(get_con),
) -> m.PlayerAvailabilityOut:
    """Your what-if for one player: out for the season, or back in a given week. It changes
    FantasyEdge's projections only (every page, every league), never ESPN or Sleeper."""
    if not con.execute("SELECT 1 FROM players WHERE player_id = ?", [player_id]).fetchone():
        raise NotFound("player", f"Player not found: {player_id}")
    if not body.out_for_season:
        _, week = _current_week(con)
        if body.return_week is None or (week is not None and body.return_week <= week):
            raise InvalidInput(
                f"Choose a return week after this week ({week})" if week else "Choose a return week"
            )
    with write_lock:
        con.execute(
            "INSERT OR REPLACE INTO player_availability VALUES (?, ?, ?, now())",
            [player_id, body.out_for_season, None if body.out_for_season else body.return_week],
        )
    context.invalidate()
    return m.PlayerAvailabilityOut(
        player_id=player_id,
        out_for_season=body.out_for_season,
        return_week=None if body.out_for_season else body.return_week,
    )


@router.delete(
    "/players/{player_id}/availability", response_model=m.PlayerAvailabilityOut, tags=["players"]
)
def clear_player_availability(
    player_id: str, con: duckdb.DuckDBPyConnection = Depends(get_con)
) -> m.PlayerAvailabilityOut:
    """Drop your what-if: back to the injury report."""
    with write_lock:
        con.execute("DELETE FROM player_availability WHERE player_id = ?", [player_id])
    context.invalidate()
    return m.PlayerAvailabilityOut(player_id=player_id, out_for_season=False, return_week=None)


@router.get("/teams/saved", response_model=list[m.SavedTeamOut], tags=["team"])
def get_saved_teams(con: duckdb.DuckDBPyConnection = Depends(get_con)) -> list[m.SavedTeamOut]:
    """Every team you've connected or entered, for the team switcher."""
    return [m.SavedTeamOut(**t) for t in leagues.saved_teams(con)]


@router.get("/meta/status", response_model=m.StatusOut)
def get_status(
    con: duckdb.DuckDBPyConnection = Depends(get_con),
    ai: Settings = Depends(get_ai_settings),
) -> m.StatusOut:
    rows = con.execute(
        "SELECT source, last_synced_at, status, detail FROM sync_log ORDER BY source"
    ).fetchall()
    season, week = _current_week(con)
    refresher, now = freshness.get(), datetime.now(UTC)
    return m.StatusOut(
        season=season,
        week=week,
        sources=[
            m.SourceStatus(source=r[0], last_synced_at=r[1], status=r[2], detail=r[3]) for r in rows
        ],
        attribution=ATTRIBUTION,
        ai_enabled=ai.ai_enabled,
        ai_model=ai.ai_model if ai.ai_enabled else None,
        data_refreshing=bool(refresher and refresher.running),
        nfl_data_stale=freshness.nfl_stale(con, now),
        unscored_week=freshness.unscored_week(con, now),
        refresh_error=refresher.last_error if refresher else None,
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
    # scope=all: download the player list and nflverse before taking the write lock, so other
    # requests aren't held up by the downloads
    fetched: dict[str, object] = {}
    if body.scope == "all":
        for name, fetch in (("players", jobs.fetch_players), ("stats", jobs.fetch_nflverse)):
            try:
                fetched[name] = fetch(c)
            except Exception as exc:  # keep going; report per-source
                ok = False
                log.exception("refresh %s failed", name)
                detail.append(f"{name} failed: {exc}")
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
                detail.append(f"league: {platform[0]} league, nothing to sync")
        if body.scope == "league":
            # Sleeper's trending adds feed the Waivers page; cheap, so every Update refreshes them
            try:
                detail.append(f"trending: {jobs.trending_sync(con, c)}")
            except Exception as exc:  # secondary data: report it, keep the roster sync result
                log.exception("refresh trending failed")
                detail.append(f"trending failed: {exc}")
        if body.scope in ("market", "all"):
            for fmt in _market_formats(con, body.league_id):
                try:
                    detail.append(f"market: {jobs.market_sync(con, c, fmt)}")
                except SourceUnavailable as exc:
                    ok = False
                    detail.append(f"market {fmt.key} failed: {exc.detail}")
        if body.scope == "all":
            writes = {
                "players": lambda: jobs.write_players(con, fetched["players"]),  # type: ignore[arg-type]
                "stats": lambda: jobs.write_nflverse(con, c, fetched["stats"]),  # type: ignore[arg-type]
                "trending": lambda: jobs.trending_sync(con, c),
            }
            for name, write in writes.items():
                if name != "trending" and name not in fetched:
                    continue  # its download failed (already reported)
                try:
                    detail.append(f"{name}: {write()}")
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
