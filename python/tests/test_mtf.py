"""v0.5 multi-timeframe: `on <tf>` inside condition tags.

The centerpiece is the golden no-repaint test: a mid-week price explosion
must NOT flip a weekly gate until the weekly bar actually closes. This is
the repainting bug PineScript security() users fight forever, deleted by
construction.
"""

import math

import pytest

import prior_lang
from prior_lang import strategy_to_source
from prior_lang.codegen import compile_strategy

BOILER = (
    "universe [sp_top_30]\ntimeframe 1h\n"
    "when {cond}\n  buy [5% portfolio]\nsell when [after 10 bars]\n"
)


def test_on_attaches_timeframe_and_roundtrips():
    s = prior_lang.compile_source(BOILER.format(cond="[rsi on 4h] < 30"))
    [c] = s["entry"]["conditions"]
    assert c["condition"] == "rsi_less_than"
    assert c["timeframe"] == "4h"
    assert prior_lang.compile_source(strategy_to_source(s)) == s
    assert "[rsi on 4h] < 30" in strategy_to_source(s)


def test_on_finer_than_strategy_rejected():
    with pytest.raises(prior_lang.PriorError, match="finer"):
        prior_lang.compile_source(
            "universe [sp_top_30]\ntimeframe 1d\n"
            "when [rsi on 1h] < 30\n  buy [5% portfolio]\nsell when [after 5 bars]\n"
        )


def test_on_equal_to_strategy_rejected():
    with pytest.raises(prior_lang.PriorError, match="drop it"):
        prior_lang.compile_source(
            "universe [sp_top_30]\ntimeframe 1d\n"
            "when [rsi on 1d] < 30\n  buy [5% portfolio]\nsell when [after 5 bars]\n"
        )


def test_comparison_sides_must_share_timeframe():
    with pytest.raises(prior_lang.PriorError, match="same timeframe"):
        prior_lang.compile_source(
            "universe [sp_top_30]\ntimeframe 1h\n"
            "when [ema 50 on 4h] crosses above [ema 200 on 1d]\n"
            "  buy [5% portfolio]\nsell when [after 5 bars]\n"
        )


def test_on_banned_in_hold_where_for_now():
    with pytest.raises(prior_lang.PriorError, match="coming later"):
        prior_lang.compile_source(
            "universe [sp_top_30]\nrebalance monthly\n"
            "hold top 3 by [momentum 63]\n  where [rsi on 1w] < 70\n"
        )


def test_on_rejected_on_non_condition_tags():
    with pytest.raises(prior_lang.PriorError, match="condition tags"):
        prior_lang.compile_source(
            "universe [sp_top_30]\nwhen [rsi] < 30\n  buy [5% portfolio]\n"
            "sell when [stop 2% on 1d]\n"
        )


def test_explain_mentions_closed_bars():
    from prior_lang.explain import explain_strategy
    s = prior_lang.compile_source(BOILER.format(cond="[rsi on 4h] < 30"))
    assert "judged on closed 4h bars" in explain_strategy(s)


def test_golden_no_repaint_weekly_gate():
    pd = pytest.importorskip("pandas")
    import numpy as np  # noqa: F401

    # 4 ISO weeks of daily bars. Weekly closes: w1=100, w2=90 (gate False:
    # 90 < mean(100,90)=95), w3 closes at 150 after exploding on Wednesday,
    # w4 flat 150. The gate may not flip before w3's bar CLOSES on Friday.
    days = pd.date_range("2026-01-05", periods=20, freq="B")  # Mon w1 .. Fri w4
    closes = (
        [100.0] * 5                                  # w1
        + [98.0, 96.0, 94.0, 92.0, 90.0]             # w2 down
        + [95.0, 100.0, 150.0, 150.0, 150.0]         # w3 explodes Wednesday
        + [150.0] * 5                                # w4
    )
    df = pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": 1_000_000},
        index=days,
    )

    src = (
        "universe $TEST\ntimeframe 1d\n"
        "when price above [sma 2 on 1w]\n  buy [5% portfolio]\n"
        "sell when [after 100 bars]\n"
    )
    strategy = prior_lang.compile_source(src)
    namespace = {"pd": pd, "np": __import__("numpy"), "math": math}
    exec(compile_strategy(strategy), namespace)
    sig = namespace["generate_signals"](df)

    # Wednesday-Thursday of week 3: price is 150, wildly above any weekly
    # SMA, but week 3 hasn't closed — the gate must still be False.
    assert sig.loc["2026-01-21"] == 0  # w3 Wednesday, the explosion bar
    assert sig.loc["2026-01-22"] == 0  # w3 Thursday
    # From week 3's close on, the gate is True → entry fires
    assert sig.loc["2026-01-26"] == 1  # w4 Monday holds the position


def test_mtf_generated_code_shape():
    s = prior_lang.compile_source(BOILER.format(cond="[rsi on 4h] < 30 and [macd_cross_up]"))
    code = compile_strategy(s)
    assert "_prior_htf_cond_0" in code          # the MTF condition is a helper
    assert "htf_4h" in code and 'resample("4h"' in code
    assert 'label="right", closed="right"' in code
    assert "macd" in code                        # the local condition stays inline
