from app.services.context import LeagueRow


def _league(playoff_week_start):
    return LeagueRow(
        league_id="x", platform="manual", external_id=None, season=2026, name="x", num_teams=12,
        roster_positions=["QB"], scoring_profile_id="p", rules={}, trade_deadline_week=None,
        uses_faab=False, faab_budget=None, playoff_week_start=playoff_week_start,
        last_synced_at=None,
    )  # fmt: skip


def test_playoff_weeks_follow_the_league():
    lg = _league(14)
    assert list(lg.playoff_weeks) == [14, 15, 16]
    assert lg.last_week == 16
    assert lg.playoff_label == "weeks 14-16"


def test_playoff_weeks_default_and_cap():
    assert list(_league(None).playoff_weeks) == [15, 16, 17]
    late = _league(17)
    assert list(late.playoff_weeks) == [17, 18]
    assert _league(18).playoff_label == "week 18"
