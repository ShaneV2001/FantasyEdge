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
from app.services import context, leagues, views
from db.conn import connect, upsert
from ingest import run as run_jobs
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
        gaps = [r["value_gap"] for r in pos["buy"]]
        assert gaps == sorted(gaps, reverse=True)
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
