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


def _first_skill_player(team: dict) -> int:
    return next(e["playerId"] for e in team["roster"]["entries"] if e["playerId"] > 0)


def test_pending_trade_shows_until_espn_processes_it(client):  # noqa: F811
    """An accepted trade waiting on league review is listed with the lineups it leads to; once
    ESPN moves the players, it is just the roster."""
    tc, router = client
    league = load_json("espn_league.json")
    league["settings"]["tradeSettings"]["revisionHours"] = 24
    t1, t2 = league["teams"][0], league["teams"][1]
    mine, theirs = _first_skill_player(t1), _first_skill_player(t2)
    txns = [
        {"id": "p1", "type": "TRADE_PROPOSAL", "status": "PENDING", "proposedDate": 1_790_000_000_000,
         "items": [{"type": "TRADE", "playerId": mine, "fromTeamId": 1, "toTeamId": 2},
                   {"type": "TRADE", "playerId": theirs, "fromTeamId": 2, "toTeamId": 1}]},
        {"id": "a1", "type": "TRADE_ACCEPT", "relatedTransactionId": "p1", "proposedDate": 1_790_000_100_000},
    ]  # fmt: skip

    def answer(request: httpx.Request) -> httpx.Response:
        if "mTransactions2" in request.url.params.get_list("view"):
            return httpx.Response(200, json={"transactions": txns})
        return httpx.Response(200, json=league)

    router.get(url__startswith=ESPN).mock(side_effect=answer)
    assert connect(tc, espn_s2=S2, swid=SWID).status_code == 200
    team_id = f"{LEAGUE}-1"

    d = tc.get(f"/team/{team_id}/pending-trades").json()
    assert d["review_hours"] == 24
    (trade,) = d["trades"]
    assert trade["partner_team_id"] == f"{LEAGUE}-2" and trade["partner_name"]
    give, get = trade["give"][0]["player_id"], trade["receive"][0]["player_id"]
    me = d["outlook"]["me"]
    assert [p["player_id"] for p in me["gives"]] == [give]
    assert [p["player_id"] for p in me["receives"]] == [get]
    assert len(me["before"]) == len(me["after"]) > 0
    after_players = {
        c["player"]["player_id"] for w in me["after"] for c in w["cells"] if c["player"]
    }
    assert give not in after_players
    # the partner's side isn't shown for a pending trade, and the other team sees it too
    assert d["outlook"]["partner"] is None
    assert len(tc.get(f"/team/{LEAGUE}-2/pending-trades").json()["trades"]) == 1
    assert tc.get(f"/team/{LEAGUE}-3/pending-trades").json() == {
        "team_id": f"{LEAGUE}-3", "review_hours": 24, "trades": [], "outlook": None,
    }  # fmt: skip

    # ESPN processes it: the players move, the feed may still say PENDING for a while
    e1 = next(e for e in t1["roster"]["entries"] if e["playerId"] == mine)
    e2 = next(e for e in t2["roster"]["entries"] if e["playerId"] == theirs)
    t1["roster"]["entries"].remove(e1)
    t2["roster"]["entries"].remove(e2)
    t1["roster"]["entries"].append(e2)
    t2["roster"]["entries"].append(e1)
    assert tc.post("/refresh", json={"scope": "league", "league_id": LEAGUE}).status_code == 200
    assert tc.get(f"/team/{team_id}/pending-trades").json()["trades"] == []


def test_trade_outlook_shows_both_lineups(espn):
    tc, _ = espn
    assert connect(tc, espn_s2=S2, swid=SWID).status_code == 200
    mine = tc.get(f"/team/{LEAGUE}-1").json()["roster"]
    theirs = tc.get(f"/team/{LEAGUE}-2").json()["roster"]
    give = next(p["player_id"] for p in mine if p["position"] == "RB")
    get = next(p["player_id"] for p in theirs if p["position"] == "RB")
    r = tc.post("/trade/outlook", json={"team_id": f"{LEAGUE}-1", "give": [give], "receive": [get]})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["slots"] and d["me"]["team_id"] == f"{LEAGUE}-1"
    assert d["partner"]["team_id"] == f"{LEAGUE}-2"
    assert [p["player_id"] for p in d["partner"]["receives"]] == [give]
    weeks = [w["week"] for w in d["me"]["after"]]
    assert weeks == [w["week"] for w in d["me"]["before"]] and weeks[0] == d["week"]
    bad = tc.post("/trade/outlook", json={"team_id": f"{LEAGUE}-1", "give": [get], "receive": []})
    assert bad.status_code == 422 and "your roster" in bad.text
