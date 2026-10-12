"""One buy / hold / sell verdict per player: our projection vs what the market charges for him.

* Model points = schedule-adjusted rest-of-season points (exactly what the Rankings page shows).
* Market-implied points: among players the market values at a position, if the market ranks a
  player r-th, it is pricing him like the player *we* rank r-th, so his market-implied points are
  that player's model points.
* value_gap = model points − market-implied points. Buy when we project clearly more than the
  market charges, sell when clearly less, hold otherwise (and always hold without a market value).

Regression flags are not a verdict on their own: the backtest showed the projection already
carries their information (and buy-low flags predict nothing). They appear as reasons.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

# Only players someone would actually start get a call: a buy needs us to rank him inside the
# startable pool, a sell needs the market to. Deeper players are holds (their gaps are noise).
STARTABLE_RANK = {"QB": 24, "RB": 60, "WR": 60, "TE": 24, "K": 16, "DEF": 16}
GAP_MIN_POINTS = 10.0
GAP_MIN_SHARE = 0.10
SCHEDULE_NOTE_MIN = 3.0  # mention the schedule when it moves ROS points at least this much


@dataclass
class Valuation:
    model_points: float
    model_rank: int | None = None  # within the market-covered players at the position
    market_rank: int | None = None
    market_implied: float | None = None
    signal: str = "hold"
    reasons: list[str] = field(default_factory=list)

    @property
    def gap(self) -> float | None:
        if self.market_implied is None:
            return None
        return round(self.model_points - self.market_implied, 1)


def threshold(market_implied: float) -> float:
    return max(GAP_MIN_POINTS, GAP_MIN_SHARE * market_implied)


def signal_for(
    gap: float | None,
    market_implied: float | None,
    model_rank: int | None = None,
    market_rank: int | None = None,
    startable: int | None = None,
) -> str:
    if gap is None or market_implied is None:
        return "hold"
    t = threshold(market_implied)
    if gap >= t and (startable is None or (model_rank or 10**6) <= startable):
        return "buy"
    if gap <= -t and (startable is None or (market_rank or 10**6) <= startable):
        return "sell"
    return "hold"


def value_players(
    players: Mapping[str, Mapping],
    model_points: Mapping[str, float],
    positions: Iterable[str],
) -> dict[str, Valuation]:
    """Valuation for every player in `model_points` (market fields only where valued)."""
    out = {pid: Valuation(round(pts, 1)) for pid, pts in model_points.items()}
    for pos in positions:
        covered = [
            pid for pid, pts in model_points.items()
            if players[pid].get("position") == pos and players[pid].get("market_value") is not None
        ]  # fmt: skip
        by_market = sorted(covered, key=lambda p: (-players[p]["market_value"], p))
        by_model = sorted(covered, key=lambda p: (-model_points[p], p))
        model_rank = {pid: i + 1 for i, pid in enumerate(by_model)}
        for r, pid in enumerate(by_market, start=1):
            v = out[pid]
            v.market_rank, v.model_rank = r, model_rank[pid]
            v.market_implied = round(model_points[by_model[r - 1]], 1)
            v.signal = signal_for(
                v.gap, v.market_implied, v.model_rank, v.market_rank, STARTABLE_RANK.get(pos)
            )
    return out


def reasons(
    p: Mapping,
    v: Valuation,
    *,
    market_label: str,
    flag_messages: Iterable[str] = (),
    schedule_delta: float = 0.0,
) -> list[str]:
    """Plain-English explanation: the value gap first, then the context behind our number."""
    pos = p.get("position") or ""
    out: list[str] = []
    if v.gap is not None:
        priced = (
            f"We project {v.model_points:.0f} rest-of-season points ({pos}{v.model_rank}); "
            f"{market_label} prices him like our {pos}{v.market_rank} (~{v.market_implied:.0f})"
        )
        if v.signal == "buy":
            out.append(f"{priced}: undervalued by {v.gap:.0f} points.")
        elif v.signal == "sell":
            out.append(f"{priced}: overvalued by {-v.gap:.0f} points.")
        else:
            out.append(f"{priced}: fairly priced ({v.gap:+.0f}).")
    else:
        out.append(f"No {market_label} value for him, so no buy/sell call.")
    out.extend(flag_messages)
    if abs(schedule_delta) >= SCHEDULE_NOTE_MIN:
        word = "adds" if schedule_delta > 0 else "costs"
        out.append(f"His remaining schedule {word} about {abs(schedule_delta):.0f} points.")
    return out
