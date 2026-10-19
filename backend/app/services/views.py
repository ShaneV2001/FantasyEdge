"""Compose LeagueContext + signals into API response models (phase-1 endpoints)."""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from datetime import datetime

from app.errors import InvalidInput, NotFound
from app.schemas import models as m
from app.services.context import MARKET_LABEL, LeagueContext
from projections.base import replacement_ranks
from scoring.rules import PRESETS, normalize
from signals import advisor as adv
from signals import startsit as ss
from signals import trade as tr
from signals import waivers as wv
from signals.byes import RosterEntry, bye_grid
from signals.lineup import SKILL_POSITIONS, SLOT_ELIGIBILITY, slot_label, starting_slots
from signals.regression import (
    FLAG_SCALES,
    TDOE_THRESHOLD,
    USAGE_SHIFT,
    Z_THRESHOLD,
    RegressionFlag,
)
from signals.targets import POSITIONS as TARGET_POSITIONS
from signals.targets import TargetRow, rank_targets, ros_points, ros_row
from signals.team import RosMath, TeamProfile, simulate_league, team_profiles

# ───────── shared helpers ─────────


def ros_math(ctx: LeagueContext) -> RosMath:
    if "math" not in ctx.memo:
        ctx.memo["math"] = RosMath(
            ctx.players,
            ctx.schedule,
            ctx.week,
            ctx.league.last_week,
            starting_slots(ctx.league.roster_positions),
            inj=ctx.tuning.injury,
        )
    return ctx.memo["math"]


def week_math(ctx: LeagueContext) -> RosMath:
    """Like `ros_math`, but each week uses the matchup-adjusted projections (`ctx.cells`). Used for
    this week's lineup decisions (My Team's best lineup, start/sit advice, the planner) so they
    all agree; season-long math (trades, waivers, byes) stays on `ros_math`."""
    if "week_math" not in ctx.memo:
        ctx.memo["week_math"] = RosMath(
            ctx.players,
            ctx.schedule,
            ctx.week,
            ctx.league.last_week,
            starting_slots(ctx.league.roster_positions),
            inj=ctx.tuning.injury,
            weekly={pid: {c.week: c.points for c in cells} for pid, cells in ctx.cells.items()},
        )
    return ctx.memo["week_math"]


def week_plan(ctx: LeagueContext, team_id: str, week: int | None = None) -> ss.WeekPlan:
    """A team's real and best lineup for a week (this week by default), locks included."""
    week = ctx.week if week is None else week
    key = ("week_plan", team_id, week)
    if key not in ctx.memo:
        team = ctx.team(team_id)
        ctx.memo[key] = ss.plan_week(
            week_math(ctx), ctx.players, team.player_ids, team.starters, week,
            locked=ss.locked_players(team.player_ids, ctx.players, ctx.schedule, week),
            reserved={p for p, s in team.slots.items() if s in ("ir", "taxi")},
        )  # fmt: skip
    return ctx.memo[key]


def profiles(ctx: LeagueContext) -> dict[str, TeamProfile]:
    """Grades vs the real league; a manual team (no league) is graded vs a simulated league."""
    if "profiles" not in ctx.memo:
        slots = starting_slots(ctx.league.roster_positions)
        rosters = {t.team_id: t.player_ids for t in ctx.teams}
        if ctx.league.platform == "manual" or len(rosters) < 2:
            mine = [p for t in ctx.teams for p in t.player_ids]
            sim = simulate_league(
                ctx.players, mine, max(ctx.league.num_teams - 1, 1), ctx.league.roster_positions
            )
            ctx.memo["profiles"] = team_profiles(
                rosters | sim, ctx.players, slots, grade_only=rosters
            )
        else:
            ctx.memo["profiles"] = team_profiles(rosters, ctx.players, slots)
    return ctx.memo["profiles"]


def grade_basis(ctx: LeagueContext) -> str:
    if ctx.league.platform == "manual" or len(ctx.teams) < 2:
        return f"a simulated {ctx.league.num_teams}-team league with your lineup settings"
    return f"the other {len(ctx.teams) - 1} teams in {ctx.league.name}"


def market_label(ctx: LeagueContext) -> str:
    return MARKET_LABEL.get(ctx.market_source or "", "Market")


def player_ref(ctx: LeagueContext, pid: str) -> m.PlayerRef:
    p = ctx.players.get(pid)
    if p is None:
        return m.PlayerRef(player_id=pid, name=pid, position="?", nfl_team=None)
    return m.PlayerRef(
        player_id=pid, name=p["name"], position=p["position"], nfl_team=p.get("nfl_team")
    )


def player_value(ctx: LeagueContext, pid: str) -> dict:
    p = ctx.players[pid]
    return dict(
        player_id=pid,
        name=p["name"],
        position=p["position"],
        nfl_team=p.get("nfl_team"),
        sleeper_id=p.get("sleeper_id"),
        ppg=p.get("ppg") or 0.0,
        p10=p.get("p10"),
        p90=p.get("p90"),
        l3_ppg=p.get("l3_ppg"),
        season_ppg=p.get("season_ppg"),
        usage_ppg=p.get("usage_ppg"),
        games_played=p.get("games_played"),
        proj_ros_points=p.get("proj_ros_points") or 0.0,
        next4_points=p.get("next4_points") or 0.0,
        games_remaining=p.get("games_remaining") or 0.0,
        ros_value_par=p.get("ros_value_par") or 0.0,
        bye_week=p.get("bye_week"),
        injury_status=p.get("injury_status"),
        availability_note=p.get("availability_note"),
        return_week=p.get("return_week"),
        market_value=p.get("market_value"),
        market_rank=p.get("market_rank_cov"),
        model_rank=p.get("model_pos_rank"),
        regression_score=p.get("regression_score") or 0.0,
        ease_next4=_r(p.get("ease_next4")),
        ease_playoffs=_r(p.get("ease_playoffs")),
        method=p.get("method"),
        signal=p.get("signal") or "hold",
        signal_reasons=list(p.get("signal_reasons") or []),
        value_gap=p.get("value_gap"),
        market_implied_points=p.get("market_implied_points"),
        model_ros_points=p.get("model_ros_points"),
    )


