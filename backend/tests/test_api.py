"""End-to-end API tests on a fixture-seeded DuckDB with every external call mocked (respx)."""

from __future__ import annotations

import dataclasses
from datetime import datetime

import httpx
import polars as pl
import pytest
import respx
from fastapi.testclient import TestClient

from app import deps
from app.config import Settings
from app.main import app
from app.services import context, leagues, views
from db.conn import connect, upsert
from ingest import run as run_jobs
from ingest.http import CachedHttp, SourceUnavailable
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
    router.get(f"{SL}/players/nfl/trending/add").mock(
        return_value=httpx.Response(200, json=load_json("sleeper_trending_add.json"))
    )
    router.get(f"{SL}/players/nfl/trending/drop").mock(return_value=httpx.Response(200, json=[]))
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
    assert set(body["grades"]) == {"QB", "RB", "WR", "TE", "K", "DEF", "FLEX", "SFLEX"}
    assert not set(body["needs"]) & {"K", "DEF", "FLEX", "SFLEX"}
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
    r = tc.get("/team/does-not-exist")
    assert r.status_code == 404 and r.json()["kind"] == "team", r.text
    r = tc.post("/league/connect", json={"username": "ghost"})
    assert r.status_code == 404 and "not found" in r.json()["detail"], r.text
    assert r.json()["kind"] == "user"


def test_internal_key_error_is_a_500_not_a_404(client, monkeypatch):
    tc, _ = client
    team_id = connect_and_pick(tc)

    def broken(ctx, team_id):
        return {}["missing"]

    monkeypatch.setattr(views, "team_view", broken)
    with TestClient(app, raise_server_exceptions=False) as raw:
        assert raw.get(f"/team/{team_id}").status_code == 500


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
    assert any(d.startswith("trending: ") for d in r.json()["detail"])  # Update refreshes them too
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


def test_manual_roster_with_bench_and_ir(client):
    tc, _ = client
    by_pos: dict[str, list[str]] = {}
    for p in tc.get("/players", params={"limit": 100}).json():
        by_pos.setdefault(p["position"], []).append(p["player_id"])
    starters = [by_pos["QB"][0], *by_pos["RB"][:2], *by_pos["WR"][:3], by_pos["TE"][0]]
    bench = [by_pos["QB"][1], by_pos["RB"][2], by_pos["WR"][3]]
    ir = [by_pos["RB"][3]]
    lineup = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "BN", "BN", "BN", "IR"]  # 3-deep bench
    body = {
        "name": "Deep Bench",
        "roster_positions": lineup,
        "player_ids": starters + bench + ir,
        "starters": starters,
        "ir": ir,
    }
    r = tc.post("/league/manual", json=body)
    assert r.status_code == 200, r.text
    team = tc.get(f"/team/{r.json()['team_id']}").json()
    slot = {p["player_id"]: p["slot"] for p in team["roster"]}
    assert all(slot[p] == "starter" for p in starters)
    assert all(slot[p] == "bench" for p in bench)
    assert slot[ir[0]] == "ir"
    advice = tc.get(f"/team/{r.json()['team_id']}/advice").json()
    assert not any("Mark your starters" in n for n in advice["notes"])

    # one more bench player than the league allows → 422 with a clear message
    too_many = body | {"player_ids": body["player_ids"] + [by_pos["WR"][4]]}
    r = tc.post("/league/manual", json=too_many)
    assert r.status_code == 422 and "bench" in r.json()["detail"]


def _manual_team(tc, name="Editable"):
    by_pos: dict[str, list[str]] = {}
    for p in tc.get("/players", params={"limit": 100}).json():
        by_pos.setdefault(p["position"], []).append(p["player_id"])
    starters = [
        by_pos["QB"][0],
        *by_pos["RB"][:2],
        *by_pos["WR"][:2],
        by_pos["TE"][0],
        by_pos["WR"][2],
    ]
    body = {
        "name": name,
        "num_teams": 10,
        "roster_positions": ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "BN", "BN"],
        "player_ids": [*starters, by_pos["RB"][2], by_pos["WR"][3]],
        "starters": starters,
    }
    r = tc.post("/league/manual", json=body)
    assert r.status_code == 200, r.text
    return r.json()["team_id"], body, by_pos


def test_manual_grades_use_simulated_league(client):
    tc, _ = client
    team_id, _, _ = _manual_team(tc)
    team = tc.get(f"/team/{team_id}").json()
    assert "simulated 10-team league" in team["grade_basis"]
    assert team["overall_grade"]["teams"] == 10
    assert all(g["teams"] == 10 for g in team["grades"].values())
    # a team built from the top of the player pool should not grade as "average everywhere"
    assert {g["grade"] for g in team["grades"].values()} != {"C"}


def test_edit_manual_team(client):
    tc, _ = client
    team_id, body, by_pos = _manual_team(tc)
    edited = body | {
        "name": "Renamed",
        "scoring": "ppr",
        "roster_positions": body["roster_positions"] + ["BN", "IR"],  # deeper bench + IR
        "player_ids": [*body["player_ids"], by_pos["TE"][1], by_pos["RB"][3]],
        "ir": [by_pos["RB"][3]],
    }
    r = tc.put(f"/team/{team_id}/roster", json=edited)
    assert r.status_code == 200, r.text
    team = tc.get(f"/team/{team_id}").json()
    assert team["team_name"] == "Renamed"
    assert team["league"]["scoring_preset"] == "ppr"
    assert team["league"]["roster_positions"].count("BN") == 3
    slots = {p["player_id"]: p["slot"] for p in team["roster"]}
    assert slots[by_pos["RB"][3]] == "ir" and slots[by_pos["TE"][1]] == "bench"

    # invalid edit is rejected and leaves the team unchanged
    bad = edited | {"roster_positions": ["QB", "RB", "BN"]}
    assert tc.put(f"/team/{team_id}/roster", json=bad).status_code == 422
    assert tc.get(f"/team/{team_id}").json()["team_name"] == "Renamed"


