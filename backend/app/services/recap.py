"""Weekly recap: how your lineup did against the best one you could have set, against the lineup
FantasyEdge's projections would have picked, and how those projections held up.

Everything is scored with the platform's own points for each player that week, so the totals match
your league. "Your roster that week" is every player the platform scored for your team that week.
The FantasyEdge lineup uses the walk-forward projections (`player.past_projections`): what the app
would have projected before that week, without that week's injury tags, with byes counted.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.errors import InvalidInput
from app.schemas import models as m
from app.services import player as ps
from app.services.context import LeagueContext
from app.services.views import player_ref
from signals.lineup import LineupPlayer, optimal_lineup, starting_slots


def _week_rows(rows: Sequence, team_id: str) -> dict[int, object]:
    return {r.week: r for r in rows if r.team_id == team_id and r.starters}


def _lineup(ctx: LeagueContext, pool: dict[str, float]) -> tuple[set[str], float]:
    """The best lineup from `pool` (player id -> points) and its points."""
    slots = starting_slots(ctx.league.roster_positions)
    cands = [
        LineupPlayer(p, ctx.players[p]["position"], v)
        for p, v in pool.items()
        if p in ctx.players and ctx.players[p].get("position")
    ]
    best = optimal_lineup(cands, slots)
    return best.starters, round(best.points, 2)


def _projected(ctx: LeagueContext, week: int, pid: str) -> tuple[float, float, float] | None:
    proj = ps.past_projections(ctx).get(week, {}).get(pid)
    team = ctx.players.get(pid, {}).get("nfl_team")
    if proj is None or not ctx.schedule.has_game(team, week):
        return None  # no projection, or on bye that week
    return proj


def _week(ctx: LeagueContext, team_id: str, row, opp_row) -> m.RecapWeekOut:
    week = row.week
    actual: dict[str, float] = row.player_points
    started = list(row.starters)
    best_ids, best_points = _lineup(ctx, actual)
    proj = {p: _projected(ctx, week, p) for p in actual}
    fe_ids, _ = _lineup(ctx, {p: (v[0] if v else 0.0) for p, v in proj.items()})
    fe_points = round(sum(actual.get(p, 0.0) for p in fe_ids), 2)
    you = round(sum(actual.get(p, 0.0) for p in started), 2)

    def out(pid: str) -> m.RecapPlayerOut:
        pr = proj.get(pid)
        a = actual.get(pid, 0.0)
        verdict = None
        if pr is not None:
            verdict = "above" if a > pr[2] else "below" if a < pr[1] else "in_range"
        return m.RecapPlayerOut(
            player=player_ref(ctx, pid),
            actual=round(a, 2),
            projected=round(pr[0], 2) if pr else None,
            p10=round(pr[1], 2) if pr else None,
            p90=round(pr[2], 2) if pr else None,
            band=verdict,  # type: ignore[arg-type]
        )

    result = None
    if opp_row is not None:
        result = "W" if row.points > opp_row.points else "L" if row.points < opp_row.points else "T"
    should = sorted(best_ids - set(started), key=lambda p: -actual.get(p, 0.0))
    instead = sorted(set(started) - best_ids, key=lambda p: actual.get(p, 0.0))
    return m.RecapWeekOut(
        week=week,
        opponent_name=next((t.team_name for t in ctx.teams if t.team_id == row.opponent_id), None),
        result=result,  # type: ignore[arg-type]
        points=round(row.points, 2),
        opponent_points=round(opp_row.points, 2) if opp_row else None,
        lineup_points=you,
        best_points=best_points,
        left_on_bench=round(max(best_points - you, 0.0), 2),
        fe_points=fe_points,
        fe_lineup=[player_ref(ctx, p) for p in sorted(fe_ids, key=lambda p: -actual.get(p, 0.0))],
        starters=[out(p) for p in started],
        should_have_started=[out(p) for p in should],
        instead_of=[out(p) for p in instead],
    )


def recap_view(
    ctx: LeagueContext, team_id: str, rows: Sequence, week: int | None = None
) -> m.RecapOut:
    ctx.team(team_id)
    mine = _week_rows(rows, team_id)
    played = sorted(w for w in mine if w < ctx.week)
    if not played:
        note = (
            "Manual teams have no weekly lineups to look back on."
            if ctx.league.platform == "manual"
            else "No completed weeks with lineups yet: use Update in the sidebar after week 1."
        )
        return m.RecapOut(team_id=team_id, week=None, weeks=[], notes=[note])
    week = played[-1] if week is None else week
    if week not in played:
        raise InvalidInput(f"week must be one of the played weeks: {played}")
    by = {(r.week, r.team_id): r for r in rows}
    weeks = [_week(ctx, team_id, mine[w], by.get((w, mine[w].opponent_id))) for w in played]
    detail = next(w for w in weeks if w.week == week)

    rated = [s for w in weeks for s in w.starters if s.projected is not None]
    season = m.RecapSeasonOut(
        weeks=len(weeks),
        lineup_points=round(sum(w.lineup_points for w in weeks), 2),
        best_points=round(sum(w.best_points for w in weeks), 2),
        fe_points=round(sum(w.fe_points for w in weeks), 2),
        left_on_bench=round(sum(w.left_on_bench for w in weeks), 2),
        starters_rated=len(rated),
        mae=round(sum(abs(s.actual - (s.projected or 0)) for s in rated) / len(rated), 2)
        if rated
        else None,
        in_band=round(sum(s.band == "in_range" for s in rated) / len(rated), 3) if rated else None,
    )
    return m.RecapOut(
        team_id=team_id,
        week=week,
        weeks=played,
        detail=detail,
        by_week=[
            m.RecapWeekSummaryOut(
                week=w.week,
                result=w.result,
                lineup_points=w.lineup_points,
                best_points=w.best_points,
                fe_points=w.fe_points,
            )
            for w in weeks
        ],  # fmt: skip
        season=season,
        notes=[
            "Projections are what FantasyEdge would have said before each week (no hindsight), "
            "without that week's injury news. Points are your league's own scoring."
        ],
    )
