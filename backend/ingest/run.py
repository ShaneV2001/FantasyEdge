"""Sync jobs: players_sync, stats_sync, market_sync, trending_sync.

CLI: `uv run python -m ingest.run [all|players|stats|market|trending]`
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime

import duckdb
import polars as pl

from app.config import Settings, get_settings
from db.conn import connect, log_sync, query_df, replace_where, transaction, upsert
from ingest import espn, idmap, nflverse, sleeper
from ingest.http import CachedHttp, SourceUnavailable
from ingest.market_values import (
    DynastyProcessSource,
    FantasyCalcSource,
    MarketFormat,
    get_market_values,
)

log = logging.getLogger("fantasyedge.ingest")


@dataclass
class Clients:
    http: CachedHttp
    sleeper: sleeper.SleeperClient
    settings: Settings
    _id_map: pl.DataFrame | None = None
    espn: espn.EspnClient | None = None

    def __post_init__(self) -> None:
        if self.espn is None:
            self.espn = espn.EspnClient(self.http)

    def id_map(self) -> pl.DataFrame:
        if self._id_map is None:
            self._id_map = idmap.fetch_id_map(self.http)
        return self._id_map


def make_clients(settings: Settings | None = None) -> Clients:
    settings = settings or get_settings()
    http = CachedHttp(settings.cache_dir)
    return Clients(http, sleeper.SleeperClient(http, settings.sleeper_base), settings)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def players_sync(con: duckdb.DuckDBPyConnection, c: Clients, force: bool = False) -> int:
    return write_players(con, fetch_players(c, force))


def fetch_players(c: Clients, force: bool = False) -> pl.DataFrame:
    """Sleeper's player list in the `players` table's shape (network only, no database)."""
    raw = c.sleeper.players(force=force)
    df = idmap.attach_internal_ids(sleeper.parse_players(raw), c.id_map())
    df = df.select(
        "player_id",
        "sleeper_id",
        "espn_id",
        "yahoo_id",
        pl.lit(None, pl.Utf8).alias("fantasycalc_id"),
        "full_name",
        "position",
        "nfl_team",
        pl.col("birth_date").str.to_date(strict=False),
        pl.col("years_exp").cast(pl.Int32),
        "status",
        pl.col("depth_chart_order").cast(pl.Int32),
        "injury_status",
        "injury_body_part",
        "injury_notes",
        pl.col("injury_start_date").str.to_date(strict=False),
        pl.lit(_now()).alias("updated_at"),
    )
    return df


def write_players(con: duckdb.DuckDBPyConnection, df: pl.DataFrame) -> int:
    changes = status_changes(query_df(con, "SELECT player_id, injury_status FROM players"), df)
    with transaction(con):  # full replace: all-or-nothing so a failed insert keeps the old table
        n = replace_where(con, "players", df, "TRUE", [])
        if not changes.is_empty():
            upsert(con, "injury_status_log", changes)
        log_sync(con, "sleeper_players", "ok", f"{n} players")
    return n


def status_changes(old: pl.DataFrame, new: pl.DataFrame) -> pl.DataFrame:
    """Players whose injury status differs from the last refresh, as injury_status_log rows.
    The first refresh (no previous players) logs nothing: every status would look new."""
    if old.is_empty():
        return pl.DataFrame()
    joined = new.select("player_id", "injury_status").join(
        old.select("player_id", pl.col("injury_status").alias("was")), on="player_id", how="inner"
    )
    changed = joined.filter(pl.col("injury_status").ne_missing(pl.col("was")))
    return changed.select(
        "player_id", pl.col("injury_status").alias("status"), pl.lit(_now()).alias("seen_at")
    )


def stats_sync(con: duckdb.DuckDBPyConnection, c: Clients) -> dict[str, int]:
    return write_nflverse(con, c, fetch_nflverse(c))


def fetch_nflverse(c: Clients) -> dict[str, pl.DataFrame]:
    """Stats, schedule and injuries for the configured seasons (network only, no database)."""
    first, last = c.settings.seasons
    return nflverse.load_all(list(range(first, last + 1)), c.id_map())


def write_nflverse(
    con: duckdb.DuckDBPyConnection, c: Clients, tables: dict[str, pl.DataFrame]
) -> dict[str, int]:
    first, last = c.settings.seasons
    counts = {}
    with transaction(con):  # every table or none: downloads are done, only writes happen here
        for table, df in tables.items():
            con.execute(f"DELETE FROM {table} WHERE season BETWEEN ? AND ?", [first, last])
            counts[table] = upsert(con, table, df)
        log_sync(con, "nflverse", "ok", ", ".join(f"{k}={v}" for k, v in counts.items()))
    return counts


def market_sync(
    con: duckdb.DuckDBPyConnection, c: Clients, fmt: MarketFormat | None = None
) -> dict:
    fmt = fmt or MarketFormat()
    sources = [FantasyCalcSource(c.http, c.settings.fantasycalc_base)]
    if c.settings.market_source == "dynastyprocess":
        sources = []
    sources.append(DynastyProcessSource(c.http, c.id_map()))
    try:
        result = get_market_values(sources, fmt)
    except SourceUnavailable as exc:
        log_sync(con, "market", "error", exc.detail)
        raise
    players = query_df(con, "SELECT player_id, sleeper_id FROM players")
    df = result.values.join(players, on="sleeper_id", how="inner").select(
        "player_id",
        pl.lit(result.source).alias("source"),
        pl.lit(date.today()).alias("snapshot_date"),
        pl.lit(fmt.key).alias("format"),
        "value",
        pl.col("overall_rank").cast(pl.Int32),
        pl.col("position_rank").cast(pl.Int32),
        "trend_30d",
    )
    upsert(con, "market_values", df)
    status = "stale" if result.fallback_used else "ok"
    log_sync(con, "market", status, f"{result.source} {fmt.key}: {df.height} values")
    return {"source": result.source, "format": fmt.key, "rows": df.height}


def trending_sync(con: duckdb.DuckDBPyConnection, c: Clients, hours: int = 24) -> int:
    players = query_df(con, "SELECT player_id, sleeper_id FROM players")
    frames = []
    for kind in ("add", "drop"):
        raw = c.sleeper.trending(kind, lookback_hours=hours, limit=50)
        frames.append(
            pl.DataFrame(
                [{"sleeper_id": str(r["player_id"]), "count": int(r["count"])} for r in raw],
                schema={"sleeper_id": pl.Utf8, "count": pl.Int64},
            ).with_columns(pl.lit(kind).alias("kind"))
        )
    df = (
        pl.concat(frames)
        .join(players, on="sleeper_id", how="inner")
        .select(
            "player_id",
            "kind",
            pl.col("count").cast(pl.Int32),
            pl.lit(hours, pl.Int32).alias("lookback_hours"),
            pl.lit(_now()).alias("fetched_at"),
        )
    )
    with transaction(con):
        replace_where(con, "trending", df, "lookback_hours = ?", [hours])
        log_sync(con, "sleeper_trending", "ok", f"{df.height} rows")
    return df.height


def main(argv: list[str]) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    job = argv[1] if len(argv) > 1 else "all"
    c = make_clients()
    con = connect(c.settings.db_path)
    if job in ("all", "players"):
        log.info("players_sync: %s players", players_sync(con, c))
    if job in ("all", "stats"):
        log.info("stats_sync: %s", stats_sync(con, c))
    if job in ("all", "market"):
        log.info("market_sync: %s", market_sync(con, c))
    if job in ("all", "trending"):
        log.info("trending_sync: %s rows", trending_sync(con, c))
    con.close()


if __name__ == "__main__":
    main(sys.argv)
