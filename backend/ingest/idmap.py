"""Player ID crosswalk (DynastyProcess `db_playerids.csv`, via nflreadpy) and internal-ID rules.

Internal `player_id` = nflverse gsis_id when known, else `sl:<sleeper_id>` (rookies, K/DEF).
"""

from __future__ import annotations

import io
from datetime import timedelta

import polars as pl

from ingest.http import CachedHttp

DP_IDS_URL = "https://raw.githubusercontent.com/dynastyprocess/data/master/files/db_playerids.csv"

ID_COLS = ["gsis_id", "sleeper_id", "espn_id", "yahoo_id", "pfr_id", "fantasypros_id", "name"]


def fetch_id_map(http: CachedHttp) -> pl.DataFrame:
    text = http.get(DP_IDS_URL, source="dynastyprocess", ttl=timedelta(hours=24)).text
    return parse_id_map(text)


def parse_id_map(csv_text: str) -> pl.DataFrame:
    df = pl.read_csv(
        io.StringIO(csv_text), infer_schema_length=0, null_values=["NA", ""]
    )  # all strings
    return df.select([c for c in ID_COLS if c in df.columns])


def internal_id(gsis_id: str | None, sleeper_id: str | None) -> str:
    if gsis_id:
        return gsis_id
    return f"sl:{sleeper_id}"


def attach_internal_ids(sleeper_players: pl.DataFrame, id_map: pl.DataFrame) -> pl.DataFrame:
    """Fill gsis_id from the crosswalk where Sleeper lacks it, then derive player_id."""
    xwalk = (
        id_map.filter(pl.col("sleeper_id").is_not_null() & pl.col("gsis_id").is_not_null())
        .select(pl.col("sleeper_id"), pl.col("gsis_id").alias("gsis_dp"))
        .unique("sleeper_id")
    )
    df = sleeper_players.join(xwalk, on="sleeper_id", how="left").with_columns(
        pl.coalesce("gsis_dp", "gsis_id").alias("gsis_id")
    )
    df = df.drop("gsis_dp").with_columns(
        pl.when(pl.col("gsis_id").is_not_null())
        .then(pl.col("gsis_id"))
        .otherwise(pl.lit("sl:") + pl.col("sleeper_id"))
        .alias("player_id")
    )
    # A gsis id can only belong to one row; keep the most "active" one if Sleeper duplicates.
    return df.sort(["player_id", "nfl_team"], nulls_last=True).unique("player_id", keep="first")
