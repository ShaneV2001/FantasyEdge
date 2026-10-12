import json

import pytest

from app import user_settings as us
from signals.schedule import MATCHUP_ALPHA
from signals.verdict import STARTABLE_RANK


def test_defaults_match_the_tuned_constants():
    s = us.UserSettings()
    assert s.alpha == MATCHUP_ALPHA
    assert s.startable == STARTABLE_RANK
    assert (s.usage_weight, s.shrink_games, s.gap_min_points, s.gap_min_share) == (
        0.5,
        8,
        10.0,
        0.10,
    )
    assert (s.play_chance_questionable, s.play_chance_doubtful, s.ir_weeks_out) == (0.85, 0.25, 4)
    assert (s.trade_accept_gain, s.trade_lean_gain, s.targets_per_tier) == (8.0, 2.0, 10)


def test_missing_file_gives_defaults_without_warning(tmp_path):
    s, warning = us.load(tmp_path / "settings.json")
    assert s == us.UserSettings() and warning is None


def test_save_writes_only_changed_values_and_round_trips(tmp_path):
    path = tmp_path / "settings.json"
    s = us.UserSettings(gap_min_points=20, matchup_alpha_rb=0.8)
    us.save(path, s)
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "gap_min_points": 20.0,
        "matchup_alpha_rb": 0.8,
    }
    assert us.load(path) == (s, None)
    assert not list(tmp_path.glob(".settings-*"))  # temp file cleaned up


@pytest.mark.parametrize(
    "content, mentions",
    [("{not json", "settings.json"), ('{"gap_min_points": 999}', "gap_min_points"),
     ('{"no_such_key": 1}', "no_such_key"), ("[1, 2]", "settings.json")],
)  # fmt: skip
def test_broken_file_falls_back_to_defaults_with_warning(tmp_path, content, mentions):
    path = tmp_path / "settings.json"
    path.write_text(content, encoding="utf-8")
    s, warning = us.load(path)
    assert s == us.UserSettings()
    assert warning is not None and mentions in warning


def test_apply_merges_partial_changes_and_validates():
    s = us.apply(us.UserSettings(), {"gap_min_points": 15, "ir_weeks_out": 2})
    assert (s.gap_min_points, s.ir_weeks_out, s.usage_weight) == (15, 2, 0.5)
    with pytest.raises(ValueError, match="no_such_key"):
        us.apply(s, {"no_such_key": 1})
    with pytest.raises(ValueError):
        us.apply(s, {"usage_weight": 1.5})
    with pytest.raises(ValueError, match="lean"):
        us.apply(s, {"trade_lean_gain": 9, "trade_accept_gain": 8})
    with pytest.raises(ValueError):
        us.apply(s, {"shrink_games": 2.5})


def test_field_schema_describes_every_field():
    rows = us.field_schema(us.UserSettings(gap_min_points=12))
    keys = [r["key"] for r in rows]
    assert keys == list(us.UserSettings.model_fields) and len(set(keys)) == len(keys)
    for r in rows:
        assert r["group"] in us.GROUPS and r["label"] and r["help"]
        assert r["min"] <= r["default"] <= r["max"]
    by_key = {r["key"]: r for r in rows}
    assert by_key["gap_min_points"]["value"] == 12 and by_key["gap_min_points"]["default"] == 10
    assert by_key["shrink_games"]["integer"] and not by_key["usage_weight"]["integer"]
    assert by_key["usage_weight"]["tuned"] and not by_key["gap_min_points"]["tuned"]


def test_describe_error_names_the_field():
    with pytest.raises(ValueError) as exc:
        us.apply(us.UserSettings(), {"easy_schedule": 5})
    assert "easy_schedule" in us.describe_error(exc.value)