def test_cannot_edit_sleeper_team(client):
    tc, _ = client
    team_id = connect_and_pick(tc)
    body = {"player_ids": ["x"], "roster_positions": ["QB"]}
    r = tc.put(f"/team/{team_id}/roster", json=body)
    assert r.status_code == 422 and "Sleeper" in r.json()["detail"]


def test_hypothetical_trade_for_manual_team(client):
    tc, _ = client
    team_id, body, by_pos = _manual_team(tc)
    give = [body["starters"][-1]]  # a WR
    receive = [by_pos["WR"][6]]  # not on any roster
    r = tc.post("/trade/evaluate", json={"team_id": team_id, "give": give, "receive": receive})
    assert r.status_code == 200, r.text
    ev = r.json()
    assert ev["partner"] is None
    assert ev["me"]["gives"][0]["player_id"] == give[0]
    assert any("hypothetical" in reason for reason in ev["reasons"])
    # receiving a player you already have is rejected
    r = tc.post(
        "/trade/evaluate", json={"team_id": team_id, "give": give, "receive": [body["starters"][0]]}
    )
    assert r.status_code == 422


def _counts(con, league_id: str) -> tuple[int, int]:
    teams = con.execute("SELECT count(*) FROM teams WHERE league_id = ?", [league_id]).fetchone()
    spots = con.execute(
        "SELECT count(*) FROM roster_spots JOIN teams USING (team_id) WHERE league_id = ?",
        [league_id],
    ).fetchone()
    return teams[0], spots[0]


def test_failed_league_sync_keeps_previous_rosters(client, monkeypatch):
    tc, _ = client
    connect_and_pick(tc)
    league_id = f"sl-{LEAGUE}"
    con = deps._con
    before = _counts(con, league_id)
    assert before[0] == 4 and before[1] > 0

    real_upsert = leagues.upsert

    def failing_upsert(con, table, df):
        if table == "roster_spots":
            raise RuntimeError("disk full")
        return real_upsert(con, table, df)

    monkeypatch.setattr(leagues, "upsert", failing_upsert)
    with TestClient(app, raise_server_exceptions=False) as raw:
        r = raw.post("/refresh", json={"scope": "league", "league_id": league_id})
    assert r.status_code == 500
    assert _counts(con, league_id) == before


def test_failed_players_sync_keeps_previous_players(client, monkeypatch):
    con = deps._con
    before = con.execute("SELECT count(*) FROM players").fetchone()[0]
    real = run_jobs.idmap.attach_internal_ids

    def broken_ids(players, id_map):  # NOT NULL violation on insert, after the delete ran
        return real(players, id_map).with_columns(pl.lit(None, pl.Utf8).alias("full_name"))

    monkeypatch.setattr(run_jobs.idmap, "attach_internal_ids", broken_ids)
    with pytest.raises(Exception, match="NOT NULL"):
        players_sync(con, deps._clients)
    assert con.execute("SELECT count(*) FROM players").fetchone()[0] == before


def test_dynasty_league_uses_dynasty_market_values(client):
    tc, router = client
    raw = load_json("sleeper_league.json")
    raw["settings"]["type"] = 2
    router.get(f"{SL}/league/{LEAGUE}").mock(return_value=httpx.Response(200, json=raw))
    leagues_raw = load_json("sleeper_leagues.json")
    for lg in leagues_raw:
        lg.setdefault("settings", {})["type"] = 2
    router.get(url__regex=rf"{SL}/user/u0/leagues/nfl/\d+").mock(
        return_value=httpx.Response(200, json=leagues_raw)
    )
    team_id = connect_and_pick(tc)
    league_id = f"sl-{LEAGUE}"
    assert context.load_league(deps._con, league_id).market_format.is_dynasty
    r = tc.post("/refresh", json={"scope": "market", "league_id": league_id})
    assert r.status_code == 200, r.text
    assert any("dynasty_" in d for d in r.json()["detail"]), r.json()
    assert tc.get(f"/team/{team_id}").status_code == 200


def test_manual_league_playoff_start(client):
    tc, _ = client
    team_id, body, _ = _manual_team(tc)
    assert tc.get(f"/team/{team_id}").json()["league"]["playoff_week_start"] == 15
    r = tc.put(f"/team/{team_id}/roster", json=body | {"playoff_week_start": 14})
    assert r.status_code == 200, r.text
    assert tc.get(f"/team/{team_id}").json()["league"]["playoff_week_start"] == 14
    assert tc.get(f"/team/{team_id}/advice").status_code == 200


def test_unknown_rostered_player_stays_visible(client):
    tc, router = client
    rosters = load_json("sleeper_rosters.json")
    mine = next(r for r in rosters if r["owner_id"] == "u0")
    mine["players"].append("99999999")  # not in the players table → no projection
    router.get(f"{SL}/league/{LEAGUE}/rosters").mock(return_value=httpx.Response(200, json=rosters))
    team_id = connect_and_pick(tc)
    roster = tc.get(f"/team/{team_id}").json()["roster"]
    ghost = next(p for p in roster if p["player_id"] == "sl:99999999")
    assert "Unknown player" in ghost["name"] and ghost["ppg"] == 0
    for path in ("advice", "byes", "regression"):
        assert tc.get(f"/team/{team_id}/{path}").status_code == 200, path
    assert tc.get("/trade/suggest", params={"team_id": team_id}).status_code == 200
    r = tc.post(
        "/trade/evaluate",
        json={"team_id": team_id, "give": ["sl:99999999"], "receive": []},
    )
    assert r.status_code == 200, r.text


