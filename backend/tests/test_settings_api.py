import json

from app import deps
from app.services import context, leagues, views
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
        "Projections", "Buy/sell & targets", "Injuries", "Advisor & trades", "Waivers & FAAB",
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


def test_bench_backups_setting_reaches_forced_drops(client):  # noqa: F811
    tc, _ = client
    team_id = connect_and_pick(tc)
    lid = leagues.league_id_for_team(deps._con, team_id)
    ctx = context.get_context(deps._con, lid, UserSettings())
    assert views.roster_rules(ctx).bench_backups == 1
    ctx = context.get_context(deps._con, lid, UserSettings(bench_backups_per_position=3))
    assert views.roster_rules(ctx).bench_backups == 3


def test_fair_trade_settings_reach_the_trade_engine(client):  # noqa: F811
    tc, _ = client
    team_id = connect_and_pick(tc)
    lid = leagues.league_id_for_team(deps._con, team_id)
    ctx = context.get_context(deps._con, lid, UserSettings())
    f = views.fairness(ctx)
    assert (f.band, f.need_premium) == (0.15, 0.10)
    assert set(f.needs) == {t.team_id for t in ctx.teams}  # every team's weak spots
    ctx = context.get_context(
        deps._con, lid, UserSettings(trade_fair_band=0.3, trade_need_premium=0.2)
    )
    assert (views.fairness(ctx).band, views.fairness(ctx).need_premium) == (0.3, 0.2)


def test_no_fair_deal_names_the_closest_package(client):  # noqa: F811
    from signals import trade as tr

    tc, _ = client
    team_id = connect_and_pick(tc)
    lid = leagues.league_id_for_team(deps._con, team_id)
    ctx = context.get_context(deps._con, lid, UserSettings())
    a, b = [p for p in ctx.team(team_id).player_ids if ctx.players[p].get("market_value")][:2]
    close = tr.MarketCheck((a,), (b,), 1000.0, 2000.0, 2.0, 0.5, 0.5, True, False)
    msg = views.no_fair_deal(ctx, tr.Offers([], close), "he or your players")
    name_a, name_b = ctx.players[a]["name"], ctx.players[b]["name"]
    assert msg == (
        f"No fair package within 15%. Closest: {name_a} (1,000) for {name_b} (2,000); "
        "you'd be short by 50%."
    )
    assert "none leaves your lineup better off" in views.no_fair_deal(
        ctx, tr.Offers([], None, fair_found=4), "x"
    )
    assert "no market value" in views.no_fair_deal(ctx, tr.Offers([]), "he or your players")


def test_free_drop_setting_reaches_forced_drops(client):  # noqa: F811
    tc, _ = client
    team_id = connect_and_pick(tc)
    lid = leagues.league_id_for_team(deps._con, team_id)
    ctx = context.get_context(deps._con, lid, UserSettings())
    assert views.roster_rules(ctx).free_drop_ppg == 0.5
    ctx = context.get_context(deps._con, lid, UserSettings(free_drop_ppg=1.5))
    assert views.roster_rules(ctx).free_drop_ppg == 1.5


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


def test_zero_gap_settings_do_not_break_advice(client):  # noqa: F811
    tc, _ = client
    team_id = connect_and_pick(tc)
    assert tc.put("/settings", json={"gap_min_points": 0, "gap_min_share": 0}).status_code == 200
    assert tc.get(f"/team/{team_id}/advice").status_code == 200
