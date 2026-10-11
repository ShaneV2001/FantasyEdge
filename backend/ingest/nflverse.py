"""nflverse ingestion (via nflreadpy). Data © nflverse, CC-BY 4.0.

Loaders are thin; every transform is a pure function on Polars frames so it can be unit-tested
against recorded fixtures.
"""

from __future__ import annotations

import polars as pl

# nflverse → Sleeper team codes (we store Sleeper style everywhere)
TEAM_FIX = {
    "LA": "LAR",
    "LVR": "LV",
    "JAC": "JAX",
    "WSH": "WAS",
    "OAK": "LV",
    "SD": "LAC",
    "STL": "LAR",
}

STATS_COLUMNS = [
    "player_id", "season", "week", "game_id", "team", "opponent",
    "snaps", "snap_pct", "routes",
    "pass_att", "pass_cmp", "pass_yds", "pass_td", "interceptions",
    "carries", "rush_yds", "rush_td",
    "targets", "receptions", "rec_yds", "rec_td",
    "air_yards", "target_share", "air_yards_share", "wopr",
    "rz_carries", "rz_targets", "gl_carries", "rz_td",
    "fumbles_lost", "two_pt", "epa_total",
    "pass_fd", "rush_fd", "rec_fd", "fumbles", "sacks_taken", "pass_int_td",
    "pass_2pt", "rush_2pt", "rec_2pt",
    "fgm_0_19", "fgm_20_29", "fgm_30_39", "fgm_40_49", "fgm_50_59", "fgm_60p", "fgmiss",
    "fgm_yds", "xpm", "xpmiss",
    "def_sack", "def_int", "def_fum_rec", "def_ff", "def_td", "def_st_td", "def_safe",
    "def_blk_kick", "def_2pt", "pts_allow", "yds_allow",
]  # fmt: skip

SKILL = ("QB", "RB", "WR", "TE")


def norm_team(col: str) -> pl.Expr:
    return pl.col(col).replace(TEAM_FIX)


def _num(col: str) -> pl.Expr:
    return pl.col(col).fill_null(0)


def _opt(df: pl.DataFrame, col: str) -> pl.Expr:
    """A count column that older nflverse releases (and test fixtures) may not have."""
    return _num(col) if col in df.columns else pl.lit(0)


def transform_weekly_stats(stats: pl.DataFrame) -> pl.DataFrame:
    """nflverse `load_player_stats` (week level) → player_week_stats columns (no RZ/snaps yet)."""
    df = stats.filter((pl.col("season_type") == "REG") & pl.col("position").is_in(SKILL))
    return df.select(
        pl.col("player_id"),
        pl.col("season").cast(pl.Int32),
        pl.col("week").cast(pl.Int32),
        pl.col("game_id"),
        norm_team("team").alias("team"),
        norm_team("opponent_team").alias("opponent"),
        _num("attempts").cast(pl.Int32).alias("pass_att"),
        _num("completions").cast(pl.Int32).alias("pass_cmp"),
        _num("passing_yards").cast(pl.Int32).alias("pass_yds"),
        _num("passing_tds").cast(pl.Int32).alias("pass_td"),
        _num("passing_interceptions").cast(pl.Int32).alias("interceptions"),
        _num("carries").cast(pl.Int32).alias("carries"),
        _num("rushing_yards").cast(pl.Int32).alias("rush_yds"),
        _num("rushing_tds").cast(pl.Int32).alias("rush_td"),
        _num("targets").cast(pl.Int32).alias("targets"),
        _num("receptions").cast(pl.Int32).alias("receptions"),
        _num("receiving_yards").cast(pl.Int32).alias("rec_yds"),
        _num("receiving_tds").cast(pl.Int32).alias("rec_td"),
        _num("receiving_air_yards").cast(pl.Int32).alias("air_yards"),
        pl.col("target_share").cast(pl.Float64),
        pl.col("air_yards_share").cast(pl.Float64),
        pl.col("wopr").cast(pl.Float64),
        (_num("rushing_fumbles_lost") + _num("receiving_fumbles_lost") + _num("sack_fumbles_lost"))
        .cast(pl.Int32)
        .alias("fumbles_lost"),
        (
            _num("passing_2pt_conversions")
            + _num("rushing_2pt_conversions")
            + _num("receiving_2pt_conversions")
        )
        .cast(pl.Int32)
        .alias("two_pt"),
        (_num("passing_epa") + _num("rushing_epa") + _num("receiving_epa")).alias("epa_total"),
        _opt(df, "passing_first_downs").cast(pl.Int32).alias("pass_fd"),
        _opt(df, "rushing_first_downs").cast(pl.Int32).alias("rush_fd"),
        _opt(df, "receiving_first_downs").cast(pl.Int32).alias("rec_fd"),
        (_opt(df, "rushing_fumbles") + _opt(df, "receiving_fumbles") + _opt(df, "sack_fumbles"))
        .cast(pl.Int32)
        .alias("fumbles"),
        _opt(df, "sacks_suffered").cast(pl.Int32).alias("sacks_taken"),
        _opt(df, "passing_2pt_conversions").cast(pl.Int32).alias("pass_2pt"),
        _opt(df, "rushing_2pt_conversions").cast(pl.Int32).alias("rush_2pt"),
        _opt(df, "receiving_2pt_conversions").cast(pl.Int32).alias("rec_2pt"),
    )


