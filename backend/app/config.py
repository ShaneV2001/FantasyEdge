"""Runtime settings, read once from the environment (and an optional repo-root .env)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    seasons: tuple[int, int]
    market_source: str
    sleeper_base: str
    fantasycalc_base: str
    # Optional ESPN defaults from .env (the Connect page can supply them instead)
    espn_s2: str | None = None
    espn_swid: str | None = None
    espn_league_id: str | None = None
    # Claude advisor chat (optional): the key stays on this computer and goes only to Anthropic
    anthropic_api_key: str | None = None
    ai_model: str = "claude-opus-5-5"
    ai_effort: str = "medium"
    ai_max_steps: int = 8  # tool rounds per answer

    def __repr__(self) -> str:  # never print the ESPN cookies or the API key
        return f"Settings(data_dir={self.data_dir!r}, seasons={self.seasons!r})"

    @property
    def ai_enabled(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "ff.duckdb"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"


def _resolve(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else (REPO_ROOT / p).resolve()


# The next season's schedule is published in May; from June on, "current" means the coming season.
SEASON_ROLLOVER_MONTH = 6


def default_seasons(today: date) -> tuple[int, int]:
    """(previous, current) NFL season: the prior season supplies norms early in the year."""
    current = today.year if today.month >= SEASON_ROLLOVER_MONTH else today.year - 1
    return current - 1, current


def seasons_from_env(value: str | None, today: date) -> tuple[int, int]:
    if not value:
        return default_seasons(today)
    first, last = (int(x) for x in value.split(","))
    return first, last


@lru_cache
def get_settings() -> Settings:
    first, last = seasons_from_env(os.getenv("FF_SEASONS"), date.today())
    return Settings(
        data_dir=_resolve(os.getenv("FF_DATA_DIR", "./data")),
        seasons=(first, last),
        market_source=os.getenv("FF_MARKET_SOURCE", "fantasycalc"),
        sleeper_base=os.getenv("FF_SLEEPER_BASE", "https://api.sleeper.app/v1"),
        fantasycalc_base=os.getenv("FF_FANTASYCALC_BASE", "https://api.fantasycalc.com"),
        espn_s2=os.getenv("ESPN_S2") or None,
        espn_swid=os.getenv("ESPN_SWID") or None,
        espn_league_id=os.getenv("ESPN_LEAGUE_ID") or None,
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY") or None,
        ai_model=os.getenv("FF_AI_MODEL") or "claude-opus-5-5",
        ai_effort=os.getenv("FF_AI_EFFORT") or "medium",
        ai_max_steps=int(os.getenv("FF_AI_MAX_STEPS") or 8),
    )
