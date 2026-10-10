"""League connect / sync / manual creation — writes leagues, teams, roster_spots, transactions."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime

import duckdb
import polars as pl

from db.conn import log_sync, query_df, replace_where, upsert
from ingest import sleeper as sl
from ingest.run import Clients, market_sync
from scoring.rules import PRESETS, describe, from_sleeper, normalize, profile_id
from signals.lineup import NON_STARTING, SLOT_ELIGIBILITY, fit_to_slots, starting_slots

log = logging.getLogger("ff_edge.leagues")


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
        raise LookupError(f"Sleeper user '{username}' not found")
    state = c.sleeper.state()
    season = int(state.get("league_season") or state["season"])
    out = []
    for raw in c.sleeper.leagues(user["user_id"], season):
        info = sl.parse_league(raw)
        rosters = sync_sleeper_league(con, c, info.external_id, raw_league=raw)
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
    prof = ensure_profile(con, rules, f"{info.name} ({describe(rules)})")
    league_id = sleeper_league_id(external_id)
    prev_mine = con.execute(
        "SELECT external_roster_id FROM teams WHERE league_id = ? AND is_mine", [league_id]
    ).fetchone()

    rosters = sl.parse_rosters(
        c.sleeper.rosters(external_id, force=force),
        c.sleeper.league_users(external_id, force=force),
        info.faab_budget,
    )
    now = _now()
    upsert(
        con,
        "leagues",
        pl.DataFrame(
            [
                {
                    "league_id": league_id,
                    "platform": "sleeper",
                    "external_id": external_id,
                    "season": info.season,
                    "name": info.name,
                    "num_teams": info.num_teams,
                    "roster_positions": json.dumps(info.roster_positions),
                    "scoring_profile_id": prof,
                    "trade_deadline_week": info.trade_deadline_week,
                    "uses_faab": info.uses_faab,
                    "faab_budget": info.faab_budget,
                    "playoff_week_start": info.playoff_week_start,
                    "last_synced_at": now,
                }
            ],
            schema_overrides={
                "trade_deadline_week": pl.Int32,
                "faab_budget": pl.Int32,
                "playoff_week_start": pl.Int32,
            },
        ),
    )
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

    _sync_transactions(con, c, external_id, league_id, force)
    _ensure_market(con, c, rules, info)
    log_sync(con, f"league:{league_id}", "ok", f"{len(rosters)} rosters")
    return rosters


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
    con: duckdb.DuckDBPyConnection, c: Clients, rules: dict, info: sl.LeagueInfo
) -> None:
    from ingest.market_values import MarketFormat

    sf = "SUPER_FLEX" in info.roster_positions or info.roster_positions.count("QB") > 1
    fmt = MarketFormat(info.num_teams, 2 if sf else 1, normalize(rules)["rec"])
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
        raise LookupError(f"roster {external_roster_id} not found in {league_id}")
    con.execute("UPDATE teams SET is_mine = (team_id = ?) WHERE league_id = ?", [row[0], league_id])
    con.execute("UPDATE leagues SET last_synced_at = ? WHERE league_id = ?", [_now(), league_id])
    return row[0]


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
        raise LookupError(f"unknown player ids: {', '.join(missing[:5])}")
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
        raise ValueError(f"unknown roster slot(s): {', '.join(sorted(set(bad)))}")
    slots = starting_slots(roster_positions)
    if not slots:
        raise ValueError("a lineup needs at least one starting slot")
    n_bench = roster_positions.count("BN") + roster_positions.count("TAXI")
    n_ir = roster_positions.count("IR")
    if len(set(player_ids)) != len(player_ids):
        raise ValueError("a player appears on the roster twice")
    ids = set(player_ids)
    if not set(starters) <= ids or not set(ir) <= ids:
        raise ValueError("starters and IR players must also be on the roster")
    if set(starters) & set(ir):
        raise ValueError("a player can't be both starting and on IR")
    if len(ir) > n_ir:
        raise ValueError(f"{len(ir)} players on IR but the league has {n_ir} IR spot(s)")
    active = [p for p in player_ids if p not in set(ir)]
    if len(active) > len(slots) + n_bench:
        raise ValueError(
            f"{len(active)} active players but only {len(slots)} starting + {n_bench} bench spots"
        )
    if starters:
        if len(starters) > len(slots):
            raise ValueError(f"{len(starters)} starters but only {len(slots)} starting slots")
        _, unplaced = fit_to_slots([(p, positions[p]) for p in starters], slots)
        if unplaced:
            raise ValueError(
                "these starters don't fit an open lineup slot: "
                + ", ".join(f"{p} ({positions[p]})" for p in unplaced)
            )
        bench = len(active) - len(starters)
        if bench > n_bench:
            raise ValueError(f"{bench} bench players but only {n_bench} bench spots")
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
                    "playoff_week_start": 15,
                    "last_synced_at": now,
                }
            ],
            schema_overrides={
                "external_id": pl.Utf8,
                "trade_deadline_week": pl.Int32,
                "faab_budget": pl.Int32,
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


def league_id_for_team(con: duckdb.DuckDBPyConnection, team_id: str) -> str:
    row = con.execute("SELECT league_id FROM teams WHERE team_id = ?", [team_id]).fetchone()
    if not row:
        raise KeyError(team_id)
    return row[0]
