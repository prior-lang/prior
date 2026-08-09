"""Candlestick pattern tags: pure trailing bar geometry.

Every pattern is confirmed at the close of its LAST bar — all inputs
are that bar and earlier — so the tags carry no lookahead by
construction, and the tests prove it directly: the signal on a prefix
of the tape is identical to the same bars' signal on the full tape.

Tapes are hand-built OHLC rows: a neutral alternating baseline that can
never fire any pattern (asserted), with exact pattern bars planted at
known indices.
"""

import math

import numpy as np
import pandas as pd
import pytest

from prior_lang import compile_source
from prior_lang.codegen import compile_strategy
from prior_lang.decompile import strategy_to_source
from prior_lang.errors import PriorError
from prior_lang.explain import explain_strategy

TMPL = (
    'strategy "P"\n\nuniverse $TEST\ntimeframe 1d\n\n{when}\n'
    "  buy [5% portfolio]\n\nsell when [after 3 bars]\n"
)


def _baseline(n):
    """Alternating green/red bars with identical extents. No inside or
    outside bars (equal highs/lows fail strict inequalities), no
    engulfings or haramis (bodies share endpoints, never strictly
    contain), no dojis at 10% (body is half the range), no hammers or
    stars (shadows are small and symmetric)."""
    rows = []
    for i in range(n):
        if i % 2 == 0:
            o, c = 100.0, 100.8
        else:
            o, c = 100.8, 100.0
        rows.append({"open": o, "high": 101.2, "low": 99.6,
                     "close": c, "volume": 1e6})
    return rows


def _frame(rows):
    return pd.DataFrame(rows, index=pd.date_range("2023-01-02",
                                                  periods=len(rows), freq="B"))


def _fires(when, df):
    """Rising-edge bars of the entry signal — the bar the pattern was
    confirmed on (the template's [after 3 bars] exit holds the raw
    signal for 3 bars, so edges are the honest comparison)."""
    s = compile_source(TMPL.format(when=when))
    ns = {"pd": pd, "np": np, "math": math}
    exec(compile_strategy(s), ns)
    sig = ns["generate_signals"](df).to_numpy()
    return [i for i in range(len(sig)) if sig[i] and (i == 0 or not sig[i - 1])]


def _tape(planted: dict[int, dict], n=30):
    rows = _baseline(n)
    for i, bar in planted.items():
        rows[i] = {**rows[i], **bar, "volume": 1e6}
    return _frame(rows)


def test_baseline_fires_nothing():
    df = _frame(_baseline(30))
    for tag in ("[inside_bar]", "[outside_bar]", "[bullish_engulfing]",
                "[bearish_engulfing]", "[bullish_harami]", "[bearish_harami]",
                "[doji]", "[hammer]", "[shooting_star]", "[morning_star]",
                "[evening_star]"):
        assert _fires(f"when {tag}", df) == [], tag


def test_inside_and_outside_bar():
    df = _tape({
        9: {"open": 100.0, "high": 105.0, "low": 95.0, "close": 101.0},
        10: {"open": 100.0, "high": 104.0, "low": 96.0, "close": 100.5},
        19: {"open": 100.0, "high": 101.0, "low": 99.7, "close": 100.5},
        20: {"open": 100.0, "high": 104.0, "low": 96.0, "close": 99.0},
    })
    assert 10 in _fires("when [inside_bar]", df)
    assert 20 in _fires("when [outside_bar]", df)
    assert 10 not in _fires("when [outside_bar]", df)
    # Equal extents are NOT inside (strict inequalities).
    eq = _tape({9: {"high": 104.0, "low": 96.0},
                10: {"high": 104.0, "low": 96.0}})
    assert 10 not in _fires("when [inside_bar]", eq)


def test_engulfing_body_based():
    df = _tape({
        9: {"open": 101.0, "high": 101.5, "low": 98.5, "close": 99.0},
        10: {"open": 98.5, "high": 102.0, "low": 98.0, "close": 101.5},
    })
    assert 10 in _fires("when [bullish_engulfing]", df)
    # Close inside the prior body: no engulfing.
    weak = _tape({
        9: {"open": 101.0, "high": 101.5, "low": 98.5, "close": 99.0},
        10: {"open": 98.5, "high": 102.0, "low": 98.0, "close": 100.5},
    })
    assert 10 not in _fires("when [bullish_engulfing]", weak)
    bear = _tape({
        9: {"open": 99.0, "high": 101.5, "low": 98.5, "close": 101.0},
        10: {"open": 101.5, "high": 102.0, "low": 98.0, "close": 98.5},
    })
    assert 10 in _fires("when [bearish_engulfing]", bear)


