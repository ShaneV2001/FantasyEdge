"""Projection engine interface + shared rest-of-season / replacement-level math.

An engine only estimates per-game points (and a band). Turning that into rest-of-season points
(byes, injuries) and points-above-replacement is shared, so swapping the phase-1 baseline for the
phase-2 model changes nothing downstream.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Protocol

import polars as pl

from signals.lineup import starting_slots
from signals.schedule import Schedule

FANTASY_LAST_WEEK = 17
IR_WEEKS_MISSED = 4  # assumption for IR/PUP/NFI designations without a return date
STATUS_THIS_WEEK = {"Out": 0.0, "Sus": 0.0, "Doubtful": 0.25, "Questionable": 0.85}
STATUS_LONG_TERM = {"IR", "PUP", "NFI", "Injured Reserve", "Physically Unable to Perform"}

# Share of each flex slot that typically goes to each position (league-wide starters).
FLEX_SHARES: dict[str, dict[str, float]] = {
    "FLEX": {"RB": 0.45, "WR": 0.45, "TE": 0.10},
    "WRRB_FLEX": {"RB": 0.5, "WR": 0.5},
    "REC_FLEX": {"WR": 0.8, "TE": 0.2},
    "SUPER_FLEX": {"QB": 0.9, "RB": 0.05, "WR": 0.05},
}


@dataclass(frozen=True)
class LeagueShape:
    num_teams: int = 12
    roster_positions: tuple[str, ...] = (
        "QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF",
        "BN", "BN", "BN", "BN", "BN", "BN",
    )  # fmt: skip
    last_week: int = FANTASY_LAST_WEEK


@dataclass
class ProjectionInputs:
    stats: pl.DataFrame  # player_week_stats + position + fp (league-scored)
    players: pl.DataFrame  # player_id, position, nfl_team, injury_status, status
    schedule: Schedule
    rules: dict[str, float]
    season: int
    week: int  # the upcoming week being projected; only data from earlier weeks is used
    league: LeagueShape = field(default_factory=LeagueShape)


class ProjectionEngine(Protocol):
    run_id: str

    def per_game(self, inputs: ProjectionInputs) -> pl.DataFrame:
        """Return player_id, ppg, p10, p90 (+ any explanatory columns)."""
        ...


# ───────── availability & rest of season ─────────


def availability(injury_status: str | None, status: str | None, week: int, start: int) -> float:
    """Expected fraction of a game the player suits up for in `week` (as of `start`)."""
    tags = {injury_status or "", status or ""}
    if tags & STATUS_LONG_TERM:
        return 0.0 if week < start + IR_WEEKS_MISSED else 1.0
    if week == start:
        return STATUS_THIS_WEEK.get(injury_status or "", 1.0)
    return 1.0


def availability_note(injury_status: str | None, status: str | None) -> str | None:
    tags = {injury_status or "", status or ""}
    if tags & STATUS_LONG_TERM:
        return f"On {injury_status or status}: assumed out {IR_WEEKS_MISSED} more weeks"
    if injury_status in STATUS_THIS_WEEK:
        pct = int(STATUS_THIS_WEEK[injury_status] * 100)
        return f"{injury_status} this week ({pct}% chance-weighted)"
    return None


def weekly_points(
    ppg: float,
    team: str | None,
    injury_status: str | None,
    status: str | None,
    schedule: Schedule,
    start: int,
    end: int,
) -> dict[int, float]:
    return {
        w: ppg * availability(injury_status, status, w, start) if schedule.plays(team, w) else 0.0
        for w in range(start, end + 1)
    }


def replacement_ranks(league: LeagueShape) -> dict[str, int]:
    """Rank of the first non-starter at each position across the whole league."""
    starters = dict.fromkeys(("QB", "RB", "WR", "TE", "K", "DEF"), 0.0)
    for slot in starting_slots(league.roster_positions):
        if slot in starters:
            starters[slot] += 1
        else:
            for pos, share in FLEX_SHARES.get(slot, {}).items():
                starters[pos] += share
    return {
        pos: math.floor(round(n * league.num_teams, 6)) + 1 for pos, n in starters.items() if n > 0
    }


def finalize(per_game: pl.DataFrame, inputs: ProjectionInputs) -> pl.DataFrame:
    """Add bye/injury-aware ROS points, next-4 points and points above replacement."""
    start, end = inputs.week, inputs.league.last_week
    info = inputs.players.select("player_id", "position", "nfl_team", "injury_status", "status")
    df = per_game.join(info, on="player_id", how="left")
    rows = []
    for r in df.iter_rows(named=True):
        wk = weekly_points(
            r["ppg"], r["nfl_team"], r["injury_status"], r["status"], inputs.schedule, start, end
        )
        bye = inputs.schedule.bye(r["nfl_team"])
        rows.append(
            {
                "player_id": r["player_id"],
                "proj_ros_points": round(sum(wk.values()), 2),
                "next4_points": round(sum(v for w, v in wk.items() if w < start + 4), 2),
                "games_remaining": round(
                    sum(
                        availability(r["injury_status"], r["status"], w, start)
                        for w in wk
                        if inputs.schedule.plays(r["nfl_team"], w)
                    ),
                    2,
                ),
                "bye_week": bye,
                "bye_upcoming": bye is not None and start <= bye <= end,
                "availability_note": availability_note(r["injury_status"], r["status"]),
            }
        )
    df = df.join(pl.DataFrame(rows, infer_schema_length=None), on="player_id", how="left")
    ranks = replacement_ranks(inputs.league)
    repl = []
    for pos, n in ranks.items():
        ros = df.filter(pl.col("position") == pos)["proj_ros_points"].sort(descending=True)
        level = float(ros[n - 1]) if ros.len() >= n else 0.0
        repl.append({"position": pos, "replacement_ros": level})
    df = df.join(pl.DataFrame(repl), on="position", how="left").with_columns(
        (pl.col("proj_ros_points") - pl.col("replacement_ros").fill_null(0))
        .round(2)
        .alias("ros_value_par"),
        pl.col("ppg").alias("proj_next4_ppg"),
    )
    return df


def run(engine: ProjectionEngine, inputs: ProjectionInputs) -> pl.DataFrame:
    return finalize(engine.per_game(inputs), inputs)