def test_connect_lists_leagues_without_full_sync(client):
    tc, router = client
    r = tc.post("/league/connect", json={"username": "alphamanager"})
    assert r.status_code == 200, r.text
    lg = r.json()["leagues"][0]
    assert len(lg["teams"]) == 4 and any(t["is_user"] for t in lg["teams"])
    con = deps._con
    assert _counts(con, lg["league_id"]) == (0, 0)
    assert con.execute("SELECT count(*) FROM market_values").fetchone()[0] == 0
    tx = [c for c in router.calls if "/transactions/" in str(c.request.url)]
    assert tx == []

    mine = next(t for t in lg["teams"] if t["is_user"])
    r = tc.post(
        f"/league/{lg['league_id']}/select-team",
        json={"external_roster_id": mine["external_roster_id"]},
    )
    assert r.status_code == 200, r.text
    teams, spots = _counts(con, lg["league_id"])
    assert teams == 4 and spots > 0
    assert con.execute("SELECT count(*) FROM market_values").fetchone()[0] > 0
    # picking again right away doesn't re-sync
    n_calls = len(router.calls)
    tc.post(
        f"/league/{lg['league_id']}/select-team",
        json={"external_roster_id": mine["external_roster_id"]},
    )
    assert len(router.calls) == n_calls


def test_rankings_every_position_by_week_and_rest_of_season(client):
    tc, _ = client
    team_id = connect_and_pick(tc)
    r = tc.get(f"/team/{team_id}/rankings")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["weeks"] == list(range(body["week"], body["last_week"] + 1))
    assert set(body["positions"]) == {"QB", "RB", "WR", "TE", "K", "DEF"}
    wr = body["positions"]["WR"]
    assert 0 < len(wr["ros"]) <= 10
    assert [x["rank"] for x in wr["ros"]] == list(range(1, len(wr["ros"]) + 1))
    pts = [x["points"] for x in wr["ros"]]
    assert pts == sorted(pts, reverse=True)
    assert [w["week"] for w in wr["weekly"]] == body["weeks"]
    owners = {x["owner"] for p in body["positions"].values() for x in p["ros"]}
    assert "Free agent" in owners or any(o and o != "Free agent" for o in owners)
    mine = [x for p in body["positions"].values() for x in p["ros"] if x["mine"]]
    assert all(x["owner"] == "Your team" for x in mine)


def test_one_verdict_per_player_everywhere(client):
    tc, _ = client
    team_id = connect_and_pick(tc)
    roster = {p["player_id"]: p["signal"] for p in tc.get(f"/team/{team_id}").json()["roster"]}
    reg = tc.get(f"/team/{team_id}/regression").json()
    for row in reg["roster"]:
        assert row["signal"] == roster[row["player"]["player_id"]]
    for pos in tc.get(f"/team/{team_id}/rankings").json()["positions"].values():
        for row in pos["ros"]:
            if row["player_id"] in roster:
                assert row["signal"] == roster[row["player_id"]]
    buy = tc.get(f"/team/{team_id}/buy-targets").json()
    for pos in buy["positions"].values():
        assert all(r["signal"] == "buy" and not r["mine"] for r in pos["buy"])
        assert all(r["signal"] == "sell" and r["mine"] for r in pos["sell"])
        tiers = [r["tier"] for r in pos["buy"]]
        assert tiers == sorted(tiers, key=["starter", "depth"].index)  # starters first
        for tier in ("starter", "depth"):
            pts = [r["model_points"] for r in pos["buy"] if r["tier"] == tier]
            assert pts == sorted(pts, reverse=True)
        line = pos["starter_line"]
        assert all(
            (r["tier"] == "starter") == (line is not None and r["model_rank"] < line)
            for r in pos["buy"]
        )
    advice = tc.get(f"/team/{team_id}/advice").json()["actions"]
    sold = {pl["player_id"] for a in advice if a["type"] == "Sell" for pl in a["players"]}
    assert all(roster[pid] == "sell" for pid in sold)


def test_player_page_projects_each_played_week_before_it_happened(client):
    tc, _ = client
    team_id = connect_and_pick(tc)
    roster = tc.get(f"/team/{team_id}").json()["roster"]
    rb = max((p for p in roster if p["position"] == "RB"), key=lambda p: p["ppg"])
    r = tc.get(f"/team/{team_id}/players/{rb['player_id']}")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["name"] == rb["name"] and d["signal"] == rb["signal"] and d["mine"]
    assert d["statline_keys"][:3] == ["carries", "rush_yds", "rush_td"]
    played = [w for w in d["weeks"] if w["played"]]
    assert played and all(w["actual"] is not None for w in played)
    assert all(w["projected"] is not None for w in played if w["week"] > 1)
    assert "rush_yds" in played[0]["statline"]
    week = tc.get(f"/team/{team_id}").json()["league"]["week"]
    assert d["upcoming"][0]["week"] == week
    assert d["headshot_url"] is None or d["headshot_url"].startswith("https://sleepercdn.com/")
    assert tc.get(f"/team/{team_id}/players/nobody").json()["kind"] == "player"
    a = d["analytics"]
    assert a["windows"][-1]["label"] == "Season" and a["windows"][-1]["games"] == len(played)
    assert "rush_share" in a["windows"][-1]["metrics"]


