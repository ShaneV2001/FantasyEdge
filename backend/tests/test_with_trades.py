"""`views.with_trades`: the league as if accepted pending trades had gone through."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services import views
from app.services.context import TeamRow
from app.services.leagues import PendingTradeRow


@dataclass
class FakeCtx:  # with_trades only touches teams and memo
    teams: list[TeamRow]
    memo: dict = field(default_factory=dict)


def team(tid: str, pids: list[str], starters: list[str]) -> TeamRow:
    return TeamRow(
        tid, "lg", None, "owner", tid, tid == "a", 0, 0, 0.0, None,
        player_ids=list(pids), starters=list(starters),
        slots={p: "starter" if p in starters else "bench" for p in pids},
    )  # fmt: skip


def trade(tid: str, moves: list[tuple[str, str, str]], drops=()) -> PendingTradeRow:
    return PendingTradeRow(
        tid,
        None,
        [{"player_id": p, "from_team": f, "to_team": t} for p, f, t in moves],
        [{"player_id": p, "team_id": t} for p, t in drops],
    )


def test_players_move_and_the_original_league_is_untouched():
    ctx = FakeCtx([team("a", ["qb", "wr1", "rb"], ["qb", "wr1"]), team("b", ["wr2", "te"], ["wr2"]),
                   team("c", ["k"], ["k"])])  # fmt: skip
    rows = [
        trade("t1", [("wr1", "a", "b"), ("wr2", "b", "a")]),
        trade("t2", [("te", "b", "a")], [("rb", "a")]),
    ]
    after = views.with_trades(ctx, rows)
    a, b, c = after.teams
    assert a.player_ids == ["qb", "wr2", "te"]  # rb dropped as part of the trade
    assert a.starters == ["qb"] and a.slots == {"qb": "starter", "wr2": "bench", "te": "bench"}
    assert b.player_ids == ["wr1"] and b.starters == [] and b.slots == {"wr1": "bench"}
    assert c is ctx.teams[2]  # a team in no trade is shared as is
    assert ctx.teams[0].player_ids == ["qb", "wr1", "rb"]  # the cached league keeps today's rosters
    assert after.memo is not ctx.memo  # its own derived results (grades, ideas, lineups)
    assert views.with_trades(ctx, list(reversed(rows))) is after  # built once per set of trades


def test_involves_keeps_only_this_teams_trades():
    rows = [trade("t1", [("x", "a", "b")]), trade("t2", [("y", "c", "d")])]
    assert [r.external_id for r in views.involves(rows, "a")] == ["t1"]
    assert views.involves(rows, "e") == []
