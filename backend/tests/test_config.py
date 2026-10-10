from datetime import date

from app.config import default_seasons, seasons_from_env


def test_offseason_keeps_the_season_that_just_ended():
    assert default_seasons(date(2027, 2, 10)) == (2025, 2026)
    assert default_seasons(date(2027, 5, 31)) == (2025, 2026)


def test_rolls_over_in_june():
    assert default_seasons(date(2027, 6, 1)) == (2026, 2027)
    assert default_seasons(date(2027, 9, 15)) == (2026, 2027)


def test_env_override_wins():
    assert seasons_from_env("2022,2024", date(2027, 9, 1)) == (2022, 2024)
    assert seasons_from_env("", date(2027, 9, 1)) == (2026, 2027)
    assert seasons_from_env(None, date(2026, 10, 10)) == (2025, 2026)
