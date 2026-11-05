import polars as pl
import pytest

from scoring.rules import HALF_PPR
from signals.matchup_factors import (
    FactorWeights,
    MatchupModel,
    build_matchup_model,
    with_depth,
)
from signals.schedule import Schedule, allowed_index, build_schedule
from tests.builders import stat_row, stats_frame

DEFENSES = [f"D{i:02d}" for i in range(12)]


def _te_league(weeks=3, soft_td=2):
    """12 TEs, each facing one defense every week; D00 gives up `soft_td` TE TDs a game."""
    rows = []
    for w in range(1, weeks + 1):
        for i, d in enumerate(DEFENSES):
            rows.append(
                stat_row(f"te{i}", "TE", 2026, w, f"T{i:02d}", opponent=d, receptions=3,
                         rec_yds=30, rec_td=soft_td if i == 0 else 0)
            )  # fmt: skip
        # "mine" is a TD-dependent TE; his own games don't feed any defense's index
        rows.append(stat_row("mine", "TE", 2026, w, "ZZZ", opponent=None, receptions=2,
                             rec_yds=20, rec_td=1))  # fmt: skip
    return stats_frame(rows)


def _sched(games=None, implied=None):
    games = dict(games or {})
    for (t, w), o in list(games.items()):
        games[(o, w)] = t
    return Schedule(2026, 18, games, {}, implied=implied or {})


def test_td_index_shrinks_toward_average():
    stats = _te_league(weeks=1)
    long = stats.with_columns(pl.col("rec_td").cast(pl.Float64), pl.lit("TE").alias("bucket"))
    raw = allowed_index(long, ["bucket"], "rec_td", 2026, 1)
    shrunk = allowed_index(long, ["bucket"], "rec_td", 2026, 1, mean_weight=8.0)

    def d00(df):
        return df.filter(pl.col("opponent") == "D00")["idx"][0]

    assert d00(raw) > d00(shrunk) > 1.0
    assert raw.filter(pl.col("opponent") == "D00")["rank"][0] == 1


def test_depth_uses_only_earlier_games():
    rows = [
        stat_row("a", "WR", 2026, 1, "AAA", targets=10),
        stat_row("b", "WR", 2026, 1, "AAA", targets=2),
        stat_row("a", "WR", 2026, 2, "AAA", targets=1),
        stat_row("b", "WR", 2026, 2, "AAA", targets=20),  # his breakout can't make him WR1 yet
        stat_row("a", "WR", 2026, 3, "AAA", targets=1),
        stat_row("b", "WR", 2026, 3, "AAA", targets=1),
    ]
    d = {
        (r[0], r[1]): r[2]
        for r in with_depth(stats_frame(rows)).select("player_id", "week", "depth").rows()
    }
    assert d[("a", 1)] == d[("b", 1)] == "WR2"  # no earlier games: nobody is WR1
    assert (d[("a", 2)], d[("b", 2)]) == ("WR1", "WR2")
    assert (d[("a", 3)], d[("b", 3)]) == ("WR2", "WR1")


def test_implied_totals_from_lines():
    games = pl.DataFrame(
        {"game_id": ["g1", "g2"], "season": [2026, 2026], "week": [1, 1],
         "home_team": ["AAA", "CCC"], "away_team": ["BBB", "DDD"], "home_score": [None, None],
         "spread_line": [3.0, None], "total_line": [45.0, 40.0]}
    )  # fmt: skip
    sched = build_schedule(games, 2026)
    assert sched.implied == {("AAA", 1): 24.0, ("BBB", 1): 21.0}  # no spread, no implied total


