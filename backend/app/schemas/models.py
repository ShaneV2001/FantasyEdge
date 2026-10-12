"""Pydantic response/request models — the API contract the frontend client is generated from."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Position = Literal["QB", "RB", "WR", "TE", "K", "DEF"]
Urgency = Literal["this_week", "before_byes", "before_deadline", "rest_of_season"]
Confidence = Literal["high", "medium", "low"]
ActionType = Literal["Trade", "Sell", "Buy", "Waiver", "Lineup", "Bye prep"]


class ErrorOut(BaseModel):
    detail: str
    source: str | None = None


# ───────── players ─────────


class PlayerRef(BaseModel):
    player_id: str
    name: str
    position: str
    nfl_team: str | None = None


class PlayerValue(PlayerRef):
    sleeper_id: str | None = None
    ppg: float = Field(description="Projected fantasy points per game (league scoring)")
    p10: float | None = None
    p90: float | None = None
    l3_ppg: float | None = None
    season_ppg: float | None = None
    usage_ppg: float | None = None
    games_played: int | None = None
    proj_ros_points: float
    next4_points: float
    games_remaining: float
    ros_value_par: float = Field(description="Rest-of-season points above replacement")
    bye_week: int | None = None
    injury_status: str | None = None
    availability_note: str | None = None
    market_value: float | None = None
    market_rank: int | None = Field(None, description="Market rank within position")
    model_rank: int | None = Field(None, description="Model ROS-value rank within position")
    regression_score: float = 0.0
    ease_next4: float | None = Field(None, description="Matchup index next 4 weeks (>1 easier)")
    ease_playoffs: float | None = None
    method: str | None = None
    signal: Literal["buy", "hold", "sell"] = Field(
        "hold", description="Our projection vs the market: one verdict used everywhere"
    )
    signal_reasons: list[str] = []
    value_gap: float | None = Field(
        None, description="Model ROS points minus what the market's price implies"
    )
    market_implied_points: float | None = None
    model_ros_points: float | None = Field(None, description="Schedule-adjusted ROS points")


class FlagOut(BaseModel):
    kind: Literal["td_over_expected", "efficiency", "usage_mismatch"]
    metric: str
    direction: int = Field(description="+1 expect better production, -1 expect worse")
    value: float
    message: str
    numbers: dict = {}


class RosterPlayer(PlayerValue):
    slot: str = Field(description="Platform slot: starter | bench | ir | taxi")
    optimal_starter: bool = Field(description="In our best full-strength lineup")
    flags: list[FlagOut] = []


# ───────── leagues ─────────


class LeagueOut(BaseModel):
    league_id: str
    platform: str
    name: str
    season: int
    week: int
    num_teams: int
    roster_positions: list[str]
    scoring: str
    scoring_preset: Literal["standard", "half_ppr", "ppr"] | None = Field(
        None, description="Preset key when the rules match one exactly"
    )
    trade_deadline_week: int | None
    deadline_passed: bool
    playoff_week_start: int = Field(description="First fantasy-playoff week")
    uses_faab: bool
    faab_budget: int | None
    last_synced_at: datetime | None


class TeamChoiceOut(BaseModel):
    external_roster_id: str
    team_name: str
    owner_name: str
    is_user: bool


class LeagueChoiceOut(BaseModel):
    league_id: str
    external_id: str
    name: str
    season: int
    num_teams: int
    scoring: str
    roster_positions: list[str]
    teams: list[TeamChoiceOut]


class ConnectRequest(BaseModel):
    platform: Literal["sleeper"] = "sleeper"
    username: str = Field(min_length=1, max_length=64)


class ConnectResponse(BaseModel):
    username: str
    leagues: list[LeagueChoiceOut]


class SelectTeamRequest(BaseModel):
    external_roster_id: str


class TeamRef(BaseModel):
    team_id: str
    league_id: str


class ManualLeagueRequest(BaseModel):
    name: str = Field(default="My team", max_length=80)
    num_teams: int = Field(default=12, ge=2, le=32)
    roster_positions: list[str] = Field(
        default=["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF", *["BN"] * 6],
        description="Starting slots plus one 'BN' per bench spot and one 'IR' per IR spot "
        "(bench depth varies by league).",
        min_length=1,
        max_length=60,
    )
    scoring: Literal["standard", "half_ppr", "ppr"] | dict[str, float] = "half_ppr"
    player_ids: list[str] = Field(
        min_length=1, max_length=60, description="Everyone on the roster (starters, bench and IR)"
    )
    starters: list[str] = Field(
        default=[],
        description="Subset of player_ids in the starting lineup; must fit the starting slots. "
        "Empty = we pick the best lineup.",
    )
    ir: list[str] = Field(default=[], description="Subset of player_ids stashed on IR")
    trade_deadline_week: int | None = None
    playoff_week_start: int = Field(
        default=15, ge=1, le=18, description="First fantasy-playoff week (playoffs run 3 weeks)"
    )


# ───────── team ─────────


class PositionGradeOut(BaseModel):
    position: str
    points: float
    league_avg: float
    rank: int
    teams: int
    grade: Literal["A", "B", "C", "D", "F"]
    delta_pct: float
    z: float = Field(0.0, description="Standard deviations above the comparison-league average")


class MarketInfo(BaseModel):
    source: str | None
    format: str
    stale: bool = Field(description="True when using a fallback source or another format")


class TeamSummary(BaseModel):
    team_id: str
    team_name: str
    owner_name: str
    is_mine: bool
    wins: int
    losses: int
    points_for: float
    starter_points: float
    grades: dict[str, PositionGradeOut]
    overall_grade: PositionGradeOut | None = None


class TeamOut(BaseModel):
    team_id: str
    team_name: str
    owner_name: str
    record: str
    league: LeagueOut
    roster: list[RosterPlayer]
    grades: dict[str, PositionGradeOut]
    overall_grade: PositionGradeOut | None = None
    grade_basis: str = Field("", description="What the grades are compared against")
    needs: list[str]
    surplus: list[str]
    starter_points: float
    league_teams: list[TeamSummary]
    market: MarketInfo


# ───────── advice / regression / byes ─────────


class TradeSideOut(BaseModel):
    team_id: str
    team_name: str
    gives: list[PlayerRef]
    receives: list[PlayerRef]
    lineup_before: float
    lineup_after: float
    lineup_delta: float
    model_value_out: float
    model_value_in: float
    market_value_out: float | None
    market_value_in: float | None


class TradeOut(BaseModel):
    verdict: Literal["accept", "lean_accept", "neutral", "decline"]
    headline: str
    reasons: list[str]
    me: TradeSideOut
    partner: TradeSideOut | None = Field(
        None, description="Null for a hypothetical trade with players not on a league roster"
    )
    danger_weeks_before: int | None = None
    danger_weeks_after: int | None = None
    tags: list[str] = []


class ActionOut(BaseModel):
    type: ActionType
    headline: str
    reasons: list[str]
    urgency: Urgency
    confidence: Confidence
    priority: float
    players: list[PlayerRef]
    counterparty_team_id: str | None = None
    counterparty_team_name: str | None = None
    trade: TradeOut | None = None


class AdviceOut(BaseModel):
    team_id: str
    season: int
    week: int
    generated_at: datetime
    actions: list[ActionOut]
    grades: dict[str, PositionGradeOut]
    overall_grade: PositionGradeOut | None = None
    grade_basis: str = ""
    needs: list[str]
    deadline_passed: bool
    market: MarketInfo
    notes: list[str] = []


class PlayerFlagsOut(BaseModel):
    player: PlayerRef
    team_id: str | None
    team_name: str | None = Field(None, description="Fantasy owner; null = free agent")
    on_my_team: bool
    regression_score: float
    actual_td: int | None = None
    expected_td: float | None = None
    tdoe: float | None = None
    market_rank: int | None = None
    model_rank: int | None = None
    signal: Literal["buy", "hold", "sell"] = "hold"
    flags: list[FlagOut]


class RegressionOut(BaseModel):
    team_id: str
    week: int
    roster: list[PlayerFlagsOut]
    league: list[PlayerFlagsOut]
    thresholds: dict[str, float]


class SlotCellOut(BaseModel):
    slot: str
    label: str
    status: Literal["ok", "thin", "empty"]
    player: PlayerRef | None = None
    ppg: float | None = None


class ByeWeekOut(BaseModel):
    week: int
    weeks_away: int
    cells: list[SlotCellOut]
    on_bye: list[str]
    starters_on_bye: list[str]
    danger: bool
    danger_slots: list[str]
    lineup_points: float
    full_strength_points: float


class PlayerByeOut(BaseModel):
    player: PlayerRef
    bye_week: int | None
    weeks_away: int | None
    done: bool


class ByesOut(BaseModel):
    team_id: str
    week: int
    last_week: int
    slots: list[str]
    weeks: list[ByeWeekOut]
    players: list[PlayerByeOut]
    danger_weeks: list[int]


# ───────── buy targets ─────────


class MatchupCell(BaseModel):
    week: int
    opponent: str | None = Field(None, description="None on a bye")
    index: float | None = Field(
        None, description="Opponent's fantasy points allowed to the position vs average (>1 easier)"
    )
    points: float = Field(description="Matchup-adjusted projected points")


class RankingRow(BaseModel):
    rank: int
    player_id: str
    name: str
    position: str
    nfl_team: str | None
    owner: str | None = Field(None, description="Team name, 'Free agent', or None if unknown")
    mine: bool
    points: float = Field(description="Matchup-adjusted projected points (week or rest of season)")
    neutral_points: float = Field(description="Same projection against an average schedule")
    schedule_delta: float = Field(description="points - neutral_points: what the schedule adds")
    avg_index: float | None
    games: int
    ppg: float
    availability_note: str | None = None
    cells: list[MatchupCell] = Field(description="Weekly view: that week; ROS: next few opponents")
    signal: Literal["buy", "hold", "sell"] = "hold"


class RankingWeek(BaseModel):
    week: int
    rows: list[RankingRow]


class RankingPosition(BaseModel):
    alpha: float = Field(description="How strongly matchups move this position (0 = not at all)")
    ros: list[RankingRow]
    weekly: list[RankingWeek]


class RankingsOut(BaseModel):
    team_id: str
    week: int
    last_week: int
    weeks: list[int]
    positions: dict[str, RankingPosition]


class BuyTargetRow(BaseModel):
    rank: int
    player_id: str
    name: str
    position: str
    nfl_team: str | None
    owner: str | None
    mine: bool
    model_points: float = Field(description="Our schedule-adjusted ROS points")
    model_rank: int | None
    market_rank: int | None
    market_implied_points: float | None = Field(
        None, description="ROS points of the player we rank where the market ranks him"
    )
    value_gap: float | None
    signal: Literal["buy", "hold", "sell"]
    reasons: list[str]
    ppg: float
    availability_note: str | None = None
    cells: list[MatchupCell]
    tier: Literal["starter", "depth"] = Field(
        description="starter: we rank him above the league's starter line; depth: bench / sleeper"
    )


class BuyTargetPosition(BaseModel):
    has_market: bool = Field(description="False when the market doesn't value this position")
    starter_line: int | None = Field(
        None, description="Rank of the first non-starter league-wide at this position"
    )
    buy: list[BuyTargetRow] = Field(description="Undervalued players on other teams / free agents")
    sell: list[BuyTargetRow] = Field(description="Your players the market overvalues")


class BuyTargetsOut(BaseModel):
    team_id: str
    week: int
    last_week: int
    market_label: str
    positions: dict[str, BuyTargetPosition]


# ───────── player page ─────────


class PlayerWeekOut(BaseModel):
    week: int
    opponent: str | None
    played: bool
    actual: float | None = Field(None, description="Fantasy points scored (league scoring)")
    projected: float | None = Field(None, description="What we projected before that week")
    p10: float | None = None
    p90: float | None = None
    statline: dict[str, float | None] = {}


class PlayerDetailOut(BaseModel):
    player_id: str
    name: str
    position: str
    nfl_team: str | None
    headshot_url: str | None
    team_logo_url: str | None
    age: int | None
    years_exp: int | None
    depth_chart_order: int | None
    injury_status: str | None
    availability_note: str | None
    bye_week: int | None
    owner: str | None = Field(None, description="Fantasy team that rosters him (None = nobody)")
    mine: bool
    ppg: float
    p10: float | None
    p90: float | None
    model_ros_points: float | None
    ros_value_par: float | None
    market_value: float | None
    model_rank: int | None
    market_rank: int | None
    market_implied_points: float | None
    value_gap: float | None
    signal: Literal["buy", "hold", "sell"]
    signal_reasons: list[str]
    flags: list[FlagOut]
    statline_keys: list[str] = Field(description="Statline columns for this position, in order")
    weeks: list[PlayerWeekOut]
    upcoming: list[MatchupCell]


# ───────── trades ─────────


class TradeEvaluateRequest(BaseModel):
    team_id: str
    give: list[str] = Field(default=[], max_length=5)
    receive: list[str] = Field(default=[], max_length=5)


class TradeSuggestOut(BaseModel):
    team_id: str
    week: int
    deadline_passed: bool
    trade_deadline_week: int | None
    ideas: list[TradeOut]


# ───────── meta ─────────


class SourceStatus(BaseModel):
    source: str
    last_synced_at: datetime | None
    status: str
    detail: str | None


class StatusOut(BaseModel):
    season: int | None
    week: int | None
    sources: list[SourceStatus]
    attribution: list[str]


class RefreshRequest(BaseModel):
    scope: Literal["league", "market", "all"] = "league"
    league_id: str | None = None


class RefreshOut(BaseModel):
    scope: str
    ok: bool
    detail: list[str]
    last_synced_at: datetime | None = None
