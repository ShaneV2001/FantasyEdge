import json

from app import deps
from app.services import context, leagues
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
