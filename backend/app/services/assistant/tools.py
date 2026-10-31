"""The advisor chat's tools: FantasyEdge's own views, read-only, for one team.

Claude never makes up projections or verdicts: it calls these and explains what they return. Each
tool validates its input with a pydantic model, resolves player names to ids the way the Players
search does (accents and case ignored, your league's players first), and returns a trimmed JSON
dump of the same response the matching page uses. Nothing here changes a roster or a setting.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

import duckdb
from pydantic import BaseModel, Field

from app.errors import InvalidInput, NotFound
from app.services import context, leagues, recap, views
from app.services import player as ps
from app.services.context import LeagueContext

MAX_CHARS = 20_000  # per tool result; lists are cut shorter until it fits
DROP_KEYS = {"owner_name", "headshot_url", "team_logo_url", "logo_url", "generated_at"}


class ToolError(Exception):
    """A problem the model can fix (unknown or ambiguous name, bad week): sent back as an error."""


@dataclass
class ToolEnv:
    ctx: LeagueContext
    con: duckdb.DuckDBPyConnection
    team_id: str


# ───────── player names ─────────


def resolve(ctx: LeagueContext, name: str, mine: frozenset[str] = frozenset()) -> str:
    """One player id for a name (accents and case ignored). A single match wins. Several exact
    matches (two players with one name): the one in this league. Several partial matches ("Allen"):
    the one on your roster (`mine`). Anything else is an error listing the options, so the model
    can use a fuller name or ask."""
    q = views.fold(name).strip()
    if not q:
        raise ToolError("empty player name")
    exact, partial = [], []
    for pid, p in ctx.players.items():
        n = views.fold(p.get("name") or "")
        if n == q:
            exact.append(pid)
        elif q in n:
            partial.append(pid)
    found = exact or partial
    if not found:
        raise ToolError(f"No player named {name!r}. Try search_players.")
    if len(found) == 1:
        return found[0]
    preferred = ctx.rostered if exact else mine
    picks = [p for p in found if p in preferred]
    if len(picks) == 1:
        return picks[0]
    found.sort(key=lambda p: -(ctx.players[p].get("ppg") or 0))
    options = ", ".join(
        f"{ctx.players[p]['name']} ({ctx.players[p].get('position')}, "
        f"{ctx.players[p].get('nfl_team') or 'FA'})"
        for p in found[:6]
    )
    raise ToolError(f"{name!r} matches several players: {options}. Use a fuller name.")


def _ids(env: ToolEnv, names: list[str]) -> list[str]:
    mine = frozenset(env.ctx.team(env.team_id).player_ids)
    return [resolve(env.ctx, n, mine) for n in names]


# ───────── output trimming ─────────


def compact(obj: Any, max_items: int = 15, max_depth: int = 99) -> Any:
    """JSON-ready, without empty values, image urls or owner names, floats to 2 decimals, long
    lists cut (with a count of what was cut) and anything nested deeper than `max_depth`
    replaced by a short note."""
    if isinstance(obj, BaseModel):
        obj = obj.model_dump(mode="json", exclude_none=True)
    if isinstance(obj, dict | list) and max_depth <= 0:
        return f"({len(obj)} {'fields' if isinstance(obj, dict) else 'items'} omitted)"
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in DROP_KEYS or v is None or v == [] or v == {}:
                continue
            out[k] = compact(v, max_items, max_depth - 1)
        return out
    if isinstance(obj, list):
        items = [compact(v, max_items, max_depth - 1) for v in obj[:max_items]]
        if len(obj) > max_items:
            items.append({"_more": len(obj) - max_items})
        return items
    if isinstance(obj, float):
        return round(obj, 2)
    return obj


# Trimming steps, gentlest first: shorter lists, then less nesting
STEPS = [(15, 99), (8, 99), (4, 99), (2, 99), (2, 6), (2, 4), (2, 3), (2, 2)]


def render(obj: Any) -> str:
    """The tool result as compact JSON that fits `MAX_CHARS`, trimmed step by step; always valid
    JSON (never cut mid-way), so the model can read whatever is left."""
    for items, depth in STEPS:
        text = json.dumps(compact(obj, items, depth), separators=(",", ":"), ensure_ascii=False)
        if len(text) <= MAX_CHARS:
            return text
    top = compact(obj, 2, 1)
    summary = top if isinstance(top, dict) else {"items": top}
    text = json.dumps({"truncated": True, **summary}, separators=(",", ":"), ensure_ascii=False)
    return text if len(text) <= MAX_CHARS else json.dumps({"truncated": True})


# ───────── tools ─────────


class NoArgs(BaseModel):
    pass


class WeekArg(BaseModel):
    week: int | None = Field(None, ge=1, le=18, description="NFL week; omit for this week")


class PlayerArg(BaseModel):
    name: str = Field(description="Player name, e.g. 'Bijan Robinson'")


class TradeArgs(BaseModel):
    give: list[str] = Field(default_factory=list, max_length=5, description="Your players' names")
    receive: list[str] = Field(
        default_factory=list, max_length=5, description="Names of the players you'd get"
    )


class FindArgs(BaseModel):
    give: list[str] = Field(min_length=1, max_length=3, description="Your players to trade away")
    want_position: Literal["QB", "RB", "WR", "TE", "ANY"] = "ANY"
    receive_count: int = Field(1, ge=1, le=2, description="Players back: 1 or 2")


class PageArg(BaseModel):
    page: int = Field(0, ge=0, le=20, description="0 = best ideas; higher pages show other deals")


class SearchArgs(BaseModel):
    query: str = Field("", max_length=60, description="Name search; empty lists the top players")
    position: Literal["QB", "RB", "WR", "TE", "K", "DEF"] | None = None
    availability: Literal["all", "mine", "other", "fa"] = Field(
        "all", description="mine: your roster; other: another team's; fa: free agents"
    )


class RankingsArgs(BaseModel):
    top: int = Field(10, ge=5, le=30, description="Players per position")
    position: Literal["QB", "RB", "WR", "TE", "K", "DEF"] | None = Field(
        None, description="One position; omit for all"
    )
    week: int | None = Field(
        None, ge=1, le=18, description="One upcoming week; omit for rest of season"
    )


def _rankings(env: ToolEnv, a: RankingsArgs) -> Any:
    """Rest-of-season lists by default, or one week's: the full grid is too big for a chat."""
    out = views.rankings_view(env.ctx, env.team_id, a.top).model_dump(mode="json")
    positions = {}
    for pos, r in out["positions"].items():
        if a.position and pos != a.position:
            continue
        if a.week is None:
            positions[pos] = {"rest_of_season": r["ros"]}
        else:
            week = next((w for w in r["weekly"] if w.get("week") == a.week), None)
            if week is None:
                raise ToolError(f"No rankings for week {a.week}; weeks: {out['weeks']}")
            positions[pos] = {f"week_{a.week}": week}
    return {"week": out["week"], "weeks": out["weeks"], "positions": positions}


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args: type[BaseModel]
    label: str  # shown in the chat while it runs
    run: Callable[[ToolEnv, Any], Any]

    def schema(self) -> dict:
        s = self.args.model_json_schema()
        s.pop("title", None)
        s["additionalProperties"] = False
        for prop in s.get("properties", {}).values():
            prop.pop("title", None)
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": s,
            "eager_input_streaming": True,
        }