def _game_keys(df: pl.DataFrame) -> list[pl.Expr]:
    return [
        pl.col("season").cast(pl.Int32),
        pl.col("week").cast(pl.Int32),
        pl.col("game_id"),
        norm_team("team").alias("team"),
        norm_team("opponent_team").alias("opponent"),
    ]


KICKING = (
    ("fg_made_0_19", "fgm_0_19"), ("fg_made_20_29", "fgm_20_29"),
    ("fg_made_30_39", "fgm_30_39"), ("fg_made_40_49", "fgm_40_49"),
    ("fg_made_50_59", "fgm_50_59"), ("fg_made_60_", "fgm_60p"),
    ("fg_missed", "fgmiss"), ("fg_made_distance", "fgm_yds"),
    ("pat_made", "xpm"), ("pat_missed", "xpmiss"),
)  # fmt: skip


def transform_kicker_stats(stats: pl.DataFrame) -> pl.DataFrame:
    """Kickers' weekly lines (nflverse player stats) in Sleeper's kicking stat terms."""
    df = stats.filter((pl.col("season_type") == "REG") & (pl.col("position") == "K"))
    return df.select(
        pl.col("player_id"),
        *_game_keys(df),
        *[_opt(df, src).cast(pl.Int32).alias(dst) for src, dst in KICKING],
    )


def defense_id(team: pl.Expr) -> pl.Expr:
    """Team defenses use Sleeper's DEF player id (the team code) under the internal sl: prefix."""
    return pl.lit("sl:") + team


def transform_team_defense(team_stats: pl.DataFrame, games: pl.DataFrame) -> pl.DataFrame:
    """One DEF row per team-game: takeaways and scores from nflverse team stats; points and
    (net) yards allowed from the opponent's score and offensive line."""
    df = team_stats.filter(pl.col("season_type") == "REG")
    own = df.select(
        *_game_keys(df),
        _opt(df, "def_sacks").cast(pl.Int32).alias("def_sack"),
        _opt(df, "def_interceptions").cast(pl.Int32).alias("def_int"),
        _opt(df, "fumble_recovery_opp").cast(pl.Int32).alias("def_fum_rec"),
        _opt(df, "def_fumbles_forced").cast(pl.Int32).alias("def_ff"),
        _opt(df, "def_tds").cast(pl.Int32).alias("def_td"),
        _opt(df, "special_teams_tds").cast(pl.Int32).alias("def_st_td"),
        _opt(df, "def_safeties").cast(pl.Int32).alias("def_safe"),
        (_opt(df, "def_fg_blocks") + _opt(df, "def_punt_blocks") + _opt(df, "def_pat_blocks"))
        .cast(pl.Int32)
        .alias("def_blk_kick"),
        _opt(df, "def_2pt_made").cast(pl.Int32).alias("def_2pt"),
    )
    offense = df.select(
        pl.col("season").cast(pl.Int32),
        pl.col("week").cast(pl.Int32),
        norm_team("team").alias("opponent"),
        (_opt(df, "passing_yards") - _opt(df, "sack_yards_lost") + _opt(df, "rushing_yards"))
        .cast(pl.Int32)
        .alias("yds_allow"),
    )
    scores = pl.concat(
        [
            games.select("season", "week", pl.col("home_team").alias("team"),
                         pl.col("away_score").alias("pts_allow")),
            games.select("season", "week", pl.col("away_team").alias("team"),
                         pl.col("home_score").alias("pts_allow")),
        ]
    ).with_columns(
        pl.col("season").cast(pl.Int32), pl.col("week").cast(pl.Int32),
        pl.col("pts_allow").cast(pl.Int32),
    )  # fmt: skip
    return (
        own.join(offense, on=["season", "week", "opponent"], how="left")
        .join(scores, on=["season", "week", "team"], how="left")
        .with_columns(defense_id(pl.col("team")).alias("player_id"))
    )