def test_past_projection_ignores_the_week_itself(client, monkeypatch):
    from app.services import player as player_svc

    tc, _ = client
    connect_and_pick(tc)
    ctx = context.get_context(deps._con, f"sl-{LEAGUE}")
    before = player_svc.past_projections(ctx)
    w = max(before)
    # blow up every stat line in week w: projections *for* week w must not move
    ctx.memo.pop("past_projections")
    ctx.stats = ctx.stats.with_columns(
        pl.when((pl.col("season") == ctx.season) & (pl.col("week") >= w))
        .then(pl.col("fp") * 10)
        .otherwise(pl.col("fp"))
        .alias("fp")
    )
    after = player_svc.past_projections(ctx)
    assert after[w] == before[w]


def test_best_lineup_leaves_out_players_on_bye(client):
    """My Team's best lineup is this week's: a starter whose team is on bye drops out of it."""
    tc, _ = client
    team_id = connect_and_pick(tc)
    before = tc.get(f"/team/{team_id}").json()
    star = next(p for p in before["roster"] if p["optimal_starter"] and p["nfl_team"])
    assert not star["on_bye"]
    ctx = context.get_context(deps._con, f"sl-{LEAGUE}")
    # put his team on bye this week (drop its game), then rebuild the view from the same context
    games = {k: v for k, v in ctx.schedule.games.items() if k != (star["nfl_team"], ctx.week)}
    ctx.schedule = dataclasses.replace(ctx.schedule, games=games)
    ctx.memo.clear()
    after = views.team_view(ctx, team_id)
    row = next(p for p in after.roster if p.player_id == star["player_id"])
    assert row.on_bye and not row.optimal_starter
    assert all(not (p.on_bye and p.optimal_starter) for p in after.roster)


def test_trade_idea_pages_and_finder(client):
    tc, _ = client
    team_id = connect_and_pick(tc)
    first = tc.get("/trade/suggest", params={"team_id": team_id}).json()
    assert first["page"] == 0
    for idea in first["ideas"]:
        for side in (idea["me"], idea["partner"]):
            assert side["new_short_weeks"] == []  # never leaves either team short
            assert len(side["weekly"]) > 0
        assert idea["partner_accepts"] is True
    if first["has_more"]:
        second = tc.get("/trade/suggest", params={"team_id": team_id, "page": 1}).json()
        shown = {(i["headline"], i["partner"]["team_id"]) for i in first["ideas"]}
        assert not shown & {(i["headline"], i["partner"]["team_id"]) for i in second["ideas"]}

    team = tc.get(f"/team/{team_id}").json()
    give = [p["player_id"] for p in team["roster"] if p["position"] == "WR"][:2]
    r = tc.post(
        "/trade/find",
        json={"team_id": team_id, "give": give, "want_position": "RB", "receive_count": 1},
    )
    assert r.status_code == 200, r.text
    found = r.json()
    assert found["searched_teams"] == 3
    for idea in found["ideas"]:
        assert [p["player_id"] for p in idea["me"]["gives"]] == give
        assert all(p["position"] == "RB" for p in idea["me"]["receives"])
        assert idea["me"]["lineup_delta"] > 0
        assert idea["partner_accepts"] in (True, False)
    bad = tc.post("/trade/find", json={"team_id": team_id, "give": [], "want_position": "RB"})
    assert bad.status_code == 422


def test_trades_for_one_player(client):
    tc, _ = client
    team_id = connect_and_pick(tc)
    team = tc.get(f"/team/{team_id}").json()
    mine = next(p for p in team["roster"] if p["position"] in ("RB", "WR"))
    other = next(t for t in team["league_teams"] if not t["is_mine"])
    theirs = next(
        p
        for p in tc.get(f"/team/{other['team_id']}").json()["roster"]
        if p["position"] in ("RB", "WR")
    )

    sell = tc.get(f"/team/{team_id}/players/{mine['player_id']}/trades").json()
    assert sell["mode"] == "sell" and sell["owner"] == team["team_name"]
    for idea in sell["ideas"]:
        assert [p["player_id"] for p in idea["me"]["gives"]] == [mine["player_id"]]
        assert idea["me"]["lineup_delta"] > 0
    wr_only = tc.get(f"/team/{team_id}/players/{mine['player_id']}/trades?want=WR").json()
    assert all(p["position"] == "WR" for i in wr_only["ideas"] for p in i["me"]["receives"])

    buy = tc.get(f"/team/{team_id}/players/{theirs['player_id']}/trades").json()
    assert buy["mode"] == "buy" and buy["owner"] == other["team_name"]
    for idea in buy["ideas"]:
        assert [p["player_id"] for p in idea["me"]["receives"]] == [theirs["player_id"]]
        assert idea["partner"]["team_id"] == other["team_id"]

    # release him from his team (in the cached league context): now nobody rosters him
    ctx = context.get_context(deps._con, f"sl-{LEAGUE}")
    holder = ctx.team(other["team_id"])
    fa = theirs["player_id"]
    holder.player_ids = [p for p in holder.player_ids if p != fa]
    ctx.memo.clear()
    free = tc.get(f"/team/{team_id}/players/{fa}/trades").json()
    assert free["mode"] == "free_agent" and free["ideas"] == [] and "waivers" in free["message"]

    assert tc.get(f"/team/{team_id}/players/nobody/trades").status_code == 404
    assert tc.get(f"/team/{team_id}/players/{fa}/trades?want=K").status_code == 422


def test_rankings_can_show_more_than_ten(client):
    tc, _ = client
    team_id = connect_and_pick(tc)
    ten = tc.get(f"/team/{team_id}/rankings").json()
    twenty = tc.get(f"/team/{team_id}/rankings", params={"top": 20}).json()
    assert ten["top"] == 10 and twenty["top"] == 20
    for pos, v in twenty["positions"].items():
        short = ten["positions"][pos]["ros"]
        assert len(short) <= 10 and len(v["ros"]) <= 20
        assert v["ros"][: len(short)] == short  # the first 10 are the same players, in order
        assert [r["rank"] for r in v["ros"]] == list(range(1, len(v["ros"]) + 1))
    assert any(len(v["ros"]) > 10 for v in twenty["positions"].values())
    assert tc.get(f"/team/{team_id}/rankings", params={"top": 500}).status_code == 422


