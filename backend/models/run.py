"""Model evaluation CLI.

    python -m models.run backtest [--seasons 2023,2024,2025] [--scoring half_ppr|ppr|standard]
    python -m models.run regression-eval [--seasons ...]
    python -m models.run tune [--seasons ...]   (last season is the holdout)
    python -m models.run tune-matchups [--seasons ...]

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
from models.regression_eval import flag_outcomes, summarize
from models.tune import tune_matchups, tune_regression, tune_thresholds, tune_weights
from projections.baseline import BaselineEngine
from projections.simple import Last3Engine, SeasonPpgEngine
from scoring.rules import PRESETS

log = logging.getLogger("fantasyedge.backtest")

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


def cmd_regression_eval(args: argparse.Namespace) -> None:
    seasons = _seasons(args.seasons)
    stats, _ = load_seasons([seasons[0] - 1, *seasons], backtest_dir(), args.refresh)
    summary = summarize(flag_outcomes(stats, PRESETS[args.scoring], seasons))
    print(f"\nRegression flags, seasons {seasons}, weeks 6-14, {args.scoring} scoring")
    print("move = next-4-week PPG minus season-to-date PPG; lift = move beyond what similar")
    print("unflagged players did, in the flagged direction (PPG); hit_adj 0.5 = coin flip\n")
    print(f"{'flag':<18}{'dir':>5}{'n':>7}{'hit_raw':>9}{'hit_adj':>9}{'lift':>7}")
    for r in summary.iter_rows(named=True):
        print(
            f"{r['kind']:<18}{r['direction']:>+5}{r['n']:>7}{r['hit_raw']:>9.0%}"
            f"{r['hit_adj']:>9.0%}{r['lift']:>7.2f}"
        )


def cmd_tune(args: argparse.Namespace) -> None:
    seasons = _seasons(args.seasons)
    train, valid = seasons[:-1], seasons[-1:]
    rules = PRESETS[args.scoring]
    stats, schedules = load_seasons([seasons[0] - 1, *seasons], backtest_dir(), args.refresh)

    print(f"\nTuning on {train}, validating on {valid} ({args.scoring})")
    w = tune_weights(stats, schedules, rules, train, valid)
    d, b = BaselineEngine(), w.best
    print("\nBaseline weights (4-week MAE, fantasy-relevant players; lower is better)")
    print(f"  default  l3={d.w_l3} season={d.w_season} usage={d.w_usage} shrink={d.shrink_games}")
    print(f"  best     l3={b.w_l3} season={b.w_season} usage={b.w_usage} shrink={b.shrink_games}")
    print(f"  train    {w.train_default:.3f} -> {w.train_best:.3f}")
    print(
        f"  holdout  {w.valid_default:.3f} -> {w.valid_best:.3f}  ({'better' if w.improves else 'not better'})"
    )

    print("\nFlag thresholds (total excess PPG = lift x flags; higher is better)")
    for r in tune_thresholds(stats, rules, train, valid):
        (vd, nd), (vb, nb) = r["valid_default"], r["valid_best"]
        print(f"  {r['kind']:<17} {r['field']}: default {r['default']} -> best {r['best']}")
        print(f"    train by value: {r['train']}")
        print(f"    holdout: default {vd:.1f} ({nd} flags) vs best {vb:.1f} ({nb} flags)")


def cmd_tune_matchups(args: argparse.Namespace) -> None:
    seasons = _seasons(args.seasons)
    train, valid = seasons[:-1], seasons[-1:]
    stats, schedules = load_seasons([seasons[0] - 1, *seasons], backtest_dir(), args.refresh)
    print(
        f"\nMatchup strength alpha per position: next-week MAE, tuned on {train}, holdout {valid}"
    )
    print("(points x (1 + alpha x (opponent index - 1)); alpha 0 = ignore the schedule)\n")

    def fmt(d: dict) -> str:
        return "  ".join(f"{a:g}:{v:.3f}" for a, v in sorted(d.items()) if v is not None)

    for r in tune_matchups(stats, schedules, PRESETS[args.scoring], train, valid):
        print(f"{r['position']:<4} train  {fmt(r['train'])}")
        print(f"     hold   {fmt(r['valid'])}")
        print(f"     rho    {fmt(r['valid_rho'])}")
        print(f"     best on train {r['best_train']:g} -> chosen {r['chosen']:g}\n")


def cmd_tune_regression(args: argparse.Namespace) -> None:
    seasons = _seasons(args.seasons)
    train, valid = seasons[:-1], seasons[-1:]
    stats, schedules = load_seasons([seasons[0] - 1, *seasons], backtest_dir(), args.refresh)
    r = tune_regression(stats, schedules, PRESETS[args.scoring], train, valid)
    print(f"Regression flags in the projection: 4-week MAE (relevant), tuned on {train}")
    for (sell, buy), mae in sorted(r["train"].items()):
        print(f"  beta_sell={sell:<5} beta_buy={buy:<5} train {mae:.4f}")
    print(
        f"best on train {r['best']}; holdout {valid}: none {r['valid_default']:.4f} "
        f"-> best {r['valid_best']:.4f}; chosen {r['chosen']}"
    )


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--seasons", help="comma-separated target seasons (default: last three)")
    p.add_argument("--scoring", choices=sorted(PRESETS), default="half_ppr")
    p.add_argument("--refresh", action="store_true", help="re-download cached seasons")


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(prog="python -m models.run")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backtest", help="walk-forward accuracy of every projection engine")
    _common(b)
    b.set_defaults(fn=cmd_backtest)
    r = sub.add_parser("regression-eval", help="do regression flags predict regression?")
    _common(r)
    r.set_defaults(fn=cmd_regression_eval)
    t = sub.add_parser("tune", help="search baseline weights and flag thresholds (holdout-checked)")
    _common(t)
    t.set_defaults(fn=cmd_tune)
    mt = sub.add_parser("tune-matchups", help="how much each position should follow its schedule")
    _common(mt)
    mt.set_defaults(fn=cmd_tune_matchups)
    tr = sub.add_parser("tune-regression", help="how much regression flags should move projections")
    _common(tr)
    tr.set_defaults(fn=cmd_tune_regression)
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
