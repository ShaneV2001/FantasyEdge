"""End-to-end API tests on a fixture-seeded DuckDB with every external call mocked (respx)."""

from __future__ import annotations

import httpx
import polars as pl
import pytest
import respx
from fastapi.testclient import TestClient

from app import deps
from app.config import Settings
from app.main import app
from app.services import context
from db.conn import connect, upsert
from ingest.http import CachedHttp
from ingest.idmap import DP_IDS_URL, attach_internal_ids, parse_id_map
from ingest.market_values import DP_VALUES_URL
from ingest.run import Clients, players_sync
from ingest.sleeper import SleeperClient
from tests.conftest import load_json, load_parquet, load_text

SL = "https://api.sleeper.app/v1"
FC = "https://api.fantasycalc.com"
LEAGUE = "999000111"


def mock_sources(router: respx.MockRouter) -> None:
    router.get(f"{SL}/state/nfl").mock(
        return_value=httpx.Response(200, json=load_json("sleeper_state.json"))
    )
    router.get(f"{SL}/user/alphamanager").mock(
        return_value=httpx.Response(200, json=load_json("sleeper_user.json"))
    )
    router.get(f"{SL}/user/ghost").mock(return_value=httpx.Response(200, text="null"))
    router.get(url__regex=rf"{SL}/user/u0/leagues/nfl/\d+").mock(
        return_value=httpx.Response(200, json=load_json("sleeper_leagues.json"))
    )
    router.get(f"{SL}/league/{LEAGUE}").mock(
        return_value=httpx.Response(200, json=load_json("sleeper_league.json"))
    )
    router.get(f"{SL}/league/{LEAGUE}/rosters").mock(
        return_value=httpx.Response(200, json=load_json("sleeper_rosters.json"))
    )
    router.get(f"{SL}/league/{LEAGUE}/users").mock(
        return_value=httpx.Response(200, json=load_json("sleeper_users.json"))
    )
    router.get(url__regex=rf"{SL}/league/{LEAGUE}/transactions/\d+").mock(
        return_value=httpx.Response(200, json=[])
    )
    router.get(f"{SL}/players/nfl").mock(
        return_value=httpx.Response(200, json=load_json("sleeper_players.json"))
    )
    router.get(f"{FC}/values/current").mock(
        return_value=httpx.Response(200, json=load_json("fantasycalc_values.json"))
    )
    router.get(DP_IDS_URL).mock(
        return_value=httpx.Response(200, text=load_text("dp_playerids.csv"))
    )
    router.get(DP_VALUES_URL).mock(
        return_value=httpx.Response(200, text=load_text("dp_values.csv"))
    )


@pytest.fixture
def client(tmp_path):
    with respx.mock(assert_all_called=False) as router:
        mock_sources(router)
        settings = Settings(tmp_path, (2025, 2026), "fantasycalc", SL, FC)
        http = CachedHttp(tmp_path / "cache", min_interval_s=0)
        clients = Clients(http, SleeperClient(http, SL), settings)
        con = connect(tmp_path / "ff.duckdb")
        players_sync(con, clients)
        upsert(con, "player_week_stats", load_parquet("player_week_stats.parquet"))
        upsert(con, "nfl_games", load_parquet("nfl_games.parquet"))
        upsert(con, "injuries", load_parquet("injuries.parquet"))
        deps.init(con, clients)
        context.invalidate()
        with TestClient(app) as tc:
            yield tc, router
        context.invalidate()
        con.close()


def connect_and_pick(tc) -> str:
    r = tc.post("/league/connect", json={"platform": "sleeper", "username": "alphamanager"})
    assert r.status_code == 200, r.text
    lg = r.json()["leagues"][0]
    assert lg["num_teams"] == 4 and lg["scoring"] == "Half PPR"
    mine = next(t for t in lg["teams"] if t["is_user"])
    r = tc.post(
        f"/league/{lg['league_id']}/select-team",
        json={"external_roster_id": mine["external_roster_id"]},
    )
    assert r.status_code == 200, r.text
    return r.json()["team_id"]