def test_players_table_filters_sorts_and_pages(client):
    tc, _ = client
    team_id = connect_and_pick(tc)
    url = f"/team/{team_id}/players"
    # the fixture league rosters every fixture player: release one so there's a free agent
    ctx = context.get_context(deps._con, f"sl-{LEAGUE}")
    holder = next(t for t in ctx.teams if not t.is_mine)
    released = holder.player_ids.pop()
    ctx.memo.clear()
    everyone = tc.get(url, params={"size": 100}).json()
    assert everyone["total"] == 60 and len(everyone["rows"]) == 60
    ros = [r["ros_points"] for r in everyone["rows"]]
    assert ros == sorted(ros, reverse=True)  # default: rest-of-season points, best first

    # pages don't overlap and add up to the total
    a = tc.get(url, params={"size": 10, "page": 0}).json()["rows"]
    b = tc.get(url, params={"size": 10, "page": 1}).json()["rows"]
    assert not {r["player_id"] for r in a} & {r["player_id"] for r in b}

    mine = tc.get(url, params={"avail": "mine", "size": 100}).json()
    assert mine["rows"] and all(r["mine"] and r["owner"] == "Your team" for r in mine["rows"])
    other = tc.get(url, params={"avail": "other", "size": 100}).json()
    assert other["rows"] and all(
        not r["mine"] and r["owner"] not in (None, "Free agent") for r in other["rows"]
    )
    fa = tc.get(url, params={"avail": "fa", "size": 100}).json()
    assert [r["player_id"] for r in fa["rows"]] == [released]
    assert fa["rows"][0]["owner"] == "Free agent"
    assert mine["total"] + other["total"] + fa["total"] == everyone["total"]

    wr = tc.get(url, params={"pos": "WR", "sort": "ppg", "dir": "asc", "size": 100}).json()
    assert {r["position"] for r in wr["rows"]} == {"WR"}
    ppg = [r["ppg"] for r in wr["rows"]]
    assert ppg == sorted(ppg)

    team = everyone["rows"][0]["nfl_team"]
    assert team in everyone["nfl_teams"]
    by_team = tc.get(url, params={"team": team, "size": 100}).json()["rows"]
    assert by_team and {r["nfl_team"] for r in by_team} == {team}

    # market: players without a market value always sort last, either direction
    for d in ("asc", "desc"):
        rows = tc.get(url, params={"sort": "market", "dir": d, "size": 100}).json()["rows"]
        vals = [r["market_value"] for r in rows]
        seen_none = False
        for v in vals:
            seen_none = seen_none or v is None
            assert not (seen_none and v is not None)
        known = [v for v in vals if v is not None]
        assert known == sorted(known, reverse=d == "desc")

    verdict = tc.get(url, params={"sort": "verdict", "size": 100}).json()["rows"]
    order = [{"buy": 0, "hold": 1, "sell": 2}[r["signal"]] for r in verdict]
    assert order == sorted(order)

    for bad in ({"sort": "height"}, {"avail": "nobody"}, {"size": 500}, {"pos": "OL"}):
        assert tc.get(url, params=bad).status_code == 422


def test_players_table_search_ignores_case_and_accents(client):
    tc, _ = client
    team_id = connect_and_pick(tc)
    first = tc.get(f"/team/{team_id}/players", params={"size": 10}).json()["rows"][0]
    surname = first["name"].split()[-1]
    hits = tc.get(f"/team/{team_id}/players", params={"q": surname.upper()}).json()["rows"]
    assert first["player_id"] in {r["player_id"] for r in hits}
    assert views.fold("Amon-Ra St. Brown") == "amonra st brown"
    assert views.fold("Zoë Ñúñez") == "zoe nunez"


def test_players_table_for_a_manual_team(client):
    tc, _ = client
    team_id, _, _ = _manual_team(tc)
    rows = tc.get(f"/team/{team_id}/players", params={"avail": "mine"}).json()["rows"]
    assert rows and all(r["mine"] for r in rows)
    others = tc.get(f"/team/{team_id}/players", params={"avail": "fa", "size": 10}).json()["rows"]
    assert all(r["owner"] is None for r in others)  # a manual team can't know who's available


def _release(team_id: str, n: int) -> list[str]:
    """Drop `n` players (skill positions) from a team in the store, so they're free agents."""
    con = deps._con
    pids = [
        r[0]
        for r in con.execute(
            """SELECT r.player_id FROM roster_spots r JOIN players p USING (player_id)
               WHERE r.team_id = ? AND p.position IN ('RB', 'WR', 'TE', 'QB')
               ORDER BY r.player_id""",
            [team_id],
        ).fetchall()
    ][:n]
    con.execute(
        f"DELETE FROM roster_spots WHERE team_id = ? AND player_id IN ({','.join('?' * len(pids))})",
        [team_id, *pids],
    )
    context.invalidate()
    return pids


