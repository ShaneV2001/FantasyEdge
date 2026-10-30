"""Pydantic response/request models — the API contract the frontend client is generated from."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Position = Literal["QB", "RB", "WR", "TE", "K", "DEF"]
Urgency = Literal["this_week", "before_byes", "before_deadline", "rest_of_season"]
Confidence = Literal["high", "medium", "low"]
ActionType = Literal["Injury", "Offer", "Trade", "Sell", "Buy", "Waiver", "Lineup", "Bye prep"]


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
    return_week: int | None = Field(
        None, description="First week he can play when known (99 = out for the season)"
    )
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
    size: float = Field(
        0.0, description="How far past its flag threshold the value is (1 = right at it)"
    )


class RosterPlayer(PlayerValue):
    slot: str = Field(description="Platform slot: starter | bench | ir | taxi")
    optimal_starter: bool = Field(
        description="In this week's best lineup (players on bye or ruled out can't be in it)"
    )
    on_bye: bool = Field(False, description="His NFL team doesn't play this week")
    flags: list[FlagOut] = []
    arriving: bool = Field(False, description="Received in an accepted trade not processed yet")


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
    scoring_notes: list[str] = Field(
        default_factory=list, description="League scoring rules FantasyEdge can't model yet"
    )


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


class EspnConnectRequest(BaseModel):
    league_id: str = Field(min_length=1, max_length=20, description="The leagueId= number")
    season: int | None = Field(None, description="Defaults to the current NFL season")
    espn_s2: str | None = Field(None, max_length=2000, description="Private leagues only")
    swid: str | None = Field(None, max_length=100, description="Private leagues only")


class CredentialsOut(BaseModel):
    """Saved ESPN cookies, masked: only the last 4 characters ever leave the backend."""

    saved: bool
    espn_s2_last4: str | None
    swid_last4: str | None
    updated_at: datetime | None


class UnmatchedPlayerOut(BaseModel):
    espn_id: int
    name: str
    position: str | None
    nfl_team: str | None


class EspnConnectResponse(BaseModel):
    league: LeagueChoiceOut
    unmatched: list[UnmatchedPlayerOut] = Field(
        description="ESPN players we couldn't match to our player data (shown with 0 projection)"
    )
    scoring_notes: list[str]
    credentials: CredentialsOut


class CredentialsRequest(BaseModel):
    espn_s2: str = Field(min_length=10, max_length=2000)
    swid: str = Field(min_length=10, max_length=100)


class EspnDefaultsOut(BaseModel):
    """What the local .env provides, so the Connect form can be pre-filled (never the cookies)."""

    league_id: str | None
    cookies_in_env: bool
    season: int


class SelectTeamRequest(BaseModel):
    external_roster_id: str


class TeamRef(BaseModel):
    team_id: str
    league_id: str


class SavedTeamOut(BaseModel):
    team_id: str
    team_name: str
    league_id: str
    league_name: str
    platform: str = Field(description="sleeper | espn | manual | demo")
    season: int
    last_synced_at: datetime | None = None
    has_login: bool = Field(description="ESPN login cookies saved for this league")


class RenameTeamRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class ForgetOut(BaseModel):
    league_id: str
    platform: str
    teams_removed: int


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
    view: Literal["current", "after"] = Field(
        "current", description="after: as if the team's accepted pending trades had gone through"
    )
    pending_trades: int = Field(0, description="How many accepted trades the 'after' view applies")


# ───────── advice / regression / byes ─────────


class WeekPointsOut(BaseModel):
    week: int
    before: float = Field(description="Projected starting-lineup points that week before the trade")
    after: float


class DropOut(BaseModel):
    player: PlayerRef
    reason: str = Field(description="Why this player is the one to cut")


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
    drops: list[DropOut] = Field(
        default_factory=list,
        description="Players this team must release to stay at its roster limit, each with why",
    )
    new_short_weeks: list[int] = Field(
        default_factory=list,
        description="Weeks it could fill its lineup before the trade but can't after (byes/injuries)",
    )
    fixed_short_weeks: list[int] = Field(default_factory=list)
    weekly: list[WeekPointsOut] = Field(default_factory=list)


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
    partner_accepts: bool | None = Field(
        None,
        description="Whether the other team would likely say yes: fair by value, their lineup "
        "gains, and no new short week (null for a hypothetical trade)",
    )
    market_values_missing: bool = Field(
        False,
        description="No player in the league has a market value: forced drops were chosen by "
        "projections only",
    )
    fair_value: bool | None = Field(
        None,
        description="Within the fair-value band for both sides, need bonus included (null when a "
        "player has no value to judge by)",
    )
    market_gap: float | None = Field(
        None, description="How far the worse-off side falls short of even by value (0.1 = 10%)"
    )


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
    view: Literal["current", "after"] = Field(
        "current", description="after: as if the team's accepted pending trades had gone through"
    )
    pending_trades: int = Field(0, description="How many accepted trades the 'after' view applies")


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
    strength: float = Field(0.0, description="His biggest flag's size")
    direction: int = Field(
        0, description="Direction of his biggest flag: +1 buy-low, -1 sell-high, 0 no flags"
    )


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
    replaces: str | None = Field(
        None, description="The full-strength starter this player fills in for this week"
    )
    why: Literal["bye", "injury"] | None = Field(None, description="Why that starter is out")
    hole: bool = Field(
        False, description="Nobody can fill the slot this week, unlike at full strength"
    )


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
    points_lost: float = Field(0.0, description="Full strength minus this week's lineup points")


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


class RosterOutlookOut(BaseModel):
    """One team's week-by-week best lineups before and after a trade (same cells as the bye grid)."""

    team_id: str
    team_name: str
    gives: list[PlayerRef]
    receives: list[PlayerRef]
    drops: list[DropOut] = Field(description="Forced cuts to stay under the roster limit")
    before: list[ByeWeekOut]
    after: list[ByeWeekOut]


