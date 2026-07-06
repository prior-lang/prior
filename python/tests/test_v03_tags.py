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
]


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