def _player(env: ToolEnv, a: PlayerArg) -> Any:
    pid = resolve(env.ctx, a.name, frozenset(env.ctx.team(env.team_id).player_ids))
    flags = [views.flag_out(f) for f in env.ctx.regression.for_player(pid)]
    override = env.con.execute(
        "SELECT out_for_season, return_week FROM player_availability WHERE player_id = ?", [pid]
    ).fetchone()
    detail = ps.player_detail(env.ctx, env.team_id, pid, flags, override)
    out = detail.model_dump(mode="json", exclude_none=True)
    out["weeks"] = out.get("weeks", [])[-5:]  # the last few games are enough for a chat answer
    return out


def _waivers(env: ToolEnv, _: NoArgs) -> Any:
    trending = env.con.execute(
        "SELECT player_id, count, fetched_at FROM trending"
        " WHERE kind = 'add' AND lookback_hours = 24 ORDER BY count DESC"
    ).fetchall()
    return views.waivers_view(env.ctx, env.team_id, trending)


def _search(env: ToolEnv, a: SearchArgs) -> Any:
    return views.players_table(
        env.ctx, env.team_id, a.query, a.position, None, a.availability, "ros", True, 0, 15
    )


def _recap(env: ToolEnv, a: WeekArg) -> Any:
    rows = leagues.matchups(env.con, env.ctx.league.league_id)
    return recap.recap_view(env.ctx, env.team_id, rows, a.week)