def _r(x: float | None, n: int = 2) -> float | None:
    return round(x, n) if x is not None else None


def flag_out(f: RegressionFlag) -> m.FlagOut:
    return m.FlagOut(
        kind=f.kind,
        metric=f.metric,
        direction=f.direction,
        value=f.value,
        message=f.message,
        numbers=f.numbers,
        size=round(abs(f.value) / FLAG_SCALES[f.kind], 2),
    )  # type: ignore[arg-type]


def grades_out(prof: TeamProfile | None) -> dict[str, m.PositionGradeOut]:
    if prof is None:
        return {}
    return {k: m.PositionGradeOut(**vars(g)) for k, g in prof.grades.items()}


def overall_out(prof: TeamProfile | None) -> m.PositionGradeOut | None:
    return m.PositionGradeOut(**vars(prof.overall)) if prof and prof.overall else None


def scoring_preset(rules: dict[str, float]) -> str | None:
    norm = normalize(rules)
    return next((k for k, v in PRESETS.items() if normalize(v) == norm), None)


def market_info(ctx: LeagueContext) -> m.MarketInfo:
    return m.MarketInfo(source=ctx.market_source, format=ctx.market_format, stale=ctx.market_stale)


def league_out(ctx: LeagueContext) -> m.LeagueOut:
    lg = ctx.league
    return m.LeagueOut(
        league_id=lg.league_id,
        platform=lg.platform,
        name=lg.name,
        season=lg.season,
        week=ctx.week,
        num_teams=lg.num_teams,
        roster_positions=lg.roster_positions,
        scoring=ctx.scoring_label,
        scoring_preset=scoring_preset(lg.rules),
        trade_deadline_week=lg.trade_deadline_week,
        deadline_passed=ctx.deadline_passed,
        playoff_week_start=lg.playoff_start,
        uses_faab=lg.uses_faab,
        faab_budget=lg.faab_budget,
        last_synced_at=lg.last_synced_at,
        scoring_notes=lg.scoring_notes,
    )


def free_agents(ctx: LeagueContext) -> list[str] | None:
    """Unrostered players with a projection (K and DEF too, so byes there get a streamer) — only
    knowable for synced platform leagues."""
    if ctx.league.platform == "manual":
        return None
    rostered = ctx.rostered
    return [
        pid
        for pid, p in ctx.players.items()
        if pid not in rostered and p.get("position") in ("QB", "RB", "WR", "TE", "K", "DEF")
        and (p.get("ppg") or 0) > 0 and p.get("nfl_team")
    ]  # fmt: skip


# ───────── /team/{id} ─────────


def _on_bye(ctx: LeagueContext, pid: str) -> bool:
    team = ctx.players[pid].get("nfl_team")
    return bool(team) and not ctx.schedule.has_game(team, ctx.week)


def team_view(ctx: LeagueContext, team_id: str) -> m.TeamOut:
    team = ctx.team(team_id)
    profs = profiles(ctx)
    prof = profs.get(team_id)
    # This week's best lineup (matchup-adjusted): a player on bye or ruled out can't be in it, and
    # a starter whose game is already final keeps his spot. Full-strength profiles are for grades.
    optimal = week_plan(ctx, team_id).starters
    slot_of = team.slots
    roster = []
    for pid in team.player_ids:
        if pid not in ctx.players:
            continue
        roster.append(
            m.RosterPlayer(
                **player_value(ctx, pid),
                slot=slot_of.get(pid, "bench"),
                optimal_starter=pid in optimal,
                on_bye=_on_bye(ctx, pid),
                flags=[flag_out(f) for f in ctx.regression.for_player(pid)],
            )
        )
    roster.sort(
        key=lambda r: (
            not r.optimal_starter,
            ["QB", "RB", "WR", "TE", "K", "DEF"].index(r.position)
            if r.position in ("QB", "RB", "WR", "TE", "K", "DEF")
            else 9,
            -r.ppg,
        )
    )
    summaries = [
        m.TeamSummary(
            team_id=t.team_id,
            team_name=t.team_name,
            owner_name=t.owner_name,
            is_mine=t.is_mine,
            wins=t.wins,
            losses=t.losses,
            points_for=t.points_for,
            starter_points=profs[t.team_id].starter_points if t.team_id in profs else 0.0,
            grades=grades_out(profs.get(t.team_id)),
            overall_grade=overall_out(profs.get(t.team_id)),
        )
        for t in ctx.teams
    ]
    return m.TeamOut(
        team_id=team.team_id,
        team_name=team.team_name,
        owner_name=team.owner_name,
        record=f"{team.wins}-{team.losses}",
        league=league_out(ctx),
        roster=roster,
        grades=grades_out(prof),
        overall_grade=overall_out(prof),
        grade_basis=grade_basis(ctx),
        needs=prof.needs if prof else [],
        surplus=prof.surplus if prof else [],
        starter_points=prof.starter_points if prof else 0.0,
        league_teams=summaries,
        market=market_info(ctx),
    )


# ───────── /team/{id}/byes ─────────


