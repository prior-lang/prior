"""The examples ARE the spec: every file in examples/ must parse, compile
to sensible JSON, and format idempotently."""

from pathlib import Path

import pytest

import prior_lang

EXAMPLES = sorted((Path(__file__).parents[2] / "examples").glob("*.prior"))


@pytest.mark.parametrize("path", EXAMPLES, ids=[p.stem for p in EXAMPLES])
def test_example_parses_and_compiles(path):
    strategy = prior_lang.compile_source(path.read_text(), filename=path.name)
    assert strategy["version"] == "0.1"
    assert strategy["entry"]["conditions"]
    assert strategy["universe"]["type"] in ("prebuilt", "manual")


@pytest.mark.parametrize("path", EXAMPLES, ids=[p.stem for p in EXAMPLES])
def test_example_formats_idempotently(path):
    once = prior_lang.format_source(path.read_text(), filename=path.name)
    twice = prior_lang.format_source(once)
    assert once == twice


def test_examples_exist():
    assert len(EXAMPLES) == 10


def test_bollinger_reversal_compiles_exactly():
    src = (Path(__file__).parents[2] / "examples" / "bollinger_reversal.prior").read_text()
    s = prior_lang.compile_source(src)
    assert s["name"] == "Bollinger Reversal"
    assert s["universe"] == {"type": "prebuilt", "key": "sp_top_30"}
    assert s["timeframe"] == "1d"
    assert s["entry"]["match_logic"] == "all"
    [cond] = s["entry"]["conditions"]
    assert cond == {
        "condition": "price_at_bollinger_band",
        "params": {"period": 20, "num_std": 1.0, "band": "lower"},
    }
    ex = s["exit"]
    assert ex["stop_loss_pct"] == 1.5
    assert ex["hold_bars"] == 5
    [xc] = ex["conditions"]
    assert xc["params"]["band"] == "middle"
    assert s["position_sizing"] == {"method": "percent_of_portfolio", "value": 0.05}
    assert s["risk"] == {"max_positions": 5, "max_position_pct": 0.10}


def test_nvda_dip_inline_ticker_scoping():
    src = (Path(__file__).parents[2] / "examples" / "nvda_dip.prior").read_text()
    s = prior_lang.compile_source(src)
    assert s["universe"] == {"type": "manual", "tickers": ["NVDA"]}
    assert s["exit"]["hold_bars"] == 10


def test_golden_cross_compiles_ma_cross_and_dollar_sizing():
    src = (Path(__file__).parents[2] / "examples" / "golden_cross.prior").read_text()
    s = prior_lang.compile_source(src)
    [cond] = s["entry"]["conditions"]
    assert cond == {"condition": "ema_crosses_above", "params": {"fast": 50, "slow": 200}}
    assert s["position_sizing"] == {"method": "fixed_dollar", "value": 10000}
    assert s["exit"]["trailing_stop_pct"] == 5.0
    assert s["risk"] == {"max_positions": 3}


def test_oversold_bounce_risk_sizing_and_composite_entry():
    src = (Path(__file__).parents[2] / "examples" / "oversold_bounce.prior").read_text()
    s = prior_lang.compile_source(src)
    conds = {c["condition"] for c in s["entry"]["conditions"]}
    assert conds == {"rsi_less_than", "volume_greater_than_avg"}
    assert s["position_sizing"] == {"method": "risk_based", "value": 0.01}
    [xc] = s["exit"]["conditions"]
    assert xc == {"condition": "rsi_crosses_above", "params": {"period": 14, "threshold": 55.0}}
    assert s["exit"]["stop_loss_pct"] == 2.0