def test_waivers_rank_free_agents_with_drops_faab_and_trending(client):
    tc, _ = client
    team_id = connect_and_pick(tc)
    team = tc.get(f"/team/{team_id}").json()
    other = next(t for t in team["league_teams"] if not t["is_mine"])
    freed = _release(other["team_id"], 6)
    mine = team["roster"][0]["player_id"]
    theirs = next(
        p["player_id"]
        for p in tc.get(f"/team/{other['team_id']}").json()["roster"]
        if p["player_id"] not in freed
    )
    now = datetime.now()
    deps._con.executemany(
        "INSERT INTO trending VALUES (?, 'add', ?, 24, ?)",
        [(freed[0], 900, now), (mine, 500, now), (theirs, 100, now), ("nobody", 50, now)],
    )

    body = tc.get(f"/team/{team_id}/waivers").json()
    rows = body["rows"]
    assert rows, "freed players should help somebody's lineup"
    assert {r["player"]["player_id"] for r in rows} <= set(freed)
    gains = [r["gain"] for r in rows]
    assert gains == sorted(gains, reverse=True) and all(g > 0 for g in gains)
    assert [r["rank"] for r in rows] == list(range(1, len(rows) + 1))
    weeks = body["last_week"] - body["week"] + 1
    assert rows[0]["gain_per_week"] == pytest.approx(rows[0]["gain"] / weeks, abs=0.01)
    # the fixture league has a bench spot open (15 players, 16 spots): nobody has to go
    assert all(r["drop"] is None for r in rows)

    faab = body["faab"]
    assert faab["uses_faab"] and faab["budget"] == 100 and faab["remaining"] is not None
    for r in rows:
        b = r["faab"]
        assert faab["min_bid"] <= b["low"] <= b["bid"] <= b["high"] <= faab["remaining"]

    trend = {t["player"]["player_id"]: t for t in body["trending"]}
    assert list(trend) == [freed[0], mine, theirs]  # most added first; unknown players skipped
    assert trend[freed[0]]["owner"] == "Free agent"
    assert trend[mine]["mine"] and trend[mine]["owner"] == "Your team"
    assert trend[theirs]["owner"] == other["team_name"]
    assert body["trending_fetched_at"] is not None and body["message"] is None

    # the Advisor's waiver cards come from the same ranking
    picks = {r["player"]["player_id"] for r in rows}
    advice = tc.get(f"/team/{team_id}/advice").json()["actions"]
    assert all(a["players"][0]["player_id"] in picks for a in advice if a["type"] == "Waiver")

    # FAAB settings change the bids
    top = rows[0]["faab"]["bid"]
    assert tc.put("/settings", json={"faab_aggression": 1.0}).status_code == 200
    again = tc.get(f"/team/{team_id}/waivers").json()
    assert again["faab"]["aggression"] == 1.0
    assert again["rows"][0]["faab"]["bid"] >= top
    tc.delete("/settings")


def test_waivers_for_a_manual_team(client):
    tc, _ = client
    team_id, _, _ = _manual_team(tc)
    body = tc.get(f"/team/{team_id}/waivers").json()
    assert body["rows"] == [] and "Connect your Sleeper or ESPN league" in body["message"]
    assert not body["faab"]["uses_faab"] and body["faab"]["remaining"] is None


def test_startsit_agrees_with_my_team_and_the_advisor(client):
    tc, _ = client
    team_id = connect_and_pick(tc)
    plan = tc.get(f"/team/{team_id}/startsit").json()
    team = tc.get(f"/team/{team_id}").json()
    assert plan["week"] == team["league"]["week"] and plan["weeks"][0] == plan["week"]
    assert len(plan["current"]) == len(plan["optimal"]) == len(plan["slots"])
    assert plan["has_lineup"]
    slots = [s["slot"] for s in plan["slots"]]
    assert slots == [s for s in team["league"]["roster_positions"] if s not in ("BN", "IR", "TAXI")]
    flex = next(s for s in plan["slots"] if s["slot"] == "FLEX")
    assert flex["eligible"] == ["RB", "TE", "WR"] and flex["label"] == "FLEX"

    # the planner's best lineup is My Team's "best lineup", and the real lineup is the platform's
    best = {p for p in plan["optimal"] if p}
    assert best == {p["player_id"] for p in team["roster"] if p["optimal_starter"]}
    real = {p for p in plan["current"] if p}
    platform = {p["player_id"] for p in team["roster"] if p["slot"] == "starter"}
    # (the fixture's starters aren't a legal lineup: ones that fit no open slot sit on the bench)
    assert real and real <= platform
    points = {p["player"]["player_id"]: p["points"] for p in plan["players"]}
    assert plan["optimal_points"] == pytest.approx(sum(points[p] for p in best), abs=0.05)
    assert plan["gap"] == pytest.approx(plan["optimal_points"] - plan["current_points"], abs=0.01)
    assert plan["gap"] >= 0

    # every Advisor start/sit card starts someone from the best lineup over a real starter
    advice = tc.get(f"/team/{team_id}/advice").json()["actions"]
    for a in advice:
        if a["type"] == "Lineup":
            start, sit = (p["player_id"] for p in a["players"])
            assert start in best and sit in platform and sit not in best

    later = tc.get(f"/team/{team_id}/startsit", params={"week": plan["weeks"][-1]}).json()
    assert later["week"] == plan["weeks"][-1] and not any(p["locked"] for p in later["players"])
    assert tc.get(f"/team/{team_id}/startsit", params={"week": 1}).status_code == 422


