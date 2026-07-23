"""SuperTrend: an ATR trailing-stop trend line, added as an operand tag.

SuperTrend is stateful (each bar's band locks against the prior bar), which
is exactly the kind of indicator that is easy to hand-code with a lookahead
or repaint bug. As a compiler-provided tag it expands to one vetted
implementation, and — like every PRIOR condition — its direction at bar i is
decided from close[i] and prior-bar values only, so it cannot look ahead.
"""

import math

import pytest

import prior_lang
from prior_lang.codegen import compile_strategy, _supertrend_code
from prior_lang.errors import PriorError

pd = pytest.importorskip("pandas")
import numpy as np  # noqa: E402


def _ohlc(closes):
    closes = np.asarray(closes, dtype=float)
    days = pd.date_range("2026-01-05", periods=len(closes), freq="B")
    return pd.DataFrame(
        {"open": closes, "high": closes * 1.005, "low": closes * 0.995,
         "close": closes, "volume": 1_000_000.0},
        index=days,
    )


def _direction(df, n=10, mult=3.0):
    """Run just the compiler-emitted SuperTrend block and return its direction
    Series (+1 up / -1 down / NaN warmup), so we can assert on it directly."""
    snippet = _supertrend_code(n, mult, "st_dir")
    src = "def _f(df):\n    close = df['close']\n    " + snippet + "\n    return cond\n"
    ns = {"pd": pd, "np": np}
    exec(src, ns)  # noqa: S102 — our own generated snippet
    return ns["_f"](df)


def _signals(src, df):
    strategy = prior_lang.compile_source(src)
    ns = {"pd": pd, "np": np, "math": math}
    exec(compile_strategy(strategy), ns)  # noqa: S102
    return ns["generate_signals"](df)


# ── Parsing / codegen ──────────────────────────────────────────────────

@pytest.mark.parametrize("cmp", ["crosses above", "crosses below", "above", "below"])
def test_supertrend_four_forms_compile(cmp):
    src = f"universe $T\nwhen price {cmp} [supertrend]\n  buy [10% portfolio]\nsell when [after 5 bars]\n"
    strategy = prior_lang.compile_source(src)          # parses + validates
    code = compile_strategy(strategy)
    assert "generate_signals" in code
    # and the generated module actually executes
    ns = {"pd": pd, "np": np, "math": math}
    exec(code, ns)


def test_supertrend_params_flow_through():
    src = "universe $T\nwhen price crosses above [supertrend 20 4]\n  buy [10% portfolio]\nsell when [after 5 bars]\n"
    code = compile_strategy(prior_lang.compile_source(src))
    assert "alpha=1/20" in code and "4.0 * atr" in code


# ── Correctness on unambiguous scenarios ───────────────────────────────

def test_supertrend_reads_bullish_in_a_clean_uptrend():
    # A steady uptrend: once warmed up, price never closes below the lower
    # band, so direction must be +1 (bullish) throughout.
    df = _ohlc([100 + i for i in range(80)])
    d = _direction(df).dropna()
    assert (d > 0).all(), "a monotonic uptrend must read bullish everywhere"


def test_supertrend_flips_down_on_a_sharp_reversal():
    # Uptrend, then a hard drop that closes well below the trailing band.
    closes = [100 + i for i in range(60)] + [159 - 4 * i for i in range(1, 40)]
    d = _direction(_ohlc(closes)).dropna()
    assert (d > 0).iloc[0]           # started bullish
    assert (d < 0).iloc[-1]          # ended bearish
    assert set(np.sign(d.unique())) >= {1.0, -1.0}   # it actually flipped


# ── The no-lookahead guarantee (the whole point) ───────────────────────

def test_supertrend_does_not_look_ahead():
    """Direction at each bar must depend only on that bar and earlier ones:
    computing on a truncated history must equal computing on the full history
    and then truncating. This is what makes the stateful indicator safe."""
    rng = np.random.default_rng(7)
    closes = 100 + np.cumsum(rng.normal(0, 1.0, 300))
    df = _ohlc(closes)
    full = _direction(df)
    for k in (120, 180, 240):
        head = _direction(df.iloc[:k])
        a = full.iloc[:k].to_numpy()
        b = head.to_numpy()
        both = ~(np.isnan(a) | np.isnan(b))
        assert np.array_equal(a[both], b[both]), f"lookahead/repaint at k={k}"


def test_supertrend_strategy_trades_on_flips():
    rng = np.random.default_rng(1)
    segs, base = [], 100.0
    for drift in (0.5, -0.5, 0.6, -0.5):
        seg = base + np.cumsum(rng.normal(drift, 0.5, 100)); base = seg[-1]
        segs.append(seg)
    df = _ohlc(np.concatenate(segs))
    sig = _signals(
        "universe $T\nwhen price crosses above [supertrend]\n  buy [10% portfolio]\n"
        "sell when price crosses below [supertrend]\n", df)
    assert int((sig != 0).sum()) > 0, "supertrend strategy produced no trades"


# ── Error contract ─────────────────────────────────────────────────────

def test_bare_supertrend_needs_a_comparison():
    with pytest.raises(PriorError) as e:
        prior_lang.compile_source("universe $T\nwhen [supertrend]\n  buy [10% portfolio]\nsell when [after 5 bars]\n")
    assert "comparison" in e.value.message
    assert "supertrend" in (e.value.suggestion or "")


def test_supertrend_rejects_touch_operator():
    with pytest.raises(PriorError) as e:
        prior_lang.compile_source("universe $T\nwhen price at [supertrend]\n  buy [10% portfolio]\nsell when [after 5 bars]\n")
    assert "supertrend" in e.value.message
