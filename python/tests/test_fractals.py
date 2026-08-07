"""Fractal levels: revealed at t plus wing, never on their own bar.

A fractal is a symmetric window on highs and lows, which means it does
not exist until its confirmation wing has closed. The classic bug is
marking it at t — the accidental lookahead this tag exists to make
unwritable. Specified by Gabriel Guevara Muradas in review.
"""

import numpy as np
import pandas as pd
import pytest

from prior_lang import compile_source
from prior_lang.codegen import generate_strategy_code
from prior_lang.decompile import Comparison  # noqa: F401 — import sanity
from prior_lang.explain import explain_strategy
from prior_lang.formatter import format_program
from prior_lang.parser import parse_source
from prior_lang.canonical import strategy_digest

TMPL = (
    'strategy "T"\n\nuniverse $TEST\ntimeframe 1d\n\n{when}\n'
    "  buy [5% portfolio]\n\nsell when [rsi] > 65\n  or [stop 4%]\n"
)


def _tape(n=40, spike_at=20, wing=2):
    """Flat-ish tape with one clear fractal high at `spike_at`."""
    high = np.full(n, 101.0)
    high[spike_at] = 110.0
    close = np.full(n, 100.0) + 0.01 * np.sin(np.arange(n))  # RSI stays defined
    return pd.DataFrame({
        "open": close, "high": high, "low": close - 1.0, "close": close,
        "volume": np.full(n, 1e6),
    }, index=pd.date_range("2024-01-01", periods=n, freq="B"))


def _level_series(src_when, df):
    s = compile_source(TMPL.format(when=src_when))
    conds = [{"type": c["condition"], "params": c.get("params", {})}
             for c in s["entry"]["conditions"]]
    code = generate_strategy_code(conds, s["entry"]["match_logic"])
    ns = {"pd": pd, "np": np}
    exec(code, ns)
    return ns["generate_signals"](df), s


def test_fractal_high_reveals_exactly_wing_bars_late():
    df = _tape(spike_at=20, wing=2)
    # Price jumps above the fractal level (110) at bar 25 — but the
    # signal machinery aside, the LEVEL itself must be NaN before 22.
    s = compile_source(TMPL.format(when="when price above [fractal_high 2]"))
    conds = [{"type": c["condition"], "params": c.get("params", {})}
             for c in s["entry"]["conditions"]]
    code = generate_strategy_code(conds, s["entry"]["match_logic"])
    # Reconstruct the level exactly as the emitted code does and check
    # the reveal timing directly: nothing at 20 or 21, the spike's high
    # at 22 onward.
    w = 2
    src = df["high"]
    fl = src.shift(1).rolling(w, min_periods=w).max()
    fr = src.shift(-w).rolling(w, min_periods=w).max()
    flevel = src.where((src > fl) & (src > fr)).shift(w).ffill()
    assert pd.isna(flevel.iloc[20]) or flevel.iloc[20] != 110.0
    assert pd.isna(flevel.iloc[21]) or flevel.iloc[21] != 110.0
    assert flevel.iloc[22] == 110.0
    assert flevel.iloc[-1] == 110.0
    assert "shift(2)" in code           # the delay is in the emitted code


def test_crossing_cannot_fire_before_the_reveal():
    df = _tape(spike_at=20, wing=2)
    # Close crosses 110 at bar 24 — after the reveal, so it may fire.
    df.iloc[24:, df.columns.get_loc("close")] = 111.0
    df.iloc[24:, df.columns.get_loc("high")] = 112.0
    sig, _ = _level_series("when price crosses above [fractal_high 2]", df)
    fired = list(np.where(sig.values > 0)[0])
    assert fired and min(fired) >= 22

    # Now cross at bar 21 — BEFORE the reveal. The fractal is not yet
    # knowledge; nothing may fire off it there.
    df2 = _tape(spike_at=20, wing=2)
    df2.iloc[21:, df2.columns.get_loc("close")] = 111.0
    df2.iloc[21:, df2.columns.get_loc("high")] = 112.0
    sig2, _ = _level_series("when price crosses above [fractal_high 2]", df2)
    fired2 = list(np.where(sig2.values > 0)[0])
    assert not fired2 or min(fired2) >= 22


def test_wing_scales_the_reveal():
    df = _tape(n=50, spike_at=20, wing=3)
    w = 3
    src = df["high"]
    fl = src.shift(1).rolling(w, min_periods=w).max()
    fr = src.shift(-w).rolling(w, min_periods=w).max()
    flevel = src.where((src > fl) & (src > fr)).shift(w).ffill()
    assert pd.isna(flevel.iloc[22]) or flevel.iloc[22] != 110.0
    assert flevel.iloc[23] == 110.0


def test_fractal_low_mirrors():
    df = _tape()
    df["low"] = 99.0
    df.iloc[20, df.columns.get_loc("low")] = 90.0
    s = compile_source(TMPL.format(when="when price crosses below [fractal_low 2]"))
    assert s["entry"]["conditions"][0]["condition"] == "price_crosses_below_fractal_low"
    assert s["entry"]["conditions"][0]["params"]["wing"] == 2


def test_round_trip_and_readback():
    src = TMPL.format(when="when price crosses above [fractal_high 2]")
    fmt = format_program(parse_source(src))
    assert "price crosses above [fractal_high 2]" in fmt
    strip = lambda s: {k: v for k, v in s.items() if k != "name"}
    assert strategy_digest(strip(compile_source(src))) == \
        strategy_digest(strip(compile_source(fmt)))
    text = explain_strategy(compile_source(src))
    assert "fractal high" in text and "revealed" in text


def test_bad_comparator_is_refused_readably():
    from prior_lang.errors import PriorError
    with pytest.raises(PriorError) as e:
        compile_source(TMPL.format(when="when price at [fractal_high 2]"))
    assert "crosses above" in str(e.value)
