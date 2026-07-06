"""Decompiler round-trips: JSON → .prior → parse → identical JSON."""

from pathlib import Path

import pytest

import prior_lang
from prior_lang import strategy_to_source

EXAMPLES = sorted((Path(__file__).parents[2] / "examples").glob("*.prior"))


@pytest.mark.parametrize("path", EXAMPLES, ids=[p.stem for p in EXAMPLES])
def test_examples_roundtrip_through_json(path):
    """compile → decompile → compile must be a fixed point."""
    strategy = prior_lang.compile_source(path.read_text(), filename=path.name)
    source = strategy_to_source(strategy)
    reparsed = prior_lang.compile_source(source)
    assert reparsed == strategy


def test_scanner_shaped_strategy_decompiles():
    """The shape the scanner's Open-as-PRIOR endpoint will send."""
    strategy = {
        "version": "0.1",
        "name": "Bollinger Reversal",
        "universe": {"type": "prebuilt", "key": "sp_top_30"},
        "timeframe": "1d",
        "entry": {
            "match_logic": "all",
            "conditions": [{
                "condition": "price_at_bollinger_band",
                "params": {"period": 20, "num_std": 1.0, "band": "lower"},
            }],
        },
        "exit": {"conditions": [], "stop_loss_pct": None, "profit_target_pct": None,
                 "trailing_stop_pct": None, "hold_bars": 5},
        "position_sizing": {"method": "percent_of_portfolio", "value": 0.10},
    }
    source = strategy_to_source(strategy)
    assert 'strategy "Bollinger Reversal"' in source
    assert "universe [sp_top_30]" in source
    assert "when price at [lower_bollinger std=1]" in source
    assert "buy [10% portfolio]" in source
    assert "sell when [after 5 bars]" in source
    # And it parses back
    reparsed = prior_lang.compile_source(source)
    assert reparsed["entry"] == strategy["entry"]
    assert reparsed["exit"]["hold_bars"] == 5


def test_default_params_omitted():
    strategy = {
        "name": None,
        "universe": {"type": "prebuilt", "key": "mega_tech"},
        "timeframe": "1d",
        "entry": {"match_logic": "all", "conditions": [
            {"condition": "rsi_less_than", "params": {"period": 14, "threshold": 30}},
            {"condition": "macd_crosses_above_signal", "params": {"fast": 12, "slow": 26, "signal": 9}},
        ]},
        "exit": {"conditions": [], "stop_loss_pct": 2.0, "profit_target_pct": None,
                 "trailing_stop_pct": None, "hold_bars": None},
        "position_sizing": {"method": "fixed_dollar", "value": 5000},
    }
    source = strategy_to_source(strategy)
    assert "[rsi] < 30" in source          # period 14 omitted
    assert "[macd_cross_up]" in source     # all defaults omitted
    assert "buy [$5000]" in source
    assert "[stop 2%]" in source


def test_unknown_condition_raises():
    with pytest.raises(prior_lang.PriorError, match="no PRIOR surface syntax"):
        strategy_to_source({
            "universe": {"type": "prebuilt", "key": "semis"},
            "entry": {"match_logic": "all",
                      "conditions": [{"condition": "made_up", "params": {}}]},
            "exit": {"hold_bars": 5},
        })
