"""Pairs/spread trading: spread($A, $B) as a first-class operand.

The spread behaves exactly like price — every price comparison works on
it, codegen computes indicators ON the spread series, and the backtester
translates a spread position into equal dollar legs (long A / short B
for +1). The golden test drives a mean-reverting ratio through a
Bollinger touch-and-revert cycle.
"""

import math

import pytest

import prior_lang
from prior_lang import strategy_to_source
from prior_lang.codegen import compile_strategy

SRC = (
    'strategy "Gold Miners Ratio"\n'
    "when spread($GLD, $GDX) at [lower_bollinger 20]\n"
    "  buy [10% portfolio]\n"
    "sell when spread($GLD, $GDX) at [middle_bollinger 20]\n"
    "  or [after 30 bars]\n"
)


def test_pair_json_shape():
    s = prior_lang.compile_source(SRC)
    assert s["universe"] == {"type": "pair", "tickers": ["GLD", "GDX"], "form": "ratio"}
    assert s["entry"]["conditions"][0]["condition"] == "price_at_bollinger_band"


def test_pair_roundtrip():
    s = prior_lang.compile_source(SRC)
    out = strategy_to_source(s)
    # period 20 is the default, so canonical form elides it
    assert "spread($GLD, $GDX) at [lower_bollinger]" in out
    assert "universe" not in out  # the spread IS the universe
    assert prior_lang.compile_source(out) == s


def test_diff_form_roundtrips():
    src = (
        "when spread($XLE, $XOP, diff) below [sma 50]\n"
        "  buy [10% portfolio]\nsell when [stop 2 atr]\n  or [after 20 bars]\n"
    )
    s = prior_lang.compile_source(src)
    assert s["universe"]["form"] == "diff"
    assert "spread($XLE, $XOP, diff)" in strategy_to_source(s)
    assert prior_lang.compile_source(strategy_to_source(s)) == s


def test_one_spread_per_file():
    with pytest.raises(prior_lang.PriorError, match="one spread"):
        prior_lang.compile_source(
            "when spread($GLD, $GDX) at [lower_bollinger]\n  buy [10% portfolio]\n"
            "sell when spread($GLD, $SLV) at [middle_bollinger]\n"
        )


def test_spread_conflicts_with_universe_and_tickers():
    with pytest.raises(prior_lang.PriorError, match="drop the universe"):
        prior_lang.compile_source(
            "universe [semis]\nwhen spread($GLD, $GDX) at [lower_bollinger]\n"
            "  buy [10% portfolio]\nsell when [after 5 bars]\n"
        )
    with pytest.raises(prior_lang.PriorError, match="no other inline"):
        prior_lang.compile_source(
            "when spread($GLD, $GDX) at [lower_bollinger]\n  buy [10% portfolio]\n"
            "sell when $NVDA above [sma 50]\n"
        )


def test_same_ticker_spread_rejected():
    with pytest.raises(prior_lang.PriorError, match="two different tickers"):
        prior_lang.compile_source(
            "when spread($GLD, $GLD) at [lower_bollinger]\n  buy [10% portfolio]\n"
            "sell when [after 5 bars]\n"
        )


def test_volume_conditions_banned_on_spreads():
    with pytest.raises(prior_lang.PriorError, match="needs volume"):
        prior_lang.compile_source(
            "when spread($GLD, $GDX) at [lower_bollinger] and [volume_spike]\n"
            "  buy [10% portfolio]\nsell when [after 5 bars]\n"
        )


def test_percent_exits_banned_on_diff_spreads():
    with pytest.raises(prior_lang.PriorError, match="undefined on a diff"):
        prior_lang.compile_source(
            "when spread($GLD, $GDX, diff) below [sma 50]\n  buy [10% portfolio]\n"
            "sell when [stop 4%]\n"
        )


def test_explain_names_the_legs():
    from prior_lang.explain import explain_strategy
    text = explain_strategy(prior_lang.compile_source(SRC))
    assert "GLD/GDX ratio spread" in text
    assert "equal dollar legs" in text


def _pair_panel(pd, np):
    """GLD flat at 100; GDX wiggles gently (so the Bollinger band never
    degenerates to the price itself), then the ratio dips hard at bars
    40-45 and reverts — one clean lower-band touch and recovery."""
    days = pd.date_range("2026-01-05", periods=80, freq="B")
    idx = np.arange(80)
    ratio = 1.0 + 0.004 * np.sin(idx / 3.0)  # ±0.4% background noise
    ratio[40:46] = [0.97, 0.94, 0.92, 0.94, 0.97, 1.0]  # dip and revert
    gld = pd.DataFrame(
        {"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 0},
        index=days,
    )
    gdx = gld.copy()
    gdx["close"] = 100.0 / ratio
    return {"GLD": gld, "GDX": gdx}


def test_golden_pair_signals_enter_dip_exit_revert():
    pd = pytest.importorskip("pandas")
    import numpy as np

    strategy = prior_lang.compile_source(SRC)
    namespace = {"pd": pd, "np": np, "math": math}
    exec(compile_strategy(strategy), namespace)
    assert namespace["PAIR"] == ("GLD", "GDX", "ratio")

    sig = namespace["generate_pair_signals"](_pair_panel(pd, np))
    assert sig.iloc[:40].eq(0).all()           # background noise never triggers
    assert (sig == 1).any()                     # entered on the band touch
    first_on = sig[sig == 1].index[0]
    assert first_on >= sig.index[40]            # entry inside the dip window
    assert first_on <= sig.index[45]
    # And the position closes after reversion (middle-band or 30-bar exit)
    after_entry = sig.loc[first_on:]
    assert after_entry.eq(0).any()


def test_pair_backtest_and_metrics():
    pd = pytest.importorskip("pandas")
    import numpy as np
    from prior_lang.backtest import run_pair_backtest

    panel = _pair_panel(pd, np)
    rows = []
    for t, bars in panel.items():
        chunk = bars.copy()
        chunk["ticker"] = t
        rows.append(chunk)
    df = pd.concat(rows).sort_index()

    res = run_pair_backtest(prior_lang.compile_source(SRC), df)
    assert res["pair"] == "GLD/GDX"
    assert res["trades"] >= 1
    # Bought the dip in the ratio and it reverted: the pair trade wins.
    assert res["total_return_pct"] > 0


def test_pair_backtest_missing_leg_errors():
    pd = pytest.importorskip("pandas")
    import numpy as np
    from prior_lang.backtest import run_pair_backtest

    panel = _pair_panel(pd, np)
    df = panel["GLD"].copy()
    df["ticker"] = "GLD"
    with pytest.raises(SystemExit, match="GDX"):
        run_pair_backtest(prior_lang.compile_source(SRC), df)
