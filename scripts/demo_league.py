"""Build a demo database with a fictional 10-team league, for screenshots and trying the app.

    python tasks.py demo          # builds data/demo/ff.duckdb, then runs the app on it

The demo copies the public data (players, NFL stats and schedules, market values, trending adds)
from data/ff.duckdb, then deletes every league, team, roster, credential and log from the copy and
adds "Demo League": made-up team names, rosters from a seeded snake draft by market value. Nothing
from your own leagues survives, and the script checks that before it finishes. Stop
`python tasks.py dev` first: the API holds a lock on the database.
"""

from __future__ import annotations

import json
import os
import random
import re
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

import duckdb  # noqa: E402
import polars as pl  # noqa: E402

from app.services.leagues import ensure_profile  # noqa: E402
from db.conn import connect, transaction, upsert  # noqa: E402
from scoring.rules import PRESETS, describe  # noqa: E402

SRC = REPO / "data" / "ff.duckdb"
DEST = REPO / "data" / "demo" / "ff.duckdb"
LEAGUE_ID = "demo-league"
SEED = 2026
ROSTER = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF", *["BN"] * 6, "IR"]
MY_PICK = 4  # draft slot of "your" team (0-based): mid-round, so it's neither stacked nor weak
TEAMS = [
    "Touchdown Turtles", "Gridiron Gurus", "Fourth & Long", "Hail Mary Heroes", "Demo Team",
    "Red Zone Rebels", "Blitz Brigade", "End Zone Express", "Pigskin Prophets", "Sunday Scaries",
]  # fmt: skip
CAPS = {"QB": 2, "RB": 6, "WR": 6, "TE": 2}
NEEDS = {"QB": 1, "RB": 2, "WR": 2, "TE": 1}
SKILL_ROUNDS = 13  # + one K and one DEF = 15 players: a full active roster (9 starters + 6 bench)


