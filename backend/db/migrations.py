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
]


def latest_version() -> int:
    return max((v for v, _ in MIGRATIONS), default=BASELINE_VERSION)