def _byes_rows(ctx: LeagueContext, team_id: str):
    key = ("byes", team_id)
    if key not in ctx.memo:
        team = ctx.team(team_id)
        entries = [
            RosterEntry(
                pid,
                p["name"],
                p["position"],
                p.get("nfl_team"),
                p.get("ppg") or 0.0,
                p.get("injury_status"),
                p.get("status"),
                p.get("return_week"),
            )
            for pid in team.player_ids
            if (p := ctx.players.get(pid))
        ]
        ctx.memo[key] = bye_grid(
            entries,
            starting_slots(ctx.league.roster_positions),
            ctx.schedule,
            ctx.week,
            ctx.league.last_week,
            ctx.replacement_ppg,
            inj=ctx.tuning.injury,
        )
    return ctx.memo[key]


def byes_view(ctx: LeagueContext, team_id: str) -> m.ByesOut:
    team = ctx.team(team_id)
    rows = _byes_rows(ctx, team_id)
    weeks = [
        m.ByeWeekOut(
            week=r.week,
            weeks_away=r.weeks_away,
            cells=[
                m.SlotCellOut(
                    slot=c.slot,
                    label=c.label,
                    status=c.status,  # type: ignore[arg-type]
                    player=player_ref(ctx, c.player_id) if c.player_id else None,
                    ppg=c.ppg,
                )
                for c in r.cells
            ],
            on_bye=r.on_bye,
            starters_on_bye=r.starters_on_bye,
            danger=r.danger,
            danger_slots=r.danger_slots,
            lineup_points=r.lineup_points,
            full_strength_points=r.full_strength_points,
        )
        for r in rows
    ]
    players = []
    for pid in team.player_ids:
        p = ctx.players.get(pid)
        if not p:
            continue
        bye = p.get("bye_week")
        players.append(
            m.PlayerByeOut(
                player=player_ref(ctx, pid),
                bye_week=bye,
                weeks_away=(bye - ctx.week) if bye is not None and bye >= ctx.week else None,
                done=bye is not None and bye < ctx.week,
            )
        )
    players.sort(key=lambda x: (x.done, x.bye_week or 99))
    return m.ByesOut(
        team_id=team_id,
        week=ctx.week,
        last_week=ctx.league.last_week,
        slots=starting_slots(ctx.league.roster_positions),
        weeks=weeks,
        players=players,
        danger_weeks=[r.week for r in rows if r.danger],
    )


# ───────── /team/{id}/regression ─────────


def regression_view(ctx: LeagueContext, team_id: str, league_limit: int = 200) -> m.RegressionOut:
    team = ctx.team(team_id)
    owner = {p: t for t in ctx.teams for p in t.player_ids}

    def row(pid: str) -> m.PlayerFlagsOut:
        p = ctx.players[pid]
        t = owner.get(pid)
        flags = [flag_out(f) for f in ctx.regression.for_player(pid)]
        top = max(flags, key=lambda f: f.size, default=None)
        return m.PlayerFlagsOut(
            player=player_ref(ctx, pid),
            team_id=t.team_id if t else None,
            team_name=t.team_name if t else None,
            on_my_team=pid in team.player_ids,
            regression_score=p.get("regression_score") or 0.0,
            actual_td=p.get("actual_td"),
            expected_td=_r(p.get("expected_td"), 1),
            tdoe=_r(p.get("tdoe"), 1),
            market_rank=p.get("market_rank_cov"),
            model_rank=p.get("model_pos_rank"),
            flags=flags,
            signal=p.get("signal") or "hold",
            strength=top.size if top else 0.0,
            direction=top.direction if top else 0,
        )

    roster = [
        row(pid)
        for pid in team.player_ids
        if pid in ctx.players and ctx.players[pid]["position"] in ("QB", "RB", "WR", "TE")
    ]
    roster.sort(key=lambda r: -abs(r.regression_score))
    flagged = {f.player_id for f in ctx.regression.flags}
    relevant = [
        pid for pid in flagged
        if pid in ctx.players and pid not in team.player_ids
        and (pid in owner or (ctx.players[pid].get("ros_value_par") or 0) > 0)
    ]  # fmt: skip
    # strongest flags first (the client shows the top 20, then more on request)
    league = sorted((row(pid) for pid in relevant), key=lambda r: (-r.strength, r.player.name))[
        :league_limit
    ]
    return m.RegressionOut(
        team_id=team_id,
        week=ctx.week,
        roster=roster,
        league=league,
        thresholds={
            "tdoe": TDOE_THRESHOLD,
            "efficiency_z": Z_THRESHOLD,
            "usage_shift": USAGE_SHIFT,
        },
    )


# ───────── trades ─────────


def roster_rules(ctx: LeagueContext) -> tr.RosterRules:
    """The league's roster limit, who sits on IR / taxi (they don't use an active spot), and how
    much bench depth per position the user keeps (forced drops cut surplus beyond it), and when a
    bench player is free to drop."""
    return tr.RosterRules(
        active_limit=tr.active_limit(ctx.league.roster_positions),
        reserved=frozenset(p for t in ctx.teams for p, s in t.slots.items() if s in ("ir", "taxi")),
        reserve_slots=tr.reserve_slots(ctx.league.roster_positions),
        bench_backups=ctx.tuning.bench_backups_per_position,
        free_drop_ppg=ctx.tuning.free_drop_ppg,
    )


