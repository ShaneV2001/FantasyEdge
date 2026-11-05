"""Opponent matchup factors finer than "points allowed to the position".

A defense's index is split by stat (catches, yards, TDs; rushing vs receiving; passing), by where
the targets went (middle of the field, a slot-style proxy, vs outside) and, for WRs, by depth
(WR1 vs WR2+). Each player meets the opponent's indexes weighted by his own scoring mix, so a
pass-catching back leans on the defense's RB-receiving numbers and a TD-dependent TE leans on
"TE TDs allowed". The betting lines add a second, independent factor: the team's implied points
this week vs its usual.

Which factors move points is chosen by the backtest (`models.run tune-factors`); the rest only
produce matchup notes ("DET allows the most TE TDs") shown as reasons.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import cached_property

import polars as pl

from scoring.rules import normalize
from signals.schedule import MATCHUP_ALPHA, Schedule, allowed_index, matchup_multiplier

SKILL = ("QB", "RB", "WR", "TE")
MIX_WINDOW = 4  # games of a player's own history behind his scoring mix
MIX_PRIOR_GAMES = 2  # pseudo-games of his position's average mix
TD_STATS = ("rush_td", "rec_td", "pass_td")

# raw stat behind each component and the rule that turns it into points. Indexes use the raw
# stat (yards allowed is yards allowed under any scoring); the player's mix uses the points.
STAT: dict[str, tuple[pl.Expr, str]] = {
    "rush_yds": (pl.col("rush_yds"), "rush_yd"),
    "rush_td": (pl.col("rush_td"), "rush_td"),
    "rec": (pl.col("receptions"), "rec"),
    "rec_yds_mid": (pl.col("rec_yds_mid"), "rec_yd"),
    "rec_yds_out": (pl.col("rec_yds") - pl.col("rec_yds_mid"), "rec_yd"),
    "rec_td": (pl.col("rec_td"), "rec_td"),
    "pass_yds": (pl.col("pass_yds"), "pass_yd"),
    "pass_td": (pl.col("pass_td"), "pass_td"),
}
ROUTES = ("rec_yds_mid", "rec_yds_out")

# notes: an opponent in the top/bottom NOTE_RANK of the league, on a part of the player's game
# worth at least NOTE_MIN_SHARE of his points; slot-style / outside by his middle-target share
NOTE_RANK = 5
NOTE_MIN_SHARE = 0.25
NOTE_MIN_GAP = 0.05  # and at least 5% off the league average (ties at 1.0 aren't news)
SLOT_SHARE = 0.35  # the median receiver gets about a fifth of his yards on middle targets
OUTSIDE_SHARE = 0.10
MAX_NOTES = 3

LABEL = {
    "rush_yds": "rushing yards", "rush_td": "rushing TDs", "rec": "catches",
    "rec_yds": "receiving yards", "rec_td": "receiving TDs", "pass_yds": "passing yards",
    "pass_td": "passing TDs", "fp": "fantasy points",
    "rec_yds_mid": "receiving yards on middle-of-field (slot-style) targets",
    "rec_yds_out": "receiving yards on outside targets",
}  # fmt: skip
GROUP = {"QB": "QBs", "RB": "RBs", "WR": "WRs", "TE": "TEs", "WR1": "WR1s", "WR2": "WR2s"}


@dataclass(frozen=True)
class FactorWeights:
    """How far each factor moves a projection. The defaults reproduce the position-level index."""

    alpha: Mapping[str, float] = field(default_factory=lambda: dict(MATCHUP_ALPHA))
    components: frozenset[str] = frozenset()  # positions scaled by stat components
    routes: frozenset[str] = frozenset()  # ...with receiving yards split middle / outside
    depth: bool = False  # WRs meet the opponent's WR1 or WR2+ index instead of all-WR
    # extra pseudo-games at the league average for TD indexes, per position
    td_prior: Mapping[str, float] = field(default_factory=dict)
    vegas: Mapping[str, float] = field(default_factory=dict)  # β per position


# Chosen by `python -m models.run tune-factors`: tuned on 2023-24, a factor kept only where it
# was best on train *and* improved the 2025 holdout. Next-week MAE on the 2025 holdout, before →
# after (weekly Spearman in brackets where it moved):
#   betting lines   QB 6.457 → 6.440, RB 4.083 → 4.067, WR 3.721 → 3.710, TE 3.075 → 3.059,
#                   K 3.773 → 3.735 (0.14 → 0.19), DEF 4.177 → 4.173 (0.23 → 0.25)
#   stat components QB 6.440 → 6.429 (TDs shrunk with 16 games), RB 4.067 → 4.053
#                   WR, TE: no gain on train, so off (TE was slightly better on the holdout)
#   middle/outside routes (WR, TE), WR1 vs WR2+: no gain, so off
# The factors left off still produce matchup notes, marked as not in the projection.
VEGAS_BETA: dict[str, float] = {
    "QB": 0.5, "RB": 0.5, "WR": 0.5, "TE": 0.5, "K": 0.75, "DEF": 0.25,
}  # fmt: skip
TUNED_FACTORS = FactorWeights(
    components=frozenset({"QB", "RB"}), td_prior={"QB": 16.0}, vegas=dict(VEGAS_BETA)
)


@dataclass(frozen=True)
class MatchupNote:
    text: str
    tone: str  # "good" | "bad" for the player
    in_projection: bool  # False: context only, the backtest didn't back this factor
    strength: float = 0.0  # how far from average, for ordering


def ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def with_depth(stats: pl.DataFrame) -> pl.DataFrame:
    """`depth`: WR1 for the team's most-targeted WR over his previous 4 games (known before
    kickoff, so the week itself can't leak in), WR2 for the other WRs, the position otherwise."""
    df = stats.sort("player_id", "season", "week").with_columns(
        pl.col("targets").fill_null(0).shift(1).rolling_sum(MIX_WINDOW, min_samples=1)
        .over("player_id").alias("_prior_tgt")
    )  # fmt: skip
    rank = pl.col("_prior_tgt").rank("ordinal", descending=True).over("season", "week", "team")
    wr = pl.col("position") == "WR"
    return (
        df.with_columns(pl.when(wr).then(rank).alias("_rank"))
        .with_columns(
            pl.when(wr & (pl.col("_rank") == 1))
            .then(pl.lit("WR1"))
            .when(wr)
            .then(pl.lit("WR2"))
            .otherwise(pl.col("position"))
            .alias("depth")
        )
        .drop("_prior_tgt", "_rank")
    )


