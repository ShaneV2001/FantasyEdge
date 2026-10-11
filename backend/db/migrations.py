"""Ordered schema migrations applied on top of the `schema.sql` baseline (version 1).

`schema.sql` is frozen: every schema change after v1 is appended here as `(version, sql)` and
must be safe on an existing store (e.g. `ADD COLUMN IF NOT EXISTS`). Never edit or reorder an
entry that has shipped; add a new one instead.
"""

from __future__ import annotations

BASELINE_VERSION = 1

MIGRATIONS: list[tuple[int, str]] = [
    # v2: redraft / keeper / dynasty, so dynasty leagues get dynasty market values
    (2, "ALTER TABLE leagues ADD COLUMN IF NOT EXISTS league_type VARCHAR DEFAULT 'redraft'"),
    # v3: stats for full Sleeper scoring (first downs, fumbles, sacks, pick-sixes, 2-pt by type)
    (
        3,
        "ALTER TABLE player_week_stats ADD COLUMN IF NOT EXISTS pass_fd INTEGER;"
        "ALTER TABLE player_week_stats ADD COLUMN IF NOT EXISTS rush_fd INTEGER;"
        "ALTER TABLE player_week_stats ADD COLUMN IF NOT EXISTS rec_fd INTEGER;"
        "ALTER TABLE player_week_stats ADD COLUMN IF NOT EXISTS fumbles INTEGER;"
        "ALTER TABLE player_week_stats ADD COLUMN IF NOT EXISTS sacks_taken INTEGER;"
        "ALTER TABLE player_week_stats ADD COLUMN IF NOT EXISTS pass_int_td INTEGER;"
        "ALTER TABLE player_week_stats ADD COLUMN IF NOT EXISTS pass_2pt INTEGER;"
        "ALTER TABLE player_week_stats ADD COLUMN IF NOT EXISTS rush_2pt INTEGER;"
        "ALTER TABLE player_week_stats ADD COLUMN IF NOT EXISTS rec_2pt INTEGER;",
    ),
]


def latest_version() -> int:
    return max((v for v, _ in MIGRATIONS), default=BASELINE_VERSION)
