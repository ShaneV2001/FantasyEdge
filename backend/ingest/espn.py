"""ESPN fantasy football client + pure parsers.

ESPN has no official public API. This reads the same endpoints fantasy.espn.com itself uses
(`lm-api-reads.fantasy.espn.com`, read-only). Private leagues need the `espn_s2` and `SWID` login
cookies; they are passed per request and never stored on the client, logged or cached.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from ingest.http import CachedHttp

SOURCE = "espn"
BASE = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl"
LEAGUE_VIEWS = ("mSettings", "mTeam", "mRoster", "mStatus")

# ESPN lineup slot IDs -> our roster_positions labels (signals/lineup.py)
SLOT: dict[int, str] = {
    0: "QB", 2: "RB", 4: "WR", 6: "TE", 23: "FLEX", 3: "WRRB_FLEX", 5: "REC_FLEX",
    7: "SUPER_FLEX", 17: "K", 16: "DEF", 20: "BN", 21: "IR",
}  # fmt: skip
SLOT_ORDER = (0, 2, 4, 6, 23, 3, 5, 7, 17, 16, 20, 21)
UNSUPPORTED_SLOT = {
    1: "TQB", 8: "DT", 9: "DE", 10: "LB", 11: "DL", 12: "CB", 13: "S", 14: "DB", 15: "DP",
    18: "P", 19: "HC", 24: "ER", 25: "Rookie",
}  # fmt: skip
BENCH, IR = 20, 21
# ESPN default position IDs -> ours
POSITION: dict[int, str] = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "DEF"}
# ESPN proTeamId -> NFL team as the local store spells it (Sleeper's abbreviations)
PRO_TEAM: dict[int, str] = {
    1: "ATL", 2: "BUF", 3: "CHI", 4: "CIN", 5: "CLE", 6: "DAL", 7: "DEN", 8: "DET", 9: "GB",
    10: "TEN", 11: "IND", 12: "KC", 13: "LV", 14: "LAR", 15: "MIA", 16: "MIN", 17: "NE",
    18: "NO", 19: "NYG", 20: "NYJ", 21: "PHI", 22: "ARI", 23: "PIT", 24: "LAC", 25: "SF",
    26: "SEA", 27: "TB", 28: "WAS", 29: "CAR", 30: "JAX", 33: "BAL", 34: "HOU",
}  # fmt: skip
DST_ID_BASE = -16000  # a D/ST's ESPN player id is -16000 - proTeamId


@dataclass(frozen=True)
class Cookies:
    espn_s2: str
    swid: str

    def as_dict(self) -> dict[str, str]:
        return {"espn_s2": self.espn_s2, "SWID": self.swid}

    def __repr__(self) -> str:  # keep secrets out of tracebacks and debug logs
        return f"Cookies(espn_s2=…{self.espn_s2[-4:]}, swid=…{self.swid[-4:]})"


class EspnClient:
    def __init__(self, http: CachedHttp, base: str = BASE):
        self.http = http
        self.base = base.rstrip("/")

    def _league_url(self, league_id: str, season: int) -> str:
        return f"{self.base}/seasons/{season}/segments/0/leagues/{league_id}"

    def league(
        self,
        league_id: str,
        season: int,
        cookies: Cookies | None,
        views: Sequence[str] = LEAGUE_VIEWS,
        force: bool = False,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> dict:
        return self.http.get_json(
            self._league_url(league_id, season),
            source=SOURCE,
            params=[("view", v) for v in views] + list((params or {}).items()),
            ttl=timedelta(minutes=5),
            force=force,
            cookies=cookies.as_dict() if cookies else None,
            headers=dict(headers) if headers else None,
        )

    def available_players(
        self, league_id: str, season: int, cookies: Cookies | None, limit: int = 300
    ) -> list[dict]:
        """Free agents and players on waivers, most-owned first."""
        flt = {
            "players": {
                "filterStatus": {"value": ["FREEAGENT", "WAIVERS"]},
                "filterSlotIds": {"value": [0, 2, 4, 6, 17, 16]},
                "limit": limit,
                "sortPercOwned": {"sortPriority": 1, "sortAsc": False},
            }
        }
        raw = self.league(
            league_id,
            season,
            cookies,
            views=("kona_player_info",),
            headers={"X-Fantasy-Filter": json.dumps(flt)},
        )
        return raw.get("players") or []

    def transactions(
        self, league_id: str, season: int, cookies: Cookies | None, week: int, force: bool = False
    ) -> list[dict]:
        raw = self.league(
            league_id,
            season,
            cookies,
            views=("mTransactions2",),
            params={"scoringPeriodId": week},
            force=force,
        )
        return raw.get("transactions") or []


# ───────── pure parsers ─────────


class UnsupportedLeague(ValueError):
    """The league uses something we can't model (e.g. IDP slots)."""