def test_harami_requires_prior_color_and_containment():
    df = _tape({
        9: {"open": 104.0, "high": 104.5, "low": 95.5, "close": 96.0},
        10: {"open": 98.0, "high": 100.5, "low": 97.5, "close": 100.0},
    })
    assert 10 in _fires("when [bullish_harami]", df)
    # Same containment after a GREEN bar is not a bullish harami.
    green_prev = _tape({
        9: {"open": 96.0, "high": 104.5, "low": 95.5, "close": 104.0},
        10: {"open": 98.0, "high": 100.5, "low": 97.5, "close": 100.0},
    })
    assert 10 not in _fires("when [bullish_harami]", green_prev)
    assert 10 in _fires("when [bearish_harami]", green_prev)


def test_doji_threshold_is_a_parameter():
    df = _tape({10: {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.05}})
    assert 10 in _fires("when [doji]", df)             # 2.5% of range <= 10%
    assert 10 not in _fires("when [doji 2%]", df)      # ...but > 2%
    with pytest.raises(PriorError):
        compile_source(TMPL.format(when="when [doji 60%]"))


def test_hammer_and_shooting_star():
    hammer = _tape({10: {"open": 100.0, "high": 100.6, "low": 98.0, "close": 100.5}})
    assert 10 in _fires("when [hammer]", hammer)
    assert 10 not in _fires("when [shooting_star]", hammer)
    star = _tape({10: {"open": 100.5, "high": 103.0, "low": 100.4, "close": 100.0}})
    assert 10 in _fires("when [shooting_star]", star)
    assert 10 not in _fires("when [hammer]", star)


def test_morning_and_evening_star():
    df = _tape({
        8: {"open": 104.0, "high": 104.5, "low": 99.5, "close": 100.0},
        9: {"open": 99.0, "high": 99.5, "low": 98.0, "close": 98.6},
        10: {"open": 99.0, "high": 103.5, "low": 98.5, "close": 103.0},
    })
    assert 10 in _fires("when [morning_star]", df)
    ev = _tape({
        8: {"open": 100.0, "high": 104.5, "low": 99.5, "close": 104.0},
        9: {"open": 105.0, "high": 105.6, "low": 104.6, "close": 105.4},
        10: {"open": 105.0, "high": 105.2, "low": 100.5, "close": 101.0},
    })
    assert 10 in _fires("when [evening_star]", ev)
    # Third bar closing below the first bar's midpoint kills it.
    weak = _tape({
        8: {"open": 104.0, "high": 104.5, "low": 99.5, "close": 100.0},
        9: {"open": 99.0, "high": 99.5, "low": 98.0, "close": 98.6},
        10: {"open": 99.0, "high": 103.5, "low": 98.5, "close": 101.0},
    })
    assert 10 not in _fires("when [morning_star]", weak)


def test_no_lookahead_prefix_stability():
    """The signal a bar shows never changes when future bars arrive."""
    df = _tape({
        8: {"open": 104.0, "high": 104.5, "low": 99.5, "close": 100.0},
        9: {"open": 99.0, "high": 99.5, "low": 98.0, "close": 98.6},
        10: {"open": 99.0, "high": 103.5, "low": 98.5, "close": 103.0},
        19: {"open": 101.0, "high": 101.5, "low": 98.5, "close": 99.0},
        20: {"open": 98.5, "high": 102.0, "low": 98.0, "close": 101.5},
    }, n=40)
    for tag in ("[morning_star]", "[bullish_engulfing]", "[inside_bar]",
                "[doji]", "[hammer]"):
        full = set(_fires(f"when {tag}", df))
        for cut in (12, 25):
            prefix = set(_fires(f"when {tag}", df.iloc[:cut]))
            assert prefix == {i for i in full if i < cut}, (tag, cut)


def test_patterns_compose_with_sequence_and_context():
    """Compound taxonomy names are compositions, not tags: a Three
    Inside Up is a bullish harami then a confirming close."""
    df = _tape({
        9: {"open": 104.0, "high": 104.5, "low": 95.5, "close": 96.0},
        10: {"open": 98.0, "high": 100.5, "low": 97.5, "close": 100.0},
        11: {"open": 100.2, "high": 105.5, "low": 100.0, "close": 105.0},
    })
    fires = _fires("when [bullish_harami] then within 2 bars [up_days 1]", df)
    assert 11 in fires
    src = TMPL.format(when="when [bullish_engulfing] and [down_days 1]")
    s = compile_source(src)
    text = explain_strategy(s["strategies"][0] if "strategies" in s else s)
    assert "bullish engulfing" in text


def test_roundtrip_and_refusals():
    src = TMPL.format(when="when [morning_star] and [doji 8%]")
    s = compile_source(src)
    strat = s["strategies"][0] if "strategies" in s else s
    rt = strategy_to_source(strat)
    s2 = compile_source(rt)
    strat2 = s2["strategies"][0] if "strategies" in s2 else s2
    import json
    assert (json.dumps(strat["entry"], sort_keys=True)
            == json.dumps(strat2["entry"], sort_keys=True))
    # Pattern tags take no arguments (doji's threshold is the exception).
    with pytest.raises(PriorError):
        compile_source(TMPL.format(when="when [hammer 5]"))