def _long(stats: pl.DataFrame) -> pl.DataFrame:
    """One row per (player-week, bucket, stat): position buckets for every skill player, plus
    WR1 / WR2 buckets for receivers."""
    df = with_depth(stats.filter(pl.col("position").is_in(SKILL))).with_columns(
        pl.col(c).fill_null(0) for c in ("rec_yds", "rec_yds_mid")
    )
    df = df.with_columns(
        *(expr.fill_null(0).cast(pl.Float64).alias(c) for c, (expr, _) in STAT.items()),
        (pl.col("rec_yds").fill_null(0).cast(pl.Float64)).alias("rec_yds"),
        pl.col("fp").cast(pl.Float64),
    )
    stats_cols = [*STAT, "rec_yds", "fp"]
    base = df.select("season", "week", "opponent", "position", "depth", *stats_cols)
    by_pos = base.drop("depth").rename({"position": "bucket"})
    by_depth = base.filter(pl.col("position") == "WR").drop("position").rename({"depth": "bucket"})
    return pl.concat([by_pos, by_depth]).unpivot(
        index=["season", "week", "opponent", "bucket"], variable_name="stat", value_name="value"
    )


def _mixes(
    stats: pl.DataFrame, rules: Mapping[str, float]
) -> tuple[dict[str, dict[str, float]], dict[str, float]]:
    """Each player's share of points by component over his last MIX_WINDOW games, shrunk
    toward his position's average share; and each player's targets over those games."""
    r = normalize(dict(rules))
    df = (
        stats.filter(pl.col("position").is_in(SKILL))
        .sort("player_id", "season", "week")
        .group_by("player_id", maintain_order=True)
        .tail(MIX_WINDOW)
        .with_columns(pl.col(c).fill_null(0) for c in ("rec_yds", "rec_yds_mid", "targets"))
        .with_columns(
            (expr.fill_null(0) * r[key]).clip(lower_bound=0).alias(c)
            for c, (expr, key) in STAT.items()
        )
    )
    per = df.group_by("player_id").agg(
        pl.col("position").last(), pl.len().alias("n"), pl.col("targets").sum(),
        *(pl.col(c).sum() for c in STAT),
    )  # fmt: skip
    total = pl.sum_horizontal(*STAT)
    per = per.with_columns(total.alias("_t")).filter(pl.col("_t") > 0)
    shares = per.with_columns((pl.col(c) / pl.col("_t")).alias(c) for c in STAT)
    pos_share = shares.group_by("position").agg(pl.col(c).mean() for c in STAT)
    pos_mix = {row.pop("position"): row for row in pos_share.iter_rows(named=True)}
    mixes = {}
    for row in shares.iter_rows(named=True):
        w = row["n"] / (row["n"] + MIX_PRIOR_GAMES)
        avg = pos_mix[row["position"]]
        mixes[row["player_id"]] = {c: w * row[c] + (1 - w) * avg[c] for c in STAT}
    targets = dict(per.select("player_id", "targets").iter_rows())
    return mixes, targets