def trade_out(ctx: LeagueContext, ev: tr.TradeEvaluation) -> m.TradeOut:
    def side(s: tr.TradeSide) -> m.TradeSideOut:
        return m.TradeSideOut(
            team_id=s.team_id,
            team_name=ctx.team(s.team_id).team_name,
            gives=[player_ref(ctx, p) for p in s.gives],
            receives=[player_ref(ctx, p) for p in s.receives],
            lineup_before=round(s.lineup_before, 1),
            lineup_after=round(s.lineup_after, 1),
            lineup_delta=s.lineup_delta,
            # whole points, rounded the same way as the reasons text so the two always agree
            model_value_out=float(round(s.model_value_out)),
            model_value_in=float(round(s.model_value_in)),
            market_value_out=s.market_value_out,
            market_value_in=s.market_value_in,
            drops=[
                m.DropOut(player=player_ref(ctx, d.player_id), reason=d.reason) for d in s.drops
            ],
            new_short_weeks=s.new_short_weeks,
            fixed_short_weeks=s.fixed_short_weeks,
            weekly=[m.WeekPointsOut(week=w.week, before=w.before, after=w.after) for w in s.weekly],
        )

    return m.TradeOut(
        verdict=ev.verdict,  # type: ignore[arg-type]
        headline=ev.headline,
        reasons=ev.reasons,
        me=side(ev.me),
        partner=side(ev.partner) if ev.partner else None,
        danger_weeks_before=ev.danger_weeks_before,
        danger_weeks_after=ev.danger_weeks_after,
        tags=ev.tags,
        partner_accepts=ev.partner_accepts,
        market_values_missing=ev.market_values_missing,
    )


def evaluate_trade(
    ctx: LeagueContext, team_id: str, give: list[str], receive: list[str]
) -> m.TradeOut:
    team = ctx.team(team_id)
    if not give and not receive:
        raise InvalidInput("pick at least one player to give or receive")
    unknown = [p for p in [*give, *receive] if p not in ctx.players]
    if unknown:
        raise InvalidInput(f"unknown player(s): {', '.join(unknown[:3])}")
    owned = [p for p in receive if ctx.owner_of(p)]
    owners = {ctx.owner_of(p).team_id for p in owned}  # type: ignore[union-attr]
    if owners == {team_id}:
        raise InvalidInput("you already have a player you're trying to receive")
    if len(owners) > 1:
        raise InvalidInput("all received players must come from the same team")
    if owned and len(owned) != len(receive):
        raise InvalidInput(
            "mix of rostered and unrostered players: trade with one team, or make it fully hypothetical"
        )
    # Players on a league team -> two-sided trade; otherwise a hypothetical trade (manual teams,
    # free agents, or players from another league) that only models your side.
    partner = ctx.team(owners.pop()) if owners else None
    try:
        ev = tr.evaluate(
            ros_math(ctx),
            ctx.players,
            (team.team_id, team.player_ids),
            (partner.team_id, partner.player_ids) if partner else None,
            give,
            receive,
            viable_ppg=ctx.replacement_ppg,
            market_label=market_label(ctx),
            accept_gain=ctx.tuning.trade_accept_gain,
            lean_gain=ctx.tuning.trade_lean_gain,
            rules=roster_rules(ctx),
        )
    except ValueError as exc:  # signals/ stays app-agnostic and raises plain ValueError
        raise InvalidInput(str(exc)) from exc
    return trade_out(ctx, ev)


def trade_candidates(ctx: LeagueContext, team_id: str) -> list[tr.TradeEvaluation]:
    """Every mutually beneficial idea, best first (computed once per context, then paged)."""
    key = ("trades", team_id)
    if key not in ctx.memo:
        if ctx.deadline_passed:
            ctx.memo[key] = []
        else:
            team = ctx.team(team_id)
            others = {t.team_id: t.player_ids for t in ctx.teams if t.team_id != team_id}
            ctx.memo[key] = tr.candidate_trades(
                ros_math(ctx),
                ctx.players,
                (team.team_id, team.player_ids),
                others,
                use_market=ctx.market_source is not None,
                market_label=market_label(ctx),
                accept_gain=ctx.tuning.trade_accept_gain,
                lean_gain=ctx.tuning.trade_lean_gain,
                viable_ppg=ctx.replacement_ppg,
                rules=roster_rules(ctx),
            )
    return ctx.memo[key]


def trade_ideas(ctx: LeagueContext, team_id: str, page: int = 0) -> list[tr.TradeEvaluation]:
    return tr.paginate(trade_candidates(ctx, team_id), page)[0]


def suggest_view(ctx: LeagueContext, team_id: str, page: int = 0) -> m.TradeSuggestOut:
    ideas, has_more = tr.paginate(trade_candidates(ctx, team_id), page)
    return m.TradeSuggestOut(
        team_id=team_id,
        week=ctx.week,
        deadline_passed=ctx.deadline_passed,
        trade_deadline_week=ctx.league.trade_deadline_week,
        ideas=[trade_out(ctx, ev) for ev in ideas],
        page=page,
        has_more=has_more,
    )


def find_view(
    ctx: LeagueContext, team_id: str, give: list[str], want_position: str, receive_count: int
) -> m.TradeFindOut:
    team = ctx.team(team_id)
    if ctx.league.platform == "manual" or len(ctx.teams) < 2:
        raise InvalidInput("Finding trade partners needs a synced Sleeper or ESPN league.")
    others = {t.team_id: t.player_ids for t in ctx.teams if t.team_id != team_id}
    try:
        ideas = tr.find_for(
            ros_math(ctx),
            ctx.players,
            (team.team_id, team.player_ids),
            others,
            give,
            want_position,
            receive_count,
            viable_ppg=ctx.replacement_ppg,
            rules=roster_rules(ctx),
            market_label=market_label(ctx),
            accept_gain=ctx.tuning.trade_accept_gain,
            lean_gain=ctx.tuning.trade_lean_gain,
        )
    except ValueError as exc:
        raise InvalidInput(str(exc)) from exc
    return m.TradeFindOut(
        team_id=team_id,
        deadline_passed=ctx.deadline_passed,
        searched_teams=len(others),
        ideas=[trade_out(ctx, ev) for ev in ideas],
    )


