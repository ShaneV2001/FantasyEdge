"""Weekly stock moves (how last week's game moved a projection) and season ranks."""

from types import SimpleNamespace

import polars as pl

from app.services import views


def _ctx(rows, positions, week=8):
    stats = pl.DataFrame(
        rows, schema={"player_id": pl.Utf8, "season": pl.Int64, "week": pl.Int64, "fp": pl.Float64},
        orient="row",
    )  # fmt: skip
    players = {pid: {"position": pos, "name": pid} for pid, pos in positions.items()}
    return SimpleNamespace(stats=stats, season=2026, week=week, memo={}, players=players)


def test_last_weeks_game_moves_the_stock(monkeypatch):
    ctx = _ctx(
        [("boom", 2026, 7, 31.0), ("bust", 2026, 7, 1.5), ("meh", 2026, 7, 12.0)],
        {"boom": "WR", "bust": "WR", "meh": "WR", "out": "WR"},
    )
    before = {"boom": 14.0, "bust": 15.0, "meh": 12.0, "out": 10.0}
    after = {"boom": 16.1, "bust": 13.4, "meh": 12.3, "out": 10.0}
    monkeypatch.setattr(views.ps, "played_weeks", lambda c: [1, 2, 3, 4, 5, 6, 7, 8])
    monkeypatch.setattr(views.ps, "neutral_projection", lambda c, w: before if w == 7 else after)
    moves = views.stock_moves(ctx)
    assert moves["boom"] == ("up", 2.1, "Scored 31.0 vs 14.0 projected in week 7")
    assert moves["bust"][0] == "down" and moves["bust"][1] == -1.6
    assert moves["meh"][0] == "flat"  # +0.3 is under max(0.5, 5%)
    assert moves["out"] == ("flat", 0.0, None)  # didn't play: no reason to show


def test_no_played_week_means_no_stock(monkeypatch):
    monkeypatch.setattr(views.ps, "played_weeks", lambda c: [1])
    assert views.stock_moves(_ctx([], {}, week=1)) == {}


def test_season_rank_needs_three_games():
    rows = [("a", 2026, w, 20.0) for w in (1, 2, 3)] + [("b", 2026, w, 25.0) for w in (1, 2)]
    rows += [("c", 2026, w, 15.0) for w in (1, 2, 3, 4)] + [("a", 2025, 1, 0.0)]
    ctx = _ctx(rows, {"a": "RB", "b": "RB", "c": "RB"})
    assert views.season_ranks(ctx) == {"a": 1, "c": 2}  # b has only 2 games
    assert views.season_production(ctx)["a"] == (3, 20.0)  # last season isn't counted