def test_startsit_locks_players_whose_game_is_final(client):
    tc, _ = client
    team_id = connect_and_pick(tc)
    plan = tc.get(f"/team/{team_id}/startsit").json()
    ctx = context.get_context(deps._con, f"sl-{LEAGUE}")
    # a starter whose team plays this week (one on bye has no game to finish)
    starter = next(
        p
        for p in sorted(x for x in plan["current"] if x)
        if ctx.schedule.has_game(ctx.players[p]["nfl_team"], ctx.week)
    )
    nfl = ctx.players[starter]["nfl_team"]
    ctx.schedule = dataclasses.replace(
        ctx.schedule, completed=ctx.schedule.completed | {(nfl, ctx.week)}
    )
    ctx.memo.clear()
    plan = tc.get(f"/team/{team_id}/startsit").json()
    row = next(p for p in plan["players"] if p["player"]["player_id"] == starter)
    assert row["locked"] and row["points"] == 0
    i = plan["current"].index(starter)
    assert plan["optimal"][i] == starter  # already played: he keeps his slot
    team = tc.get(f"/team/{team_id}").json()
    assert next(p for p in team["roster"] if p["player_id"] == starter)["optimal_starter"]


def _free_agent_rb(tc, team_id):
    """Release the other team's best RB so he's on waivers; returns his id."""
    team = tc.get(f"/team/{team_id}").json()
    other = next(t for t in team["league_teams"] if not t["is_mine"])
    rb = max(
        (p for p in tc.get(f"/team/{other['team_id']}").json()["roster"] if p["position"] == "RB"),
        key=lambda p: p["ppg"],
    )["player_id"]
    deps._con.execute(
        "DELETE FROM roster_spots WHERE team_id = ? AND player_id = ?", [other["team_id"], rb]
    )
    context.invalidate()
    return rb


def test_a_torn_acl_ends_the_season_everywhere(client):
    tc, _ = client
    team_id = connect_and_pick(tc)
    rb = _free_agent_rb(tc, team_id)
    assert rb in {
        r["player"]["player_id"] for r in tc.get(f"/team/{team_id}/waivers").json()["rows"]
    }

    deps._con.execute(
        """UPDATE players SET injury_status = 'IR', injury_body_part = 'Knee - ACL',
           injury_notes = 'Surgery' WHERE player_id = ?""",
        [rb],
    )
    context.invalidate()
    detail = tc.get(f"/team/{team_id}/players/{rb}").json()
    assert detail["return_week"] == 99 and detail["availability_source"] == "rule"
    assert detail["availability_note"] == "Out for the season (Knee - ACL, surgery)"
    assert detail["injury_detail"] == "Knee - ACL, surgery"
    assert detail["model_ros_points"] in (None, 0)
    rows = tc.get(f"/team/{team_id}/waivers").json()["rows"]
    assert rb not in {r["player"]["player_id"] for r in rows}
    table = tc.get(f"/team/{team_id}/players", params={"q": detail["name"]}).json()["rows"]
    assert table[0]["return_week"] == 99 and table[0]["ros_points"] == 0


def test_your_availability_what_if_round_trip(client):
    tc, _ = client
    team_id = connect_and_pick(tc)
    rb = _free_agent_rb(tc, team_id)
    week = tc.get(f"/team/{team_id}").json()["league"]["week"]
    before = next(
        r
        for r in tc.get(f"/team/{team_id}/waivers").json()["rows"]
        if r["player"]["player_id"] == rb
    )

    later = week + 4
    r = tc.put(f"/players/{rb}/availability", json={"return_week": later})
    assert r.status_code == 200 and r.json() == {
        "player_id": rb,
        "out_for_season": False,
        "return_week": later,
    }
    row = next(
        r
        for r in tc.get(f"/team/{team_id}/waivers").json()["rows"]
        if r["player"]["player_id"] == rb
    )
    assert row["return_week"] == later and row["gain"] < before["gain"]
    detail = tc.get(f"/team/{team_id}/players/{rb}").json()
    assert detail["availability_source"] == "override" and detail["override_return_week"] == later
    assert detail["availability_note"] == f"Out until week {later} (your what-if)"

    assert tc.put(f"/players/{rb}/availability", json={"out_for_season": True}).status_code == 200
    rows = tc.get(f"/team/{team_id}/waivers").json()["rows"]
    assert rb not in {r["player"]["player_id"] for r in rows}
    assert tc.get(f"/team/{team_id}/players/{rb}").json()["override_out_for_season"]

    assert tc.delete(f"/players/{rb}/availability").status_code == 200
    again = next(
        r
        for r in tc.get(f"/team/{team_id}/waivers").json()["rows"]
        if r["player"]["player_id"] == rb
    )
    assert again["gain"] == before["gain"] and again["return_week"] is None

    assert tc.put(f"/players/{rb}/availability", json={"return_week": week}).status_code == 422
    assert tc.put(f"/players/{rb}/availability", json={}).status_code == 422
    assert tc.put(f"/players/{rb}/availability", json={"return_week": 30}).status_code == 422
    assert tc.put("/players/nobody/availability", json={"out_for_season": True}).status_code == 404