def copy_store(src: Path, dest: Path) -> None:
    if not src.exists():
        sys.exit(f"{src} not found: run `python tasks.py data` first.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    for f in (dest, dest.with_suffix(".duckdb.wal")):
        f.unlink(missing_ok=True)
    try:
        shutil.copyfile(src, dest)
        wal = src.with_suffix(".duckdb.wal")
        if wal.exists():
            shutil.copyfile(wal, dest.with_suffix(".duckdb.wal"))
    except PermissionError:
        sys.exit("data/ff.duckdb is locked: stop `python tasks.py dev`, then run this again.")


def wipe_leagues(con: duckdb.DuckDBPyConnection) -> None:
    """Delete everything tied to a league or team, plus logs and scoring-profile names."""
    scoped = {
        t
        for (t,) in con.execute(
            """SELECT DISTINCT table_name FROM information_schema.columns
               WHERE column_name IN ('league_id', 'team_id')"""
        ).fetchall()
    }
    for table in sorted(scoped | {"league_credentials", "sync_log", "scoring_profiles"}):
        con.execute(f'DELETE FROM "{table}"')


def market_format(con: duckdb.DuckDBPyConnection) -> tuple[str, int, float]:
    """The stored 1-QB redraft market format with the most values (closest to 10 teams)."""
    rows = con.execute(
        "SELECT format, count(*) FROM market_values WHERE value IS NOT NULL GROUP BY format"
    ).fetchall()
    best = None
    for fmt, n in rows:
        m = re.fullmatch(r"redraft_1qb_(\d+)_ppr([\d.]+)", fmt or "")
        if m:
            key = (n >= 150, -abs(int(m[1]) - 10), n)
            if best is None or key > best[0]:
                best = (key, fmt, int(m[1]), float(m[2]))
    if best is None:
        sys.exit("No 1-QB redraft market values stored: connect any league once, then retry.")
    return best[1], best[2], best[3]


DRAFT_NOISE = 0.45  # sd of the log draft-day value around today's market value


def draft(con: duckdb.DuckDBPyConnection, fmt: str, n_teams: int) -> list[list[str]]:
    """A snake draft by a noisy "draft-day" value, not today's: drafting by current market value
    is drafting with hindsight, which hands every team this season's hits (unrealistically
    stacked rosters). The noise gives each team a real mix of hits and misses."""
    rng = random.Random(SEED)
    pool = con.execute(
        """SELECT p.player_id, p.position, max(m.value) AS v
           FROM players p JOIN market_values m USING (player_id)
           WHERE m.format = ? AND p.position IN ('QB', 'RB', 'WR', 'TE') AND p.nfl_team IS NOT NULL
           GROUP BY ALL ORDER BY v DESC, p.player_id""",
        [fmt],
    ).fetchall()
    noisy = [(v * rng.lognormvariate(0, DRAFT_NOISE), pid, pos) for pid, pos, v in pool]
    available = [(pid, pos) for _, pid, pos in sorted(noisy, reverse=True)]
    teams: list[list[tuple[str, str]]] = [[] for _ in range(n_teams)]
    for rnd in range(SKILL_ROUNDS):
        order = range(n_teams) if rnd % 2 == 0 else reversed(range(n_teams))
        left = SKILL_ROUNDS - rnd
        for t in order:
            have = [pos for _, pos in teams[t]]
            missing = {p for p, k in NEEDS.items() if have.count(p) < k}
            open_spots = sum(max(k - have.count(p), 0) for p, k in NEEDS.items())
            ok = [
                (pid, pos)
                for pid, pos in available
                if have.count(pos) < CAPS[pos]
                and (open_spots < left or pos in missing)  # fill the starting spots in time
            ]
            pick = ok[min(rng.randrange(3), len(ok) - 1)]  # one of the best 3 left: drafts vary
            available.remove(pick)
            teams[t].append(pick)
    for pos in ("K", "DEF"):
        spare = [
            pid
            for (pid,) in con.execute(
                "SELECT player_id FROM players WHERE position = ? AND nfl_team IS NOT NULL ORDER BY player_id",
                [pos],
            ).fetchall()
        ]
        rng.shuffle(spare)
        for t in range(n_teams):
            teams[t].append((spare[t], pos))
    return [[pid for pid, _ in roster] for roster in teams]


def starters(roster: list[str], positions: dict[str, str]) -> set[str]:
    """Draft order = value order, so the first players at each position start (plus the FLEX)."""
    out: list[str] = []
    for pos, n in (("QB", 1), ("RB", 2), ("WR", 2), ("TE", 1), ("K", 1), ("DEF", 1)):
        out += [p for p in roster if positions[p] == pos][:n]
    flex = next(p for p in roster if p not in out and positions[p] in ("RB", "WR", "TE"))
    return {*out, flex}


def build(src: Path = SRC, dest: Path = DEST, needles: list[str] | None = None) -> str:
    """Copy `src` to `dest`, replace its leagues with the demo league; returns your team id.
    `needles`: private identifiers that must not survive (default: ESPN ids from .env)."""
    copy_store(src, dest)
    con = connect(dest)
    try:
        with transaction(con):
            wipe_leagues(con)
        fmt, n_teams, ppr = market_format(con)
        rosters = draft(con, fmt, n_teams)
        positions = dict(con.execute("SELECT player_id, position FROM players").fetchall())
        season = con.execute("SELECT max(season) FROM nfl_games").fetchone()[0]
        rules = PRESETS["ppr"] | {"rec": ppr}
        profile = ensure_profile(con, rules, f"Demo ({describe(rules)})")
        rng = random.Random(SEED + 1)
        now = datetime.now(UTC).replace(tzinfo=None)
        names = (TEAMS * 2)[:n_teams]
        if n_teams > MY_PICK:
            names[MY_PICK] = "Demo Team"
        with transaction(con):
            upsert(
                con,
                "leagues",
                pl.DataFrame(
                    [
                        {
                            "league_id": LEAGUE_ID, "platform": "demo", "external_id": None,
                            "season": season, "name": "Demo League", "num_teams": n_teams,
                            "roster_positions": json.dumps(ROSTER), "scoring_profile_id": profile,
                            "trade_deadline_week": 11, "uses_faab": True, "faab_budget": 100,
                            "playoff_week_start": 15, "league_type": "redraft",
                            "last_synced_at": now,
                        }
                    ],
                    schema_overrides={"external_id": pl.Utf8, "faab_budget": pl.Int32},
                ),
            )  # fmt: skip
            upsert(
                con,
                "teams",
                pl.DataFrame(
                    [
                        {
                            "team_id": f"{LEAGUE_ID}-{i + 1}", "league_id": LEAGUE_ID,
                            "external_roster_id": str(i + 1), "owner_name": f"Manager {i + 1}",
                            "team_name": names[i], "is_mine": i == MY_PICK,
                            "wins": (w := rng.randint(1, 5)), "losses": 6 - w,
                            "points_for": round(rng.uniform(640, 820), 1),
                            "faab_remaining": rng.choice([100, 92, 85, 77, 64, 58, 45, 31]),
                        }
                        for i in range(n_teams)
                    ],
                    schema_overrides={"faab_remaining": pl.Int32},
                ),
            )  # fmt: skip
            upsert(
                con,
                "roster_spots",
                pl.DataFrame(
                    [
                        {
                            "team_id": f"{LEAGUE_ID}-{i + 1}",
                            "player_id": p,
                            "slot": "starter" if p in starters(r, positions) else "bench",
                            "synced_at": now,
                        }
                        for i, r in enumerate(rosters)
                        for p in r
                    ]
                ),
            )
        problem = check(con, needles if needles is not None else private_ids())
    finally:
        con.close()
    if problem:
        dest.unlink(missing_ok=True)
        sys.exit(f"Refusing: {problem}. Demo store deleted.")
    return f"{LEAGUE_ID}-{MY_PICK + 1}"


def check(con: duckdb.DuckDBPyConnection, needles: list[str]) -> str | None:
    """What's wrong with the demo store, if anything of the user's own leagues survived."""
    leagues = [r[0] for r in con.execute("SELECT league_id FROM leagues").fetchall()]
    if leagues != [LEAGUE_ID]:
        return f"{len(leagues)} leagues in the demo store, expected only the demo league"
    if con.execute("SELECT count(*) FROM league_credentials").fetchone()[0]:
        return "saved credentials survived"
    cols = con.execute(
        """SELECT table_name, column_name FROM information_schema.columns
           WHERE data_type IN ('VARCHAR', 'JSON') AND table_schema = 'main'"""
    ).fetchall()
    for table, col in cols:
        for needle in needles:
            hit = con.execute(
                f'SELECT count(*) FROM "{table}" WHERE CAST("{col}" AS VARCHAR) LIKE ?',
                [f"%{needle}%"],
            ).fetchone()[0]
            if hit:
                return f"a private identifier survived in {table}.{col}"
    return None


def private_ids() -> list[str]:
    return [v for k in ("ESPN_LEAGUE_ID", "ESPN_SWID") if (v := _env(k))]


def _env(key: str) -> str | None:
    if os.getenv(key):
        return os.environ[key].strip()
    env = REPO / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip().strip('"') or None
    return None


if __name__ == "__main__":
    team = build()
    print(f"Demo store ready: {DEST.relative_to(REPO)} (your team: {team})")