@dataclass
class EspnLeague:
    external_id: str
    season: int
    name: str
    num_teams: int
    roster_positions: list[str]
    scoring_items: list[dict]
    trade_deadline: datetime | None
    uses_faab: bool
    faab_budget: int | None
    playoff_week_start: int | None
    final_week: int | None
    current_week: int
    league_type: str = "redraft"
    # an accepted trade waits this long for league review before ESPN processes it
    trade_review_hours: int | None = None


def parse_league(raw: Mapping) -> EspnLeague:
    s = raw.get("settings") or {}
    counts = {int(k): int(v) for k, v in (s.get("rosterSettings") or {}).get("lineupSlotCounts", {}).items() if v}  # fmt: skip
    odd = sorted(UNSUPPORTED_SLOT[k] for k in counts if k in UNSUPPORTED_SLOT)
    unknown = sorted(k for k in counts if k not in SLOT and k not in UNSUPPORTED_SLOT)
    if odd or unknown:
        what = ", ".join(odd + [f"slot #{k}" for k in unknown])
        raise UnsupportedLeague(
            f"This league uses lineup slots FantasyEdge can't model yet: {what}"
        )
    roster_positions = [SLOT[k] for k in SLOT_ORDER for _ in range(counts.get(k, 0))]

    sched = s.get("scheduleSettings") or {}
    regular = sched.get("matchupPeriodCount")
    playoff_start = int(regular) + 1 if regular else None
    final_week = None
    if playoff_start:
        teams_in = int(sched.get("playoffTeamCount") or 0)
        rounds = math.ceil(math.log2(teams_in)) if teams_in > 1 else 0
        length = int(sched.get("playoffMatchupPeriodLength") or 1)
        final_week = min(int(regular) + rounds * length, 18)

    trade = s.get("tradeSettings") or {}
    deadline_ms = trade.get("deadlineDate")
    review = trade.get("revisionHours")
    acq = s.get("acquisitionSettings") or {}
    uses_faab = bool(acq.get("isUsingAcquisitionBudget"))
    keepers = int((s.get("draftSettings") or {}).get("keeperCount") or 0)
    return EspnLeague(
        external_id=str(raw["id"]),
        season=int(raw["seasonId"]),
        name=s.get("name") or "ESPN league",
        num_teams=int(s.get("size") or len(raw.get("teams") or []) or 10),
        roster_positions=roster_positions,
        scoring_items=list((s.get("scoringSettings") or {}).get("scoringItems") or []),
        trade_deadline=datetime.fromtimestamp(deadline_ms / 1000, UTC).replace(tzinfo=None)
        if deadline_ms
        else None,
        uses_faab=uses_faab,
        faab_budget=int(acq["acquisitionBudget"])
        if uses_faab and acq.get("acquisitionBudget") is not None
        else None,
        playoff_week_start=playoff_start,
        final_week=final_week,
        current_week=int(raw.get("scoringPeriodId") or 1),
        league_type="keeper" if keepers else "redraft",
        trade_review_hours=int(review) if review is not None and int(review) >= 0 else None,
    )