def test_saved_teams_rename_and_forget(client):
    tc, _ = client
    sleeper_team = connect_and_pick(tc)
    manual_team, _, _ = _manual_team(tc, name="Bench Mob")
    saved = {t["team_id"]: t for t in tc.get("/teams/saved").json()}
    assert set(saved) == {sleeper_team, manual_team}  # only the teams you picked, not rivals
    assert saved[sleeper_team]["platform"] == "sleeper" and not saved[sleeper_team]["has_login"]
    assert saved[manual_team]["team_name"] == "Bench Mob"

    # rename: manual teams only (platform names come from Sleeper/ESPN)
    r = tc.patch(f"/team/{manual_team}", json={"name": "  Waiver Wire Kings "})
    assert r.status_code == 200
    assert tc.get(f"/team/{manual_team}").json()["team_name"] == "Waiver Wire Kings"
    r = tc.patch(f"/team/{sleeper_team}", json={"name": "Nope"})
    assert r.status_code == 422 and "Sleeper" in r.json()["detail"]
    assert tc.patch(f"/team/{manual_team}", json={"name": ""}).status_code == 422

    # forget the Sleeper league: every team, roster and saved login goes, nothing else
    league_id = f"sl-{LEAGUE}"
    deps._con.execute(
        "INSERT INTO league_credentials VALUES (?, 's2', '{SWID}', now())", [league_id]
    )
    assert {t["team_id"]: t for t in tc.get("/teams/saved").json()}[sleeper_team]["has_login"]
    r = tc.delete(f"/team/{sleeper_team}")
    assert r.status_code == 200
    assert r.json() == {"league_id": league_id, "platform": "sleeper", "teams_removed": 4}
    con = deps._con
    for table in ("leagues", "teams", "transactions", "league_credentials"):
        n = con.execute(f"SELECT count(*) FROM {table} WHERE league_id = ?", [league_id]).fetchone()
        assert n[0] == 0, table
    assert _counts(con, league_id) == (0, 0)
    assert [t["team_id"] for t in tc.get("/teams/saved").json()] == [manual_team]
    assert tc.get(f"/team/{sleeper_team}").status_code == 404
    assert con.execute("SELECT count(*) FROM players").fetchone()[0] > 0  # shared data stays

    # delete the manual team
    assert tc.delete(f"/team/{manual_team}").json()["platform"] == "manual"
    assert tc.get("/teams/saved").json() == []
    assert tc.delete(f"/team/{manual_team}").status_code == 404


def test_loading_a_team_refreshes_a_stale_roster(client, monkeypatch):
    tc, _ = client
    team_id = connect_and_pick(tc)
    league_id = f"sl-{LEAGUE}"
    con = deps._con
    con.execute(
        "UPDATE leagues SET last_synced_at = now() - INTERVAL 2 HOUR WHERE league_id = ?",
        [league_id],
    )
    old = con.execute(
        "SELECT last_synced_at FROM leagues WHERE league_id = ?", [league_id]
    ).fetchone()
    assert tc.get(f"/team/{team_id}").status_code == 200
    new = con.execute(
        "SELECT last_synced_at FROM leagues WHERE league_id = ?", [league_id]
    ).fetchone()
    assert new[0] > old[0]  # re-pulled from Sleeper on load

    # Sleeper down: the page still loads from the cached rosters
    con.execute(
        "UPDATE leagues SET last_synced_at = now() - INTERVAL 2 HOUR WHERE league_id = ?",
        [league_id],
    )

    def down(*a, **k):
        raise SourceUnavailable("sleeper", "503 from upstream", 503)

    monkeypatch.setattr(leagues, "sync_sleeper_league", down)
    r = tc.get(f"/team/{team_id}")
    assert r.status_code == 200 and len(r.json()["roster"]) >= 14


def test_regression_report_strongest_flags_first(client):
    tc, _ = client
    team_id = connect_and_pick(tc)
    reg = tc.get(f"/team/{team_id}/regression").json()
    rows = [r for r in reg["roster"] + reg["league"] if r["flags"]]
    assert rows, "the fixture season should flag someone"
    for r in rows:
        sizes = [f["size"] for f in r["flags"]]
        assert all(s >= 0.99 for s in sizes)  # a flag only fires past its threshold
        assert r["strength"] == max(sizes)
        top = max(r["flags"], key=lambda f: f["size"])
        assert r["direction"] == top["direction"] in (1, -1)
    strengths = [r["strength"] for r in reg["league"]]
    assert strengths == sorted(strengths, reverse=True)


def _one_for_two(tc, team_id):
    """Give one of our RB/WRs for two of another team's."""
    team = tc.get(f"/team/{team_id}").json()
    mine = [p["player_id"] for p in team["roster"] if p["position"] in ("RB", "WR")]
    other = next(t for t in team["league_teams"] if not t["is_mine"])
    theirs = [
        p["player_id"]
        for p in tc.get(f"/team/{other['team_id']}").json()["roster"]
        if p["position"] in ("RB", "WR")
    ][:2]
    r = tc.post("/trade/evaluate", json={"team_id": team_id, "give": mine[:1], "receive": theirs})
    assert r.status_code == 200, r.text
    return r.json()


def test_drops_come_with_reasons(client):
    tc, router = client
    # our roster is full (16 of 16 active spots): move one of u3's bench receivers to us
    rosters = load_json("sleeper_rosters.json")
    mine = next(r for r in rosters if r["owner_id"] == "u0")
    donor = next(r for r in rosters if r["owner_id"] == "u3")
    donor["players"].remove("7525")
    mine["players"].append("7525")
    router.get(f"{SL}/league/{LEAGUE}/rosters").mock(return_value=httpx.Response(200, json=rosters))
    team_id = connect_and_pick(tc)
    assert len(tc.get(f"/team/{team_id}").json()["roster"]) == 16
    # a 1-for-2 puts us one over the limit: exactly one of ours has to go, with a reason
    trade = _one_for_two(tc, team_id)
    side = trade["me"]
    assert "drops" in side
    assert len(side["drops"]) == 1 and len(side["drop_reasons"]) == 1
    (dropped,), (why,) = side["drops"], side["drop_reasons"]
    assert isinstance(why, str) and why
    assert any(f"drop {dropped['name']} ({why})" in r for r in trade["reasons"])


def test_a_roster_with_room_drops_nobody(client):
    tc, _ = client
    team_id = connect_and_pick(tc)
    # 15 of 16 spots: a 1-for-2 fills the last one, so nobody has to go
    assert len(tc.get(f"/team/{team_id}").json()["roster"]) == 15
    trade = _one_for_two(tc, team_id)
    assert trade["me"]["drops"] == [] and trade["me"]["drop_reasons"] == []
    assert not any("to make room" in r for r in trade["reasons"])