@dataclass
class MatchupModel:
    weights: FactorWeights
    total: Mapping[tuple[str, str], float]  # (opponent, position) → fp allowed index
    idx: Mapping[tuple[str, str, str], float]  # (opponent, bucket, stat) → index
    rank: Mapping[tuple[str, str, str], int]  # same keys → 1 = allows the most
    teams_ranked: Mapping[tuple[str, str], int]  # (bucket, stat) → teams in the ranking
    mix: Mapping[str, Mapping[str, float]]  # player → component share of his points
    depth: Mapping[str, str]  # WR player → WR1 / WR2
    implied: Mapping[tuple[str, int], float]  # (team, week) → implied points

    @classmethod
    def position_only(
        cls, total: Mapping[tuple[str, str], float], alpha: Mapping[str, float]
    ) -> MatchupModel:
        """Just the position-level index (no components, lines or notes)."""
        return cls(FactorWeights(alpha=dict(alpha)), total, {}, {}, {}, {}, {}, {})

    # ───────── multipliers ─────────

    def multiplier(self, pid: str, pos: str, team: str | None, opp: str | None, week: int) -> float:
        if opp is None:
            return 1.0
        return self.defense_multiplier(pid, pos, opp) * self.vegas_multiplier(pos, team, opp, week)

    def _mix_for(self, pid: str, pos: str) -> dict[str, float] | None:
        mix = self.mix.get(pid)
        if mix is None:
            return None
        if pos in self.weights.routes:
            return dict(mix)
        out = {c: v for c, v in mix.items() if c not in ROUTES}
        out["rec_yds"] = sum(mix[c] for c in ROUTES)
        return out

    def bucket(self, pid: str, pos: str) -> str:
        return self.depth.get(pid, "WR2") if pos == "WR" and self.weights.depth else pos

    def defense_multiplier(self, pid: str, pos: str, opp: str) -> float:
        a = self.weights.alpha.get(pos, 0.0)
        if a == 0:
            return 1.0
        mix = self._mix_for(pid, pos) if pos in self.weights.components else None
        if not mix:
            return matchup_multiplier(self.total, opp, pos, a)
        b = self.bucket(pid, pos)
        m = sum(s * (1 + a * (self.idx.get((opp, b, c), 1.0) - 1)) for c, s in mix.items())
        return max(m, 0.0)

    @cached_property
    def _by_week(self) -> dict[int, dict[str, float]]:
        out: dict[int, dict[str, float]] = {}
        for (t, w), v in self.implied.items():
            out.setdefault(w, {})[t] = v
        return out

    def _team_average(self, team: str, week: int) -> float | None:
        vals = [v[team] for w, v in self._by_week.items() if w <= week and team in v]
        return sum(vals) / len(vals) if len(vals) >= 2 else None

    def _league_average(self, week: int) -> float | None:
        vals = [x for w, v in self._by_week.items() if w <= week for x in v.values()]
        return sum(vals) / len(vals) if vals else None

    def vegas_multiplier(self, pos: str, team: str | None, opp: str | None, week: int) -> float:
        """Team's implied points this week vs its own average so far (its projection already
        reflects how good the offense is). DEF: the opponent's implied points vs the league's,
        lower is better."""
        b = self.weights.vegas.get(pos, 0.0)
        if b == 0 or team is None:
            return 1.0
        if pos == "DEF":
            imp, ref = self.implied.get((opp, week)), self._league_average(week)
            return 1.0 if imp is None or not ref else max(1 - b * (imp / ref - 1), 0.0)
        imp, ref = self.implied.get((team, week)), self._team_average(team, week)
        return 1.0 if imp is None or not ref else max(1 + b * (imp / ref - 1), 0.0)

    # ───────── notes ─────────

    def _rank_note(self, opp: str, bucket: str, stat: str, in_proj: bool) -> MatchupNote | None:
        rank = self.rank.get((opp, bucket, stat))
        n = self.teams_ranked.get((bucket, stat), 0)
        strength = abs(self.idx.get((opp, bucket, stat), 1.0) - 1)
        if rank is None or n < 2 * NOTE_RANK or strength < NOTE_MIN_GAP:
            return None
        what = f"{LABEL[stat]} to {GROUP[bucket]}"
        if rank <= NOTE_RANK:
            most = "the most" if rank == 1 else f"the {ordinal(rank)}-most"
            return MatchupNote(f"{opp} allows {most} {what}.", "good", in_proj, strength)
        if rank > n - NOTE_RANK:
            k = n - rank + 1
            fewest = "the fewest" if k == 1 else f"the {ordinal(k)}-fewest"
            return MatchupNote(f"{opp} allows {fewest} {what}.", "bad", in_proj, strength)
        return None

    def _vegas_note(self, pos: str, team: str, opp: str, week: int) -> MatchupNote | None:
        week_imp = self._by_week.get(week, {})
        if team not in week_imp or opp not in week_imp or len(week_imp) < 2 * NOTE_RANK:
            return None
        side = opp if pos == "DEF" else team  # a defense wants the other side to score little
        order = sorted(week_imp, key=lambda t: -week_imp[t])
        rank, n = order.index(side) + 1, len(order)
        total = week_imp[team] + week_imp[opp]
        head = f"Game total {total:.1f}: {side} implied for {week_imp[side]:.1f}"
        if rank <= NOTE_RANK:
            tone, where = ("bad" if pos == "DEF" else "good"), f"{ordinal(rank)}-highest"
        elif rank > n - NOTE_RANK:
            tone, where = ("good" if pos == "DEF" else "bad"), f"{ordinal(n - rank + 1)}-lowest"
        else:
            return None
        strength = abs(week_imp[side] / (sum(week_imp.values()) / n) - 1)
        in_proj = self.weights.vegas.get(pos, 0.0) > 0
        return MatchupNote(f"{head} ({where} this week).", tone, in_proj, strength)

    def notes(
        self, pid: str, pos: str, team: str | None, opp: str | None, week: int
    ) -> list[MatchupNote]:
        """Why this matchup is better or worse than usual for this player, strongest first."""
        if opp is None or team is None:
            return []
        out: list[MatchupNote | None] = [self._vegas_note(pos, team, opp, week)]
        mix = self.mix.get(pid)
        if pos in SKILL and mix:
            comp = self.weights.alpha.get(pos, 0.0) > 0 and pos in self.weights.components
            rec_yds = sum(mix[c] for c in ROUTES)
            mid = mix["rec_yds_mid"] / rec_yds if rec_yds > 0 else 0.0
            route = None
            if pos in ("WR", "TE") and rec_yds >= NOTE_MIN_SHARE:
                if mid >= SLOT_SHARE:
                    route = "rec_yds_mid"
                elif mid <= OUTSIDE_SHARE:
                    route = "rec_yds_out"
            for stat in ("rush_yds", "rush_td", "rec", "rec_yds", "rec_td", "pass_yds", "pass_td"):
                share = rec_yds if stat == "rec_yds" else mix[stat]
                if share < NOTE_MIN_SHARE or (stat == "rec_yds" and route):
                    continue
                out.append(self._rank_note(opp, pos, stat, comp))
            if route:
                out.append(self._rank_note(opp, pos, route, comp and pos in self.weights.routes))
            if pos == "WR" and self.depth.get(pid) == "WR1":
                out.append(self._rank_note(opp, "WR1", "fp", comp and self.weights.depth))
        notes = sorted((n for n in out if n), key=lambda n: -n.strength)
        return notes[:MAX_NOTES]


