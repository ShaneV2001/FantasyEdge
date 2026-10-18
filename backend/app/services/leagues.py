"""League connect / sync / manual creation — writes leagues, teams, roster_spots, transactions."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import duckdb
import polars as pl

from app.errors import AuthRequired, InvalidInput, NotFound
from db.conn import log_sync, query_df, replace_where, transaction, upsert
from ingest import espn as es
from ingest import sleeper as sl
from ingest.http import AuthRejected, SourceUnavailable
from ingest.market_values import market_format_for
from ingest.run import Clients, market_sync
from scoring.espn import from_espn
from scoring.rules import PRESETS, describe, from_sleeper, normalize, profile_id
from signals.lineup import NON_STARTING, SLOT_ELIGIBILITY, fit_to_slots, starting_slots

log = logging.getLogger("fantasyedge.leagues")


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def sleeper_league_id(external_id: str) -> str:
    return f"sl-{external_id}"


def sleeper_team_id(external_id: str, roster_id: str) -> str:
    return f"sl-{external_id}-{roster_id}"


def ensure_profile(con: duckdb.DuckDBPyConnection, rules: dict[str, float], name: str) -> str:
    rules = normalize(rules)
    pid = profile_id(rules)
    con.execute(
        "INSERT OR IGNORE INTO scoring_profiles VALUES (?, ?, ?)", [pid, name, json.dumps(rules)]
    )
    return pid


def sleeper_to_internal(con: duckdb.DuckDBPyConnection, sleeper_ids: list[str]) -> dict[str, str]:
    if not sleeper_ids:
        return {}
    df = query_df(
        con,
        "SELECT sleeper_id, player_id FROM players WHERE sleeper_id IN (SELECT unnest(?))",
        [sleeper_ids],
    )
    found = dict(df.iter_rows())
    return {s: found.get(s, f"sl:{s}") for s in sleeper_ids}


# ───────── Sleeper ─────────


@dataclass
class TeamChoice:
    external_roster_id: str
    team_name: str
    owner_name: str
    is_user: bool


@dataclass
class LeagueChoice:
    league_id: str
    external_id: str
    name: str
    season: int
    num_teams: int
    scoring: str
    roster_positions: list[str]
    teams: list[TeamChoice]


def connect_sleeper(
    con: duckdb.DuckDBPyConnection, c: Clients, username: str
) -> list[LeagueChoice]:
    user = c.sleeper.user(username.strip())
    if not user:
        raise NotFound("user", f"Sleeper user '{username}' not found")
    state = c.sleeper.state()
    season = int(state.get("league_season") or state["season"])
    out = []
    for raw in c.sleeper.leagues(user["user_id"], season):
        # Only what the picker needs: the full sync (rosters, transactions, market values) runs
        # when a team is selected, so users in many leagues don't wait for all of them.
        info = sl.parse_league(raw)
        rosters = sl.parse_rosters(
            c.sleeper.rosters(info.external_id),
            c.sleeper.league_users(info.external_id),
            info.faab_budget,
        )
        with transaction(con):
            _upsert_sleeper_league(con, info, from_sleeper(info.scoring_settings), synced_at=None)
        out.append(
            LeagueChoice(
                league_id=sleeper_league_id(info.external_id),
                external_id=info.external_id,
                name=info.name,
                season=info.season,
                num_teams=info.num_teams,
                scoring=describe(from_sleeper(info.scoring_settings)),
                roster_positions=info.roster_positions,
                teams=[
                    TeamChoice(
                        r.roster_id, r.team_name, r.owner_name, r.owner_id == user["user_id"]
                    )
                    for r in rosters
                ],
            )
        )
    return out


def sync_sleeper_league(
    con: duckdb.DuckDBPyConnection,
    c: Clients,
    external_id: str,
    raw_league: dict | None = None,
    force: bool = False,
) -> list[sl.RosterInfo]:
    raw = (
        raw_league
        if raw_league is not None and not force
        else c.sleeper.league(external_id, force=force)
    )
    info = sl.parse_league(raw)
    rules = from_sleeper(info.scoring_settings)
    league_id = sleeper_league_id(external_id)
    # Fetch everything before touching the store so a network failure can't leave it half-written.
    rosters = sl.parse_rosters(
        c.sleeper.rosters(external_id, force=force),
        c.sleeper.league_users(external_id, force=force),
        info.faab_budget,
    )
    with transaction(con):
        _write_sleeper_league(con, external_id, league_id, info, rules, rosters)
    _sync_transactions(con, c, external_id, league_id, force)
    _ensure_market(con, c, rules, info)
    log_sync(con, f"league:{league_id}", "ok", f"{len(rosters)} rosters")
    return rosters


def _upsert_sleeper_league(
    con: duckdb.DuckDBPyConnection,
    info: sl.LeagueInfo,
    rules: dict[str, float],
    synced_at: datetime | None,
) -> None:
    """Scoring profile + league row. `synced_at=None` keeps the previous sync time (a league
    listed at connect isn't synced until a team is picked)."""
    prof = ensure_profile(con, rules, f"{info.name} ({describe(rules)})")
    league_id = sleeper_league_id(info.external_id)
    if synced_at is None:
        row = con.execute(
            "SELECT last_synced_at FROM leagues WHERE league_id = ?", [league_id]
        ).fetchone()
        synced_at = row[0] if row else None
    upsert(
        con,
        "leagues",
        pl.DataFrame(
            [
                {
                    "league_id": league_id,
                    "platform": "sleeper",
                    "external_id": info.external_id,
                    "season": info.season,
                    "name": info.name,
                    "num_teams": info.num_teams,
                    "roster_positions": json.dumps(info.roster_positions),
                    "scoring_profile_id": prof,
                    "trade_deadline_week": info.trade_deadline_week,
                    "uses_faab": info.uses_faab,
                    "faab_budget": info.faab_budget,
                    "playoff_week_start": info.playoff_week_start,
                    "league_type": info.league_type,
                    "last_synced_at": synced_at,
                }
            ],
            schema_overrides={
                "trade_deadline_week": pl.Int32,
                "faab_budget": pl.Int32,
                "playoff_week_start": pl.Int32,
                "last_synced_at": pl.Datetime("us"),
            },
        ),
    )


SYNC_MAX_AGE = timedelta(minutes=10)


def ensure_synced(
    con: duckdb.DuckDBPyConnection, c: Clients, league_id: str, max_age: timedelta = SYNC_MAX_AGE
) -> bool:
    """Full-sync a Sleeper league if it was only listed at connect (or is stale). True if synced."""
    row = con.execute(
        "SELECT platform, external_id FROM leagues WHERE league_id = ?", [league_id]
    ).fetchone()
    if row is None:
        raise NotFound("league", f"League not found: {league_id}")
    platform, external_id = row
    if platform not in ("sleeper", "espn") or not needs_sync(con, league_id, max_age):
        return False
    if platform == "espn":
        sync_espn_league(con, c, league_id)
    else:
        sync_sleeper_league(con, c, external_id)
    return True


def needs_sync(con: duckdb.DuckDBPyConnection, league_id: str, max_age: timedelta) -> bool:
    """True when a Sleeper league has never been fully synced or its last sync is too old."""
    row = con.execute(
        """SELECT l.last_synced_at, (SELECT count(*) FROM teams t WHERE t.league_id = l.league_id)
           FROM leagues l WHERE l.league_id = ?""",
        [league_id],
    ).fetchone()
    if row is None:
        raise NotFound("league", f"League not found: {league_id}")
    synced_at, n_teams = row
    return not n_teams or synced_at is None or _now() - synced_at > max_age


def _write_sleeper_league(
    con: duckdb.DuckDBPyConnection,
    external_id: str,
    league_id: str,
    info: sl.LeagueInfo,
    rules: dict[str, float],
    rosters: list[sl.RosterInfo],
) -> None:
    """League row, teams and roster spots for one Sleeper league (caller wraps in a transaction)."""
    prev_mine = con.execute(
        "SELECT external_roster_id FROM teams WHERE league_id = ? AND is_mine", [league_id]
    ).fetchone()
    now = _now()
    _upsert_sleeper_league(con, info, rules, synced_at=now)
    all_ids = sleeper_to_internal(con, [p for r in rosters for p in r.players])
    team_rows, spot_rows = [], []
    for r in rosters:
        tid = sleeper_team_id(external_id, r.roster_id)
        team_rows.append(
            {
                "team_id": tid,
                "league_id": league_id,
                "external_roster_id": r.roster_id,
                "owner_name": r.owner_name,
                "team_name": r.team_name,
                "is_mine": bool(prev_mine and prev_mine[0] == r.roster_id),
                "wins": r.wins,
                "losses": r.losses,
                "points_for": r.points_for,
                "faab_remaining": r.faab_remaining,
            }
        )
        starters, reserve, taxi = set(r.starters), set(r.reserve), set(r.taxi)
        for sid in r.players:
            slot = (
                "starter"
                if sid in starters
                else "ir"
                if sid in reserve
                else "taxi"
                if sid in taxi
                else "bench"
            )
            spot_rows.append(
                {"team_id": tid, "player_id": all_ids[sid], "slot": slot, "synced_at": now}
            )
    replace_where(
        con,
        "teams",
        pl.DataFrame(team_rows, schema_overrides={"faab_remaining": pl.Int32}),
        "league_id = ?",
        [league_id],
    )
    con.execute(
        "DELETE FROM roster_spots WHERE team_id IN (SELECT team_id FROM teams WHERE league_id = ?) OR team_id LIKE ?",
        [league_id, f"sl-{external_id}-%"],
    )
    if spot_rows:
        upsert(con, "roster_spots", pl.DataFrame(spot_rows).unique(["team_id", "player_id"]))


def _sync_transactions(
    con: duckdb.DuckDBPyConnection, c: Clients, external_id: str, league_id: str, force: bool
) -> None:
    try:
        week = int(c.sleeper.state().get("week") or 1)
        rows = []
        for w in range(max(1, week - 1), week + 1):
            for t in c.sleeper.transactions(external_id, w, force=force):
                rows.append(
                    {
                        "league_id": league_id,
                        "external_id": str(t.get("transaction_id")),
                        "kind": t.get("type"),
                        "week": w,
                        "created_at": datetime.fromtimestamp((t.get("created") or 0) / 1000),
                        "payload": json.dumps(t),
                    }
                )
        if rows:
            upsert(con, "transactions", pl.DataFrame(rows))
    except Exception as exc:  # transactions are informational only
        log.warning("transactions sync failed for %s: %s", league_id, exc)


def _ensure_market(
    con: duckdb.DuckDBPyConnection, c: Clients, rules: dict, info: sl.LeagueInfo | es.EspnLeague
) -> None:
    fmt = market_format_for(
        info.roster_positions, info.num_teams, normalize(rules)["rec"], info.league_type
    )
    have = con.execute(
        "SELECT count(*) FROM market_values WHERE format = ? AND snapshot_date = ?",
        [fmt.key, date.today()],
    ).fetchone()[0]
    if have:
        return
    try:
        market_sync(con, c, fmt)
    except Exception as exc:
        log.warning(
            "market sync failed for %s: %s (advice will use older/default values)", fmt.key, exc
        )


def select_team(con: duckdb.DuckDBPyConnection, league_id: str, external_roster_id: str) -> str:
    row = con.execute(
        "SELECT team_id FROM teams WHERE league_id = ? AND external_roster_id = ?",
        [league_id, str(external_roster_id)],
    ).fetchone()
    if not row:
        raise NotFound("roster", f"roster {external_roster_id} not found in {league_id}")
    con.execute("UPDATE teams SET is_mine = (team_id = ?) WHERE league_id = ?", [row[0], league_id])
    con.execute("UPDATE leagues SET last_synced_at = ? WHERE league_id = ?", [_now(), league_id])
    return row[0]


# ───────── ESPN ─────────

ESPN_EXPIRED = "Your ESPN login has expired — paste fresh cookies."
ESPN_PRIVATE = "This ESPN league is private — add your espn_s2 and SWID cookies to connect it."


def espn_league_id(external_id: str, season: int) -> str:
    return f"es-{external_id}-{season}"


def espn_team_id(external_id: str, season: int, team_id: str) -> str:
    return f"es-{external_id}-{season}-{team_id}"


def espn_cookies(c: Clients, espn_s2: str | None, swid: str | None) -> es.Cookies | None:
    """Cookies from the request, else from .env; None for a public league."""
    s2 = (espn_s2 or c.settings.espn_s2 or "").strip()
    sw = (swid or c.settings.espn_swid or "").strip()
    if not s2 and not sw:
        return None
    if not s2 or not sw:
        raise InvalidInput("Private ESPN leagues need both cookies: espn_s2 and SWID.")
    if not sw.startswith("{"):
        sw = "{" + sw.strip("{}") + "}"  # SWID is a GUID in braces; people often drop them
    return es.Cookies(s2, sw)


def save_credentials(con: duckdb.DuckDBPyConnection, league_id: str, cookies: es.Cookies) -> None:
    con.execute(
        "INSERT OR REPLACE INTO league_credentials VALUES (?, ?, ?, ?)",
        [league_id, cookies.espn_s2, cookies.swid, _now()],
    )


def load_credentials(con: duckdb.DuckDBPyConnection, league_id: str) -> es.Cookies | None:
    row = con.execute(
        "SELECT espn_s2, swid FROM league_credentials WHERE league_id = ?", [league_id]
    ).fetchone()
    return es.Cookies(row[0], row[1]) if row and row[0] and row[1] else None


def masked_credentials(con: duckdb.DuckDBPyConnection, league_id: str) -> dict:
    """What the UI may see: whether cookies are saved, and their last 4 characters only."""
    row = con.execute(
        "SELECT espn_s2, swid, updated_at FROM league_credentials WHERE league_id = ?", [league_id]
    ).fetchone()
    if not row:
        return {"saved": False, "espn_s2_last4": None, "swid_last4": None, "updated_at": None}
    return {
        "saved": True,
        "espn_s2_last4": (row[0] or "")[-4:] or None,
        "swid_last4": (row[1] or "").rstrip("}")[-4:] or None,
        "updated_at": row[2],
    }


def _auth_error(cookies: es.Cookies | None) -> AuthRequired:
    if cookies:
        return AuthRequired("espn_auth", ESPN_EXPIRED)
    return AuthRequired("espn_private", ESPN_PRIVATE)


def _fetch_espn(
    c: Clients, external_id: str, season: int, cookies: es.Cookies | None, force: bool
) -> dict:
    assert c.espn is not None
    try:
        raw = c.espn.league(external_id, season, cookies, force=force)
    except AuthRejected:
        raise _auth_error(cookies) from None
    except SourceUnavailable as exc:
        if exc.status == 404:
            raise NotFound("league", f"ESPN league {external_id} not found for {season}") from None
        raise
    if es.is_private_without_access(raw):
        raise _auth_error(cookies)
    return raw


@dataclass
class IdMatch:
    ids: dict[int, str]  # ESPN player id -> internal player_id
    unmatched: list[es.EspnPlayer]


def espn_to_internal(
    con: duckdb.DuckDBPyConnection, id_map: pl.DataFrame | None, players: list[es.EspnPlayer]
) -> IdMatch:
    """ESPN ids -> ours: Sleeper's espn_id, then the DynastyProcess crosswalk, then name + team +
    position. D/ST map to `sl:<TEAM>`. Anything left is returned so it can be shown, not dropped."""
    known = query_df(con, "SELECT player_id, espn_id, full_name, position, nfl_team FROM players")
    have = set(known["player_id"].to_list())
    by_espn = {
        str(e): p for p, e in known.select("player_id", "espn_id").iter_rows() if e is not None
    }
    by_dp: dict[str, str] = {}
    if id_map is not None and {"espn_id", "gsis_id"} <= set(id_map.columns):
        for e, g in id_map.select("espn_id", "gsis_id").drop_nulls().iter_rows():
            if g in have:
                by_dp.setdefault(str(e).split(".")[0], g)
    by_name: dict[tuple, list[str]] = {}
    by_name_pos: dict[tuple, list[str]] = {}
    for pid, _, name, pos, team in known.iter_rows():
        by_name.setdefault((es.name_key(name or ""), pos, team), []).append(pid)
        by_name_pos.setdefault((es.name_key(name or ""), pos), []).append(pid)

    ids: dict[int, str] = {}
    unmatched = []
    for p in players:
        key = str(p.espn_id)
        if p.position == "DEF" or p.espn_id < 0:
            team_def = f"sl:{p.nfl_team}"
            pid = team_def if p.nfl_team and team_def in have else None
        else:
            pid = by_espn.get(key) or by_dp.get(key)
            if pid is None:
                hits = by_name.get((es.name_key(p.name), p.position, p.nfl_team)) or []
                hits = hits or by_name_pos.get((es.name_key(p.name), p.position)) or []
                pid = hits[0] if len(hits) == 1 else None
        if pid is None:
            unmatched.append(p)
            pid = f"espn:{p.espn_id}"
        ids[p.espn_id] = pid
    return IdMatch(ids, unmatched)


def _placeholder_players(con: duckdb.DuckDBPyConnection, unmatched: list[es.EspnPlayer]) -> None:
    """Unmatched ESPN players get a name-only row so they show up (projected 0) instead of
    vanishing. `players_sync` replaces the table; the next league sync adds them back."""
    rows = [
        {"player_id": f"espn:{p.espn_id}", "espn_id": str(p.espn_id), "full_name": p.name,
         "position": p.position, "nfl_team": p.nfl_team, "status": "Unmatched (ESPN)",
         "updated_at": _now()}
        for p in unmatched
        if p.position
    ]  # fmt: skip
    if rows:  # players has two unique keys, so replace rather than INSERT OR REPLACE
        replace_where(
            con,
            "players",
            pl.DataFrame(rows, schema_overrides={"nfl_team": pl.Utf8}),
            "player_id IN (SELECT unnest(?))",
            [[r["player_id"] for r in rows]],
        )


@dataclass
class EspnSync:
    league_id: str
    info: es.EspnLeague
    rules: dict[str, float]
    teams: list[es.EspnTeam]
    unmatched: list[es.EspnPlayer]
    scoring_notes: list[str]


def _week_starts(con: duckdb.DuckDBPyConnection, season: int) -> dict[int, datetime]:
    rows = con.execute(
        "SELECT week, min(kickoff) FROM nfl_games WHERE season = ? AND kickoff IS NOT NULL GROUP BY 1",
        [season],
    ).fetchall()
    return {int(w): k for w, k in rows}


def _sync_espn(
    con: duckdb.DuckDBPyConnection, c: Clients, raw: dict, cookies: es.Cookies | None
) -> EspnSync:
    try:
        info = es.parse_league(raw)
        rules, notes = from_espn(info.scoring_items)
    except ValueError as exc:  # includes UnsupportedLeague
        raise InvalidInput(str(exc)) from exc
    teams, players = es.parse_teams(raw, info)
    try:
        id_map = c.id_map()
    except Exception as exc:  # the crosswalk is a fallback; Sleeper's ESPN ids cover most players
        log.warning("DynastyProcess id map unavailable: %s", type(exc).__name__)
        id_map = None
    match = espn_to_internal(con, id_map, list(players.values()))
    if match.unmatched:
        log.info("%d ESPN player(s) not matched to the local store", len(match.unmatched))
    league_id = espn_league_id(info.external_id, info.season)
    deadline = es.deadline_week(info.trade_deadline, _week_starts(con, info.season))
    now = _now()
    with transaction(con):
        prev_mine = con.execute(
            "SELECT external_roster_id FROM teams WHERE league_id = ? AND is_mine", [league_id]
        ).fetchone()
        prof = ensure_profile(con, rules, f"{info.name} (ESPN, {describe(rules)})")
        league_row = {
            "league_id": league_id,
            "platform": "espn",
            "external_id": info.external_id,
            "season": info.season,
            "name": info.name,
            "num_teams": info.num_teams,
            "roster_positions": json.dumps(info.roster_positions),
            "scoring_profile_id": prof,
            "trade_deadline_week": deadline,
            "uses_faab": info.uses_faab,
            "faab_budget": info.faab_budget,
            "playoff_week_start": info.playoff_week_start,
            "league_type": info.league_type,
            "last_synced_at": now,
            "final_week": info.final_week,
            "scoring_notes": json.dumps(notes),
        }
        upsert(
            con,
            "leagues",
            pl.DataFrame(
                [league_row],
                schema_overrides={
                    "trade_deadline_week": pl.Int32,
                    "faab_budget": pl.Int32,
                    "playoff_week_start": pl.Int32,
                    "final_week": pl.Int32,
                    "last_synced_at": pl.Datetime("us"),
                },
            ),
        )
        _placeholder_players(con, match.unmatched)
        team_rows, spot_rows = [], []
        for t in teams:
            tid = espn_team_id(info.external_id, info.season, t.team_id)
            team_rows.append(
                {
                    "team_id": tid,
                    "league_id": league_id,
                    "external_roster_id": t.team_id,
                    "owner_name": t.owner_name,
                    "team_name": t.team_name,
                    "is_mine": bool(prev_mine and prev_mine[0] == t.team_id),
                    "wins": t.wins,
                    "losses": t.losses,
                    "points_for": t.points_for,
                    "faab_remaining": t.faab_remaining,
                }
            )
            spot_rows += [
                {"team_id": tid, "player_id": match.ids[eid], "slot": slot, "synced_at": now}
                for eid, slot in t.roster
            ]
        replace_where(
            con,
            "teams",
            pl.DataFrame(team_rows, schema_overrides={"faab_remaining": pl.Int32}),
            "league_id = ?",
            [league_id],
        )
        con.execute(
            "DELETE FROM roster_spots WHERE team_id IN (SELECT team_id FROM teams WHERE league_id = ?) OR team_id LIKE ?",
            [league_id, f"{league_id}-%"],
        )
        if spot_rows:
            upsert(con, "roster_spots", pl.DataFrame(spot_rows).unique(["team_id", "player_id"]))
        if cookies is not None:
            save_credentials(con, league_id, cookies)
    _sync_espn_transactions(con, c, info, league_id, cookies)
    _ensure_market(con, c, rules, info)
    log_sync(con, f"league:{league_id}", "ok", f"{len(teams)} teams")
    return EspnSync(league_id, info, rules, teams, match.unmatched, notes)


def _sync_espn_transactions(
    con: duckdb.DuckDBPyConnection,
    c: Clients,
    info: es.EspnLeague,
    league_id: str,
    cookies: es.Cookies | None,
) -> None:
    assert c.espn is not None
    try:
        rows = []
        for w in range(max(1, info.current_week - 1), info.current_week + 1):
            for t in c.espn.transactions(info.external_id, info.season, cookies, w):
                created = t.get("proposedDate") or t.get("processDate") or 0
                rows.append(
                    {
                        "league_id": league_id,
                        "external_id": str(t.get("id")),
                        "kind": str(t.get("type") or "").lower(),
                        "week": w,
                        "created_at": datetime.fromtimestamp(created / 1000),
                        "payload": json.dumps(t),
                    }
                )
        if rows:
            upsert(con, "transactions", pl.DataFrame(rows).unique("external_id"))
    except Exception as exc:  # transactions are informational only (no cookie values in the log)
        log.warning("transactions sync failed for %s: %s", league_id, type(exc).__name__)


def connect_espn(
    con: duckdb.DuckDBPyConnection,
    c: Clients,
    external_id: str,
    season: int,
    espn_s2: str | None = None,
    swid: str | None = None,
) -> tuple[LeagueChoice, EspnSync]:
    """Fetch and store an ESPN league (one request has everything), and list its teams to pick."""
    external_id = external_id.strip()
    if not external_id.isdigit():
        raise InvalidInput("The ESPN league ID is the number after leagueId= in your league's URL.")
    cookies = espn_cookies(c, espn_s2, swid)
    raw = _fetch_espn(c, external_id, season, cookies, force=True)
    res = _sync_espn(con, c, raw, cookies)
    choice = LeagueChoice(
        league_id=res.league_id,
        external_id=external_id,
        name=res.info.name,
        season=res.info.season,
        num_teams=res.info.num_teams,
        scoring=describe(res.rules),
        roster_positions=res.info.roster_positions,
        teams=[
            TeamChoice(
                t.team_id, t.team_name, t.owner_name, bool(cookies and cookies.swid in t.owner_ids)
            )
            for t in res.teams
        ],
    )
    return choice, res


def _espn_row(con: duckdb.DuckDBPyConnection, league_id: str) -> tuple[str, int]:
    row = con.execute(
        "SELECT external_id, season FROM leagues WHERE league_id = ? AND platform = 'espn'",
        [league_id],
    ).fetchone()
    if row is None:
        raise NotFound("league", f"League not found: {league_id}")
    return row[0], int(row[1])


def sync_espn_league(
    con: duckdb.DuckDBPyConnection, c: Clients, league_id: str, force: bool = False
) -> EspnSync:
    external_id, season = _espn_row(con, league_id)
    cookies = load_credentials(con, league_id)
    raw = _fetch_espn(c, external_id, season, cookies, force=force)
    return _sync_espn(con, c, raw, cookies)


def replace_credentials(
    con: duckdb.DuckDBPyConnection, c: Clients, league_id: str, espn_s2: str, swid: str
) -> EspnSync:
    """Check new cookies against ESPN first; only working cookies replace the saved ones."""
    external_id, season = _espn_row(con, league_id)
    cookies = espn_cookies(c, espn_s2, swid)
    if cookies is None:
        raise InvalidInput("Paste both cookies: espn_s2 and SWID.")
    raw = _fetch_espn(c, external_id, season, cookies, force=True)
    return _sync_espn(con, c, raw, cookies)


# ───────── manual ─────────


def roster_slots(
    con: duckdb.DuckDBPyConnection,
    *,
    roster_positions: list[str],
    player_ids: list[str],
    starters: list[str],
    ir: list[str],
) -> dict[str, str]:
    """Validate a hand-entered roster and return player_id -> 'starter' | 'bench' | 'ir'."""
    known = dict(
        query_df(
            con,
            "SELECT player_id, position FROM players WHERE player_id IN (SELECT unnest(?))",
            [player_ids],
        ).iter_rows()
    )
    missing = [p for p in player_ids if p not in known]
    if missing:
        raise NotFound("player", f"unknown player ids: {', '.join(missing[:5])}")
    return assign_roster_slots(roster_positions, known, player_ids, starters, ir)


def assign_roster_slots(
    roster_positions: list[str],
    positions: dict[str, str],
    player_ids: list[str],
    starters: list[str],
    ir: list[str],
) -> dict[str, str]:
    """Pure roster-shape checks: starters fit the lineup, bench and IR fit their depth."""
    bad = [s for s in roster_positions if s not in SLOT_ELIGIBILITY and s not in NON_STARTING]
    if bad:
        raise InvalidInput(f"unknown roster slot(s): {', '.join(sorted(set(bad)))}")
    slots = starting_slots(roster_positions)
    if not slots:
        raise InvalidInput("a lineup needs at least one starting slot")
    n_bench = roster_positions.count("BN") + roster_positions.count("TAXI")
    n_ir = roster_positions.count("IR")
    if len(set(player_ids)) != len(player_ids):
        raise InvalidInput("a player appears on the roster twice")
    ids = set(player_ids)
    if not set(starters) <= ids or not set(ir) <= ids:
        raise InvalidInput("starters and IR players must also be on the roster")
    if set(starters) & set(ir):
        raise InvalidInput("a player can't be both starting and on IR")
    if len(ir) > n_ir:
        raise InvalidInput(f"{len(ir)} players on IR but the league has {n_ir} IR spot(s)")
    active = [p for p in player_ids if p not in set(ir)]
    if len(active) > len(slots) + n_bench:
        raise InvalidInput(
            f"{len(active)} active players but only {len(slots)} starting + {n_bench} bench spots"
        )
    if starters:
        if len(starters) > len(slots):
            raise InvalidInput(f"{len(starters)} starters but only {len(slots)} starting slots")
        _, unplaced = fit_to_slots([(p, positions[p]) for p in starters], slots)
        if unplaced:
            raise InvalidInput(
                "these starters don't fit an open lineup slot: "
                + ", ".join(f"{p} ({positions[p]})" for p in unplaced)
            )
        bench = len(active) - len(starters)
        if bench > n_bench:
            raise InvalidInput(f"{bench} bench players but only {n_bench} bench spots")
    starter_set, ir_set = set(starters), set(ir)
    return {
        p: "starter" if p in starter_set else "ir" if p in ir_set else "bench" for p in player_ids
    }


def create_manual(
    con: duckdb.DuckDBPyConnection,
    *,
    name: str,
    num_teams: int,
    roster_positions: list[str],
    scoring: str | dict[str, float],
    player_ids: list[str],
    season: int,
    starters: list[str] | None = None,
    ir: list[str] | None = None,
    trade_deadline_week: int | None = None,
    playoff_week_start: int = 15,
) -> tuple[str, str]:
    rules = PRESETS[scoring] if isinstance(scoring, str) else normalize(scoring)
    slot_of = roster_slots(
        con,
        roster_positions=roster_positions,
        player_ids=player_ids,
        starters=starters or [],
        ir=ir or [],
    )
    prof = ensure_profile(con, rules, f"Manual ({describe(rules)})")
    league_id = f"mn-{uuid.uuid4().hex[:10]}"
    team_id = f"{league_id}-1"
    now = _now()
    with transaction(con):
        upsert(
            con,
            "leagues",
            pl.DataFrame(
                [
                    {
                        "league_id": league_id,
                        "platform": "manual",
                        "external_id": None,
                        "season": season,
                        "name": name,
                        "num_teams": num_teams,
                        "roster_positions": json.dumps(roster_positions),
                        "scoring_profile_id": prof,
                        "trade_deadline_week": trade_deadline_week,
                        "uses_faab": False,
                        "faab_budget": None,
                        "playoff_week_start": playoff_week_start,
                        "league_type": "redraft",
                        "last_synced_at": now,
                    }
                ],
                schema_overrides={
                    "external_id": pl.Utf8,
                    "trade_deadline_week": pl.Int32,
                    "faab_budget": pl.Int32,
                    "playoff_week_start": pl.Int32,
                },
            ),
        )
        upsert(
            con,
            "teams",
            pl.DataFrame(
                [
                    {
                        "team_id": team_id,
                        "league_id": league_id,
                        "external_roster_id": "1",
                        "owner_name": "Me",
                        "team_name": name,
                        "is_mine": True,
                        "wins": 0,
                        "losses": 0,
                        "points_for": 0.0,
                        "faab_remaining": None,
                    }
                ],
                schema_overrides={"faab_remaining": pl.Int32},
            ),
        )
        upsert(
            con,
            "roster_spots",
            pl.DataFrame(
                [
                    {"team_id": team_id, "player_id": p, "slot": slot_of[p], "synced_at": now}
                    for p in player_ids
                ]
            ),
        )
    return league_id, team_id


def saved_teams(con: duckdb.DuckDBPyConnection) -> list[dict]:
    """Every team you've picked, across Sleeper, ESPN, manual and demo leagues (newest first)."""
    rows = con.execute(
        """SELECT t.team_id, t.team_name, l.league_id, l.name, l.platform, l.season,
                  l.last_synced_at, c.league_id IS NOT NULL
           FROM teams t JOIN leagues l USING (league_id)
           LEFT JOIN league_credentials c USING (league_id)
           WHERE t.is_mine
           ORDER BY l.last_synced_at DESC NULLS LAST, t.team_name"""
    ).fetchall()
    keys = ("team_id", "team_name", "league_id", "league_name", "platform", "season",
            "last_synced_at", "has_login")  # fmt: skip
    return [dict(zip(keys, r, strict=True)) for r in rows]


def forget_league(con: duckdb.DuckDBPyConnection, league_id: str) -> tuple[str, int]:
    """Delete a league and everything stored for it (teams, rosters, transactions, saved
    trades, ESPN login, sync log) in one transaction. Nothing changes on Sleeper or ESPN.
    Returns (platform, teams removed)."""
    row = con.execute("SELECT platform FROM leagues WHERE league_id = ?", [league_id]).fetchone()
    if row is None:
        raise NotFound("league", f"League not found: {league_id}")
    n = con.execute("SELECT count(*) FROM teams WHERE league_id = ?", [league_id]).fetchone()[0]
    with transaction(con):
        con.execute(
            "DELETE FROM roster_spots WHERE team_id IN (SELECT team_id FROM teams WHERE league_id = ?)",
            [league_id],
        )
        for table in ("teams", "transactions", "saved_trades", "league_credentials", "leagues"):
            con.execute(f"DELETE FROM {table} WHERE league_id = ?", [league_id])
        con.execute("DELETE FROM sync_log WHERE source = ?", [f"league:{league_id}"])
    return row[0], n


def rename_team(con: duckdb.DuckDBPyConnection, team_id: str, name: str) -> str:
    """Rename a manual team (its league carries the same name). Platform teams take their name
    from Sleeper/ESPN, so they're renamed there."""
    row = con.execute(
        "SELECT l.league_id, l.platform FROM teams t JOIN leagues l USING (league_id) WHERE t.team_id = ?",
        [team_id],
    ).fetchone()
    if row is None:
        raise NotFound("team", f"Team not found: {team_id}")
    league_id, platform = row
    if platform != "manual":
        raise InvalidInput(
            f"This team's name comes from {platform.capitalize()}: rename it there, then Update."
        )
    name = name.strip()
    if not name:
        raise InvalidInput("Give the team a name.")
    with transaction(con):
        con.execute("UPDATE teams SET team_name = ? WHERE team_id = ?", [name, team_id])
        con.execute("UPDATE leagues SET name = ? WHERE league_id = ?", [name, league_id])
    return league_id


def league_id_for_team(con: duckdb.DuckDBPyConnection, team_id: str) -> str:
    row = con.execute("SELECT league_id FROM teams WHERE team_id = ?", [team_id]).fetchone()
    if not row:
        raise NotFound("team", f"Team not found: {team_id}")
    return row[0]


def update_manual(
    con: duckdb.DuckDBPyConnection,
    team_id: str,
    *,
    name: str,
    num_teams: int,
    roster_positions: list[str],
    scoring: str | dict[str, float],
    player_ids: list[str],
    starters: list[str] | None = None,
    ir: list[str] | None = None,
    trade_deadline_week: int | None = None,
    playoff_week_start: int = 15,
) -> tuple[str, str]:
    """Replace a manual team's settings and roster (players, starters, bench, IR)."""
    row = con.execute(
        "SELECT l.league_id, l.platform FROM teams t JOIN leagues l USING (league_id) WHERE t.team_id = ?",
        [team_id],
    ).fetchone()
    if not row:
        raise NotFound("team", f"Team not found: {team_id}")
    league_id, platform = row
    if platform != "manual":
        raise InvalidInput(
            f"{platform.title()} rosters sync from {platform.title()} — change them there, then press Update."
        )
    rules = PRESETS[scoring] if isinstance(scoring, str) else normalize(scoring)
    slot_of = roster_slots(
        con,
        roster_positions=roster_positions,
        player_ids=player_ids,
        starters=starters or [],
        ir=ir or [],
    )
    prof = ensure_profile(con, rules, f"Manual ({describe(rules)})")
    now = _now()
    with transaction(con):
        con.execute(
            """UPDATE leagues SET name = ?, num_teams = ?, roster_positions = ?,
                      scoring_profile_id = ?, trade_deadline_week = ?, playoff_week_start = ?,
                      last_synced_at = ? WHERE league_id = ?""",
            [name, num_teams, json.dumps(roster_positions), prof, trade_deadline_week,
             playoff_week_start, now, league_id],
        )  # fmt: skip
        con.execute("UPDATE teams SET team_name = ? WHERE team_id = ?", [name, team_id])
        con.execute("DELETE FROM roster_spots WHERE team_id = ?", [team_id])
        upsert(
            con,
            "roster_spots",
            pl.DataFrame(
                [
                    {"team_id": team_id, "player_id": p, "slot": slot_of[p], "synced_at": now}
                    for p in player_ids
                ]
            ),
        )
    return league_id, team_id
