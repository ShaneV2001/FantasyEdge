"""Player page: bio, verdict, statlines, and what we projected each week vs what happened.

Past projections are a walk-forward replay: for each week already played this season, the app's
engine (with the same matchup adjustment as the Rankings page) projects every player from only the
games before that week. One replay per league context, shared by every player page.
"""

from __future__ import annotations

from datetime import date

import polars as pl

from app.errors import NotFound
from app.schemas import models as m
from app.services.context import LeagueContext, engine_for
from app.services.player_analytics import player_analytics
from projections.base import ProjectionInputs
from projections.matchup import MatchupAdjusted

SLEEPER_HEADSHOT = "https://sleepercdn.com/content/nfl/players/{}.jpg"
SLEEPER_TEAM_LOGO = "https://sleepercdn.com/images/team_logos/nfl/{}.png"

STATLINE: dict[str, tuple[str, ...]] = {
    "QB": ("pass_cmp", "pass_att", "pass_yds", "pass_td", "interceptions", "carries", "rush_yds", "rush_td"),
    "RB": ("carries", "rush_yds", "rush_td", "targets", "receptions", "rec_yds", "rec_td", "snap_pct"),
    "WR": ("targets", "receptions", "rec_yds", "rec_td", "carries", "rush_yds", "snap_pct"),
    "TE": ("targets", "receptions", "rec_yds", "rec_td", "snap_pct"),
    "K": ("fgm", "fgm_50p", "fgmiss", "xpm", "xpmiss"),
    "DEF": ("def_sack", "def_int", "def_fum_rec", "def_td", "pts_allow", "yds_allow"),
}  # fmt: skip


def _players_frame(ctx: LeagueContext) -> pl.DataFrame:
    rows = [
        (pid, p.get("position"), p.get("nfl_team"))
        for pid, p in ctx.players.items()
        if p.get("position")
    ]
    return pl.DataFrame(
        rows, schema={"player_id": pl.Utf8, "position": pl.Utf8, "nfl_team": pl.Utf8}, orient="row"
    ).with_columns(
        pl.lit(None, pl.Utf8).alias("injury_status"), pl.lit(None, pl.Utf8).alias("status")
    )


def played_weeks(ctx: LeagueContext) -> list[int]:
    cur = ctx.stats.filter(pl.col("season") == ctx.season)
    return sorted(cur["week"].unique().to_list()) if cur.height else []


def past_projections(ctx: LeagueContext) -> dict[int, dict[str, tuple[float, float, float]]]:
    """{week: {player_id: (ppg, p10, p90)}} projected before each played week (memoized)."""
    if "past_projections" in ctx.memo:
        return ctx.memo["past_projections"]
    engine = MatchupAdjusted(engine_for(ctx.tuning), ctx.tuning.alpha)
    players = _players_frame(ctx)
    s = ctx.season
    out: dict[int, dict[str, tuple[float, float, float]]] = {}
    for w in played_weeks(ctx):
        hist = ctx.stats.filter(
            (pl.col("season") == s - 1) | ((pl.col("season") == s) & (pl.col("week") < w))
        )
        if hist.is_empty():
            continue
        inp = ProjectionInputs(hist, players, ctx.schedule, ctx.league.rules, s, w, ctx.shape)
        df = engine.per_game(inp).filter(~pl.col("method").is_in(["default", "no_data"]))
        out[w] = {
            r[0]: (r[1], r[2], r[3]) for r in df.select("player_id", "ppg", "p10", "p90").rows()
        }
    ctx.memo["past_projections"] = out
    return out


def neutral_projection(ctx: LeagueContext, week: int) -> dict[str, float]:
    """Points per game the app's engine projects from the games before `week` (no schedule
    adjustment, so a change between weeks is the player's own play), memoized per week."""
    key = ("neutral_projection", week)
    if key not in ctx.memo:
        s = ctx.season
        hist = ctx.stats.filter(
            (pl.col("season") == s - 1) | ((pl.col("season") == s) & (pl.col("week") < week))
        )
        out: dict[str, float] = {}
        if not hist.is_empty():
            inp = ProjectionInputs(
                hist, _players_frame(ctx), ctx.schedule, ctx.league.rules, s, week, ctx.shape
            )
            df = engine_for(ctx.tuning).per_game(inp)
            df = df.filter(~pl.col("method").is_in(["default", "no_data"]))
            out = dict(df.select("player_id", "ppg").rows())
        ctx.memo[key] = out
    return ctx.memo[key]


