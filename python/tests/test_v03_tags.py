"""v0.3 vocabulary sweep: breakouts, gaps, streaks, levels, ADX, stochastic.

Every new surface form: compiles to the expected registry condition,
formats idempotently, and survives the JSON round trip (compile →
decompile → compile is a fixed point).
"""

import pytest

import prior_lang
from prior_lang import strategy_to_source

BOILER = "universe [sp_top_30]\nwhen {cond}\n  buy [5% portfolio]\nsell when [after 5 bars]\n"


def _cond(surface: str) -> dict:
    s = prior_lang.compile_source(BOILER.format(cond=surface))
    [c] = s["entry"]["conditions"]
    return c


CASES = [
    ("[new_high]", "price_new_high", {"period": 252}),
    ("[new_high 20]", "price_new_high", {"period": 20}),
    ("[new_low 50]", "price_new_low", {"period": 50}),
    ("[gap_up]", "gap_up", {"min_gap_pct": 2.0}),
    ("[gap_up 3%]", "gap_up", {"min_gap_pct": 3.0}),
    ("[gap_down 1.5%]", "gap_down", {"min_gap_pct": 1.5}),
    ("[up_days 3]", "up_days", {"count": 3}),
    ("[down_days 4]", "down_days", {"count": 4}),
    ("price above 250", "price_above_level", {"level": 250.0}),
    ("price below 10", "price_below_level", {"level": 10.0}),
    ("[adx] > 25", "adx_greater_than", {"period": 14, "threshold": 25.0}),
    ("[adx 20] < 15", "adx_less_than", {"period": 20, "threshold": 15.0}),
    ("[stoch] < 20", "stoch_less_than", {"period": 14, "smooth": 3, "threshold": 20.0}),
    ("[stoch] > 80", "stoch_greater_than", {"period": 14, "smooth": 3, "threshold": 80.0}),
    ("[stoch 5 smooth=2] crosses above 20", "stoch_crosses_above",
     {"period": 5, "smooth": 2, "threshold": 20.0}),
    ("[stoch] crosses below 80", "stoch_crosses_below",
     {"period": 14, "smooth": 3, "threshold": 80.0}),
    ("price above [vwap]", "price_above_vwap", {"period": 20}),
    ("price below [vwap 30]", "price_below_vwap", {"period": 30}),
    ("[squeeze]", "bollinger_squeeze", {"lookback": 126, "pct": 10.0, "period": 20, "num_std": 2.0}),
    ("[squeeze 90 pct=20]", "bollinger_squeeze", {"lookback": 90, "pct": 20.0, "period": 20, "num_std": 2.0}),
    ("[obv_rising]", "obv_rising", {"period": 20}),
]


ATR_BOILER = "universe [sp_top_30]\nwhen [macd_cross_up]\n  buy [5% portfolio]\nsell when {exits}\n"


def test_atr_stop_and_chandelier_compile():
    s = prior_lang.compile_source(ATR_BOILER.format(exits="[stop 2 atr]\n  or [trailing 3 atr]"))
    ex = s["exit"]
    assert ex["stop_loss_atr"] == 2.0 and ex["stop_loss_pct"] is None
    assert ex["trailing_stop_atr"] == 3.0
    # Round trip
    assert prior_lang.compile_source(strategy_to_source(s)) == s
    # And the surface prints back with the atr unit
    assert "[stop 2 atr]" in strategy_to_source(s)


def test_breakeven_compiles_and_roundtrips():
    s = prior_lang.compile_source(ATR_BOILER.format(exits="[breakeven after 2%]\n  or [stop 4%]"))
    assert s["exit"]["breakeven_trigger_pct"] == 2.0
    assert s["exit"]["stop_loss_pct"] == 4.0
    assert prior_lang.compile_source(strategy_to_source(s)) == s
    # convenience form without 'after'
    s2 = prior_lang.compile_source(ATR_BOILER.format(exits="[breakeven 2%]\n  or [stop 4%]"))
    assert s2["exit"]["breakeven_trigger_pct"] == 2.0


def test_priced_exit_bad_form_suggests_both_units():
    with pytest.raises(prior_lang.PriorError) as e:
        prior_lang.compile_source(ATR_BOILER.format(exits="[stop 2]"))
    assert "2 atr" in (e.value.suggestion or "")


def test_generated_python_contains_atr_and_breakeven_machinery():
    from prior_lang.codegen import compile_strategy
    s = prior_lang.compile_source(
        ATR_BOILER.format(exits="[stop 2 atr]\n  or [breakeven after 2%]\n  or [after 30 bars]")
    )
    code = compile_strategy(s)
    assert "atr_arr" in code and "entry_atr" in code
    assert "be_armed" in code


@pytest.mark.parametrize("surface,condition,params", CASES, ids=[c[0] for c in CASES])
def test_surface_compiles(surface, condition, params):
    assert _cond(surface) == {"condition": condition, "params": params}


@pytest.mark.parametrize("surface,condition,params", CASES, ids=[c[0] for c in CASES])
def test_roundtrip_fixed_point(surface, condition, params):
    strategy = prior_lang.compile_source(BOILER.format(cond=surface))
    assert prior_lang.compile_source(strategy_to_source(strategy)) == strategy


@pytest.mark.parametrize("surface", [c[0] for c in CASES])
def test_fmt_idempotent(surface):
    src = BOILER.format(cond=surface)
    once = prior_lang.format_source(src)
    assert prior_lang.format_source(once) == once


def test_adx_threshold_range():
    with pytest.raises(prior_lang.PriorError, match="0 and 100"):
        prior_lang.compile_source(BOILER.format(cond="[adx] > 150"))


def test_stoch_rejects_at():
    with pytest.raises(prior_lang.PriorError, match="crosses"):
        prior_lang.compile_source(BOILER.format(cond="[stoch] at 20"))


def test_price_level_rejects_at():
    e = None
    with pytest.raises(prior_lang.PriorError, match="above/below") as e:
        prior_lang.compile_source(BOILER.format(cond="price at 250"))


def test_combined_v03_strategy_explains():
    src = (
        "universe [semis]\n"
        "when [new_high 50] and [adx] > 25 and [volume_spike 2x]\n"
        "  buy [10% portfolio]\n"
        "sell when [stoch] crosses below 80\n"
        "  or [trailing 5%]\n"
    )
    s = prior_lang.compile_source(src)
    assert len(s["entry"]["conditions"]) == 3
    from prior_lang.explain import explain_strategy
    text = explain_strategy(s)
    assert "new 50-bar closing high" in text
    assert "ADX(14) is above 25" in text
    assert "crosses below 80" in text