# ───────── advice ─────────


def advice_view(ctx: LeagueContext, team_id: str) -> m.AdviceOut:
    team = ctx.team(team_id)
    profs = profiles(ctx)
    msgs: dict[str, list[str]] = {}
    for f in ctx.regression.flags:
        msgs.setdefault(f.player_id, []).append(f.message)
    inp = adv.AdvisorInputs(
        my_team_id=team_id,
        rosters={t.team_id: t.player_ids for t in ctx.teams},
        team_names={t.team_id: t.team_name for t in ctx.teams},
        starters=team.starters,
        players=ctx.players,
        profiles=profs,
        byes=_byes_rows(ctx, team_id),
        math=ros_math(ctx),
        week_plan=week_plan(ctx, team_id),
        week=ctx.week,
        trade_deadline_week=ctx.league.trade_deadline_week,
        trade_ideas=trade_ideas(ctx, team_id),
        free_agents=free_agents(ctx),
        regression_messages=msgs,
        waivers=waiver_picks(ctx, team_id),
        market_label=market_label(ctx),
        playoff_label=ctx.league.playoff_label,
        waiver_min_gain=ctx.tuning.waiver_min_gain,
        start_sit_min_gain=ctx.tuning.start_sit_min_gain,
        easy_schedule=ctx.tuning.easy_schedule,
        tough_schedule=ctx.tuning.tough_schedule,
        gap_min_points=ctx.tuning.gap_min_points,
        gap_min_share=ctx.tuning.gap_min_share,
    )
    actions = adv.build_feed(inp)
    names = {t.team_id: t.team_name for t in ctx.teams}
    notes = []
    if ctx.market_stale:
        notes.append(
            f"Market values are from {market_label(ctx)} ({ctx.market_format}); "
            "FantasyCalc values for your exact format weren't available."
        )
    if ctx.market_source is None:
        notes.append("No market values available — market-based reasons are skipped.")
    if ctx.deadline_passed:
        notes.append(
            f"Trade deadline (week {ctx.league.trade_deadline_week}) has passed — trade advice hidden."
        )
    if ctx.league.platform == "manual":
        notes.append(
            "Manual team: waiver advice and trade partners need a synced league (free agents and "
            "other rosters unknown)."
            + ("" if team.starters else " Mark your starters to get start/sit advice.")
        )
    return m.AdviceOut(
        team_id=team_id,
        season=ctx.season,
        week=ctx.week,
        generated_at=datetime.now(),
        actions=[
            m.ActionOut(
                type=a.type,  # type: ignore[arg-type]
                headline=a.headline,
                reasons=a.reasons,
                urgency=a.urgency,  # type: ignore[arg-type]
                confidence=a.confidence,  # type: ignore[arg-type]
                priority=a.priority,
                players=[player_ref(ctx, p) for p in a.player_ids],
                counterparty_team_id=a.team_id,
                counterparty_team_name=names.get(a.team_id) if a.team_id else None,
                trade=trade_out(ctx, a.trade) if a.trade else None,
            )
            for a in actions
        ],
        grades=grades_out(profs.get(team_id)),
        overall_grade=overall_out(profs.get(team_id)),
        grade_basis=grade_basis(ctx),
        needs=profs[team_id].needs if team_id in profs else [],
        deadline_passed=ctx.deadline_passed,
        market=market_info(ctx),
        notes=notes,
    )


# ───────── buy targets ─────────


def _owner_label(ctx: LeagueContext, pid: str, team_id: str) -> tuple[str | None, bool]:
    owner = ctx.owner_of(pid)
    if owner is not None:
        return (
            "Your team" if owner.team_id == team_id else owner.team_name
        ), owner.team_id == team_id
    return (None if ctx.league.platform == "manual" else "Free agent"), False


def _cells_out(cells) -> list[m.MatchupCell]:
    return [
        m.MatchupCell(week=c.week, opponent=c.opponent, index=c.index, points=c.points)
        for c in cells
    ]


def _ranking_row(ctx: LeagueContext, team_id: str, rank: int, r: TargetRow) -> m.RankingRow:
    p = ctx.players[r.player_id]
    owner, mine = _owner_label(ctx, r.player_id, team_id)
    return m.RankingRow(
        rank=rank,
        player_id=r.player_id,
        name=p["name"],
        position=r.position,
        nfl_team=p.get("nfl_team"),
        owner=owner,
        mine=mine,
        points=r.points,
        neutral_points=r.neutral_points,
        schedule_delta=r.schedule_delta,
        avg_index=r.avg_index,
        games=r.games,
        ppg=_r(p.get("ppg")) or 0.0,
        availability_note=p.get("availability_note"),
        cells=_cells_out(r.cells),
        signal=p.get("signal") or "hold",
    )


def rankings_view(ctx: LeagueContext, team_id: str, top: int = 10) -> m.RankingsOut:
    """Top `top` players at each position by matchup-adjusted points: each week and rest of season."""
    ctx.team(team_id)
    start, end = ctx.week, ctx.league.last_week
    key = ("rankings", top)
    if key not in ctx.memo:
        pool = {
            pid: p for pid, p in ctx.players.items() if pid in ctx.cells and (p.get("ppg") or 0) > 0
        }
        ctx.memo[key] = rank_targets(pool, ctx.cells, start, end, top=top)
    ranked = ctx.memo[key]
    return m.RankingsOut(
        team_id=team_id,
        top=top,
        week=start,
        last_week=end,
        weeks=list(range(start, end + 1)),
        positions={
            pos: m.RankingPosition(
                alpha=ctx.tuning.alpha.get(pos, 0.0),
                ros=[_ranking_row(ctx, team_id, i + 1, r) for i, r in enumerate(v["ros"])],
                weekly=[
                    m.RankingWeek(
                        week=w,
                        rows=[_ranking_row(ctx, team_id, i + 1, r) for i, r in enumerate(rows)],
                    )
                    for w, rows in v["weekly"].items()
                ],
            )
            for pos, v in ranked.items()
        },
    )