def _age(birth: object) -> int | None:
    if not isinstance(birth, date):
        return None
    today = date.today()
    return today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))


def _statline(row: dict, position: str) -> dict[str, float | None]:
    keys = STATLINE.get(position, ())
    out: dict[str, float | None] = {}
    for k in keys:
        if k == "fgm":
            out[k] = sum(row.get(c) or 0 for c in
                         ("fgm_0_19", "fgm_20_29", "fgm_30_39", "fgm_40_49", "fgm_50_59", "fgm_60p"))  # fmt: skip
        elif k == "fgm_50p":
            out[k] = (row.get("fgm_50_59") or 0) + (row.get("fgm_60p") or 0)
        else:
            v = row.get(k)
            out[k] = round(float(v), 3) if v is not None else None
    return out


def _images(p: dict) -> tuple[str | None, str | None]:
    team = (p.get("nfl_team") or "").lower() or None
    logo = SLEEPER_TEAM_LOGO.format(team) if team else None
    if p.get("position") == "DEF":
        return logo, logo
    sid = p.get("sleeper_id")
    return (SLEEPER_HEADSHOT.format(sid) if sid else None), logo


def player_detail(
    ctx: LeagueContext,
    team_id: str,
    player_id: str,
    flags: list,
    override: tuple[bool | None, int | None] | None = None,
) -> m.PlayerDetailOut:
    """`override`: the user's saved what-if (out_for_season, return_week), if any."""
    team = ctx.team(team_id)
    p = ctx.players.get(player_id)
    if p is None:
        raise NotFound("player", f"Player not found: {player_id}")
    pos = p.get("position") or "?"
    owner = ctx.owner_of(player_id)
    headshot, logo = _images(p)

    rows = {
        r["week"]: r
        for r in ctx.stats.filter(
            (pl.col("player_id") == player_id) & (pl.col("season") == ctx.season)
        ).iter_rows(named=True)
    }
    past = past_projections(ctx)
    weeks = []
    # weeks already over, plus this week if he has played (this week's unplayed game is upcoming)
    past_weeks = {w for w in played_weeks(ctx) if w < ctx.week}
    for w in sorted(past_weeks | set(rows)):
        row = rows.get(w)
        proj = past.get(w, {}).get(player_id)
        weeks.append(
            m.PlayerWeekOut(
                week=w,
                opponent=(row or {}).get("opponent") or ctx.schedule.opponent(p.get("nfl_team"), w),
                played=row is not None,
                actual=round(row["fp"], 2) if row else None,
                projected=proj[0] if proj else None,
                p10=proj[1] if proj else None,
                p90=proj[2] if proj else None,
                statline=_statline(row, pos) if row else {},
            )
        )
    upcoming = [
        m.MatchupCell(week=c.week, opponent=c.opponent, index=c.index, points=c.points)
        for c in ctx.cells.get(player_id, [])
    ]
    return m.PlayerDetailOut(
        player_id=player_id,
        name=p["name"],
        position=pos,
        nfl_team=p.get("nfl_team"),
        headshot_url=headshot,
        team_logo_url=logo,
        age=_age(p.get("birth_date")),
        years_exp=p.get("years_exp"),
        depth_chart_order=p.get("depth_chart_order"),
        injury_status=p.get("injury_status"),
        availability_note=p.get("availability_note"),
        injury_detail=p.get("injury_detail"),
        return_week=p.get("return_week"),
        availability_source=p.get("availability_source"),
        override_return_week=override[1] if override else None,
        override_out_for_season=bool(override and override[0]),
        bye_week=p.get("bye_week"),
        owner=owner.team_name if owner else None,
        mine=player_id in team.player_ids,
        ppg=round(p.get("ppg") or 0.0, 2),
        p10=p.get("p10"),
        p90=p.get("p90"),
        model_ros_points=p.get("model_ros_points"),
        ros_value_par=p.get("ros_value_par"),
        market_value=p.get("market_value"),
        model_rank=p.get("model_pos_rank"),
        market_rank=p.get("market_rank_cov"),
        market_implied_points=p.get("market_implied_points"),
        value_gap=p.get("value_gap"),
        signal=p.get("signal") or "hold",
        signal_reasons=list(p.get("signal_reasons") or []),
        flags=flags,
        statline_keys=list(STATLINE.get(pos, ())),
        weeks=weeks,
        upcoming=upcoming,
        analytics=player_analytics(ctx.stats, player_id, ctx.season, pos),
    )
