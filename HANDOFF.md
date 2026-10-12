# ff-edge handoff

_Last updated 2026-10-12. Branch `main`, everything committed and pushed to `origin`
(github.com/ShaneV2001/ff-edge)._

## Where things stand

ff-edge is a local fantasy-football advisor: a FastAPI + DuckDB backend (`backend/`) and a Vite +
React frontend (`frontend/`). It connects to a Sleeper league (or a hand-entered roster) and gives
projections, rankings, buy/sell verdicts, bye planning, trade evaluation and an advisor feed.

This round of work (about 30 commits since `81d58ae`) did three things:

1. **Robustness fixes.** All 12 audit items (A1–A12) are done.
2. **Measured accuracy, and acted on it.** A walk-forward backtest drove these changes: retuned
   projections, kicker and defense projections, schedule (matchup) adjustment, and an evidence check
   on regression flags.
3. **New features.**
   - **Rankings:** schedule-adjusted, by week and rest of season.
   - **One verdict per player:** buy/hold/sell, our projection vs the market.
   - **Buy targets page.**
   - **Player pages:** headshot, projected-vs-actual chart, game log.
   - **More team grades:** K, DEF and flex slots.
   - **Settings page:** 24 tunable values in four groups, saved to `data/settings.json`.

**Tests:** 374 backend (pytest) and 28 frontend (vitest). Lint, format, typecheck and the API-client
drift check are all clean.

## Run it

```bash
python tasks.py setup      # once: uv sync + pnpm install
python tasks.py dev        # API on :8000 + web on :5173
python tasks.py data       # ingest nflverse + Sleeper (API must be stopped: DuckDB single writer)
python tasks.py test       # ruff + pytest + oxlint + tsc + vitest
python tasks.py gen-api    # regenerate frontend/src/api from the FastAPI schema
python tasks.py backtest   # walk-forward accuracy table (downloads 2022-25 once to data/backtest/)
cd backend && uv run python -m models.run {regression-eval|tune|tune-matchups|tune-regression}
```

- **Refreshing data while the API runs:** use the sidebar **Update** button or
  `POST /refresh {"scope":"all"}`. The CLI can't open the database while the API holds its lock.
- **The user's real data:** three manual teams (`mn-fb00b62d02-1`, `mn-74c67e6195-1`,
  `mn-a5ace67aff-1`), season 2026, week 5.

## How the model works now (and why)

All of the numbers below come from the backtest. The README sections "Accuracy", "Rankings", and
"One verdict per player" are the user-facing versions.

| Piece | What it does | Evidence |
|---|---|---|
| **Baseline projection** (`projections/baseline.py`) | `ppg = 0.5 × season PPG + 0.5 × usage-implied PPG`; season PPG is shrunk toward last season over 8 games | Tuned on 2023–24 and held out on 2025: fantasy-relevant 4-week MAE went from 4.08 to 3.76. Last-3-games form made it worse, so it was dropped. |
| **K / DEF** | Real stat lines (kicking from nflverse player stats; DEF built from team stats + schedule, keyed `sl:<TEAM>`), shrunk toward the position average (128 prior games) | Their weekly scoring barely predicts itself (Spearman ~0.05). Accuracy ties the old flat 8/7, but the projections now follow league scoring. |
| **Matchups** (`signals/schedule.py` `MATCHUP_ALPHA`) | Weekly points × `1 + α (opponent index − 1)`. α: QB 0.25, RB 0.5, WR 0.25, TE 0, K 0.25, DEF 0.75 | DEF weekly ranking accuracy roughly doubled (0.12 → 0.23); the other positions gained a little; TE didn't benefit. |
| **Regression flags** (`signals/regression.py`) | TD over expected, efficiency z-scores, usage vs production | Sell flags predict declines (+1.1 to +1.6 PPG lift). Buy flags are coin flips. Folding the flags into the projection did **not** help (best β = 0), because the projection already carries their signal. They are shown as reasons only. |
| **Verdict** (`signals/verdict.py`) | Gap = our schedule-adjusted ROS points − the points of the player we rank where the market ranks him. Buy/sell at ±max(10 pts, 10%), only inside the startable pool (QB24 / RB60 / WR60 / TE24) | This was a product decision with the user: "a player can't be a buy and a sell". It is computed once in `build_context` and every page and the advisor read it. The Buy targets page tiers buys by our rank vs `replacement_ranks` (starters, then depth/sleepers), each by ROS points, because sorting by gap put deep sleepers above startable players. |
| **Team grades** (`signals/team.py`) | z-scored vs the league: QB–TE, K, DEF, and each flex slot type. Needs/surplus are QB–TE only | Requested by the user. |

## Code map (what's new)

- `backend/db/migrations.py`: ordered migrations. `schema.sql` is frozen at v1; the store is at v4.
  **Every schema change goes here as a new migration.**
- `backend/app/errors.py`: `NotFound(kind)` (404 with `kind`), `InvalidInput` (422), `NotReady`.
  Any other exception is a 500 by design.
- `backend/app/services/context.py`: `build_context` is the single place that projects, scores the
  schedule, and attaches the verdict to every player. Per-league results are cached in `_cache`;
  derived results go in `ctx.memo`.