class TradeOutlookOut(BaseModel):
    week: int
    slots: list[str]
    me: RosterOutlookOut
    partner: RosterOutlookOut | None = None


class PendingTradeOut(BaseModel):
    id: str
    partner_team_id: str | None
    partner_name: str | None
    give: list[PlayerRef]
    receive: list[PlayerRef]
    drops: list[PlayerRef] = Field(description="Players released as part of the trade")
    accepted_at: datetime | None


class PendingTradesOut(BaseModel):
    """Trades both teams accepted on ESPN that haven't processed yet (league review period)."""

    team_id: str
    review_hours: int | None = Field(None, description="League review period before processing")
    trades: list[PendingTradeOut]
    outlook: TradeOutlookOut | None = Field(
        None, description="Your lineups with every pending trade applied"
    )


class PivotOut(BaseModel):
    player: PlayerRef
    points: float = Field(description="This week's projection")
    kickoff: datetime | None = Field(None, description="Kickoff (UTC)")


class GamedayAlertOut(BaseModel):
    player: PlayerRef
    slot: str = Field(description="Lineup slot label, e.g. RB or FLEX")
    severity: Literal["out", "high", "medium", "low"] = Field(
        description="out: won't play; high: Doubtful; medium: Questionable; low: missed practice"
    )
    status: str
    points: float = Field(description="This week's projection, already discounted for the status")
    kickoff: datetime | None = Field(None, description="Kickoff (UTC)")
    status_since: datetime | None = Field(
        None, description="When Sleeper's status last changed (UTC), if seen by a refresh"
    )
    reasons: list[str]
    pivot: PivotOut | None = Field(None, description="Best bench player for the slot")
    late_pivot: PivotOut | None = Field(
        None,
        description="Best bench player kicking off no earlier than him, when the pivot plays first",
    )
    free_agent: PivotOut | None = Field(
        None, description="Best free agent for the slot, when he beats the bench"
    )


class GamedayOut(BaseModel):
    """This week's starters who might not play, with who to start instead."""

    team_id: str
    week: int
    generated_at: datetime
    checked: int = Field(description="Starters checked (games not yet kicked off)")
    alerts: list[GamedayAlertOut]
    notes: list[str] = []


class MatchupPlayerOut(BaseModel):
    slot: str
    player: PlayerRef | None = Field(None, description="None = empty slot")
    projected: float = Field(
        description="Points still projected this week (0 once his game is final)"
    )
    actual: float | None = Field(None, description="Points scored so far this week")
    state: Literal["final", "live", "upcoming", "bye", "empty"]


class MatchupSideOut(BaseModel):
    team_id: str
    team_name: str
    projected: float = Field(description="Expected final score: banked points + projections")
    sd: float = Field(description="Spread of that expectation (1 sd)")
    actual: float = Field(description="Points scored so far")
    lineup: list[MatchupPlayerOut]