def red_zone_from_pbp(pbp: pl.DataFrame) -> pl.DataFrame:
    """Per player-week red-zone (≤20 yds) and goal-line (≤5 yds) opportunities + RZ TDs."""
    plays = pbp.filter(
        (pl.col("season_type") == "REG")
        & (pl.col("two_point_attempt").fill_null(0) == 0)
        & pl.col("yardline_100").is_not_null()
    ).with_columns(
        (pl.col("yardline_100") <= 20).alias("rz"),
        (pl.col("yardline_100") <= 5).alias("gl"),
    )
    rush = (
        plays.filter((pl.col("rush_attempt") == 1) & pl.col("rusher_player_id").is_not_null())
        .group_by(pl.col("rusher_player_id").alias("player_id"), "season", "week")
        .agg(
            pl.col("rz").sum().alias("rz_carries"),
            pl.col("gl").sum().alias("gl_carries"),
            (pl.col("rz") & (pl.col("rush_touchdown") == 1)).sum().alias("rz_rush_td"),
        )
    )
    rec = (
        plays.filter(
            (pl.col("pass_attempt") == 1)
            & (pl.col("sack").fill_null(0) == 0)
            & pl.col("receiver_player_id").is_not_null()
        )
        .group_by(pl.col("receiver_player_id").alias("player_id"), "season", "week")
        .agg(
            pl.col("rz").sum().alias("rz_targets"),
            (pl.col("rz") & (pl.col("pass_touchdown") == 1)).sum().alias("rz_rec_td"),
        )
    )
    out = rush.join(rec, on=["player_id", "season", "week"], how="full", coalesce=True)
    return out.select(
        "player_id",
        pl.col("season").cast(pl.Int32),
        pl.col("week").cast(pl.Int32),
        pl.col("rz_carries").fill_null(0).cast(pl.Int32),
        pl.col("rz_targets").fill_null(0).cast(pl.Int32),
        pl.col("gl_carries").fill_null(0).cast(pl.Int32),
        (pl.col("rz_rush_td").fill_null(0) + pl.col("rz_rec_td").fill_null(0))
        .cast(pl.Int32)
        .alias("rz_td"),
    )


def pick_sixes_from_pbp(pbp: pl.DataFrame) -> pl.DataFrame:
    """Interceptions returned for a touchdown, charged to the passer (Sleeper `pass_int_td`)."""
    return (
        pbp.filter(
            (pl.col("season_type") == "REG")
            & (pl.col("interception").fill_null(0) == 1)
            & (pl.col("return_touchdown").fill_null(0) == 1)
            & pl.col("passer_player_id").is_not_null()
        )
        .group_by(pl.col("passer_player_id").alias("player_id"), "season", "week")
        .agg(pl.len().cast(pl.Int32).alias("pass_int_td"))
        .with_columns(pl.col("season").cast(pl.Int32), pl.col("week").cast(pl.Int32))
    )


def snaps_by_gsis(snaps: pl.DataFrame, id_map: pl.DataFrame) -> pl.DataFrame:
    xwalk = id_map.select("pfr_id", "gsis_id").drop_nulls().unique("pfr_id")
    return (
        snaps.filter(pl.col("game_type") == "REG")
        .join(xwalk, left_on="pfr_player_id", right_on="pfr_id", how="inner")
        .select(
            pl.col("gsis_id").alias("player_id"),
            pl.col("season").cast(pl.Int32),
            pl.col("week").cast(pl.Int32),
            pl.col("offense_snaps").cast(pl.Int32).alias("snaps"),
            pl.col("offense_pct").cast(pl.Float64).alias("snap_pct"),
        )
        .unique(["player_id", "season", "week"])
    )


