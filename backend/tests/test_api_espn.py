"""ESPN leagues end to end: connect (private and public), pick a team, every page, Update, and
expired / missing login cookies. ESPN is mocked with a scrubbed recording of a real league."""

from __future__ import annotations

import httpx
import pytest

from app.services import context
from tests.conftest import load_json
from tests.test_api import client  # noqa: F401  (fixture)

ESPN = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/2026/segments/0/leagues/12345678"
S2 = "AEB" + "s" * 200 + "9f3a"
SWID = "{00000000-0000-4000-8000-000000000010}"  # the fixture's owner of Team 1
LEAGUE = "es-12345678-2026"


@pytest.fixture
def espn(client):  # noqa: F811
    tc, router = client
    route = router.get(url__startswith=ESPN)
    route.mock(return_value=httpx.Response(200, json=load_json("espn_league.json")))
    return tc, route


def connect(tc, **cookies):
    return tc.post(
        "/league/espn/connect", json={"league_id": "12345678", "season": 2026, **cookies}
    )


def test_connect_private_league_and_use_every_page(espn):
    tc, route = espn
    r = connect(tc, espn_s2=S2, swid=SWID)
    assert r.status_code == 200, r.text
    d = r.json()
    lg = d["league"]
    assert lg["league_id"] == LEAGUE and lg["num_teams"] == 10 and lg["scoring"] == "PPR"
    assert [t["team_name"] for t in lg["teams"] if t["is_user"]] == ["Team 1"]  # found by SWID
    assert d["credentials"] == {
        "saved": True,
        "espn_s2_last4": "9f3a",
        "swid_last4": "0010",
        "updated_at": d["credentials"]["updated_at"],
    }
    assert S2 not in r.text  # the cookie itself never comes back
    assert "1-point safety" in d["scoring_notes"]
    sent = route.calls.last.request.headers["cookie"]
    assert S2 in sent and SWID in sent

    r = tc.post(f"/league/{LEAGUE}/select-team", json={"external_roster_id": "1"})
    assert r.status_code == 200, r.text
    team_id = r.json()["team_id"]
    team = tc.get(f"/team/{team_id}").json()
    assert team["league"]["platform"] == "espn" and team["league"]["playoff_week_start"] == 15
    assert team["league"]["trade_deadline_week"] is not None
    assert len(team["roster"]) == 17
    for path in ("advice", "byes", "rankings", "buy-targets", "regression"):
        assert tc.get(f"/team/{team_id}/{path}").status_code == 200, path
    assert tc.get(f"/trade/suggest?team_id={team_id}").status_code == 200

    r = tc.post("/refresh", json={"scope": "league", "league_id": LEAGUE})
    assert r.status_code == 200 and "ESPN rosters synced" in r.json()["detail"][0]


def test_unmatched_players_are_listed_and_kept(espn):
    tc, _ = espn
    d = connect(tc, espn_s2=S2, swid=SWID).json()
    total = sum(len(t["roster"]["entries"]) for t in load_json("espn_league.json")["teams"])
    team = tc.get(f"/team/{LEAGUE}-2").json()
    assert team["roster"]  # every rostered player shows up, matched or not
    names = {p["name"] for p in team["roster"]}
    assert {u["name"] for u in d["unmatched"]} & names or not d["unmatched"]
    assert len(d["unmatched"]) < total


def test_expired_cookies(espn):
    tc, route = espn
    assert connect(tc, espn_s2=S2, swid=SWID).status_code == 200
    route.mock(return_value=httpx.Response(401, json={"messages": ["You are not authorized"]}))
    context.invalidate()
    r = tc.post("/refresh", json={"scope": "league", "league_id": LEAGUE})
    assert r.status_code == 401
    assert r.json()["kind"] == "espn_auth" and "expired" in r.json()["detail"]
    r = tc.put(
        f"/league/{LEAGUE}/credentials", json={"espn_s2": "A" * 40, "swid": "{BAD-SWID-0000}"}
    )
    assert r.status_code == 401  # bad replacement cookies aren't saved
    assert tc.get(f"/league/{LEAGUE}/credentials").json()["espn_s2_last4"] == "9f3a"

    route.mock(return_value=httpx.Response(200, json=load_json("espn_league.json")))
    r = tc.put(f"/league/{LEAGUE}/credentials", json={"espn_s2": "B" * 40 + "new1", "swid": SWID})
    assert r.status_code == 200 and r.json()["espn_s2_last4"] == "new1"


def test_private_league_without_cookies(espn):
    tc, route = espn
    route.mock(return_value=httpx.Response(401, json={"messages": ["not authorized"]}))
    r = connect(tc)
    assert r.status_code == 401 and r.json()["kind"] == "espn_private"


def test_public_league_needs_no_cookies(espn):
    tc, route = espn
    r = connect(tc)
    assert r.status_code == 200
    assert "cookie" not in route.calls.last.request.headers
    assert r.json()["credentials"]["saved"] is False


def test_bad_inputs(espn):
    tc, _ = espn
    assert tc.post("/league/espn/connect", json={"league_id": "abc"}).status_code == 422
    assert connect(tc, espn_s2=S2).status_code == 422  # one cookie without the other
    assert tc.get("/league/espn/defaults").json()["cookies_in_env"] is False
