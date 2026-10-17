"""ESPN client and parsers: settings, rosters, ID matching, and login-cookie handling."""

from __future__ import annotations

import logging
from datetime import datetime

import httpx
import polars as pl
import pytest
import respx

from app.services import leagues
from db.conn import connect, replace_where
from ingest import espn as es
from ingest.espn import Cookies, EspnClient, EspnPlayer
from ingest.http import AuthRejected, CachedHttp
from tests.conftest import load_json

URL = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/2026/segments/0/leagues/12345678"
COOKIES = Cookies("AEB" + "x" * 300 + "S2END", "{11111111-2222-3333-4444-5555SWIDEND}")


@pytest.fixture(scope="module")
def raw() -> dict:
    return load_json("espn_league.json")


def test_parse_league(raw):
    info = es.parse_league(raw)
    assert info.external_id == "12345678" and info.season == 2026 and info.num_teams == 10
    assert info.roster_positions == ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"] + [
        "BN"
    ] * 7 + ["IR"]
    # 14-week regular season, 4-team playoff with 2-week rounds -> weeks 15-18
    assert info.playoff_week_start == 15 and info.final_week == 18
    assert info.trade_deadline is not None and not info.uses_faab and info.faab_budget is None


def test_unsupported_slots_are_named():
    raw = {
        "id": 1,
        "seasonId": 2026,
        "settings": {"rosterSettings": {"lineupSlotCounts": {"0": 1, "10": 2}}},
    }
    with pytest.raises(es.UnsupportedLeague, match="LB"):
        es.parse_league(raw)


def test_deadline_week():
    starts = {12: datetime(2026, 11, 25, 20), 13: datetime(2026, 12, 3, 20)}
    assert es.deadline_week(datetime(2026, 12, 2, 17), starts) == 12
    assert es.deadline_week(None, starts) is None


def test_parse_teams(raw):
    info = es.parse_league(raw)
    teams, players = es.parse_teams(raw, info)
    assert [t.team_name for t in teams] == ["Team 1", "Team 2", "Team 3", "Team 4"]
    assert all(t.owner_name.startswith("owner") for t in teams)
    slots = {slot for t in teams for _, slot in t.roster}
    assert slots <= {"starter", "bench", "ir"} and "starter" in slots and "bench" in slots
    dst = [p for p in players.values() if p.espn_id < 0]
    assert dst and all(p.position == "DEF" and p.nfl_team for p in dst)


def test_dst_id_encodes_team():
    p = es.player_of({"playerId": -16023, "playerPoolEntry": {"player": {"defaultPositionId": 16}}})
    assert p.nfl_team == "PIT" and p.position == "DEF"
    wsh = es.player_of(
        {"playerId": -16028, "playerPoolEntry": {"player": {"defaultPositionId": 16}}}
    )
    assert wsh.nfl_team == "WAS"  # ESPN's WSH is WAS in the local store


def test_name_key():
    assert es.name_key("Marvin Harrison Jr.") == es.name_key("Marvin Harrison")
    assert es.name_key("Amon-Ra St. Brown") == "amon ra st brown"


def test_cookies_never_shown_in_repr():
    text = repr(COOKIES)
    assert "S2END" in text[-30:] or "2END" in text  # last 4 only
    assert "x" * 10 not in text and "11111111" not in text


def test_espn_to_internal_order(tmp_path):
    con = connect(tmp_path / "ff.duckdb")
    replace_where(
        con,
        "players",
        pl.DataFrame(
            [
                {
                    "player_id": "00-A",
                    "espn_id": "100",
                    "full_name": "Has Espn Id",
                    "position": "WR",
                    "nfl_team": "KC",
                },
                {
                    "player_id": "00-B",
                    "espn_id": None,
                    "full_name": "Crosswalk Only",
                    "position": "RB",
                    "nfl_team": "NE",
                },
                {
                    "player_id": "00-C",
                    "espn_id": None,
                    "full_name": "Name Match Jr.",
                    "position": "TE",
                    "nfl_team": "SF",
                },
                {
                    "player_id": "sl:PIT",
                    "espn_id": None,
                    "full_name": "Pittsburgh Steelers",
                    "position": "DEF",
                    "nfl_team": "PIT",
                },
            ]
        ),
        "TRUE",
        [],
    )
    id_map = pl.DataFrame({"espn_id": ["200"], "gsis_id": ["00-B"]})
    players = [
        EspnPlayer(100, "Whatever", "WR", "KC"),
        EspnPlayer(200, "Different Name", "RB", "NE"),
        EspnPlayer(300, "Name Match", "TE", "SF"),
        EspnPlayer(-16023, "Steelers D/ST", "DEF", "PIT"),
        EspnPlayer(400, "Brand New Rookie", "WR", "DAL"),
    ]
    m = leagues.espn_to_internal(con, id_map, players)
    assert m.ids == {100: "00-A", 200: "00-B", 300: "00-C", -16023: "sl:PIT", 400: "espn:400"}
    assert [p.name for p in m.unmatched] == ["Brand New Rookie"]  # listed, not silently dropped


def test_cookies_sent_but_never_cached_or_logged(tmp_path, caplog):
    http = CachedHttp(tmp_path / "cache", min_interval_s=0)
    client = EspnClient(http)
    caplog.set_level(logging.DEBUG)
    with respx.mock as router:
        route = router.get(url__startswith=URL).mock(
            return_value=httpx.Response(200, json={"ok": 1})
        )
        client.league("12345678", 2026, COOKIES, force=True)
        sent = route.calls.last.request.headers["cookie"]
    assert "espn_s2=" + COOKIES.espn_s2 in sent and "SWID=" in sent
    cached = b"".join(p.read_bytes() for p in (tmp_path / "cache").iterdir())
    assert b"S2END" not in cached and b"SWIDEND" not in cached
    assert "S2END" not in caplog.text and "SWIDEND" not in caplog.text


def test_expired_login_is_never_answered_from_cache(tmp_path):
    http = CachedHttp(tmp_path / "cache", min_interval_s=0)
    client = EspnClient(http)
    with respx.mock as router:
        route = router.get(url__startswith=URL)
        route.mock(return_value=httpx.Response(200, json={"settings": {}, "teams": [1]}))
        client.league("12345678", 2026, COOKIES)  # cached now
        route.mock(return_value=httpx.Response(401, json={"messages": ["not authorized"]}))
        with pytest.raises(AuthRejected):
            client.league("12345678", 2026, COOKIES, force=True)


def test_private_without_access():
    assert es.is_private_without_access({"id": 1})
    assert es.is_private_without_access(None)
    assert not es.is_private_without_access({"settings": {}, "teams": [{}]})
