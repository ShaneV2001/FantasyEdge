import json

from app import deps
from app.services import context, leagues
from app.services.context import ENGINE, engine_for
from app.user_settings import UserSettings
from tests.test_api import client, connect_and_pick  # noqa: F401  (pytest fixture)


def test_get_returns_defaults_and_schema(client):  # noqa: F811
    tc, _ = client
    r = tc.get("/settings")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["warning"] is None and body["path"].endswith("settings.json")
    fields = {f["key"]: f for f in body["fields"]}
    assert fields["usage_weight"]["value"] == fields["usage_weight"]["default"] == 0.5
    assert {f["group"] for f in body["fields"]} == {
        "Projections", "Buy/sell & targets", "Injuries", "Advisor & trades",
    }  # fmt: skip


def test_put_saves_only_changes_and_delete_resets(client):  # noqa: F811
    tc, _ = client
    r = tc.put("/settings", json={"gap_min_points": 20, "ir_weeks_out": 2})
    assert r.status_code == 200, r.text
    vals = {f["key"]: f["value"] for f in r.json()["fields"]}
    assert vals["gap_min_points"] == 20 and vals["ir_weeks_out"] == 2
    on_disk = json.loads(deps.settings_path().read_text(encoding="utf-8"))
    assert on_disk == {"gap_min_points": 20.0, "ir_weeks_out": 2}
    # a second PUT merges with what's saved
    tc.put("/settings", json={"usage_weight": 0.4})
    vals = {f["key"]: f["value"] for f in tc.get("/settings").json()["fields"]}
    assert (vals["gap_min_points"], vals["usage_weight"]) == (20, 0.4)
    r = tc.delete("/settings")
    assert r.status_code == 200
    assert not deps.settings_path().exists()
    assert all(f["value"] == f["default"] for f in r.json()["fields"])


def test_put_rejects_bad_values(client):  # noqa: F811
    tc, _ = client
    for body, needle in [
        ({"gap_min_points": 999}, "gap_min_points"),
        ({"no_such_key": 1}, "no_such_key"),
        ({"trade_lean_gain": 30}, "lean"),
    ]:
        r = tc.put("/settings", json=body)
        assert r.status_code == 422, body
        assert needle in r.json()["detail"]
    assert not deps.settings_path().exists()  # nothing saved


def test_broken_file_reports_warning_and_put_replaces_it(client):  # noqa: F811
    tc, _ = client
    deps.settings_path().write_text("{oops", encoding="utf-8")
    assert "settings.json" in tc.get("/settings").json()["warning"]
    assert tc.put("/settings", json={"gap_min_points": 12}).status_code == 200
    assert tc.get("/settings").json()["warning"] is None


def test_context_cache_is_keyed_on_settings(client):  # noqa: F811
    tc, _ = client
    team_id = connect_and_pick(tc)
    lid = leagues.league_id_for_team(deps._con, team_id)
    a = context.get_context(deps._con, lid, UserSettings())
    assert context.get_context(deps._con, lid, UserSettings()) is a
    b = context.get_context(deps._con, lid, UserSettings(gap_min_points=20))
    assert b is not a and b.tuning.gap_min_points == 20


def test_engine_follows_settings():
    assert engine_for(UserSettings()) == ENGINE
    e = engine_for(UserSettings(usage_weight=0.2, shrink_games=3))
    assert (e.w_usage, e.w_season, e.w_l3, e.shrink_games) == (0.2, 0.8, 0.0, 3)


def test_projection_settings_change_team_numbers(client):  # noqa: F811
    tc, _ = client
    team_id = connect_and_pick(tc)

    def ppg():
        return {p["player_id"]: p["ppg"] for p in tc.get(f"/team/{team_id}").json()["roster"]}

    before = ppg()
    tc.put("/settings", json={"usage_weight": 0.0})
    assert ppg() != before
    tc.put("/settings", json={"matchup_alpha_rb": 0.0})
    rb = tc.get(f"/team/{team_id}/rankings").json()["positions"]["RB"]
    assert rb["alpha"] == 0.0
    assert all(r["schedule_delta"] == 0 for r in rb["ros"])


def test_verdict_settings_change_buy_targets(client):  # noqa: F811
    tc, _ = client
    team_id = connect_and_pick(tc)

    def buys():
        pos = tc.get(f"/team/{team_id}/buy-targets").json()["positions"]
        return pos, sum(len(p["buy"]) for p in pos.values())

    tc.put("/settings", json={"gap_min_points": 0, "gap_min_share": 0})
    _, loose = buys()
    tc.put("/settings", json={"gap_min_points": 50, "gap_min_share": 0.5})
    _, strict = buys()
    assert loose > 0 and strict <= loose
    tc.put("/settings", json={"gap_min_points": 0, "gap_min_share": 0, "targets_per_tier": 3})
    pos, _ = buys()
    for p in pos.values():
        for tier in ("starter", "depth"):
            assert sum(r["tier"] == tier for r in p["buy"]) <= 3