- `backend/app/user_settings.py`: `UserSettings` (defaults = the tuned constants) and load/save of
  `data/settings.json`, which holds only changed values. `LeagueContext.tuning` carries them, and
  `get_context` keys its cache on them. The backtest always runs on the defaults.
- `backend/app/services/player.py`: player page and the memoized walk-forward `past_projections`.
- `backend/signals/targets.py` (week cells / rankings), `signals/verdict.py`, `projections/matchup.py`
  and `projections/regression_adj.py` (kept for experiments; unused in the app).
- `backend/models/`: `backtest.py`, `data.py` (season cache), `regression_eval.py`, `tune.py`, and
  the `run.py` CLI.
- `frontend/src/routes/`: `rankings.tsx`, `buy-targets.tsx`, `player.tsx`, `settings.tsx` (+ tests).
  `components/player/` holds `matchups.tsx`, `PlayerLink.tsx` and `badges.tsx` (`SignalBadge` takes
  the API verdict). `lib/stale-team.ts` sends a stale saved team back to Connect.
  `test/render.tsx` renders components with a router.
- **New API routes:**
  - `GET /team/{id}/rankings`
  - `GET /team/{id}/buy-targets`
  - `GET /team/{id}/players/{player_id}`
  - `GET/PUT/DELETE /settings` (PUT takes `{key: value}` for changed fields only; 422 on unknown
    keys or out-of-range values)
  - `/team/{id}/targets` was renamed to `/rankings`.

## Gotchas (learned the hard way)

- **The uvicorn `--reload` watcher is unreliable on this Windows machine.** After backend edits,
  restart `python tasks.py dev`. Several "it didn't work" moments were just a stale server.
- **DuckDB allows one writer.** With the API up, `models.run backtest` can't write `model_runs`, so it
  saves a JSON copy to `data/backtest/results-*.json` instead.
- **Line endings.** Python `write_text` on Windows writes CRLF. Edit with
  `read_bytes().decode().replace("\r\n", "\n")` and write the bytes back.
- **Bash heredocs on this machine mangle `\n` escapes** and very long quoted scripts. For big edits,
  write a script file to the scratchpad and run it.
- **Commit attribution:** the user wants **no** `Co-Authored-By` / "Generated with" lines, and every
  commit pushed right away (`git push`).
- **Backtest data:** `data/backtest/{season}_stats_v2.parquet`. Bump `models/data.CACHE_VERSION`
  when the cached columns change.
- **Market values (FantasyCalc) cover about 200 players and no K/DEF,** so those verdicts are always
  hold. The Buy targets page explains this.
- **The current week can be partly played.** Weekly rankings for it omit finished games, and the
  player page lists a partly played week once.

## Open work (prioritized)

These are what's left of the original audit (Sprints 3–5) plus things noticed along the way. Keep the
rule that model changes ship only if the backtest's 2025 holdout improves.

1. **Opportunity-quality features (audit B3):** snap share, WOPR, air yards and goal-line carries
   are ingested but unused. Test each in `BaselineEngine` via `models.run backtest` and `tune`.
2. **Practice status (B3) and injury-shortened games (B5):** the `injuries` table is never read, and
   games a player left early drag his averages down.
3. **Empirical (skewed) p10–p90 bands (B5).** Coverage is 79% today, but the band is symmetric
   while fantasy scoring is right-skewed.
4. **Rookie / no-history prior (B6):** these players project 0 until they play. A market-implied
   prior would fix it. This also produced odd deep-WR buy gaps before the startable-pool rule.
5. **Waivers and trades (audit C):**
   - FAAB bid ranges and trending adds/drops (the `trending` table is never read)
   - bench-upgrade waivers
   - trades that account for roster spots (2-for-1 deals)
   - the danger-week check is skipped on suggested trades (`trade.py` doesn't pass `viable_ppg`)
6. **Operations (audit D):**
   - GitHub Actions CI (ruff, pytest, oxlint, tsc, vitest, gen-api drift)
   - background refresh jobs with progress
   - incremental play-by-play downloads
   - a data-freshness panel and a multi-team switcher
   - pruning the HTTP cache
7. **Small items:**
   - The flag-threshold search (`models.run tune`) favored the loosest values. They were
     deliberately left unchanged (more flags, less lift each).
   - `regression_adj.py` is an unused experiment; delete it if it's still unused later.

## Verify a change end to end

1. Run `python tasks.py test`, then `python tasks.py gen-api` and check `git diff frontend/src/api`
   is empty.
2. Restart `python tasks.py dev` and check:
   - `curl localhost:8000/team/mn-fb00b62d02-1/rankings`
   - `curl localhost:8000/team/mn-fb00b62d02-1/buy-targets`
   - `curl localhost:8000/team/mn-fb00b62d02-1/players/00-0038542`
3. In a browser, open My Team, Rankings, Buy targets and a player page, and check the console has no
   errors. Earlier sessions drove Chrome with `playwright-core` installed in the scratchpad, not in
   the repo.
4. For model changes, run `python tasks.py backtest` (stop the API to record `model_runs`) and
   compare against the README Accuracy table.
