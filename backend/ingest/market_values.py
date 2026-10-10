"""Market (trade) values behind a swappable interface.

Primary: FantasyCalc (unofficial, undocumented endpoint — cached 24h, may disappear).
Fallback: DynastyProcess values CSV (joined to Sleeper IDs via the FantasyPros-ID crosswalk).
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol

import polars as pl

from ingest.http import CachedHttp, SourceUnavailable

log = logging.getLogger("ff_edge.market")

MARKET_SCHEMA = {
    "sleeper_id": pl.Utf8,
    "name": pl.Utf8,
    "position": pl.Utf8,
    "value": pl.Float64,
    "overall_rank": pl.Int64,
    "position_rank": pl.Int64,
    "trend_30d": pl.Float64,
}

DP_VALUES_URL = (
    "https://raw.githubusercontent.com/dynastyprocess/data/master/files/values-players.csv"
)


@dataclass(frozen=True)
class MarketFormat:
    num_teams: int = 12
    num_qbs: int = 1  # 2 for superflex
    ppr: float = 0.5
    is_dynasty: bool = False

    @property
    def key(self) -> str:
        kind = "dynasty" if self.is_dynasty else "redraft"
        ppr = f"{self.ppr:g}"
        return f"{kind}_{self.num_qbs}qb_{self.num_teams}_ppr{ppr}"


def market_format_for(
    roster_positions: list[str], num_teams: int, ppr: float, league_type: str = "redraft"
) -> MarketFormat:
    """The market-value format matching a league: superflex if it can start 2 QBs, dynasty
    values only for dynasty leagues (keeper leagues trade like redraft)."""
    sf = "SUPER_FLEX" in roster_positions or roster_positions.count("QB") > 1
    return MarketFormat(num_teams, 2 if sf else 1, ppr, is_dynasty=league_type == "dynasty")


class MarketValueSource(Protocol):
    name: str

    def fetch(self, fmt: MarketFormat) -> pl.DataFrame: ...


class FantasyCalcSource:
    name = "fantasycalc"

    def __init__(self, http: CachedHttp, base: str = "https://api.fantasycalc.com"):
        self.http = http
        self.base = base.rstrip("/")

    def fetch(self, fmt: MarketFormat) -> pl.DataFrame:
        params = {
            "isDynasty": str(fmt.is_dynasty).lower(),
            "numQbs": fmt.num_qbs,
            "numTeams": fmt.num_teams,
            "ppr": fmt.ppr,
        }
        raw = self.http.get_json(
            f"{self.base}/values/current", source=self.name, params=params, ttl=timedelta(hours=24)
        )
        return parse_fantasycalc(raw)


def parse_fantasycalc(raw: list[dict]) -> pl.DataFrame:
    if not isinstance(raw, list) or not raw:
        raise ValueError("FantasyCalc returned an unexpected payload")
    rows = []
    for item in raw:
        p = item.get("player") or {}
        if not p.get("sleeperId"):
            continue
        rows.append(
            {
                "sleeper_id": str(p["sleeperId"]),
                "name": p.get("name"),
                "position": p.get("position"),
                "value": float(item.get("value") or 0),
                "overall_rank": item.get("overallRank"),
                "position_rank": item.get("positionRank"),
                "trend_30d": float(item.get("trend30Day") or 0),
            }
        )
    return pl.DataFrame(rows, schema=MARKET_SCHEMA)


class DynastyProcessSource:
    """DynastyProcess values are dynasty-flavoured; good enough as a rank-order fallback."""

    name = "dynastyprocess"

    def __init__(self, http: CachedHttp, id_map: pl.DataFrame):
        self.http = http
        self.id_map = id_map

    def fetch(self, fmt: MarketFormat) -> pl.DataFrame:
        text = self.http.get(DP_VALUES_URL, source=self.name, ttl=timedelta(hours=24)).text
        return parse_dynastyprocess(text, self.id_map, superflex=fmt.num_qbs == 2)


def parse_dynastyprocess(csv_text: str, id_map: pl.DataFrame, superflex: bool) -> pl.DataFrame:
    df = pl.read_csv(io.StringIO(csv_text), infer_schema_length=0, null_values=["NA", ""])
    value_col = "value_2qb" if superflex else "value_1qb"
    xwalk = id_map.select("fantasypros_id", "sleeper_id").drop_nulls().unique("fantasypros_id")
    df = (
        df.join(xwalk, left_on="fp_id", right_on="fantasypros_id", how="inner")
        .select(
            pl.col("sleeper_id"),
            pl.col("player").alias("name"),
            pl.col("pos").alias("position"),
            pl.col(value_col).cast(pl.Float64).alias("value"),
        )
        .filter(pl.col("position").is_in(["QB", "RB", "WR", "TE"]))
        .sort("value", descending=True)
        .unique("sleeper_id", keep="first", maintain_order=True)
    )
    return df.with_columns(
        pl.col("value").rank("ordinal", descending=True).cast(pl.Int64).alias("overall_rank"),
        pl.col("value")
        .rank("ordinal", descending=True)
        .over("position")
        .cast(pl.Int64)
        .alias("position_rank"),
        pl.lit(0.0).alias("trend_30d"),
    ).select(list(MARKET_SCHEMA))


@dataclass
class MarketResult:
    source: str
    fmt: MarketFormat
    values: pl.DataFrame
    fallback_used: bool
    errors: list[str]


def get_market_values(sources: list[MarketValueSource], fmt: MarketFormat) -> MarketResult:
    """Try sources in order; first non-empty result wins. Raises if all fail."""
    errors: list[str] = []
    for i, src in enumerate(sources):
        try:
            df = src.fetch(fmt)
            if df.is_empty():
                raise ValueError("empty result")
            if i > 0:
                log.warning("market values: using fallback %s (%s)", src.name, "; ".join(errors))
            return MarketResult(src.name, fmt, df, i > 0, errors)
        except (SourceUnavailable, ValueError, KeyError, pl.exceptions.PolarsError) as exc:
            errors.append(f"{src.name}: {exc}")
            log.warning("market source %s failed: %s", src.name, exc)
    raise SourceUnavailable("market", "; ".join(errors))
