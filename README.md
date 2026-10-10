# ff-edge

An open-source fantasy football assistant: connect your league, get rest-of-season player values,
regression flags, a bye-week planner and trade ideas, all from free data sources.

> **Status:** Phase 1 — Team Advisor MVP (rule-based projections). The ML model lands in Phase 2.

## Quick start

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/), Node 20+ (pnpm via `corepack`).

```bash
cp .env.example .env
python tasks.py setup     # or: make setup
python tasks.py data      # pull Sleeper players, nflverse stats/schedules/injuries, market values
python tasks.py dev       # API on :8000, web on :5173
python tasks.py test      # ruff + pytest + vitest
```

`make <target>` works too if you have `make`; it delegates to `tasks.py`.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the stack, DuckDB schema and API contract.

## Data sources & attribution

| Source | Use | Terms |
|---|---|---|
| [Sleeper API](https://docs.sleeper.com) | Leagues, rosters, players, trending adds/drops | Free for non-commercial use. Trending data shown in the app is credited to Sleeper. |
| [nflverse](https://github.com/nflverse) via `nflreadpy` | Weekly stats, play-by-play, snaps, schedules, injuries | Data licensed **CC-BY 4.0**; FTN charting data **CC-BY-SA 4.0**. |
| [FantasyCalc](https://fantasycalc.com) | Crowd-sourced trade market values | Unofficial/undocumented endpoint; cached and optional. |
| [DynastyProcess data](https://github.com/dynastyprocess/data) | Player ID crosswalk, fallback values | Open data repository. |

No site is scraped; only public APIs and published data files are used.

## Disclaimer

ff-edge is an independent project and is **not affiliated with, endorsed by, or sponsored by** Sleeper,
ESPN, Yahoo, FantasyCalc, DynastyProcess, nflverse or the NFL. All trademarks belong to their owners.
Projections are estimates, not guarantees.

## License

MIT — see [LICENSE](LICENSE).
