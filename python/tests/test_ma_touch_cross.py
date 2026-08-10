"""Price crossing and touching a moving average or VWAP.

crosses above/below: this close on the new side, the PREVIOUS close on
the other side (or exactly on the line) — two closed bars, no lookahead.
at (touch): the bar's range traded through the line — low <= line <=
high, confirmed at the close. A bar whose whole range sits beyond the
line, including a gap over it, did not touch it.
"""

import math

import numpy as np
import pandas as pd
import pytest

from prior_lang import compile_source
from prior_lang.codegen import compile_strategy
from prior_lang.errors import PriorError

TMPL = (
    'strategy "M"\n\nuniverse $TEST\ntimeframe 1d\n\n{when}\n'
    "  buy [5% portfolio]\n\nsell when [after 3 bars]\n"
)


def _frame(rows):
    return pd.DataFrame(rows, index=pd.date_range("2023-01-02",
                                                  periods=len(rows), freq="B"))


def _fires(when, df):
    """Rising-edge bars of the entry signal (the [after 3 bars] exit
    holds the raw signal, so edges are the honest comparison)."""
    s = compile_source(TMPL.format(when=when))
    ns = {"pd": pd, "np": np, "math": math}
    exec(compile_strategy(s), ns)
    sig = ns["generate_signals"](df).to_numpy()
    return [i for i in range(len(sig)) if sig[i] and (i == 0 or not sig[i - 1])]


def _bars(closes, lows=None, highs=None):
    closes = list(closes)
    lows = list(lows) if lows is not None else [c - 0.2 for c in closes]
    highs = list(highs) if highs is not None else [c + 0.2 for c in closes]
    return _frame([
        {"open": c, "high": h, "low": lo, "close": c, "volume": 1e6}
        for c, h, lo in zip(closes, highs, lows)
    ])


def test_cross_above_sma_fires_on_the_crossing_bar_only():
    # sma3 by hand: bar3 close 9 dips below its average (a downward
    # cross), bar5 close 12 comes back through it (the upward cross):
    #   bar4 close 9, sma (10+9+9)/3=9.33 -> below
    #   bar5 close 12, sma (9+9+12)/3=10  -> above, prev below: CROSS
    #   bar6 close 12, sma (9+12+12)/3=11 -> still above: no re-fire
    closes = [10, 10, 10, 9, 9, 12, 12, 12, 12, 12]
    df = _bars(closes, lows=[c - 0.1 for c in closes], highs=[c + 0.1 for c in closes])
    assert _fires("when price crosses above [sma 3]", df) == [5]
    assert _fires("when price crosses below [sma 3]", df) == [3]


def test_cross_below_sma_mirrors():
    closes = [10, 10, 10, 11, 11, 8, 8, 8, 8, 8]
    df = _bars(closes, lows=[c - 0.1 for c in closes], highs=[c + 0.1 for c in closes])
    assert _fires("when price crosses below [sma 3]", df) == [5]
    assert _fires("when price crosses above [sma 3]", df) == [3]


def test_touch_requires_the_range_through_the_line():
    # Steadily rising tape with tight ranges: the 3-bar average trails
    # ~1.9% below the close while the low sits only 0.1% below, so no
    # bar touches the line — except the one planted bar whose wick
    # reaches down through it. Exactly one touch, by hand.
    closes = [100.0 * (1.02 ** i) for i in range(20)]
    lows = [c * 0.999 for c in closes]
    highs = [c * 1.001 for c in closes]
    lows[12] = closes[12] * 0.97   # deep wick through the trailing average
    df = _bars(closes, lows=lows, highs=highs)
    assert _fires("when price at [sma 3]", df) == [12]


def test_gap_over_the_line_is_not_a_touch():
    # price runs from 10 to 12 but bar 11 GAPS: low 11.5, while sma3 at
    # bar 11 is (10+10+12)/3 = 10.67 — the line was never traded.
    closes = [10.0] * 10 + [12.0, 12.0, 12.0]
    lows = [9.8] * 10 + [11.5, 11.8, 11.8]
    highs = [10.2] * 10 + [12.2, 12.2, 12.2]
    df = _bars(closes, lows=lows, highs=highs)
    fires = _fires("when price at [sma 3]", df)
    assert 10 not in fires and 11 not in fires


def test_vwap_touch_and_cross_run():
    # Flat tape at 10 with constant volume: vwap == typical price == 10
    # once the 20-bar window fills; ranges straddle it, so the touch
    # signal's first edge is bar 19. After the jump to 12 nothing
    # touches until bar 30's deep wick.
    n = 40
    closes = [10.0] * 25 + [12.0] * (n - 25)
    lows = [9.9] * 25 + [11.9] * (n - 25)
    highs = [10.1] * 25 + [12.1] * (n - 25)
    lows[30] = 9.0
    df = _bars(closes, lows=lows, highs=highs)
    fires = _fires("when price at [vwap]", df)
    assert fires[0] == 19
    assert 30 in fires
    # crossing above the vwap happens once at the jump (close 12 above,
    # prev close 10 was at/below the line)
    assert _fires("when price crosses above [vwap]", df) == [25]


def test_no_lookahead_prefix_stability():
    rng = np.random.default_rng(9)
    closes = 100 * np.cumprod(1 + rng.normal(0, 0.02, 80))
    lows = closes * (1 - np.abs(rng.normal(0, 0.01, 80)))
    highs = closes * (1 + np.abs(rng.normal(0, 0.01, 80)))
    df = _bars(closes, lows=lows, highs=highs)
    for when in ("when price crosses above [ema 9]",
                 "when price at [ema 9]",
                 "when price crosses below [sma 5]",
                 "when price at [vwap 10]"):
        full = _fires(when, df)
        for k in (30, 55):
            prefix = _fires(when, df.iloc[:k])
            assert prefix == [i for i in full if i < k], (when, k)


def test_unsupported_comparator_lists_the_full_menu():
    with pytest.raises(PriorError, match="crosses above, crosses below, or at"):
        compile_source(TMPL.format(when="when price >= [sma 50]"))
