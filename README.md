# ff-edge

**An open-source fantasy football assistant that tells you what to do with your team, and shows its work.**

Connect your Sleeper league (or enter a roster by hand) and ff-edge gives you:

- **An advisor feed**: a ranked list of 5–10 concrete moves (trade, sell, buy, waiver, lineup, bye prep), each with the numbers behind it, an urgency and a confidence level.
- **A regression report**: who is scoring on unsustainable touchdowns or efficiency, and who is due to bounce back.
- **A bye-week planner**: a week-by-week grid of which lineup slots you can and can't fill, with "danger weeks" flagged before they arrive.
- **Trade ideas and a trade analyzer**: 1-for-1 and 2-for-1 deals where *both* teams' starting lineups improve, judged on rest-of-season lineup points rather than raw player value.
- **Rest-of-season player values** computed under *your* league's scoring rules.

Everything runs locally on free, public data. There are no accounts, API keys or paid services.

> **Project status: Phase 1 (Team Advisor MVP), in progress.**
> The backend (ingestion, projections, regression, byes, trades, advisor) is built and tested.
> The API and web UI are being wired up now. Projections are rule-based in Phase 1; an ML model
> replaces them in Phase 2, but only if it beats the baselines (see [Roadmap](#roadmap)).

---

## Contents

- [How it works](#how-it-works)
- [Quick start](#quick-start)
- [Project layout](#project-layout)
- [API](#api)
- [Data sources & attribution](#data-sources--attribution)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [Disclaimer](#disclaimer) · [License](#license)

---

## How it works

Every number in ff-edge comes from a formula you can read and change. The constants live at the
top of each module, and nothing is hidden inside a model.

### League-aware scoring
Your Sleeper `scoring_settings` (PPR level, TE premium, passing TD value, etc.) are read directly, and
every historical stat line is re-scored under those rules. The same player has a different value in a
PPR league than in a standard one. Manual leagues can pick Standard, Half-PPR or PPR.

### Phase 1 projection
```
projected PPG = 0.5 × last-3-game PPG + 0.3 × season PPG + 0.2 × usage-implied PPG
```
- **Usage-implied PPG** = recent targets, carries and pass attempts × the positional league-average
  points per opportunity, plus expected touchdowns from where the opportunities happened (red zone
  vs. elsewhere).
- Early in the season (< 4 games), season PPG is blended with last season's.
- **Rest-of-season points** = projected PPG × the games left, skipping the bye, games already played
  this week, and expected missed time (Out this week; IR/PUP assumed out 4 more weeks).
- **ROS value** = points above replacement at the player's position, for your league size and
  lineup slots (FLEX and SUPER_FLEX are counted as a position mix).
- A 10th–90th percentile band comes from each player's week-to-week volatility.

### Regression flags
| Signal | Rule | Example message |
|---|---|---|
| TD over expected | Expected TDs = red-zone opportunities × positional red-zone TD rate + other opportunities × non-red-zone rate. A gap of **≥ +2** means "due to cool off"; **≤ −2** means "due to bounce back". | "5 TDs on 11 red-zone touches (72 total opportunities); expected ~2.2. Likely to slow down." |
| Efficiency outliers | Yards per carry (≥ 30 carries), yards per target and catch rate (≥ 20 targets), and fantasy points per opportunity, as z-scores against positional norms. **\|z\| ≥ 1.5** is flagged. | "6.2 yards per carry vs RB norm 4.2 (z = +2.2, 87 carries). Expect it to drift down." |
| Usage vs production | Share of team opportunities over the last 4 games vs points scored. Rising usage with falling points means production should catch up; falling usage with steady points is a warning sign. | "Opportunity share up from 15% to 30% over the last 4 games while points went 9.0 → 4.0." |

### Bye-week planner
Bye weeks come straight from the NFL schedule: a team's bye is the week it has no game. For every
remaining week, ff-edge builds your best legal lineup from the players available that week and marks
each slot **ok**, **thin** (only a below-replacement option) or **empty**. A **danger week** is
one where a slot is worse than it is at full strength, so a position that's weak all season doesn't
flag every week.

### Trades
Each trade is scored by its effect on **both teams' rest-of-season starting-lineup points**,
recomputed week by week with byes and injuries included. Model value and FantasyCalc market value are
shown alongside. The trade finder only suggests deals where both sides gain and the market values
are close enough that the other manager might accept. Trade advice is hidden once your league's
trade deadline passes.

### The advisor feed
Candidate actions are ranked by:
```
priority = urgency weight × impact × confidence weight
```
- **Urgency weights:** this week 3.0 · before byes 2.2 · before deadline 1.6 · rest of season 1.0
- **Confidence** reflects how many independent signals agree.
- **Sell** candidates need negative regression, optionally backed by a market rank well above our
  projection, an upcoming bye or a tough schedule.
- **Buy** targets sit at your weakest positions, show positive regression or are undervalued by
  the market, and ideally belong to teams with depth to spare there.

---

## Quick start

**Requirements:** Python 3.11+, [uv](https://docs.astral.sh/uv/), Node 20+ (pnpm comes via `corepack`).

```bash
git clone <this repo> ff-edge && cd ff-edge
cp .env.example .env

python tasks.py setup   # install backend (uv) and frontend (pnpm) dependencies
python tasks.py data    # pull Sleeper players, nflverse stats/schedules/injuries, market values
python tasks.py dev     # API on http://localhost:8000, web app on http://localhost:5173
```

| Command | What it does |
|---|---|
| `python tasks.py data` | Refresh all data (≈15 MB Sleeper player map at most once/day, nflverse files, market values) |
| `python tasks.py test` | `ruff` lint/format check, `pytest` (offline, recorded fixtures), frontend tests |
| `python tasks.py api` / `web` | Run the API or the web app on its own |
| `python tasks.py gen-api` | Regenerate the typed TypeScript client from the API's OpenAPI schema |

If you have `make`, the same targets work as `make setup`, `make data`, `make dev`, `make test`.

All data lives in `data/` (gitignored): a single DuckDB file plus an HTTP response cache.

---

## Project layout

```
backend/
  app/          FastAPI app, Pydantic schemas, services (league sync, cached league context)
  ingest/       sleeper.py, nflverse.py, market_values.py, idmap.py, http.py (retry + cache)
  db/           DuckDB schema
  scoring/      league scoring rules → fantasy points
  projections/  engine interface, phase-1 baseline, positional norms
  signals/      regression, byes, lineup optimizer, team grades, trades, advisor
  tests/        unit + API tests on recorded fixtures (no live network calls)
frontend/       Vite + React + TypeScript + shadcn/ui
scripts/        fixture recorder
```

[ARCHITECTURE.md](ARCHITECTURE.md) is the source of truth for the stack, database schema, API
contract and frontend structure.

---

## API

FastAPI serves interactive docs at `http://localhost:8000/docs`. Phase 1 endpoints:

| Method | Path | Purpose |
|---|---|---|
| POST | `/league/connect` | Sleeper username → your leagues and teams |
| POST | `/league/{id}/select-team` | Mark which team is yours |
| POST | `/league/manual` | Create a league from a hand-entered roster |
| GET | `/team/{id}` | Roster with projections, values, grades by position |
| GET | `/team/{id}/advice` | Ranked advisor feed + team grade |
| GET | `/team/{id}/regression` | Regression flags for your roster and the league |
| GET | `/team/{id}/byes` | Week × slot bye grid and danger weeks |
| POST | `/trade/evaluate` | Score a proposed trade for both sides |
| GET | `/trade/suggest` | Mutually beneficial trade ideas |
| POST | `/refresh` | Re-sync league, market or all data |
| GET | `/meta/status` | Last sync time per source, current NFL week |

---

## Data sources & attribution

| Source | Used for | Terms |
|---|---|---|
| [Sleeper API](https://docs.sleeper.com) | Leagues, rosters, players, trending adds/drops | Free for non-commercial use. ff-edge stays far below the rate limit and fetches the player map at most once per day. Trending data is credited to Sleeper wherever it's shown. |
| [nflverse](https://github.com/nflverse) via [`nflreadpy`](https://github.com/nflverse/nflreadpy) | Weekly stats, play-by-play (red-zone splits), snap counts, schedules, injuries | Data licensed **CC-BY 4.0**; FTN charting data **CC-BY-SA 4.0**. |
| [FantasyCalc](https://fantasycalc.com) | Crowd-sourced trade market values | Unofficial endpoint, cached for 24 h; the app falls back gracefully if it changes. |
| [DynastyProcess data](https://github.com/dynastyprocess/data) | Player ID crosswalk (Sleeper ↔ nflverse ↔ ESPN/Yahoo), fallback market values | Open data repository. |

ff-edge does not scrape any website. It uses only public APIs and published data files.

---

## Roadmap

| Phase | Scope | Status |
|---|---|---|
| 1 | **Team Advisor MVP**: ingestion, rule-based projections, regression report, bye planner, trade analyzer/finder, advisor feed; Connect, Advisor, My Team, Byes and Trade pages | 🚧 in progress |
| 2 | **Model v1**: leakage-safe features, LightGBM with quantile bands, walk-forward evaluation vs. season-PPG and last-3 baselines; swapped in only if it beats both | planned |
| 3 | Rest of the API: players, start/sit, waivers, buy/sell signals board, model report | planned |
| 4 | Rest of the UI: players table, player pages, waivers, start/sit, signals, model transparency page | planned |
| 5 | ESPN + Yahoo connectors, daily GitHub Actions refresh, Docker Compose, screenshots | planned |

---

## Contributing

Issues and pull requests are welcome. Please:
- run `python tasks.py test` before opening a PR. Tests must pass offline, against fixtures.
- keep feature and signal functions small, typed and pure, and include unit tests.
- never commit secrets. Use `.env` (see `.env.example`).
- respect each data source's terms and rate limits, and route HTTP through `ingest/http.py`.

---

## Disclaimer

ff-edge is an independent project and is **not affiliated with, endorsed by, or sponsored by**
Sleeper, ESPN, Yahoo, FantasyCalc, DynastyProcess, nflverse or the NFL. All trademarks belong to their
respective owners. Projections are estimates, not guarantees. Use them to inform your decisions, not
to make them for you.

## License

[MIT](LICENSE)
