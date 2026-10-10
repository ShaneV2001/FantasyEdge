import httpx
import pytest
import respx

from ingest.http import CachedHttp, SourceUnavailable
from ingest.idmap import DP_IDS_URL, attach_internal_ids, parse_id_map
from ingest.market_values import (
    DP_VALUES_URL,
    DynastyProcessSource,
    FantasyCalcSource,
    MarketFormat,
    get_market_values,
    parse_fantasycalc,
)
from ingest.sleeper import parse_players
from tests.conftest import load_json, load_text

FC = "https://api.fantasycalc.com"


def test_format_key():
    assert MarketFormat(12, 1, 0.5).key == "redraft_1qb_12_ppr0.5"
    assert MarketFormat(10, 2, 1.0, True).key == "dynasty_2qb_10_ppr1"


def test_parse_fantasycalc():
    df = parse_fantasycalc(load_json("fantasycalc_values.json"))
    assert df.height > 50
    assert df["sleeper_id"].null_count() == 0
    top_rb = df.filter(df["position"] == "RB").sort("position_rank").row(0, named=True)
    assert top_rb["position_rank"] == 1 and top_rb["value"] > 0


def test_parse_fantasycalc_rejects_garbage():
    with pytest.raises(ValueError):
        parse_fantasycalc({"error": "nope"})  # type: ignore[arg-type]


@respx.mock
def test_fantasycalc_failure_falls_back_to_dynastyprocess(tmp_path):
    http = CachedHttp(tmp_path, min_interval_s=0)
    respx.get(f"{FC}/values/current").mock(return_value=httpx.Response(502))
    respx.get(DP_VALUES_URL).mock(return_value=httpx.Response(200, text=load_text("dp_values.csv")))
    id_map = parse_id_map(load_text("dp_playerids.csv"))

    result = get_market_values(
        [FantasyCalcSource(http, FC), DynastyProcessSource(http, id_map)], MarketFormat()
    )
    assert result.source == "dynastyprocess"
    assert result.fallback_used and result.errors
    assert result.values.height > 10
    assert result.values["position_rank"].min() == 1


@respx.mock
def test_all_market_sources_down_raises(tmp_path):
    http = CachedHttp(tmp_path, min_interval_s=0)
    respx.get(f"{FC}/values/current").mock(return_value=httpx.Response(500))
    with pytest.raises(SourceUnavailable):
        get_market_values([FantasyCalcSource(http, FC)], MarketFormat())


def test_internal_ids_prefer_gsis():
    players = parse_players(load_json("sleeper_players.json"))
    id_map = parse_id_map(load_text("dp_playerids.csv"))
    df = attach_internal_ids(players, id_map)
    assert df["player_id"].n_unique() == df.height
    skill = df.filter(df["position"].is_in(["QB", "RB", "WR", "TE"]))
    assert skill["player_id"].str.starts_with("00-").mean() > 0.9
    assert df.filter(df["position"] == "DEF")["player_id"].str.starts_with("sl:").all()


def test_dp_ids_url_constant():
    assert DP_IDS_URL.endswith("db_playerids.csv")