class StandingOut(BaseModel):
    team_id: str
    team_name: str
    is_mine: bool
    wins: int
    losses: int
    points_for: float
    proj_wins: float = Field(description="Expected final wins")
    proj_losses: float
    playoff_pct: float = Field(description="Share of simulated seasons in the playoffs (0–1)")
    top_seed_pct: float = Field(description="Share of simulated seasons as the 1 seed (0–1)")


class ScheduleWeekOut(BaseModel):
    week: int
    opponent_id: str | None
    opponent_name: str | None
    win_prob: float | None = Field(None, description="Your chance to win (unplayed weeks)")
    result: Literal["W", "L", "T"] | None = Field(None, description="Weeks already played")
    points: float | None = None
    opponent_points: float | None = None


class MatchupOut(BaseModel):
    """This week's head-to-head matchup, the standings with playoff odds, and your schedule."""

    team_id: str
    week: int
    has_schedule: bool = Field(description="False for manual teams or before the first sync")
    me: MatchupSideOut | None = None
    opponent: MatchupSideOut | None = None
    win_prob: float | None = Field(None, description="Your chance to win this week (0–1)")
    standings: list[StandingOut] = []
    schedule: list[ScheduleWeekOut] = []
    playoff_teams: int | None = None
    regular_season_weeks: int | None = None
    sims: int = 0
    notes: list[str] = []


class RecapPlayerOut(BaseModel):
    player: PlayerRef
    actual: float = Field(description="Points the platform scored him that week")
    projected: float | None = Field(None, description="FantasyEdge's projection before the week")
    p10: float | None = None
    p90: float | None = None
    band: Literal["above", "in_range", "below"] | None = Field(
        None, description="Where the actual landed vs the projection's p10–p90 band"
    )


class RecapWeekOut(BaseModel):
    week: int
    opponent_name: str | None
    result: Literal["W", "L", "T"] | None
    points: float = Field(description="Your score as the platform recorded it")
    opponent_points: float | None
    lineup_points: float = Field(description="Your starters' points")
    best_points: float = Field(description="The best lineup you could have set, in hindsight")
    left_on_bench: float
    fe_points: float = Field(description="What FantasyEdge's projected-best lineup scored")
    fe_lineup: list[PlayerRef]
    starters: list[RecapPlayerOut]
    should_have_started: list[RecapPlayerOut] = Field(
        description="Bench players in the best lineup"
    )
    instead_of: list[RecapPlayerOut] = Field(description="Starters the best lineup sat")


class RecapWeekSummaryOut(BaseModel):
    week: int
    result: Literal["W", "L", "T"] | None
    lineup_points: float
    best_points: float
    fe_points: float


class RecapSeasonOut(BaseModel):
    weeks: int
    lineup_points: float
    best_points: float
    fe_points: float
    left_on_bench: float
    starters_rated: int = Field(description="Starter-weeks with a FantasyEdge projection")
    mae: float | None = Field(None, description="Mean absolute error of those projections")
    in_band: float | None = Field(None, description="Share that landed inside p10–p90 (0–1)")


class RecapOut(BaseModel):
    """Looking back: your lineup vs the best one and vs FantasyEdge's, and projection accuracy."""

    team_id: str
    week: int | None = Field(None, description="The week shown (None: nothing to recap yet)")
    weeks: list[int] = Field(description="Weeks that can be recapped")
    detail: RecapWeekOut | None = None
    by_week: list[RecapWeekSummaryOut] = []
    season: RecapSeasonOut | None = None
    notes: list[str] = []


class TradeOfferOut(BaseModel):
    id: str
    direction: Literal["received", "sent"] = Field(
        description="received: another team proposed it to you; sent: you proposed it"
    )
    partner_team_id: str | None
    partner_name: str | None
    give: list[PlayerRef]
    receive: list[PlayerRef]
    drops: list[PlayerRef] = Field(description="Your players the offer releases")
    proposed_at: datetime | None
    evaluation: TradeOut | None = Field(
        None, description="The trade analyzer's verdict for your side, when it can be graded"
    )
    note: str | None = Field(None, description="Why the offer couldn't be graded")