TOOLS: list[Tool] = [
    Tool(
        "my_team",
        "Your roster with each player's projection (points per game, rest-of-season points), "
        "buy/hold/sell verdict, injury status and lineup slot, plus team grades by position vs "
        "the league and your record. Start here for questions about your team.",
        NoArgs,
        "Reading your roster",
        lambda env, _: views.team_view(env.ctx, env.team_id),
    ),
    Tool(
        "advisor_feed",
        "FantasyEdge's ranked to-do list for this week: injuries, trade offers, lineup changes, "
        "bye-week holes, trade ideas, sells, buys and waiver adds, each with its reasons.",
        NoArgs,
        "Checking the advisor",
        lambda env, _: views.advice_view(
            env.ctx,
            env.team_id,
            accepted=leagues.pending_trades(env.con, env.ctx.league.league_id),
            offers=leagues.trade_offers(env.con, env.ctx.league.league_id),
        ),  # fmt: skip
    ),
    Tool(
        "start_sit",
        "Your current lineup vs the best lineup for a week (matchup-adjusted projections), with "
        "every roster player's projection and who is locked (game started) or on IR.",
        WeekArg,
        "Planning the lineup",
        lambda env, a: views.startsit_view(env.ctx, env.team_id, a.week),
    ),
    Tool(
        "gameday_alerts",
        "This week's starters who might not play (injury status, practice reports, byes) with "
        "the bench player or free agent to start instead and their kickoff times.",
        NoArgs,
        "Checking injuries",
        lambda env, _: views.gameday_view(
            env.ctx,
            env.team_id,
            context.status_changes(env.con, env.ctx.team(env.team_id).player_ids),
        ),  # fmt: skip
    ),
    Tool(
        "matchup",
        "This week's head-to-head matchup (both lineups, expected scores, your chance to win), "
        "the standings with playoff odds, and your schedule with results and chances.",
        NoArgs,
        "Looking at your matchup",
        lambda env, _: views.matchup_view(
            env.ctx, env.team_id, leagues.matchups(env.con, env.ctx.league.league_id)
        ),
    ),
    Tool(
        "recap",
        "A played week looked back on: your lineup vs the best possible and vs FantasyEdge's "
        "projected-best lineup, which starters beat or missed their projection range, and "
        "season-to-date projection accuracy. Omit week for the last completed week.",
        WeekArg,
        "Reviewing past weeks",
        _recap,
    ),
    Tool(
        "player",
        "One player in depth: projection and its p10-p90 range, verdict and the reasons, market "
        "value, schedule ease, injury, usage analytics and recent games (projected vs actual).",
        PlayerArg,
        "Looking up a player",
        _player,
    ),
    Tool(
        "search_players",
        "Find players by name, position and who has them (yours, another team's, free agents), "
        "best rest-of-season projection first. Use it to get exact names.",
        SearchArgs,
        "Searching players",
        _search,
    ),
    Tool(
        "waivers",
        "Free agents ranked by how many rest-of-season points they add to your starting lineup "
        "after the best drop, with a FAAB bid range, plus the most-added players league-wide.",
        NoArgs,
        "Scanning waivers",
        _waivers,
    ),
    Tool(
        "evaluate_trade",
        "Grade a specific trade for both sides: lineup points before and after (rest of "
        "season), forced drops, bye-week holes it creates or fixes, fair-value check by market "
        "value, and whether the other team would likely accept. Players received must all come "
        "from one team (or none, for a hypothetical).",
        TradeArgs,
        "Running the trade analyzer",
        lambda env, a: views.evaluate_trade(
            env.ctx, env.team_id, _ids(env, a.give), _ids(env, a.receive)
        ),
    ),
    Tool(
        "find_trade",
        "Search every team for fair trades that give away these players for a position you "
        "want, the ones the other team should also like first.",
        FindArgs,
        "Searching for trades",
        lambda env, a: views.find_view(
            env.ctx, env.team_id, _ids(env, a.give), a.want_position, a.receive_count
        ),
    ),
    Tool(
        "trade_ideas",
        "Mutually beneficial trade ideas across the league (both lineups gain, fair by market "
        "value), best first. Higher pages show different deals.",
        PageArg,
        "Looking for trade ideas",
        lambda env, a: views.suggest_view(env.ctx, env.team_id, a.page),
    ),
    Tool(
        "trade_offers",
        "Open trade offers sent to you or by you (ESPN only), each graded by the trade analyzer.",
        NoArgs,
        "Checking trade offers",
        lambda env, _: views.offers_view(
            env.ctx, env.team_id, leagues.trade_offers(env.con, env.ctx.league.league_id)
        ),
    ),
    Tool(
        "byes",
        "Week by week for the rest of the season: which starters are on bye or hurt, who fills "
        "in, and weeks your lineup has a hole.",
        NoArgs,
        "Checking byes",
        lambda env, _: views.byes_view(env.ctx, env.team_id),
    ),
    Tool(
        "rankings",
        "Schedule-adjusted positional rankings, rest of season by default or for one upcoming "
        "week, with who owns each player.",
        RankingsArgs,
        "Pulling rankings",
        _rankings,
    ),
    Tool(
        "buy_targets",
        "Players the market undervalues vs FantasyEdge's projection (buy), and your players it "
        "overvalues (sell).",
        NoArgs,
        "Finding buy targets",
        lambda env, _: views.buy_targets_view(env.ctx, env.team_id),
    ),
]
BY_NAME = {t.name: t for t in TOOLS}


def run_tool(env: ToolEnv, name: str, raw: Any) -> tuple[str, bool]:
    """(result text, is_error). Validation, name and input problems come back as errors the
    model can read and fix; anything else is a bug and propagates."""
    tool = BY_NAME.get(name)
    if tool is None:
        return f"Unknown tool {name!r}.", True
    try:
        args = tool.args.model_validate(raw if isinstance(raw, dict) else {})
    except ValueError as exc:
        return f"Invalid input for {name}: {exc}", True
    try:
        return render(tool.run(env, args)), False
    except (ToolError, InvalidInput) as exc:
        return str(exc), True
    except NotFound as exc:
        return exc.detail, True
