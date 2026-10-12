import pytest

from app.services.player_analytics import player_analytics
from tests.builders import stat_row, stats_frame


def _wr_season(weeks=6):
    rows = []
    for w in range(1, weeks + 1):
        # week w: the WR gets w targets and w-1 catches; a teammate gets 10 targets every week
        rows.append(
            stat_row("wr", "WR", 2026, w, team="KC", targets=w, receptions=w - 1, rec_yds=10 * w,
                     air_yards=8 * w, rec_yac=3 * w, snap_pct=0.5 + w / 100,
                     rz_targets=1 if w % 2 else 0, rz_td=1 if w == 6 else 0, epa_total=1.0)
        )  # fmt: skip
        rows.append(stat_row("te", "TE", 2026, w, team="KC", targets=10, air_yards=40, carries=2))
    rows.append(stat_row("wr", "WR", 2025, 17, team="KC", targets=50))  # last season: ignored
    return stats_frame(rows)


def test_windows_shortest_first_and_season_last():
    a = player_analytics(_wr_season(), "wr", 2026, "WR")
    assert [(w.label, w.games) for w in a.windows] == [("L3", 3), ("L5", 5), ("Season", 6)]


def test_windows_that_cover_the_season_are_dropped():
    a = player_analytics(_wr_season(weeks=4), "wr", 2026, "WR")
    assert [w.label for w in a.windows] == ["L3", "Season"]
    a = player_analytics(_wr_season(weeks=3), "wr", 2026, "WR")
    assert [w.label for w in a.windows] == ["Season"]


def test_rates_are_ratios_of_sums_and_counts_per_game():
    l3 = player_analytics(_wr_season(), "wr", 2026, "WR").windows[0].metrics
    # weeks 4-6: targets 15, catches 12, yards 150, air yards 120, YAC 45
    assert l3["catch_rate"] == pytest.approx(12 / 15, abs=1e-3)
    assert l3["yds_per_target"] == pytest.approx(10.0)
    assert l3["adot"] == pytest.approx(8.0)
    assert l3["yac_per_rec"] == pytest.approx(45 / 12, abs=1e-2)
    assert l3["yac_per_game"] == pytest.approx(15.0)
    assert l3["rz_targets"] == pytest.approx(1 / 3, abs=1e-2)
    assert l3["rz_td"] == pytest.approx(1 / 3, abs=1e-2)
    assert l3["snap_pct"] == pytest.approx(0.55, abs=1e-3)


def test_team_shares_use_the_same_games():
    l3 = player_analytics(_wr_season(), "wr", 2026, "WR").windows[0].metrics
    assert l3["target_share"] == pytest.approx(15 / 45, abs=1e-3)
    assert l3["air_yards_share"] == pytest.approx(120 / 240, abs=1e-3)
    assert l3["wopr"] == pytest.approx(1.5 * 15 / 45 + 0.7 * 0.5, abs=1e-2)


def test_position_picks_metrics_and_groups():
    a = player_analytics(_wr_season(), "wr", 2026, "WR")
    keys = set(a.windows[0].metrics)
    assert "catch_rate" in keys and "yds_per_carry" not in keys and "cmp_pct" not in keys
    assert [g.key for g in a.groups] == ["usage", "efficiency", "yac", "scoring"]
    assert all(set(g.metrics) <= keys for g in a.groups)


def test_zero_denominators_and_missing_yac_are_null():
    rows = [
        stat_row("rb", "RB", 2026, w, team="NO", carries=0, targets=0, rec_yac=None) for w in (1, 2)
    ]
    m = player_analytics(stats_frame(rows), "rb", 2026, "RB").windows[-1].metrics
    assert m["yds_per_carry"] is None and m["rush_share"] is None and m["yds_per_target"] is None
    assert m["yac_per_game"] is None and m["yac_per_rec"] is None


def test_qb_uses_passing_air_yards_and_yac():
    rows = [
        stat_row("qb", "QB", 2026, w, team="BUF", pass_att=30, pass_cmp=20, pass_yds=240,
                 pass_air_yards=210, pass_yac=90, carries=5)
        for w in (1, 2)
    ]  # fmt: skip
    rows += [stat_row("rb", "RB", 2026, w, team="BUF", carries=15) for w in (1, 2)]
    m = player_analytics(stats_frame(rows), "qb", 2026, "QB").windows[-1].metrics
    assert m["adot"] == pytest.approx(7.0)
    assert m["cmp_pct"] == pytest.approx(0.667, abs=1e-3)
    assert m["yac_pct"] == pytest.approx(0.375)
    assert m["yac_per_game"] == pytest.approx(90.0)
    assert m["rush_share"] == pytest.approx(0.25)


def test_no_games_or_kicker_gives_none():
    stats = _wr_season()
    assert player_analytics(stats, "nobody", 2026, "WR") is None
    assert player_analytics(stats, "wr", 2026, "K") is None
