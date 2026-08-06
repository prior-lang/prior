"""score_from: warm up on earlier bars, score only the window.

The defect this guards: an out-of-sample window sliced bare has no
indicator history, so a 200-day average is NaN through a 128-bar
holdout and the strategy scores zero trades — refused for abstaining
when it was starved. The first real options keeper (gated on the
200-day) was marked "did not hold up" by exactly this. Warming up on
pre-window bars leaks nothing: live trading carries indicator history
in the same way.
"""

import numpy as np
import pandas as pd

from prior_lang import compile_source
from prior_lang.backtest import run_backtest
from prior_lang.options_backtest import run_options_backtest

EQ = (
    'strategy "T"\n\nuniverse $TEST\ntimeframe 1d\n\n'
    "when price above [sma 200]\n  buy [5% portfolio]\n\n"
    "sell when price below [sma 200]\n  or [stop 4%]\n"
)

OPT = (
    'strategy "T"\n\nuniverse $TEST\n\n'
    "when price above [sma 200]\n  write [csp delta=25 dte=7]\n\n"
    "close at [profit 50%]\n  or [dte 2]\n\n"
    "risk [contracts 1]\n"
)


def _bars(n=600, seed=7):
    # An oscillator around its own 200-day average, so sma-200 crossings
    # keep happening INSIDE the scored window. A trending tape puts the
    # only crossing in the warmup and both variants score zero trades
    # for tape reasons, which is not the defect under test.
    rng = np.random.default_rng(seed)
    i = np.arange(n)
    close = 100 * (1 + 0.08 * np.sin(2 * np.pi * i / 80)) \
        * np.exp(np.cumsum(rng.normal(0, 0.002, n)))
    return pd.DataFrame({
        "open": close, "high": close * 1.005, "low": close * 0.995,
        "close": close, "volume": np.full(n, 1e6),
    }, index=pd.date_range("2023-01-02", periods=n, freq="B"))


def test_equity_bare_window_starves_but_warmup_scores():
    df = _bars()
    window = df.iloc[-128:]
    bare = run_backtest(compile_source(EQ), window, capital=100_000.0)
    assert bare["trades"] == 0            # the defect, demonstrated
    warm = run_backtest(compile_source(EQ), df, capital=100_000.0,
                        score_from=window.index[0])
    assert warm["trades"] > 0
    assert warm["bars"] == len(window)    # scored the window, not the warmup


def test_options_bare_window_starves_but_warmup_scores():
    df = _bars()
    window = df.iloc[-128:]
    rows = []
    for d in df.index:
        px = float(df.at[d, "close"])
        rows.append({"date": d, "expiry": d + pd.Timedelta(days=7),
                     "strike": round(px * 0.97), "right": "P",
                     "delta": -0.25, "mid": 0.50})
    chains = pd.DataFrame(rows)
    s = compile_source(OPT)
    bare = run_options_backtest(s, window, chains)
    assert bare["cycles"] == 0            # the defect, demonstrated
    warm = run_options_backtest(s, df, chains, score_from=window.index[0])
    assert warm["cycles"] > 0
    # Nothing scored may predate the window.
    if len(warm["orders"]):
        assert warm["orders"]["date"].min() >= window.index[0]
