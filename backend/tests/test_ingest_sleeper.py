import httpx
import pytest
import respx

from ingest.http import CachedHttp, SourceUnavailable
from ingest.sleeper import (
    SleeperClient,
    deadline_passed,
    parse_league,
    parse_players,
    parse_rosters,
)
from tests.conftest import load_json

BASE = "https://api.sleeper.app/v1"


def test_parse_league_reads_settings():
    info = parse_league(load_json("sleeper_league.json"))
    assert info.num_teams == 4
    assert info.trade_deadline_week == 11
    assert info.uses_faab and info.faab_budget == 100
    assert info.playoff_week_start == 15
    assert info.scoring_settings["rec"] == 0.5
    assert "SUPER_FLEX" in info.roster_positions


def test_parse_league_no_deadline_sentinel():
    raw = load_json("sleeper_league.json") | {"settings": {"trade_deadline": 99}}
    assert parse_league(raw).trade_deadline_week is None


def test_parse_rosters_joins_owner_and_faab():
    rosters = parse_rosters(
        load_json("sleeper_rosters.json"), load_json("sleeper_users.json"), faab_budget=100
    )
    assert len(rosters) == 4
    r = rosters[1]
    assert r.team_name == "Team Bravo"
    assert r.faab_remaining == 90
    assert r.points_for == pytest.approx(410.5)
    assert len(r.players) == 15


def test_parse_players_keeps_fantasy_positions():
    df = parse_players(load_json("sleeper_players.json"))
    assert set(df["position"].unique()) <= {"QB", "RB", "WR", "TE", "K", "DEF"}
    defs = df.filter(df["position"] == "DEF")
    assert defs.height == 4 and set(defs["nfl_team"]) == {"BUF", "BAL", "PHI", "DEN"}


def test_deadline_passed():
    assert not deadline_passed(None, 17)
    assert not deadline_passed(11, 11)
    assert deadline_passed(11, 12)


@respx.mock
def test_client_caches_and_serves_stale_on_failure(tmp_path):
    route = respx.get(f"{BASE}/state/nfl").mock(
        return_value=httpx.Response(200, json=load_json("sleeper_state.json"))
    )
    client = SleeperClient(CachedHttp(tmp_path, min_interval_s=0), BASE)
    assert client.state()["season"] == "2026"
    assert client.state()["week"] == 5  # served from cache
    assert route.call_count == 1

    route.mock(return_value=httpx.Response(503))
    state = client.http.get(f"{BASE}/state/nfl", source="sleeper", force=True)
    assert state.stale and state.json()["week"] == 5


@respx.mock
def test_client_raises_source_unavailable_without_cache(tmp_path):
    respx.get(f"{BASE}/user/nobody").mock(return_value=httpx.Response(500))
    client = SleeperClient(CachedHttp(tmp_path, min_interval_s=0), BASE)
    with pytest.raises(SourceUnavailable):
        client.user("nobody")
