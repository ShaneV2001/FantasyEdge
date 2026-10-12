# Settings page: user-adjustable model weights and thresholds

_2026-10-11. Status: approved design, not yet implemented._

## Why

The project is going open source (as **FantasyEdge**; the rename is a separate step). People who try
it will want to tune the model to their own opinions. Today every weight is a hard-coded constant.
Settings must be easy to share (paste into an issue, ship presets), survive a database reset, and
never let a bad value crash the app.

## Decisions

- **Scope:** one set of settings for the whole install. League rules (scoring, roster, team count)
  stay per league, as now.
- **Storage:** `data/settings.json` (already git-ignored via `data/`), not DuckDB. It holds **only
  values that differ from the defaults**, so future default changes still reach users.
- **Groups exposed:** projections, buy/sell & targets, injuries, advisor & trades.
- **The backtest keeps using defaults.** ("Backtest my settings" is a possible later feature.)

## Settings

Defaults are today's constants. Each field has a label, help text, min and max.

| Group | Key | Default | Range | Replaces |
|---|---|---|---|---|
| Projections | `usage_weight` | 0.5 | 0–1 | `W_USAGE`; season weight = 1 − this (`W_L3` stays 0) |
| Projections | `shrink_games` | 8 | 0–17 | `SHRINK_GAMES` |
| Projections | `matchup_alpha_{qb,rb,wr,te,k,def}` | .25/.5/.25/0/.25/.75 | 0–1.5 | `MATCHUP_ALPHA` |
| Buy/sell | `gap_min_points` | 10 | 0–50 | `GAP_MIN_POINTS` |
| Buy/sell | `gap_min_share` | 0.10 | 0–0.5 | `GAP_MIN_SHARE` |
| Buy/sell | `startable_{qb,rb,wr,te}` | 24/60/60/24 | 1–100 | `STARTABLE_RANK` (K/DEF stay fixed) |
| Buy/sell | `targets_per_tier` | 10 | 3–25 | `top` in `buy_targets_view` |
| Injuries | `play_chance_questionable` | 0.85 | 0–1 | `STATUS_THIS_WEEK["Questionable"]` |
| Injuries | `play_chance_doubtful` | 0.25 | 0–1 | `STATUS_THIS_WEEK["Doubtful"]` |
| Injuries | `ir_weeks_out` | 4 | 0–17 | `IR_WEEKS_MISSED` |
| Advisor | `waiver_min_gain` | 1.5 | 0–10 | `WAIVER_MIN_GAIN` |
| Advisor | `start_sit_min_gain` | 1.0 | 0–10 | `START_SIT_MIN_GAIN` |
| Advisor | `easy_schedule` | 1.08 | 1.0–1.3 | `EASY_SCHEDULE` |
| Advisor | `tough_schedule` | 0.92 | 0.7–1.0 | `TOUGH_SCHEDULE` |
| Trades | `trade_accept_gain` | 8.0 | 0–50 | `ACCEPT_GAIN` |
| Trades | `trade_lean_gain` | 2.0 | 0–50, must be ≤ accept | `LEAN_GAIN` |

Projection fields are labelled "tuned by backtest" so users know the defaults are measured.

## Components

**`backend/app/user_settings.py`**: a pydantic `UserSettings` model with flat keys (named so it doesn't clash with the env config `app.config.Settings`) (fields above, `Field(ge, le,
description)`, a validator for lean ≤ accept), plus:
- `load(path) -> (Settings, warning | None)`. A missing file gives defaults. Unreadable JSON or
  invalid values give defaults plus a warning string; it never raises.
- `save(path, settings)` writes only the non-default values (`model_dump(exclude_defaults=True)`),
  through a temp file and then a rename, so the file is never half-written.
- `schema()`: per field, the key, group, label, help, default, min, max and current value.

**API (`backend/app/routes/settings.py`)**
- `GET /settings` returns the values, the per-field schema and any warning.
- `PUT /settings` takes a partial update, validates it (422 on a bad value), saves it, clears the
  league context cache and returns the new state.
- `DELETE /settings` deletes the file (back to defaults) and clears the cache.

**Plumbing.** The settings are passed explicitly; no module globals are mutated.
- `build_context` loads the settings once and stores them on `LeagueContext.settings`. The cache
  key includes a settings hash, so a saved change always rebuilds.
- `BaselineEngine(w_season=1-u, w_usage=u, shrink_games=...)`, which already has these
  parameters.
- `all_cells(..., alpha=settings.matchup_alpha)`. `player.py` also uses `MatchupAdjusted(ENGINE,
  alpha)` with the settings, and the Rankings view shows the alpha from the settings.
- `availability()` / `availability_note()` get an optional `InjuryAssumptions` argument whose
  defaults are the current constants. Callers in the app pass the settings, and the backtest
  passes nothing.
- `verdict.signal_for` / `threshold` / `value_players` take `gap_min_points`, `gap_min_share`
  and `startable`.
- The advisor and trade functions take the relevant thresholds as parameters with the current
  defaults.

**Frontend (`frontend/src/routes/settings.tsx`)**: a "Settings" sidebar link with one card per
group, built from the `GET /settings` schema (number inputs). Each field
shows "default X" and a reset link when changed. Projection cards carry the backtest note. The page
has **Save** (PUT, then invalidate all queries), **Reset all** (DELETE, with a confirm) and a warning
banner when the file was invalid. Client-side ranges come from the schema; the server stays
authoritative.

## Errors

- A broken `settings.json` gives defaults plus a banner. The app keeps working, and saving
  overwrites the bad file.
- An out-of-range or inconsistent PUT gives a 422 (`InvalidInput`) with the field name, shown
  inline.
- A failed write surfaces as a 500, and the old file is unchanged (temp file, then rename).

## Testing

- `load`/`save`: round trip, only non-defaults written, missing file, bad JSON, out-of-range
  values (each falls back with a warning).
- API: GET shape, PUT 422 on bad values and on lean > accept, DELETE resets.
- Behaviour: raising `gap_min_points` reduces the number of buy verdicts; `usage_weight=0`
  changes projections; `play_chance_questionable` changes a Questionable player's weekly points.
- The backtest output is unchanged (it uses defaults).
- Frontend: the page renders the groups from the schema, editing then saving calls PUT, and reset
  restores the default.

## Out of scope

Per-league settings, presets UI, "backtest my settings", K/DEF startable ranks, flex shares,
regression flag thresholds, the rename and release prep.