def deadline_week(deadline: datetime | None, week_starts: Mapping[int, datetime]) -> int | None:
    """Last NFL week whose first game kicks off before the trade deadline (trades allowed in it)."""
    if deadline is None or not week_starts:
        return None
    weeks = [w for w, start in week_starts.items() if start <= deadline]
    return max(weeks) if weeks else 0


@dataclass
class EspnPlayer:
    espn_id: int
    name: str
    position: str | None
    nfl_team: str | None


@dataclass
class EspnTeam:
    team_id: str
    team_name: str
    owner_name: str
    owner_ids: list[str]
    wins: int
    losses: int
    points_for: float
    faab_remaining: int | None
    # (espn player id, "starter" | "bench" | "ir")
    roster: list[tuple[int, str]] = field(default_factory=list)


def _owner_name(member: Mapping | None, fallback: str) -> str:
    if not member:
        return fallback
    full = " ".join(x for x in (member.get("firstName"), member.get("lastName")) if x)
    return member.get("displayName") or full or fallback


def player_of(entry: Mapping) -> EspnPlayer:
    p = (entry.get("playerPoolEntry") or {}).get("player") or entry.get("player") or {}
    pid = int(entry.get("playerId") or p.get("id"))
    pos = POSITION.get(int(p.get("defaultPositionId") or -1))
    team = PRO_TEAM.get(int(p.get("proTeamId") or 0))
    if pid < 0 and team is None:  # D/ST ids encode the team
        team = PRO_TEAM.get(DST_ID_BASE - pid)
    return EspnPlayer(pid, p.get("fullName") or f"ESPN player {pid}", pos, team)


def parse_teams(raw: Mapping, league: EspnLeague) -> tuple[list[EspnTeam], dict[int, EspnPlayer]]:
    members = {m.get("id"): m for m in raw.get("members") or []}
    teams, players = [], {}
    for t in raw.get("teams") or []:
        tid = str(t["id"])
        name = (
            t.get("name")
            or " ".join(x for x in (t.get("location"), t.get("nickname")) if x)
            or f"Team {tid}"
        )
        rec = (t.get("record") or {}).get("overall") or {}
        spent = (t.get("transactionCounter") or {}).get("acquisitionBudgetSpent") or 0
        roster = []
        for e in (t.get("roster") or {}).get("entries") or []:
            p = player_of(e)
            players[p.espn_id] = p
            slot = int(e.get("lineupSlotId", BENCH))
            roster.append(
                (p.espn_id, "bench" if slot == BENCH else "ir" if slot == IR else "starter")
            )
        teams.append(
            EspnTeam(
                team_id=tid,
                team_name=name,
                owner_name=_owner_name(members.get(t.get("primaryOwner")), t.get("abbrev") or name),
                owner_ids=list(t.get("owners") or []),
                wins=int(rec.get("wins") or 0),
                losses=int(rec.get("losses") or 0),
                points_for=float(rec.get("pointsFor") or t.get("points") or 0.0),
                faab_remaining=league.faab_budget - int(spent)
                if league.faab_budget is not None
                else None,
                roster=roster,
            )
        )
    return teams, players


@dataclass(frozen=True)
class PendingTrade:
    """A trade both sides accepted that ESPN hasn't processed yet (league review period)."""

    external_id: str
    accepted_at: datetime | None
    # (espn player id, from ESPN team id, to ESPN team id)
    moves: list[tuple[int, str, str]]
    # (espn player id, ESPN team id) released to make room
    drops: list[tuple[int, str]] = field(default_factory=list)


# Transactions that end a proposal before it is processed
_ENDS_TRADE = {"TRADE_DECLINE", "TRADE_VETO", "TRADE_ERROR"}


def _ms(value: Any) -> datetime | None:
    return datetime.fromtimestamp(value / 1000, UTC).replace(tzinfo=None) if value else None


