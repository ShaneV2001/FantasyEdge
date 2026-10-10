"""Sleeper API client + pure parsers. Docs: https://docs.sleeper.com (free, non-commercial).

Rules we follow: stay far below 1000 calls/min, fetch /players/nfl at most once per day.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import polars as pl

from ingest.http import CachedHttp

FANTASY_POSITIONS = ("QB", "RB", "WR", "TE", "K", "DEF")
SOURCE = "sleeper"


class SleeperClient:
    def __init__(self, http: CachedHttp, base: str = "https://api.sleeper.app/v1"):
        self.http = http
        self.base = base.rstrip("/")

    def _get(self, path: str, ttl: timedelta, force: bool = False, **params: Any) -> Any:
        return self.http.get_json(
            f"{self.base}{path}", source=SOURCE, params=params or None, ttl=ttl, force=force
        )

    def state(self) -> dict:
        return self._get("/state/nfl", timedelta(minutes=30))

    def user(self, username: str) -> dict | None:
        return self._get(f"/user/{username}", timedelta(hours=1))

    def leagues(self, user_id: str, season: int | str) -> list[dict]:
        return self._get(f"/user/{user_id}/leagues/nfl/{season}", timedelta(minutes=10)) or []

    def league(self, league_id: str, force: bool = False) -> dict:
        return self._get(f"/league/{league_id}", timedelta(minutes=10), force)

    def rosters(self, league_id: str, force: bool = False) -> list[dict]:
        return self._get(f"/league/{league_id}/rosters", timedelta(minutes=5), force) or []

    def league_users(self, league_id: str, force: bool = False) -> list[dict]:
        return self._get(f"/league/{league_id}/users", timedelta(minutes=30), force) or []

    def transactions(self, league_id: str, week: int, force: bool = False) -> list[dict]:
        return (
            self._get(f"/league/{league_id}/transactions/{week}", timedelta(minutes=5), force) or []
        )

    def players(self, force: bool = False) -> dict[str, dict]:
        # ~15 MB — Sleeper asks callers to fetch this at most once per day.
        return self._get("/players/nfl", timedelta(hours=24), force)

    def trending(self, kind: str = "add", lookback_hours: int = 24, limit: int = 25) -> list[dict]:
        return self._get(
            f"/players/nfl/trending/{kind}",
            timedelta(minutes=30),
            lookback_hours=lookback_hours,
            limit=limit,
        )


# ───────── pure parsers ─────────


# Sleeper `settings.type`
LEAGUE_TYPES = {0: "redraft", 1: "keeper", 2: "dynasty"}


@dataclass
class LeagueInfo:
    external_id: str
    name: str
    season: int
    num_teams: int
    roster_positions: list[str]
    scoring_settings: dict[str, float]
    trade_deadline_week: int | None
    uses_faab: bool
    faab_budget: int | None
    playoff_week_start: int | None
    league_type: str = "redraft"
    status: str = ""
    avatar: str | None = None
    extra: dict = field(default_factory=dict)


def parse_league(raw: dict) -> LeagueInfo:
    settings = raw.get("settings") or {}
    deadline = settings.get("trade_deadline")
    # Sleeper uses 99 for "no deadline"
    deadline = None if deadline in (None, 0, 99) else int(deadline)
    waiver_type = settings.get("waiver_type")
    budget = settings.get("waiver_budget")
    return LeagueInfo(
        external_id=str(raw["league_id"]),
        name=raw.get("name") or "Sleeper league",
        season=int(raw.get("season") or 0),
        num_teams=int(settings.get("num_teams") or raw.get("total_rosters") or 12),
        roster_positions=list(raw.get("roster_positions") or []),
        scoring_settings={k: float(v) for k, v in (raw.get("scoring_settings") or {}).items()},
        trade_deadline_week=deadline,
        uses_faab=waiver_type == 2,
        faab_budget=int(budget) if budget is not None and waiver_type == 2 else None,
        playoff_week_start=int(settings["playoff_week_start"])
        if settings.get("playoff_week_start")
        else None,
        league_type=LEAGUE_TYPES.get(int(settings.get("type") or 0), "redraft"),
        status=raw.get("status") or "",
        avatar=raw.get("avatar"),
    )


@dataclass
class RosterInfo:
    roster_id: str
    owner_id: str | None
    owner_name: str
    team_name: str
    players: list[str]
    starters: list[str]
    reserve: list[str]
    taxi: list[str]
    wins: int
    losses: int
    points_for: float
    faab_remaining: int | None


def parse_rosters(
    rosters: list[dict], users: list[dict], faab_budget: int | None
) -> list[RosterInfo]:
    by_user = {u["user_id"]: u for u in users}
    out = []
    for r in rosters:
        owner = by_user.get(r.get("owner_id") or "", {})
        settings = r.get("settings") or {}
        display = owner.get("display_name") or f"Team {r['roster_id']}"
        team_name = (owner.get("metadata") or {}).get("team_name") or display
        fpts = float(settings.get("fpts") or 0) + float(settings.get("fpts_decimal") or 0) / 100
        used = settings.get("waiver_budget_used")
        out.append(
            RosterInfo(
                roster_id=str(r["roster_id"]),
                owner_id=r.get("owner_id"),
                owner_name=display,
                team_name=team_name,
                players=[p for p in (r.get("players") or []) if p],
                starters=[p for p in (r.get("starters") or []) if p and p != "0"],
                reserve=[p for p in (r.get("reserve") or []) if p],
                taxi=[p for p in (r.get("taxi") or []) if p],
                wins=int(settings.get("wins") or 0),
                losses=int(settings.get("losses") or 0),
                points_for=fpts,
                faab_remaining=(faab_budget - int(used or 0)) if faab_budget is not None else None,
            )
        )
    return out


def parse_players(raw: dict[str, dict]) -> pl.DataFrame:
    """Sleeper player map → one row per fantasy-relevant player (Sleeper-keyed)."""
    rows = []
    for sid, p in raw.items():
        pos = p.get("position")
        if pos not in FANTASY_POSITIONS:
            continue
        if pos != "DEF" and not p.get("active") and not p.get("team"):
            continue
        name = p.get("full_name") or " ".join(
            x for x in (p.get("first_name"), p.get("last_name")) if x
        )
        if pos == "DEF":
            name = f"{p.get('first_name', sid)} {p.get('last_name', 'DEF')}".strip()
        gsis = (p.get("gsis_id") or "").strip() or None
        rows.append(
            {
                "sleeper_id": str(sid),
                "gsis_id": gsis,
                "espn_id": str(p["espn_id"]) if p.get("espn_id") else None,
                "yahoo_id": str(p["yahoo_id"]) if p.get("yahoo_id") else None,
                "full_name": name or sid,
                "position": pos,
                "nfl_team": p.get("team") or (sid if pos == "DEF" else None),
                "birth_date": p.get("birth_date") or None,
                "years_exp": p.get("years_exp"),
                "status": p.get("status"),
                "injury_status": p.get("injury_status"),
                "depth_chart_order": p.get("depth_chart_order"),
            }
        )
    return pl.DataFrame(
        rows,
        schema={
            "sleeper_id": pl.Utf8,
            "gsis_id": pl.Utf8,
            "espn_id": pl.Utf8,
            "yahoo_id": pl.Utf8,
            "full_name": pl.Utf8,
            "position": pl.Utf8,
            "nfl_team": pl.Utf8,
            "birth_date": pl.Utf8,
            "years_exp": pl.Int64,
            "status": pl.Utf8,
            "injury_status": pl.Utf8,
            "depth_chart_order": pl.Int64,
        },
    )


def deadline_passed(trade_deadline_week: int | None, current_week: int) -> bool:
    return trade_deadline_week is not None and current_week > trade_deadline_week