def _tier(p: dict, line: int | None) -> str:
    """starter if we rank him above the league's starter line, else bench depth / sleeper."""
    rank = p.get("model_pos_rank")
    return "starter" if line is not None and rank is not None and rank < line else "depth"


def _buy_row(
    ctx: LeagueContext, team_id: str, rank: int, pid: str, line: int | None
) -> m.BuyTargetRow:
    p = ctx.players[pid]
    owner, mine = _owner_label(ctx, pid, team_id)
    return m.BuyTargetRow(
        rank=rank,
        player_id=pid,
        name=p["name"],
        position=p["position"],
        nfl_team=p.get("nfl_team"),
        owner=owner,
        mine=mine,
        model_points=p.get("model_ros_points") or 0.0,
        model_rank=p.get("model_pos_rank"),
        market_rank=p.get("market_rank_cov"),
        market_implied_points=p.get("market_implied_points"),
        value_gap=p.get("value_gap"),
        signal=p.get("signal") or "hold",
        reasons=list(p.get("signal_reasons") or []),
        ppg=_r(p.get("ppg")) or 0.0,
        availability_note=p.get("availability_note"),
        cells=_cells_out(ros_row(pid, p["position"], ctx.cells[pid]).cells),
        tier=_tier(p, line),
    )


def buy_targets_view(ctx: LeagueContext, team_id: str, top: int | None = None) -> m.BuyTargetsOut:
    """Per position: undervalued players you don't own (would-be starters first, then bench depth
    and sleepers, each best projection first), and your overvalued ones."""
    top = top or ctx.tuning.targets_per_tier
    team = ctx.team(team_id)
    mine = set(team.player_ids)
    lines = replacement_ranks(ctx.shape)
    positions = {}
    for pos in TARGET_POSITIONS:
        line = lines.get(pos)
        valued = [
            pid
            for pid, p in ctx.players.items()
            if p.get("position") == pos and pid in ctx.cells and p.get("value_gap") is not None
        ]
        best_first = sorted(
            (pid for pid in valued if ctx.players[pid]["signal"] == "buy" and pid not in mine),
            key=lambda pid: (
                -(ctx.players[pid].get("model_ros_points") or 0.0),
                -ctx.players[pid]["value_gap"],
            ),
        )
        tiers = [
            [pid for pid in best_first if _tier(ctx.players[pid], line) == t][:top]
            for t in ("starter", "depth")
        ]
        sell = sorted(
            (pid for pid in valued if ctx.players[pid]["signal"] == "sell" and pid in mine),
            key=lambda pid: ctx.players[pid]["value_gap"],
        )
        positions[pos] = m.BuyTargetPosition(
            has_market=bool(valued),
            starter_line=line,
            buy=[
                _buy_row(ctx, team_id, i + 1, pid, line)
                for tier in tiers
                for i, pid in enumerate(tier)
            ],
            sell=[_buy_row(ctx, team_id, i + 1, pid, line) for i, pid in enumerate(sell)],
        )
    return m.BuyTargetsOut(
        team_id=team_id,
        week=ctx.week,
        last_week=ctx.league.last_week,
        market_label=market_label(ctx),
        positions=positions,
    )


# ───────── players table ─────────

TABLE_POSITIONS = ("QB", "RB", "WR", "TE", "K", "DEF")
_VERDICT_ORDER = {"buy": 0, "hold": 1, "sell": 2}


def fold(text: str) -> str:
    """Lower-case, accent-free, punctuation-free text for name search (Amon-Ra -> amonra)."""
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return "".join(ch for ch in plain.lower() if ch.isalnum() or ch == " ")


def _table_pool(ctx: LeagueContext) -> list[str]:
    if "table_pool" not in ctx.memo:
        rostered = ctx.rostered
        ctx.memo["table_pool"] = [
            pid for pid, p in ctx.players.items()
            if p.get("position") in TABLE_POSITIONS
            and ((p.get("ppg") or 0) > 0 or pid in rostered)
        ]  # fmt: skip
    return ctx.memo["table_pool"]


def _ros_points(ctx: LeagueContext, pid: str) -> float:
    cells = ctx.cells.get(pid)
    if cells is not None:
        return ros_points(cells)
    return ctx.players[pid].get("proj_ros_points") or 0.0


