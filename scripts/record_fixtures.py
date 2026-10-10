"""Record small, trimmed fixtures for offline tests from the local cache/DB.

Run after `python tasks.py data`:  cd backend && uv run python ../scripts/record_fixtures.py

* Real responses (trimmed): Sleeper state/trending/players subset, FantasyCalc, DynastyProcess.
* Synthetic league: a 4-team Sleeper-shaped league drafted from real players with fake owners —
  we never commit anyone's real league.
* DB slices (parquet): player_week_stats / nfl_games / injuries for the fixture players.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from db.conn import connect  # noqa: E402
from ingest.idmap import DP_IDS_URL  # noqa: E402
from ingest.market_values import DP_VALUES_URL  # noqa: E402
from ingest.run import make_clients  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "backend" / "tests" / "fixtures"
SEASON = 2026
ROSTER_POSITIONS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "SUPER_FLEX", "K", "DEF"] + [
    "BN"
] * 6
NEEDS = {"QB": 2, "RB": 4, "WR": 5, "TE": 2, "K": 1, "DEF": 1}


def dump(name: str, data) -> None:
    (OUT / name).write_text(json.dumps(data, indent=1), encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    c = make_clients()
    con = connect(c.settings.db_path)

    dump("sleeper_state.json", c.sleeper.state())
    dump("sleeper_trending_add.json", c.sleeper.trending("add", 24, 10))

    fc = c.http.get_json(
        f"{c.settings.fantasycalc_base}/values/current",
        source="fantasycalc",
        params={"isDynasty": "false", "numQbs": 1, "numTeams": 12, "ppr": 0.5},
    )
    by_pos: dict[str, list] = {}
    for item in fc:
        by_pos.setdefault(item["player"]["position"], []).append(item)
    fc_trim = [i for pos in ("QB", "RB", "WR", "TE") for i in by_pos.get(pos, [])[:24]]
    dump("fantasycalc_values.json", fc_trim)

    # ---- synthetic league drafted from real players (snake by FantasyCalc value) -----------
    pool = sorted(fc_trim, key=lambda i: -i["value"])
    teams: list[list[str]] = [[] for _ in range(4)]
    counts = [dict.fromkeys(NEEDS, 0) for _ in range(4)]
    order = [0, 1, 2, 3, 3, 2, 1, 0]
    pick = 0
    while pool and pick < 400 and any(sum(c_.values()) < sum(NEEDS.values()) - 2 for c_ in counts):
        t = order[pick % 8]
        pick += 1
        for i, item in enumerate(pool):
            pos = item["player"]["position"]
            if counts[t][pos] < NEEDS[pos]:
                teams[t].append(str(item["player"]["sleeperId"]))
                counts[t][pos] += 1
                pool.pop(i)
                break
    # kickers / defenses straight from Sleeper ids
    ks = [
        r[0]
        for r in con.execute(
            "SELECT sleeper_id FROM players WHERE position='K' AND nfl_team IS NOT NULL "
            "AND status='Active' ORDER BY sleeper_id LIMIT 4"
        ).fetchall()
    ]
    defs = ["BUF", "BAL", "PHI", "DEN"]
    for t in range(4):
        teams[t] += [ks[t], defs[t]]

    owners = ["Alpha", "Bravo", "Charlie", "Delta"]
    users = [
        {"user_id": f"u{i}", "display_name": f"{o}Manager", "metadata": {"team_name": f"Team {o}"}}
        for i, o in enumerate(owners)
    ]
    rosters = [
        {
            "roster_id": i + 1,
            "owner_id": f"u{i}",
            "players": ps,
            "starters": ps[:10],
            "reserve": [],
            "taxi": None,
            "settings": {"wins": 2 + i % 2, "losses": 2 - i % 2, "fpts": 400 + 10 * i,
                         "fpts_decimal": 50, "waiver_budget_used": 10 * i},
        }
        for i, ps in enumerate(teams)
    ]
    league = {
        "league_id": "999000111",
        "name": "Fixture League",
        "season": str(SEASON),
        "status": "in_season",
        "total_rosters": 4,
        "roster_positions": ROSTER_POSITIONS,
        "scoring_settings": {"pass_yd": 0.04, "pass_td": 4, "pass_int": -1, "rush_yd": 0.1,
                             "rush_td": 6, "rec": 0.5, "rec_yd": 0.1, "rec_td": 6,
                             "fum_lost": -2, "rush_2pt": 2, "rec_2pt": 2, "pass_2pt": 2},
        "settings": {"num_teams": 4, "trade_deadline": 11, "waiver_type": 2,
                     "waiver_budget": 100, "playoff_week_start": 15},
    }
    dump("sleeper_league.json", league)
    dump("sleeper_rosters.json", rosters)
    dump("sleeper_users.json", users)
    dump("sleeper_user.json", {"user_id": "u0", "username": "alphamanager",
                               "display_name": "AlphaManager"})
    dump("sleeper_leagues.json", [league])

    all_ids = {p for ps in teams for p in ps}
    raw_players = c.sleeper.players()
    dump("sleeper_players.json", {k: v for k, v in raw_players.items() if k in all_ids})

    # ---- DynastyProcess (header + rows for fixture players) ----------------------------------
    ids_text = c.http.get(DP_IDS_URL, source="dynastyprocess").text
    ids = pl.read_csv(io.StringIO(ids_text), infer_schema_length=0, null_values=["NA", ""])
    ids_sub = ids.filter(pl.col("sleeper_id").is_in(list(all_ids)))
    ids_sub.write_csv(OUT / "dp_playerids.csv", null_value="NA")
    vals_text = c.http.get(DP_VALUES_URL, source="dynastyprocess").text
    vals = pl.read_csv(io.StringIO(vals_text), infer_schema_length=0, null_values=["NA", ""])
    vals.filter(pl.col("fp_id").is_in(ids_sub["fantasypros_id"].drop_nulls().to_list())).write_csv(
        OUT / "dp_values.csv", null_value="NA"
    )

    # ---- DB slices --------------------------------------------------------------------------
    gsis = ids_sub["gsis_id"].drop_nulls().to_list()
    con.execute("SELECT * FROM player_week_stats").pl().write_parquet(
        OUT / "player_week_stats.parquet"
    )
    con.execute("SELECT * FROM nfl_games").pl().write_parquet(OUT / "nfl_games.parquet")
    con.execute("SELECT * FROM injuries WHERE season = ?", [SEASON]).pl().filter(
        pl.col("player_id").is_in(gsis)
    ).write_parquet(OUT / "injuries.parquet")
    print(f"fixtures written to {OUT}")


if __name__ == "__main__":
    main()
