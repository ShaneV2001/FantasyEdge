"""Model evaluation CLI.

    python -m models.run backtest [--seasons 2023,2024,2025] [--scoring half_ppr|ppr|standard]

Downloads (once, then cached) the seasons plus the season before the first, runs the walk-forward
backtest for every engine, prints a comparison and records one `model_runs` row per engine.
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import polars as pl

from app.config import get_settings
from db.conn import connect, upsert
from models.backtest import metrics, metrics_json, walk_forward
from models.data import load_seasons
from projections.baseline import BaselineEngine
from projections.simple import Last3Engine, SeasonPpgEngine
from scoring.rules import PRESETS

log = logging.getLogger("ff_edge.backtest")

ENGINES = (BaselineEngine(), SeasonPpgEngine(), Last3Engine())


def _seasons(arg: str | None) -> list[int]:
    if arg:
        return [int(s) for s in arg.split(",")]
    last = get_settings().seasons[0]  # the most recent completed (or in-progress) prior season
    return [last - 2, last - 1, last]


def backtest_dir() -> Path:
    return get_settings().data_dir / "backtest"


def comparison_table(results: dict[str, pl.DataFrame], relevant_only: bool) -> str:
    """One row per position; MAE(4wk) / Spearman / coverage for each engine side by side."""
    lines = []
    header = f"{'pos':<5}{'n':>7}" + "".join(
        f"  {name[:12]:>12} {'mae4':>6} {'rho':>5} {'cov':>5}" for name in results
    )
    lines.append(header)
    tables = {name: metrics(p, relevant_only) for name, p in results.items()}
    first = next(iter(tables.values()))
    for pos in first["position"].to_list():
        row = f"{pos:<5}{first.filter(pl.col('position') == pos)['n'][0]:>7}"
        for t in tables.values():
            r = t.filter(pl.col("position") == pos).row(0, named=True)
            rho = r["spearman"] if r["spearman"] is not None else float("nan")
            row += f"  {'':>12} {r['mae_4']:>6.2f} {rho:>5.2f} {r['coverage']:>5.0%}"
        lines.append(row)
    return "\n".join(lines)


def store_runs(rows: list[dict], out_dir: Path) -> None:
    """model_runs rows into the app store, plus a JSON copy (the store may be locked by the API)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = rows[0]["run_id"].rsplit("-", 1)[-1]
    (out_dir / f"results-{stamp}.json").write_text(json.dumps(rows, indent=1, default=str))
    try:
        con = connect(get_settings().db_path)
    except duckdb.IOException as exc:
        log.warning("store busy (is the API running?) — results saved as JSON only: %s", exc)
        return
    with con:
        upsert(con, "model_runs", pl.DataFrame(rows, infer_schema_length=None))
    log.info("recorded %d model_runs rows", len(rows))


def cmd_backtest(args: argparse.Namespace) -> None:
    seasons = _seasons(args.seasons)
    rules = PRESETS[args.scoring]
    stats, schedules = load_seasons([seasons[0] - 1, *seasons], backtest_dir(), args.refresh)
    results = {e.run_id: walk_forward(e, stats, schedules, rules, seasons) for e in ENGINES}
    print(f"\nWalk-forward backtest, seasons {seasons}, {args.scoring} scoring")
    print("mae4 = mean |projection − avg of next 4 games| · rho = weekly Spearman vs next game ·")
    print("cov = share of next-game scores inside the p10–p90 band (target 80%)\n")
    print("Fantasy-relevant players (top QB24 / RB60 / WR60 / TE24 projected each week):")
    print(comparison_table(results, relevant_only=True))
    print("\nAll projected players who played:")
    print(comparison_table(results, relevant_only=False))

    now = datetime.now(UTC).replace(tzinfo=None)
    stamp = now.strftime("%Y%m%dT%H%M%S")
    rows = [
        {
            "run_id": f"backtest-{name}-{stamp}",
            "trained_at": now,
            "model_version": name,
            "feature_version": "none",
            "train_seasons": ",".join(map(str, seasons)),
            "valid_season": seasons[-1],
            "metrics": json.dumps({"scoring": args.scoring, **metrics_json(preds)}),
            "feature_importance": None,
            "artifact_path": None,
            "is_active": name == BaselineEngine().run_id,
        }
        for name, preds in results.items()
    ]
    store_runs(rows, backtest_dir())


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(prog="python -m models.run")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backtest", help="walk-forward accuracy of every projection engine")
    b.add_argument("--seasons", help="comma-separated target seasons (default: last three)")
    b.add_argument("--scoring", choices=sorted(PRESETS), default="half_ppr")
    b.add_argument("--refresh", action="store_true", help="re-download cached seasons")
    b.set_defaults(fn=cmd_backtest)
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