class TradeOffersOut(BaseModel):
    """Open ESPN trade offers nobody has answered yet, graded for your side."""

    team_id: str
    supported: bool = Field(
        description="False for Sleeper and manual leagues: their APIs don't share open offers"
    )
    received: list[TradeOfferOut]
    sent: list[TradeOfferOut]


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
    top: int = Field(10, description="How many players per position each list holds")
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


class AnalyticsWindowOut(BaseModel):
    label: Literal["L3", "L5", "Season"]
    games: int
    metrics: dict[str, float | None] = Field(description="Metric key → value; null = no data")


class AnalyticsGroupOut(BaseModel):
    key: str
    label: str
    metrics: list[str]


class PlayerAnalyticsOut(BaseModel):
    groups: list[AnalyticsGroupOut]
    windows: list[AnalyticsWindowOut] = Field(description="Shortest window first; Season is last")


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
    injury_detail: str | None = Field(
        None, description="Injury report detail, e.g. 'Knee - ACL, surgery'"
    )
    return_week: int | None = Field(
        None, description="First week he can play when known (99 = out for the season)"
    )
    availability_source: Literal["rule", "override"] | None = Field(
        None, description="rule: season-ending injury in the report; override: your what-if"
    )
    override_return_week: int | None = Field(None, description="Your saved what-if return week")
    override_out_for_season: bool = False
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
    analytics: PlayerAnalyticsOut | None = Field(None, description="None for K/DEF or no games")


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
    page: int = 0
    has_more: bool = Field(False, description="Another page has ideas this one didn't show")


class TradeFindRequest(BaseModel):
    team_id: str
    give: list[str] = Field(min_length=1, max_length=3)
    want_position: Literal["QB", "RB", "WR", "TE", "ANY"] = "RB"
    receive_count: int = Field(1, ge=1, le=2)


class PlayerTradesOut(BaseModel):
    """Trades built around one player."""

    team_id: str
    player: PlayerRef
    mode: Literal["sell", "buy", "free_agent", "unavailable"] = Field(
        description="sell: he's yours (deals giving him away); buy: on another team (what it takes "
        "to get him); free_agent / unavailable: no trades, see message"
    )
    owner: str | None
    ideas: list[TradeOut]
    message: str | None = None


class TradeFindOut(BaseModel):
    team_id: str
    deadline_passed: bool
    searched_teams: int
    ideas: list[TradeOut]
    message: str | None = Field(
        None, description="Why there are no ideas: the closest package by value, if any"
    )


# ───────── availability what-if ─────────


class PlayerAvailabilityIn(BaseModel):
    out_for_season: bool = False
    return_week: int | None = Field(None, ge=1, le=18, description="First week he plays again")


class PlayerAvailabilityOut(BaseModel):
    player_id: str
    out_for_season: bool
    return_week: int | None


# ───────── players table ─────────

PlayerSort = Literal["ppg", "ros", "value", "market", "verdict", "name"]
Availability = Literal["all", "mine", "other", "fa"]


class PlayerTableRow(PlayerRef):
    owner: str | None = Field(None, description="Team name, 'Your team', 'Free agent', or None")
    mine: bool
    ppg: float = Field(description="Projected points per game (league scoring)")
    ros_points: float = Field(description="Schedule-adjusted projected points, rest of season")
    ros_value_par: float = Field(description="Rest-of-season points above replacement")
    market_value: float | None = None
    signal: Literal["buy", "hold", "sell"] = "hold"
    value_gap: float | None = None
    injury_status: str | None = None
    bye_week: int | None = None
    return_week: int | None = Field(
        None, description="First week he can play when known (99 = out for the season)"
    )
    availability_note: str | None = None


class FaabBid(BaseModel):
    low: int
    bid: int
    high: int


class WaiverRow(BaseModel):
    rank: int
    player: PlayerRef
    ppg: float
    ros_points: float = Field(description="His schedule-adjusted projected points, rest of season")
    gain: float = Field(
        description="Net rest-of-season starting-lineup points from adding him (after the drop)"
    )
    gain_per_week: float
    drop: PlayerRef | None = Field(None, description="Who you'd release (None: open roster spot)")
    drop_ppg: float | None = None
    drop_reason: str | None = Field(None, description="Why that player is the one to cut")
    fixes_weeks: list[int] = Field(description="Weeks you can't fill a slot today that he fills")
    need: bool = Field(description="Fills a short week or a position you're weak at")
    injury_status: str | None = None
    bye_week: int | None = None
    return_week: int | None = Field(
        None, description="First week he can play when known (99 = out for the season)"
    )
    signal: Literal["buy", "hold", "sell"] = "hold"
    faab: FaabBid | None = Field(None, description="Suggested bid range (FAAB leagues only)")


