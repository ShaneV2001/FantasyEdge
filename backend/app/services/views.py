"""Compose LeagueContext + signals into API response models (phase-1 endpoints)."""

from __future__ import annotations

from datetime import datetime

from app.errors import InvalidInput
from app.schemas import models as m
from app.services.context import LeagueContext
from scoring.rules import PRESETS, normalize
from signals import advisor as adv
from signals import trade as tr
from signals.byes import RosterEntry, bye_grid
from signals.lineup import starting_slots
from signals.regression import TDOE_THRESHOLD, USAGE_SHIFT, Z_THRESHOLD, RegressionFlag
from signals.schedule import MATCHUP_ALPHA
from signals.targets import POSITIONS as TARGET_POSITIONS
from signals.targets import TargetRow, rank_targets
from signals.team import RosMath, TeamProfile, simulate_league, team_profiles

MARKET_LABEL = {"fantasycalc": "FantasyCalc", "dynastyprocess": "DynastyProcess"}


# ───────── shared helpers ─────────


def ros_math(ctx: LeagueContext) -> RosMath:
    if "math" not in ctx.memo:
        ctx.memo["math"] = RosMath(
            ctx.players,
            ctx.schedule,
            ctx.week,
            ctx.league.last_week,
            starting_slots(ctx.league.roster_positions),
        )
    return ctx.memo["math"]


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
        market_value=p.get("market_value"),
        market_rank=p.get("market_rank_cov"),
        model_rank=p.get("model_pos_rank"),
        regression_score=p.get("regression_score") or 0.0,
        ease_next4=_r(p.get("ease_next4")),
        ease_playoffs=_r(p.get("ease_playoffs")),
        method=p.get("method"),
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
    )


def free_agents(ctx: LeagueContext) -> list[str] | None:
    """Unrostered skill players with a projection — only knowable for synced platform leagues."""
    if ctx.league.platform == "manual":
        return None
    rostered = ctx.rostered
    return [
        pid
        for pid, p in ctx.players.items()
        if pid not in rostered and p.get("position") in ("QB", "RB", "WR", "TE") and (p.get("ppg") or 0) > 0
        and p.get("nfl_team")
    ]  # fmt: skip


# ───────── /team/{id} ─────────


def team_view(ctx: LeagueContext, team_id: str) -> m.TeamOut:
    team = ctx.team(team_id)
    profs = profiles(ctx)
    prof = profs.get(team_id)
    optimal = set(prof.starters) if prof else set()
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


def regression_view(ctx: LeagueContext, team_id: str, league_limit: int = 40) -> m.RegressionOut:
    team = ctx.team(team_id)
    owner = {p: t for t in ctx.teams for p in t.player_ids}

    def row(pid: str) -> m.PlayerFlagsOut:
        p = ctx.players[pid]
        t = owner.get(pid)
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
            flags=[flag_out(f) for f in ctx.regression.for_player(pid)],
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
    league = sorted((row(pid) for pid in relevant), key=lambda r: -abs(r.regression_score))[
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
            model_value_out=round(s.model_value_out, 1),
            model_value_in=round(s.model_value_in, 1),
            market_value_out=s.market_value_out,
            market_value_in=s.market_value_in,
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
        )
    except ValueError as exc:  # signals/ stays app-agnostic and raises plain ValueError
        raise InvalidInput(str(exc)) from exc
    return trade_out(ctx, ev)


def trade_ideas(ctx: LeagueContext, team_id: str) -> list[tr.TradeEvaluation]:
    key = ("trades", team_id)
    if key not in ctx.memo:
        if ctx.deadline_passed:
            ctx.memo[key] = []
        else:
            team = ctx.team(team_id)
            others = {t.team_id: t.player_ids for t in ctx.teams if t.team_id != team_id}
            ctx.memo[key] = tr.suggest(
                ros_math(ctx),
                ctx.players,
                (team.team_id, team.player_ids),
                others,
                use_market=ctx.market_source is not None,
                market_label=market_label(ctx),
            )
    return ctx.memo[key]


def suggest_view(ctx: LeagueContext, team_id: str) -> m.TradeSuggestOut:
    ideas = trade_ideas(ctx, team_id)
    return m.TradeSuggestOut(
        team_id=team_id,
        week=ctx.week,
        deadline_passed=ctx.deadline_passed,
        trade_deadline_week=ctx.league.trade_deadline_week,
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
        week=ctx.week,
        trade_deadline_week=ctx.league.trade_deadline_week,
        trade_ideas=trade_ideas(ctx, team_id),
        free_agents=free_agents(ctx),
        regression_messages=msgs,
        market_label=market_label(ctx),
        playoff_label=ctx.league.playoff_label,
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


def _target_row(ctx: LeagueContext, team_id: str, rank: int, r: TargetRow) -> m.TargetRow:
    p = ctx.players[r.player_id]
    owner, mine = _owner_label(ctx, r.player_id, team_id)
    return m.TargetRow(
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
        cells=[
            m.TargetCell(week=c.week, opponent=c.opponent, index=c.index, points=c.points)
            for c in r.cells
        ],
    )


def targets_view(ctx: LeagueContext, team_id: str) -> m.TargetsOut:
    """Top players at each position by matchup-adjusted points: each week and rest of season."""
    ctx.team(team_id)
    start, end = ctx.week, ctx.league.last_week
    if "targets" not in ctx.memo:
        pool = {
            pid: p
            for pid, p in ctx.players.items()
            if p.get("position") in TARGET_POSITIONS
            and p.get("nfl_team")
            and (p.get("ppg") or 0) > 0
        }
        ctx.memo["targets"] = rank_targets(
            pool, ctx.schedule, ctx.matchup, MATCHUP_ALPHA, start, end
        )
    ranked = ctx.memo["targets"]
    return m.TargetsOut(
        team_id=team_id,
        week=start,
        last_week=end,
        weeks=list(range(start, end + 1)),
        positions={
            pos: m.TargetPosition(
                alpha=MATCHUP_ALPHA.get(pos, 0.0),
                ros=[_target_row(ctx, team_id, i + 1, r) for i, r in enumerate(v["ros"])],
                weekly=[
                    m.TargetWeek(
                        week=w,
                        rows=[_target_row(ctx, team_id, i + 1, r) for i, r in enumerate(rows)],
                    )
                    for w, rows in v["weekly"].items()
                ],
            )
            for pos, v in ranked.items()
        },
    )
