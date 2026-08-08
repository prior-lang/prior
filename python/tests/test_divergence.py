"""[bullish_divergence] / [bearish_divergence]: price vs RSI at pivots.

The pivots are strict fractal extremes and inherit the fractal reveal
law: a pivot does not exist until its wing closes, so the divergence is
only comparable once the SECOND pivot is revealed, and the condition
changes value exactly at reveal bars. The classic repainting divergence
(drawn through a pivot that was not confirmed yet) is unwritable.

Tapes plant pivots explicitly on flat baseline lows/highs (a flat
baseline can never make a strict fractal), while the closes are shaped
separately to steer RSI at each pivot bar.
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
from prior_lang.formatter import format_program
from prior_lang.parser import parse_source
from prior_lang.canonical import strategy_digest

TMPL = (
    'strategy "D"\n\nuniverse $TEST\ntimeframe 1d\n\n{when}\n'
    "  buy [5% portfolio]\n\nsell when [after 3 bars]\n"
)


def _closes(n, fall, rise):
    """Alternating flat-ish returns, a steep fall over `fall` bars, a
    recovery over `rise` bars. RSI is ~0 at the fall's bottom and high
    inside the recovery."""
    ret = np.where(np.arange(n) % 2 == 0, 0.0005, -0.0005)
    ret[fall[0]:fall[1]] = -0.01
    ret[rise[0]:rise[1]] = 0.004
    return 100 * np.cumprod(1 + ret)


def _frame(close, low=None, high=None):
    n = len(close)
    return pd.DataFrame({
        "open": close,
        "high": high if high is not None else np.full(n, 200.0),
        "low": low if low is not None else np.full(n, 50.0),
        "close": close, "volume": np.full(n, 1e6),
    }, index=pd.date_range("2023-01-02", periods=n, freq="B"))


def _fires(when, df):
    s = compile_source(TMPL.format(when=when))
    ns = {"pd": pd, "np": np, "math": math}
    exec(compile_strategy(s), ns)
    return list(np.nonzero(ns["generate_signals"](df).to_numpy())[0])


def _bull_tape(n=60, p1=25, p2=35):
    # Closes: steep fall into p1 (RSI ~0 there), recovery into p2 (RSI
    # high there). Lows: flat 95 except the two planted pivots — a
    # lower low in price against a higher low in RSI.
    close = _closes(n, (p1 - 13, p1 + 1), (p1 + 1, p2 + 1))
    low = np.full(n, 95.0)
    low[p1], low[p2] = 85.0, 84.0
    return _frame(close, low=low)


def test_bullish_divergence_fires_exactly_at_the_reveal():
    p2, w = 35, 2
    df = _bull_tape(p2=p2)
    fired = _fires("when [bullish_divergence rsi 2]", df)
    assert fired and fired[0] == p2 + w
    # Nothing before the second pivot's wing closed: the pivot at p2
    # exists from bar p2, but is not knowledge until p2 + wing.


def test_no_fire_when_the_indicator_confirms_the_low():
    # Same price pivots, closes mirrored: RSI is HIGH at p1 and low at
    # p2, so price and indicator agree — no divergence.
    n, p1, p2 = 60, 25, 35
    close = _closes(n, (p1 + 1, p2 + 1), (p1 - 13, p1 + 1))
    low = np.full(n, 95.0)
    low[p1], low[p2] = 85.0, 84.0
    assert _fires("when [bullish_divergence rsi 2]", _frame(close, low=low)) == []


def test_pivots_too_far_apart_are_not_a_divergence():
    n, p1, p2 = 115, 25, 95
    close = _closes(n, (p1 - 13, p1 + 1), (p2 - 9, p2 + 1))
    low = np.full(n, 95.0)
    low[p1], low[p2] = 85.0, 84.0
    df = _frame(close, low=low)
    assert _fires("when [bullish_divergence rsi 2]", df) == []   # 70 > 60
    fired = _fires("when [bullish_divergence rsi 2 within=100]", df)
    assert fired and fired[0] == p2 + 2


def test_bearish_divergence_mirrors_on_highs():
    n, p1, p2 = 60, 25, 35
    # Closes rise steeply into p1 (RSI high), fall into p2 (RSI lower);
    # highs plant a higher high in price.
    ret = np.where(np.arange(n) % 2 == 0, 0.0005, -0.0005)
    ret[p1 - 13:p1 + 1] = 0.01
    # One down bar inside the rally: a pure 14-bar rally has zero losses,
    # which makes RSI undefined (NaN) under the divide guard — and a
    # pivot with undefined RSI is honestly skipped, not compared.
    ret[p1 - 6] = -0.002
    ret[p1 + 1:p2 + 1] = -0.004
    close = 100 * np.cumprod(1 + ret)
    high = np.full(n, 130.0)
    high[p1], high[p2] = 140.0, 141.0
    df = _frame(close, high=high)
    fired = _fires("when [bearish_divergence rsi 2]", df)
    assert fired and fired[0] == p2 + 2


def test_unknown_indicator_is_refused_readably():
    with pytest.raises(PriorError) as e:
        compile_source(TMPL.format(when="when [bullish_divergence macd 2]"))
    assert "rsi" in str(e.value)


def test_round_trip_readback_and_exit_usage():
    src = TMPL.format(when="when [bullish_divergence rsi 2]")
    fmt = format_program(parse_source(src))
    assert "[bullish_divergence rsi 2]" in fmt
    strip = lambda s: {k: v for k, v in s.items() if k != "name"}
    assert strategy_digest(strip(compile_source(src))) == \
        strategy_digest(strip(compile_source(fmt)))
    text = explain_strategy(compile_source(src))
    assert "bullish divergence" in text and "revealed" in text
    back = strategy_to_source(compile_source(src))
    assert "[bullish_divergence rsi]" in back
    # And the bearish twin belongs in exits — Sunil's dead rule was a
    # divergence exit.
    exit_src = src.replace("sell when [after 3 bars]",
                           "sell when [bearish_divergence rsi 2]\n  or [after 30 bars]")
    s = compile_source(exit_src)
    assert any(c["condition"] == "bearish_divergence"
               for c in s["exit"]["conditions"])