class FaabInfo(BaseModel):
    uses_faab: bool
    budget: int | None
    remaining: int | None
    full_gain: float
    aggression: float
    min_bid: int


class TrendingRow(BaseModel):
    player: PlayerRef
    adds: int = Field(description="Sleeper users who added him in the last 24 hours")
    owner: str | None = Field(None, description="Team name, 'Your team', 'Free agent', or None")
    mine: bool
    ppg: float | None = None
    signal: Literal["buy", "hold", "sell"] = "hold"


class WaiversOut(BaseModel):
    team_id: str
    week: int
    last_week: int
    rows: list[WaiverRow]
    needs: list[str]
    faab: FaabInfo
    trending: list[TrendingRow]
    trending_fetched_at: datetime | None = None
    as_of: datetime | None = Field(None, description="When rosters were last synced")
    message: str | None = None


class StartSitSlot(BaseModel):
    slot: str = Field(description="Lineup slot key (QB, RB, FLEX, SUPER_FLEX, ...)")
    label: str
    eligible: list[str] = Field(description="Positions that can fill it")


class StartSitPlayer(BaseModel):
    player: PlayerRef
    points: float = Field(description="Projected points this week (matchup-adjusted; 0 if done)")
    opponent: str | None = None
    matchup_index: float | None = Field(None, description=">1 = easier than average")
    on_bye: bool
    injury_status: str | None = None
    return_week: int | None = Field(
        None, description="First week he can play when known (99 = out for the season)"
    )
    locked: bool = Field(description="His game this week is already final: he can't be moved")
    reserved: bool = Field(description="On IR or taxi: can't be started")


class StartSitOut(BaseModel):
    team_id: str
    week: int
    weeks: list[int] = Field(description="Weeks you can plan")
    slots: list[StartSitSlot]
    players: list[StartSitPlayer]
    current: list[str | None] = Field(description="Your real lineup, one player id per slot")
    optimal: list[str | None] = Field(description="The best lineup, one player id per slot")
    current_points: float
    optimal_points: float
    gap: float = Field(description="optimal_points - current_points")
    has_lineup: bool = Field(description="False when the platform gave no starters (manual team)")


class PlayersTableOut(BaseModel):
    team_id: str
    rows: list[PlayerTableRow]
    total: int = Field(description="Players matching the filters (all pages)")
    page: int
    size: int
    nfl_teams: list[str] = Field(description="NFL teams in the pool, for the team filter")
    market_label: str


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
    ai_enabled: bool = Field(False, description="An ANTHROPIC_API_KEY is set: the Ask page works")
    ai_model: str | None = None


# ───────── advisor chat ─────────


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = Field(None, description="Continue this conversation")


class ChatUsageOut(BaseModel):
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: float | None = Field(
        None, description="Estimate at list prices (None: unknown model)"
    )


class ChatSummaryOut(BaseModel):
    id: str
    title: str
    model: str | None
    updated_at: datetime


class ChatMessageOut(BaseModel):
    role: Literal["user", "assistant"]
    text: str
    tools: list[str] = Field(description="Tools the answer used")


class ChatDeletedOut(BaseModel):
    deleted: str


class ChatOut(BaseModel):
    id: str
    team_id: str
    title: str
    model: str | None
    messages: list[ChatMessageOut]
    usage: ChatUsageOut


class RefreshRequest(BaseModel):
    scope: Literal["league", "market", "all"] = "league"
    league_id: str | None = None


class RefreshOut(BaseModel):
    scope: str
    ok: bool
    detail: list[str]
    last_synced_at: datetime | None = None


# ───────── settings ─────────


class SettingFieldOut(BaseModel):
    key: str
    group: str
    label: str
    help: str
    default: float
    min: float
    max: float
    integer: bool
    tuned: bool = Field(description="Default was picked by the walk-forward backtest")
    value: float


class SettingsOut(BaseModel):
    fields: list[SettingFieldOut]
    warning: str | None = Field(None, description="Set when settings.json was unreadable")
    path: str = Field(description="Where the settings file lives")
