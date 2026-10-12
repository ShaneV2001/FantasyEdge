import pytest

from signals.verdict import Valuation, reasons, signal_for, value_players


def P(pos, market_value=None):
    return {"position": pos, "market_value": market_value}


def test_market_implied_points_and_gap():
    # market order: a > b > c ; our order: b (200) > c (150) > a (100)
    players = {"a": P("RB", 900), "b": P("RB", 800), "c": P("RB", 700), "x": P("RB")}
    vals = value_players(players, {"a": 100, "b": 200, "c": 150, "x": 300}, ["RB"])
    a, b, c, x = (vals[k] for k in "abcx")
    assert (a.market_rank, a.model_rank, a.market_implied, a.gap) == (1, 3, 200, -100)
    assert a.signal == "sell"
    assert (b.market_implied, b.gap, b.signal) == (150, 50, "buy")
    assert (c.market_implied, c.gap, c.signal) == (100, 50, "buy")
    assert x.signal == "hold" and x.gap is None  # no market value → no call


@pytest.mark.parametrize(
    "gap, implied, expected",
    [(9.9, 50, "hold"), (10, 50, "buy"), (-10, 50, "sell"), (19, 200, "hold"), (20, 200, "buy"),
     (None, None, "hold")],
)  # fmt: skip
def test_threshold_is_10_points_or_10_percent(gap, implied, expected):
    assert signal_for(gap, implied) == expected


def test_fairly_priced_player_with_sell_flags_is_hold():
    # same rank for us and the market: regression flags explain, they don't decide
    players = {"bijan": P("RB", 1000), "other": P("RB", 500)}
    v = value_players(players, {"bijan": 260, "other": 120}, ["RB"])["bijan"]
    assert v.signal == "hold"
    text = reasons(
        players["bijan"] | {"position": "RB"},
        v,
        market_label="FantasyCalc",
        flag_messages=["5.8 yards per carry vs RB norm 4.2."],
        schedule_delta=-5.7,
    )
    assert "fairly priced" in text[0] and "5.8 yards per carry" in text[1]
    assert "costs about 6 points" in text[2]


def test_reasons_without_market():
    v = Valuation(80.0)
    assert reasons({"position": "K"}, v, market_label="FantasyCalc")[0].startswith("No FantasyCalc")


def test_deep_players_get_no_call():
    # 70 market-valued WRs; the market's WR65 is projected far above where it ranks him
    players = {f"w{i}": P("WR", 1000 - i) for i in range(70)}
    pts = {f"w{i}": 200 - 2 * i for i in range(70)}
    pts["w64"] = 150  # we rank him ~WR26, market WR65 → clear buy
    pts["w66"] = 75  # we rank him ~WR63 (outside the pool), market WR67 → hold despite the gap
    vals = value_players(players, pts, ["WR"])
    assert vals["w64"].signal == "buy"
    assert vals["w66"].gap > 0 and vals["w66"].signal == "hold"
    assert signal_for(-50, 100, model_rank=10, market_rank=80, startable=60) == "hold"
    assert signal_for(-50, 100, model_rank=80, market_rank=10, startable=60) == "sell"