def build_player_week_stats(
    stats: pl.DataFrame, pbp: pl.DataFrame | None, snaps: pl.DataFrame | None
) -> pl.DataFrame:
    base = transform_weekly_stats(stats)
    keys = ["player_id", "season", "week"]
    if pbp is not None:
        base = base.join(red_zone_from_pbp(pbp), on=keys, how="left")
        base = base.join(pick_sixes_from_pbp(pbp), on=keys, how="left")
    if snaps is not None:
        base = base.join(snaps, on=keys, how="left")
    for col in ("rz_carries", "rz_targets", "gl_carries", "rz_td", "pass_int_td"):
        if col not in base.columns:
            base = base.with_columns(pl.lit(0, pl.Int32).alias(col))
        base = base.with_columns(pl.col(col).fill_null(0))
    for col, dtype in (("snaps", pl.Int32), ("snap_pct", pl.Float64), ("routes", pl.Int32)):
        if col not in base.columns:
            base = base.with_columns(pl.lit(None, dtype).alias(col))
    return with_stats_columns(base).unique(keys, keep="last")


INT_STATS = {c for c in STATS_COLUMNS if c not in {"player_id", "game_id", "team", "opponent"}}
FLOAT_STATS = {"snap_pct", "target_share", "air_yards_share", "wopr", "epa_total"}


def with_stats_columns(df: pl.DataFrame) -> pl.DataFrame:
    """Select STATS_COLUMNS, adding any a partial frame (kickers, defenses) lacks as null."""

    def dtype(c: str) -> pl.DataType:
        return pl.Float64 if c in FLOAT_STATS else pl.Int32 if c in INT_STATS else pl.Utf8

    missing = [pl.lit(None, dtype(c)).alias(c) for c in STATS_COLUMNS if c not in df.columns]
    return df.with_columns(missing).select(STATS_COLUMNS)


def build_kicker_and_defense(
    stats: pl.DataFrame, team_stats: pl.DataFrame | None, games: pl.DataFrame
) -> pl.DataFrame:
    """K and DEF rows in player_week_stats shape (no snaps/usage columns)."""
    frames = [with_stats_columns(transform_kicker_stats(stats))]
    if team_stats is not None:
        frames.append(with_stats_columns(transform_team_defense(team_stats, games)))
    return pl.concat(frames).unique(["player_id", "season", "week"], keep="last")


def transform_schedule(sched: pl.DataFrame) -> pl.DataFrame:
    """Regular-season games only (byes are derived from missing weeks)."""
    return sched.filter(pl.col("game_type") == "REG").select(
        "game_id",
        pl.col("season").cast(pl.Int32),
        pl.col("week").cast(pl.Int32),
        norm_team("home_team").alias("home_team"),
        norm_team("away_team").alias("away_team"),
        (pl.col("gameday") + pl.lit(" ") + pl.col("gametime").fill_null("13:00"))
        .str.strptime(pl.Datetime, "%Y-%m-%d %H:%M", strict=False)
        .alias("kickoff"),
        pl.col("home_score").cast(pl.Int32),
        pl.col("away_score").cast(pl.Int32),
    )


def transform_injuries(inj: pl.DataFrame) -> pl.DataFrame:
    return (
        inj.filter(pl.col("gsis_id").is_not_null() & (pl.col("season_type") == "REG"))
        .select(
            pl.col("gsis_id").alias("player_id"),
            pl.col("season").cast(pl.Int32),
            pl.col("week").cast(pl.Int32),
            pl.col("report_status"),
            pl.col("practice_status"),
            pl.col("report_primary_injury").alias("body_part"),
        )
        .unique(["player_id", "season", "week"], keep="last")
    )


# ───────── loaders (network) ─────────


def load_all(seasons: list[int], id_map: pl.DataFrame) -> dict[str, pl.DataFrame]:
    import nflreadpy as nfl

    stats = nfl.load_player_stats(seasons, summary_level="week")
    team_stats = nfl.load_team_stats(seasons, summary_level="week")
    pbp = nfl.load_pbp(seasons)
    snaps = nfl.load_snap_counts(seasons)
    games = transform_schedule(nfl.load_schedules(seasons))
    inj = nfl.load_injuries(seasons)
    skill = build_player_week_stats(stats, pbp, snaps_by_gsis(snaps, id_map))
    return {
        "player_week_stats": pl.concat([skill, build_kicker_and_defense(stats, team_stats, games)]),
        "nfl_games": games,
        "injuries": transform_injuries(inj),
    }