def players_table(
    ctx: LeagueContext,
    team_id: str,
    q: str = "",
    pos: str | None = None,
    nfl_team: str | None = None,
    avail: str = "all",
    sort: str = "ros",
    desc: bool = True,
    page: int = 0,
    size: int = 50,
) -> m.PlayersTableOut:
    """Every player, filtered, sorted and paged on the server."""
    team = ctx.team(team_id)
    mine = set(team.player_ids)
    rostered = ctx.rostered
    pool = _table_pool(ctx)
    needle = fold(q).replace(" ", "")

    def keep(pid: str) -> bool:
        p = ctx.players[pid]
        if pos and p.get("position") != pos:
            return False
        if nfl_team and p.get("nfl_team") != nfl_team:
            return False
        if avail == "mine" and pid not in mine:
            return False
        if avail == "other" and (pid in mine or pid not in rostered):
            return False
        if avail == "fa" and pid in rostered:
            return False
        return not needle or needle in fold(p.get("name") or "").replace(" ", "")

    hits = [pid for pid in pool if keep(pid)]

    def value(pid: str) -> float | None:
        p = ctx.players[pid]
        if sort == "ppg":
            return p.get("ppg") or 0.0
        if sort == "ros":
            return _ros_points(ctx, pid)
        if sort == "value":
            return p.get("ros_value_par") or 0.0
        return p.get("market_value")  # market

    def name(pid: str) -> str:
        return fold(ctx.players[pid].get("name") or pid)

    if sort == "name":
        hits.sort(key=name, reverse=desc)
    elif sort == "verdict":
        # "desc" = best verdict first: buys with the largest gap, holds, then sells
        def verdict_key(pid: str) -> tuple:
            p = ctx.players[pid]
            return (
                _VERDICT_ORDER.get(p.get("signal") or "hold", 1),
                -(p.get("value_gap") or 0.0),
                name(pid),
            )

        hits.sort(key=verdict_key, reverse=not desc)
    else:
        known = [pid for pid in hits if value(pid) is not None]
        unknown = [pid for pid in hits if value(pid) is None]  # no market value: always last
        known.sort(key=name)
        known.sort(key=lambda pid: value(pid), reverse=desc)  # stable: ties stay by name
        unknown.sort(key=name)
        hits = known + unknown

    rows = []
    for pid in hits[page * size : (page + 1) * size]:
        p = ctx.players[pid]
        owner, is_mine = _owner_label(ctx, pid, team_id)
        rows.append(
            m.PlayerTableRow(
                player_id=pid,
                name=p.get("name") or pid,
                position=p["position"],
                nfl_team=p.get("nfl_team"),
                owner=owner,
                mine=is_mine,
                ppg=_r(p.get("ppg")) or 0.0,
                ros_points=round(_ros_points(ctx, pid), 1),
                ros_value_par=_r(p.get("ros_value_par"), 1) or 0.0,
                market_value=p.get("market_value"),
                signal=p.get("signal") or "hold",
                value_gap=_r(p.get("value_gap"), 1),
                injury_status=p.get("injury_status"),
                bye_week=p.get("bye_week"),
                return_week=p.get("return_week"),
                availability_note=p.get("availability_note"),
            )
        )
    return m.PlayersTableOut(
        team_id=team_id,
        rows=rows,
        total=len(hits),
        page=page,
        size=size,
        nfl_teams=sorted({t for pid in pool if (t := ctx.players[pid].get("nfl_team"))}),
        market_label=market_label(ctx),
    )


# ───────── start / sit planner ─────────


def startsit_view(ctx: LeagueContext, team_id: str, week: int | None = None) -> m.StartSitOut:
    """Real lineup vs best lineup for a week, with what each slot accepts, for the planner."""
    team = ctx.team(team_id)
    week = ctx.week if week is None else week
    if not ctx.week <= week <= ctx.league.last_week:
        raise InvalidInput(f"week must be between {ctx.week} and {ctx.league.last_week}")
    plan = week_plan(ctx, team_id, week)
    reserved = {p for p, s in team.slots.items() if s in ("ir", "taxi")}
    players = []
    for pid in team.player_ids:
        p = ctx.players.get(pid)
        if p is None:
            continue
        cell = next((c for c in ctx.cells.get(pid, []) if c.week == week), None)
        code = p.get("nfl_team")
        players.append(
            m.StartSitPlayer(
                player=player_ref(ctx, pid),
                points=plan.points.get(pid, 0.0),
                opponent=ctx.schedule.opponent(code, week),
                matchup_index=cell.index if cell else None,
                on_bye=bool(code) and not ctx.schedule.has_game(code, week),
                injury_status=p.get("injury_status"),
                return_week=p.get("return_week"),
                locked=pid in plan.locked,
                reserved=pid in reserved,
            )
        )
    players.sort(key=lambda x: -x.points)
    return m.StartSitOut(
        team_id=team_id,
        week=week,
        weeks=list(range(ctx.week, ctx.league.last_week + 1)),
        slots=[
            m.StartSitSlot(slot=s, label=slot_label(s), eligible=sorted(SLOT_ELIGIBILITY[s]))
            for s in plan.slots
        ],
        players=players,
        current=plan.current,
        optimal=plan.optimal,
        current_points=plan.current_points,
        optimal_points=plan.optimal_points,
        gap=round(plan.optimal_points - plan.current_points, 2),
        has_lineup=bool(team.starters),
    )


# ───────── waivers ─────────

TRENDING_LIMIT = 25


def waiver_picks(ctx: LeagueContext, team_id: str) -> list[wv.WaiverPick]:
    """Free agents ranked by net rest-of-season gain to this team's lineup (empty: manual)."""
    key = ("waivers", team_id)
    if key not in ctx.memo:
        fas = free_agents(ctx)
        prof = profiles(ctx).get(team_id)
        ctx.memo[key] = (
            []
            if fas is None
            else wv.rank_waivers(
                ros_math(ctx), ctx.players, team_id, ctx.team(team_id).player_ids, fas,
                roster_rules(ctx), ctx.replacement_ppg, prof.needs if prof else (),
            )
        )  # fmt: skip
    return ctx.memo[key]


def faab_remaining(ctx: LeagueContext, team_id: str) -> int | None:
    if not ctx.league.uses_faab:
        return None
    left = ctx.team(team_id).faab_remaining
    return left if left is not None else ctx.league.faab_budget