def build_matchup_model(
    scored: pl.DataFrame,
    schedule: Schedule,
    teams: Mapping[str, str | None],
    rules: Mapping[str, float],
    season: int,
    through_week: int,
    weights: FactorWeights | None = None,
    total: Mapping[tuple[str, str], float] | None = None,
) -> MatchupModel:
    """Everything the multipliers and notes need, from history through `through_week` only.

    `teams` is each player's current NFL team (WR depth is ranked within it); `total` reuses an
    already built `fp_allowed_index`.
    """
    from signals.schedule import fp_allowed_index

    weights = weights or FactorWeights()
    if total is None:
        total = fp_allowed_index(scored, season, through_week)
    hist = scored.filter((pl.col("season") < season) | (pl.col("week") <= through_week))
    if "rec_yds_mid" not in hist.columns:  # stores ingested before migration v13
        hist = hist.with_columns(pl.lit(0, pl.Int32).alias("rec_yds_mid"))
    td = pl.col("stat").is_in(TD_STATS)
    prior_by_bucket = {b: weights.td_prior.get(b[:2], 0.0) for b in GROUP}  # WR1/WR2 → WR
    long = _long(hist)
    df = allowed_index(
        long, ["bucket", "stat"], "value", season, through_week,
        mean_weight=pl.when(td).then(
            pl.col("bucket").replace_strict(prior_by_bucket, default=0.0, return_dtype=pl.Float64)
        ).otherwise(0.0),
    )  # fmt: skip
    idx, rank = {}, {}
    for o, b, st, i, r in df.select("opponent", "bucket", "stat", "idx", "rank").iter_rows():
        idx[(o, b, st)] = float(i)
        rank[(o, b, st)] = int(r)
    counts = df.group_by("bucket", "stat").len()
    teams_ranked = {(b, st): int(n) for b, st, n in counts.iter_rows()}

    mix, targets = _mixes(hist, rules)
    positions = dict(
        hist.sort("season", "week").group_by("player_id").agg(pl.col("position").last()).iter_rows()
    )
    by_team: dict[str, list[str]] = {}
    for pid, t in teams.items():
        if positions.get(pid) == "WR" and t and pid in targets:
            by_team.setdefault(t, []).append(pid)
    depth = {}
    for pids in by_team.values():
        pids.sort(key=lambda p: (-targets[p], p))
        for i, pid in enumerate(pids):
            depth[pid] = "WR1" if i == 0 else "WR2"
    return MatchupModel(weights, total, idx, rank, teams_ranked, mix, depth, dict(schedule.implied))
