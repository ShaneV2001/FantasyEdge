"""Head-to-head matchups, the same shape for every platform."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class WeekMatchup:
    """One team's head-to-head matchup in one week, in the platform's own ids."""

    week: int
    team: str  # roster id (Sleeper) / team id (ESPN)
    opponent: str | None  # None = no opponent that week
    points: float
    starters: list[str] = field(default_factory=list)  # player ids who started (empty = unknown)
    player_points: dict[str, float] = field(default_factory=dict)
