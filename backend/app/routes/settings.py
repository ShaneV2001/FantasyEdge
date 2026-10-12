"""User settings: model weights and thresholds, saved to data/settings.json."""

from __future__ import annotations

from fastapi import APIRouter

from app import user_settings as us
from app.deps import settings_path
from app.errors import InvalidInput
from app.schemas import models as m
from app.services import context

router = APIRouter(prefix="/settings", tags=["settings"])


def _out(s: us.UserSettings, warning: str | None = None) -> m.SettingsOut:
    return m.SettingsOut(
        fields=[m.SettingFieldOut(**f) for f in us.field_schema(s)],
        warning=warning,
        path=str(settings_path()),
    )


@router.get("", response_model=m.SettingsOut)
def get_user_settings() -> m.SettingsOut:
    """Every setting with its current value, default, allowed range and help text."""
    s, warning = us.load(settings_path())
    return _out(s, warning)


@router.put("", response_model=m.SettingsOut)
def update_user_settings(changes: dict[str, float]) -> m.SettingsOut:
    """Change some settings (others keep their saved values). Every page recomputes."""
    current, _ = us.load(settings_path())
    try:
        new = us.apply(current, changes)
    except ValueError as exc:
        raise InvalidInput(us.describe_error(exc)) from exc
    us.save(settings_path(), new)
    context.invalidate()
    return _out(new)


@router.delete("", response_model=m.SettingsOut)
def reset_user_settings() -> m.SettingsOut:
    """Back to the defaults (deletes settings.json)."""
    settings_path().unlink(missing_ok=True)
    context.invalidate()
    return _out(us.UserSettings())