def waivers_view(
    ctx: LeagueContext, team_id: str, trending: Sequence[tuple[str, int, datetime]] = ()
) -> m.WaiversOut:
    """Free agents by what they add to your lineup (with the drop and a FAAB range), plus
    Sleeper's trending adds and who has each of them in your league."""
    ctx.team(team_id)  # 404 for an unknown team
    t = ctx.tuning
    remaining = faab_remaining(ctx, team_id)
    rows = []
    for i, w in enumerate(waiver_picks(ctx, team_id)):
        p = ctx.players[w.player_id]
        bid = wv.faab_bid(w.gain, remaining, t.faab_full_gain, t.faab_aggression, t.faab_min_bid)
        rows.append(
            m.WaiverRow(
                rank=i + 1,
                player=player_ref(ctx, w.player_id),
                ppg=_r(p.get("ppg")) or 0.0,
                ros_points=round(_ros_points(ctx, w.player_id), 1),
                gain=w.gain,
                gain_per_week=w.gain_per_week,
                drop=player_ref(ctx, w.drop) if w.drop else None,
                drop_ppg=_r(ctx.players[w.drop].get("ppg")) if w.drop in ctx.players else None,
                drop_reason=w.drop_reason,
                fixes_weeks=w.fixes_weeks,
                need=w.need,
                injury_status=p.get("injury_status"),
                bye_week=p.get("bye_week"),
                return_week=p.get("return_week"),
                signal=p.get("signal") or "hold",
                faab=m.FaabBid(low=bid[0], bid=bid[1], high=bid[2]) if bid else None,
            )
        )
    trend_rows = []
    for pid, adds, _ in list(trending)[:TRENDING_LIMIT]:
        p = ctx.players.get(pid)
        if p is None:
            continue
        owner, mine = _owner_label(ctx, pid, team_id)
        trend_rows.append(
            m.TrendingRow(
                player=player_ref(ctx, pid),
                adds=adds,
                owner=owner,
                mine=mine,
                ppg=_r(p.get("ppg")),
                signal=p.get("signal") or "hold",
            )
        )
    prof = profiles(ctx).get(team_id)
    manual = ctx.league.platform == "manual"
    return m.WaiversOut(
        team_id=team_id,
        week=ctx.week,
        last_week=ctx.league.last_week,
        rows=rows,
        needs=prof.needs if prof else [],
        faab=m.FaabInfo(
            uses_faab=ctx.league.uses_faab,
            budget=ctx.league.faab_budget,
            remaining=remaining,
            full_gain=t.faab_full_gain,
            aggression=t.faab_aggression,
            min_bid=t.faab_min_bid,
        ),
        trending=trend_rows,
        trending_fetched_at=max((f for _, _, f in trending), default=None),
        as_of=ctx.league.last_synced_at,
        message=(
            "A manual team doesn't know who's on other rosters, so it can't list free agents. "
            "Connect your Sleeper or ESPN league to see waiver pickups."
            if manual
            else None
        ),
    )


# ───────── trades for one player ─────────

PLAYER_TRADE_LIMIT = 10


def player_trades_view(
    ctx: LeagueContext, team_id: str, player_id: str, want_position: str = "ANY"
) -> m.PlayerTradesOut:
    """Trades built around one player: shop him if he's yours, or what it takes to get him."""
    team = ctx.team(team_id)
    p = ctx.players.get(player_id)
    if p is None:
        raise NotFound("player", f"Player not found: {player_id}")
    owner = ctx.owner_of(player_id)

    def out(
        mode: str,
        ideas: tuple[tr.TradeEvaluation, ...] | list[tr.TradeEvaluation] = (),
        message: str | None = None,
    ) -> m.PlayerTradesOut:
        return m.PlayerTradesOut(
            team_id=team_id,
            player=player_ref(ctx, player_id),
            mode=mode,  # type: ignore[arg-type]
            owner=owner.team_name if owner else None,
            ideas=[trade_out(ctx, ev) for ev in ideas],
            message=message,
        )

    if ctx.league.platform == "manual" or len(ctx.teams) < 2:
        return out(
            "unavailable",
            message="Trades need a synced Sleeper or ESPN league (other rosters unknown). "
            "Use the Trade page's analyzer for a hypothetical deal.",
        )
    if ctx.deadline_passed:
        return out(
            "unavailable",
            message=f"Your league's trade deadline (week {ctx.league.trade_deadline_week}) has passed.",
        )
    if owner is None:
        return out(
            "free_agent",
            message=f"{p['name']} is a free agent: add him off waivers instead of trading for him.",
        )
    if p.get("position") not in SKILL_POSITIONS:
        return out("unavailable", message="Trade ideas cover QBs, RBs, WRs and TEs.")

    common = dict(
        viable_ppg=ctx.replacement_ppg,
        rules=roster_rules(ctx),
        market_label=market_label(ctx),
        accept_gain=ctx.tuning.trade_accept_gain,
        lean_gain=ctx.tuning.trade_lean_gain,
    )
    math = ros_math(ctx)
    mine = (team.team_id, team.player_ids)
    if owner.team_id == team_id:
        others = {t.team_id: t.player_ids for t in ctx.teams if t.team_id != team_id}
        ideas = [
            ev
            for n in (1, 2)
            for ev in tr.find_for(
                math, ctx.players, mine, others, [player_id], want_position, n, **common
            )
        ]
        ideas.sort(key=lambda e: (not e.partner_accepts, -e.score))
        return out("sell", ideas[:PLAYER_TRADE_LIMIT])
    ideas = tr.acquire_for(
        math,
        ctx.players,
        mine,
        (owner.team_id, owner.player_ids),
        player_id,
        limit=PLAYER_TRADE_LIMIT,
        use_market=ctx.market_source is not None,
        **common,
    )
    return out("buy", ideas)