@dataclass(frozen=True)
class TradeOffer:
    """A trade one team proposed that the other side hasn't answered yet."""

    external_id: str
    proposed_at: datetime | None
    proposer: str  # ESPN team id
    moves: list[tuple[int, str, str]]
    drops: list[tuple[int, str]] = field(default_factory=list)


def _open_proposals(
    transactions: Sequence[Mapping],
) -> list[tuple[str, Mapping, list[Mapping]]]:
    """PENDING `TRADE_PROPOSAL`s nothing has ended, each with the transactions that point at it.

    ESPN keeps the original proposal at status PENDING and links later steps to it through
    `relatedTransactionId`. A decline, veto, a CANCELED copy of the proposal or an EXECUTED
    accept (the trade went through) ends it."""
    related: dict[str, list[Mapping]] = {}
    for t in transactions:
        if t.get("relatedTransactionId"):
            related.setdefault(str(t["relatedTransactionId"]), []).append(t)
    out = []
    for t in {str(t.get("id")): t for t in transactions}.values():
        if t.get("type") != "TRADE_PROPOSAL" or t.get("status") != "PENDING":
            continue
        links = related.get(str(t.get("id")), [])
        ended = any(
            r.get("type") in _ENDS_TRADE
            or (r.get("type") == "TRADE_PROPOSAL" and r.get("status") == "CANCELED")
            or (r.get("type") == "TRADE_ACCEPT" and r.get("status") == "EXECUTED")
            for r in links
        )
        if not ended:
            out.append((str(t.get("id")), t, links))
    return out


def _trade_items(t: Mapping) -> tuple[list[tuple[int, str, str]], list[tuple[int, str]]]:
    items = t.get("items") or []
    moves = [
        (int(i["playerId"]), str(i["fromTeamId"]), str(i["toTeamId"]))
        for i in items
        if i.get("type") == "TRADE" and i.get("playerId") is not None
    ]
    drops = [
        (int(i["playerId"]), str(i["fromTeamId"]))
        for i in items
        if i.get("type") == "DROP" and i.get("playerId") is not None
    ]
    return moves, drops


def parse_pending_trades(transactions: Sequence[Mapping]) -> list[PendingTrade]:
    """Accepted-but-unprocessed trades from `mTransactions2`: open proposals with a separate
    `TRADE_ACCEPT` pointing at them."""
    out = []
    for tid, t, links in _open_proposals(transactions):
        accepts = [r for r in links if r.get("type") == "TRADE_ACCEPT"]
        moves, drops = _trade_items(t)
        if not accepts or not moves:
            continue
        accepted = max((r.get("proposedDate") or 0 for r in accepts), default=0)
        out.append(PendingTrade(tid, _ms(accepted), moves, drops))
    out.sort(key=lambda p: p.accepted_at or datetime.min)
    return out


def parse_trade_offers(transactions: Sequence[Mapping]) -> list[TradeOffer]:
    """Open proposals nobody has accepted yet, newest first. The proposer is the proposal's
    `teamId` when ESPN sends one, else the team giving the first player."""
    out = []
    for tid, t, links in _open_proposals(transactions):
        moves, drops = _trade_items(t)
        if not moves or any(r.get("type") == "TRADE_ACCEPT" for r in links):
            continue
        proposer = str(t["teamId"]) if t.get("teamId") else moves[0][1]
        out.append(TradeOffer(tid, _ms(t.get("proposedDate")), proposer, moves, drops))
    out.sort(key=lambda o: o.proposed_at or datetime.min, reverse=True)
    return out


def is_private_without_access(raw: Any) -> bool:
    """ESPN sometimes answers an unauthorised request with 200 and no league data."""
    return not isinstance(raw, Mapping) or "settings" not in raw or not raw.get("teams")


_SUFFIX = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b")


def name_key(name: str) -> str:
    """Normalised name for fallback matching: lowercase, no punctuation or Jr./III suffixes."""
    s = re.sub(r"[^a-z ]", "", name.lower().replace("-", " "))
    return " ".join(_SUFFIX.sub("", s).split())