def test_connect_select_and_team_view(client):
    tc, _ = client
    team_id = connect_and_pick(tc)
    r = tc.get(f"/team/{team_id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["league"]["week"] >= 1
    assert len(body["roster"]) >= 14
    assert set(body["grades"]) == {"QB", "RB", "WR", "TE"}
    assert any(p["market_value"] for p in body["roster"])
    assert body["market"]["source"] == "fantasycalc"
    assert len(body["league_teams"]) == 4


def test_advice_regression_byes(client):
    tc, _ = client
    team_id = connect_and_pick(tc)

    advice = tc.get(f"/team/{team_id}/advice").json()
    assert 1 <= len(advice["actions"]) <= 10
    for a in advice["actions"]:
        assert a["reasons"] and a["urgency"] and a["confidence"]
    prios = [a["priority"] for a in advice["actions"]]
    assert prios == sorted(prios, reverse=True)

    reg = tc.get(f"/team/{team_id}/regression").json()
    assert reg["thresholds"]["tdoe"] == 2.0
    assert all(row["player"]["position"] in ("QB", "RB", "WR", "TE") for row in reg["roster"])

    byes = tc.get(f"/team/{team_id}/byes").json()
    assert byes["weeks"][0]["week"] == byes["week"]
    assert len(byes["weeks"][0]["cells"]) == len(byes["slots"])
    assert all(c["status"] in ("ok", "thin", "empty") for w in byes["weeks"] for c in w["cells"])


def test_trade_evaluate_and_suggest(client):
    tc, _ = client
    team_id = connect_and_pick(tc)
    team = tc.get(f"/team/{team_id}").json()
    other = next(t for t in team["league_teams"] if not t["is_mine"])
    other_roster = tc.get(f"/team/{other['team_id']}").json()["roster"]

    give = next(p["player_id"] for p in team["roster"] if p["position"] == "WR")
    receive = next(p["player_id"] for p in other_roster if p["position"] == "WR")
    r = tc.post("/trade/evaluate", json={"team_id": team_id, "give": [give], "receive": [receive]})
    assert r.status_code == 200, r.text
    ev = r.json()
    assert ev["verdict"] in ("accept", "lean_accept", "neutral", "decline")
    assert ev["partner"]["team_id"] == other["team_id"]
    assert ev["me"]["lineup_delta"] == pytest.approx(
        ev["me"]["lineup_after"] - ev["me"]["lineup_before"], abs=0.11
    )

    s = tc.get("/trade/suggest", params={"team_id": team_id}).json()
    assert s["trade_deadline_week"] == 11
    for idea in s["ideas"]:
        assert idea["me"]["lineup_delta"] > 0 and idea["partner"]["lineup_delta"] > 0


def test_trade_validation_errors(client):
    tc, _ = client
    team_id = connect_and_pick(tc)
    r = tc.post("/trade/evaluate", json={"team_id": team_id, "give": [], "receive": []})
    assert r.status_code == 422
    r = tc.post("/trade/evaluate", json={"team_id": team_id, "give": ["nope"], "receive": []})
    assert r.status_code == 422


def test_manual_league_flow(client):
    tc, _ = client
    found = tc.get("/players", params={"q": "", "pos": "RB", "limit": 5}).json()
    assert len(found) == 5 and all(p["position"] == "RB" for p in found)
    pool = tc.get("/players", params={"limit": 30}).json()
    r = tc.post(
        "/league/manual",
        json={
            "name": "Couch League",
            "num_teams": 10,
            "scoring": "ppr",
            "player_ids": [p["player_id"] for p in pool[:15]],
        },
    )
    assert r.status_code == 200, r.text
    team_id = r.json()["team_id"]
    advice = tc.get(f"/team/{team_id}/advice").json()
    assert any("Manual team" in n for n in advice["notes"])
    assert tc.get(f"/team/{team_id}").json()["league"]["scoring"] == "PPR"
    assert tc.get(f"/team/{team_id}/byes").status_code == 200


def test_unknown_team_and_user(client):
    tc, _ = client
    assert tc.get("/team/does-not-exist").status_code == 404
    r = tc.post("/league/connect", json={"username": "ghost"})
    assert r.status_code == 404 and "not found" in r.json()["detail"], r.text


def test_sleeper_down_returns_503(client):
    tc, router = client
    router.get(f"{SL}/user/downuser").mock(return_value=httpx.Response(503))
    r = tc.post("/league/connect", json={"username": "downuser"})
    assert r.status_code == 503 and r.json()["source"] == "sleeper"


def test_status_and_refresh(client):
    tc, _ = client
    team_id = connect_and_pick(tc)
    st = tc.get("/meta/status").json()
    assert st["week"] is not None and any("nflverse" in a for a in st["attribution"])
    league_id = tc.get(f"/team/{team_id}").json()["league"]["league_id"]
    r = tc.post("/refresh", json={"scope": "league", "league_id": league_id})
    assert r.status_code == 200 and r.json()["ok"]
    # team stays selected across a re-sync
    assert tc.get(f"/team/{team_id}").json()["team_id"] == team_id


def test_openapi_lists_phase1_paths(client):
    tc, _ = client
    paths = tc.get("/openapi.json").json()["paths"]
    for p in (
        "/league/connect", "/league/{league_id}/select-team", "/league/manual", "/team/{team_id}",
        "/team/{team_id}/advice", "/team/{team_id}/regression", "/team/{team_id}/byes",
        "/trade/evaluate", "/trade/suggest", "/meta/status", "/refresh",
    ):  # fmt: skip
        assert p in paths, p


def test_players_table_has_internal_ids(client):
    ids = attach_internal_ids(
        pl.DataFrame(
            {"sleeper_id": ["x"], "gsis_id": [None]},
            schema={"sleeper_id": pl.Utf8, "gsis_id": pl.Utf8},
        ).with_columns(pl.lit(None, pl.Utf8).alias("nfl_team")),
        parse_id_map(load_text("dp_playerids.csv")),
    )
    assert ids["player_id"][0] == "sl:x"