def test_vegas_multiplier_vs_own_average():
    implied = {("AAA", 1): 20.0, ("AAA", 2): 30.0, ("BBB", 2): 20.0}
    m = MatchupModel(FactorWeights(alpha={}, vegas={"WR": 1.0, "DEF": 1.0}), {}, {}, {}, {}, {},
                     {}, implied)  # fmt: skip
    assert m.vegas_multiplier("WR", "AAA", "BBB", 2) == pytest.approx(1.2)  # 30 vs average 25
    assert m.vegas_multiplier("WR", "AAA", "BBB", 1) == 1.0  # one game: no average yet
    assert m.vegas_multiplier("WR", "AAA", "BBB", 3) == 1.0  # no line posted
    assert m.vegas_multiplier("RB", "AAA", "BBB", 2) == 1.0  # β = 0
    # a defense facing AAA's 30 vs a league average of 70/3 ≈ 23.3 is a worse matchup
    assert m.vegas_multiplier("DEF", "BBB", "AAA", 2) == pytest.approx(1 - (30 / (70 / 3) - 1))


def test_components_follow_the_players_mix():
    # D00 is soft only against RB rushing; a pure pass-catching back shouldn't care
    rows = []
    for w in (1, 2, 3):
        for i, d in enumerate(DEFENSES):
            rows.append(stat_row(f"rb{i}", "RB", 2026, w, f"T{i:02d}", opponent=d,
                                 rush_yds=150 if i == 0 else 60, receptions=3, rec_yds=25))  # fmt: skip
        rows.append(stat_row("grinder", "RB", 2026, w, "ZZZ", opponent=None, rush_yds=90))
        rows.append(stat_row("catcher", "RB", 2026, w, "YYY", opponent=None, receptions=6,
                             rec_yds=50))  # fmt: skip
    stats = stats_frame(rows)
    teams = {"grinder": "ZZZ", "catcher": "YYY"}
    sched = _sched()
    comp = build_matchup_model(stats, sched, teams, HALF_PPR, 2026, 3,
                               FactorWeights(alpha={"RB": 1.0}, components=frozenset({"RB"})))  # fmt: skip
    flat = build_matchup_model(stats, sched, teams, HALF_PPR, 2026, 3,
                               FactorWeights(alpha={"RB": 1.0}))  # fmt: skip
    grinder, catcher = (comp.defense_multiplier(p, "RB", "D00") for p in ("grinder", "catcher"))
    # the catcher's mix is shrunk toward the average back's (who does run), so not exactly 1.0
    assert grinder > 1.4 and catcher < 1.2
    # the position-level index can't tell them apart
    assert flat.defense_multiplier("grinder", "RB", "D00") == flat.defense_multiplier(
        "catcher", "RB", "D00"
    )


def test_notes_name_the_weakness_and_say_if_it_moves_points():
    stats = _te_league()
    model = build_matchup_model(stats, _sched(), {"mine": "ZZZ"}, HALF_PPR, 2026, 3)
    notes = model.notes("mine", "TE", "ZZZ", "D00", 4)
    assert [n.text for n in notes] == ["D00 allows the most receiving TDs to TEs."]
    assert notes[0].tone == "good" and not notes[0].in_projection  # TE components aren't tuned in
    # when every defense is the same, nobody is news
    flat = build_matchup_model(_te_league(soft_td=0), _sched(), {"mine": "ZZZ"}, HALF_PPR, 2026, 3)
    assert flat.notes("mine", "TE", "ZZZ", "D00", 4) == []
    tuned = build_matchup_model(stats, _sched(), {"mine": "ZZZ"}, HALF_PPR, 2026, 3,
                                FactorWeights(alpha={"TE": 0.5}, components=frozenset({"TE"})))  # fmt: skip
    assert tuned.notes("mine", "TE", "ZZZ", "D00", 4)[0].in_projection


def test_vegas_note_ranks_the_week():
    implied = {(f"T{i:02d}", 1): 15.0 + i for i in range(12)}
    m = MatchupModel(FactorWeights(), {}, {}, {}, {}, {}, {}, implied)
    top = m.notes("x", "K", "T11", "T00", 1)
    assert top[0].text == "Game total 41.0: T11 implied for 26.0 (the highest this week)."
    assert top[0].tone == "good"
    # the defense facing T11 sees the same line as bad news
    assert m.notes("x", "DEF", "T00", "T11", 1)[0].tone == "bad"
