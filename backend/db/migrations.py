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
    # v4: kicker and team-defense stat lines (DEF rows are keyed sl:<TEAM>)
    (
        4,
        "ALTER TABLE player_week_stats ADD COLUMN IF NOT EXISTS fgm_0_19 INTEGER;"
        "ALTER TABLE player_week_stats ADD COLUMN IF NOT EXISTS fgm_20_29 INTEGER;"
        "ALTER TABLE player_week_stats ADD COLUMN IF NOT EXISTS fgm_30_39 INTEGER;"
        "ALTER TABLE player_week_stats ADD COLUMN IF NOT EXISTS fgm_40_49 INTEGER;"
        "ALTER TABLE player_week_stats ADD COLUMN IF NOT EXISTS fgm_50_59 INTEGER;"
        "ALTER TABLE player_week_stats ADD COLUMN IF NOT EXISTS fgm_60p INTEGER;"
        "ALTER TABLE player_week_stats ADD COLUMN IF NOT EXISTS fgmiss INTEGER;"
        "ALTER TABLE player_week_stats ADD COLUMN IF NOT EXISTS fgm_yds INTEGER;"
        "ALTER TABLE player_week_stats ADD COLUMN IF NOT EXISTS xpm INTEGER;"
        "ALTER TABLE player_week_stats ADD COLUMN IF NOT EXISTS xpmiss INTEGER;"
        "ALTER TABLE player_week_stats ADD COLUMN IF NOT EXISTS def_sack INTEGER;"
        "ALTER TABLE player_week_stats ADD COLUMN IF NOT EXISTS def_int INTEGER;"
        "ALTER TABLE player_week_stats ADD COLUMN IF NOT EXISTS def_fum_rec INTEGER;"
        "ALTER TABLE player_week_stats ADD COLUMN IF NOT EXISTS def_ff INTEGER;"
        "ALTER TABLE player_week_stats ADD COLUMN IF NOT EXISTS def_td INTEGER;"
        "ALTER TABLE player_week_stats ADD COLUMN IF NOT EXISTS def_st_td INTEGER;"
        "ALTER TABLE player_week_stats ADD COLUMN IF NOT EXISTS def_safe INTEGER;"
        "ALTER TABLE player_week_stats ADD COLUMN IF NOT EXISTS def_blk_kick INTEGER;"
        "ALTER TABLE player_week_stats ADD COLUMN IF NOT EXISTS def_2pt INTEGER;"
        "ALTER TABLE player_week_stats ADD COLUMN IF NOT EXISTS pts_allow INTEGER;"
        "ALTER TABLE player_week_stats ADD COLUMN IF NOT EXISTS yds_allow INTEGER;",
    ),
    # v5: yards after catch and passing air yards, for the player-page analytics
    (
        5,
        "ALTER TABLE player_week_stats ADD COLUMN IF NOT EXISTS rec_yac INTEGER;"
        "ALTER TABLE player_week_stats ADD COLUMN IF NOT EXISTS pass_yac INTEGER;"
        "ALTER TABLE player_week_stats ADD COLUMN IF NOT EXISTS pass_air_yards INTEGER;",
    ),
    # v6: ESPN leagues. Login cookies for private leagues stay in this local file only (never
    # returned by the API except as their last 4 characters); final_week covers ESPN's
    # multi-week playoff rounds; scoring_notes lists league rules we can't model.
    (
        6,
        "CREATE TABLE IF NOT EXISTS league_credentials ("
        " league_id VARCHAR PRIMARY KEY, espn_s2 VARCHAR, swid VARCHAR, updated_at TIMESTAMP);"
        "ALTER TABLE leagues ADD COLUMN IF NOT EXISTS final_week INTEGER;"
        "ALTER TABLE leagues ADD COLUMN IF NOT EXISTS scoring_notes JSON;",
    ),
    # v7: injury details from Sleeper (a torn ACL means the season is over, not "out 4 weeks"),
    # and the user's own what-if per player ("out for the season" / "back in week N").
    (
        7,
        "ALTER TABLE players ADD COLUMN IF NOT EXISTS injury_body_part VARCHAR;"
        "ALTER TABLE players ADD COLUMN IF NOT EXISTS injury_notes VARCHAR;"
        "ALTER TABLE players ADD COLUMN IF NOT EXISTS injury_start_date DATE;"
        "CREATE TABLE IF NOT EXISTS player_availability ("
        " player_id VARCHAR PRIMARY KEY, out_for_season BOOLEAN, return_week INTEGER,"
        " updated_at TIMESTAMP);",
    ),
]


def latest_version() -> int:
    return max((v for v, _ in MIGRATIONS), default=BASELINE_VERSION)
