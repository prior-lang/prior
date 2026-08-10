"""Fill conventions: close (default) vs next-open.

The close fill assumes trading the very print that fired the rule — the
favorable reading. next-open moves every position change to the next
bar's open, so the old position carries the overnight gap and the new
position the open-to-close move. Both numbers must be exact, and on
data with no overnight gaps the two conventions must agree to the bit.
"""

import numpy as np
import pandas as pd
import pytest

from prior_lang import compile_source
from prior_lang.backtest import (
    run_backtest,
    run_pair_backtest,
    run_portfolio_backtest,
    run_ranking_backtest,
)
from prior_lang.errors import PriorError

RULES_SRC = (
    'strategy "Fill Test"\n\nuniverse $TT\ntimeframe 1d\n\n'
    'when price above 100\n  buy [5% portfolio]\n\n'
    'sell when price below 100 or [after 500 bars]\n'
)


def _frame(closes, opens=None, start="2023-01-02"):
    closes = np.asarray(closes, dtype=float)
    if opens is None:
        # no overnight gaps: every bar opens exactly at the prior close
        opens = np.concatenate([[closes[0]], closes[:-1]])
    idx = pd.date_range(start, periods=len(closes), freq="B")
    return pd.DataFrame({
        "open": np.asarray(opens, dtype=float),
        "high": np.maximum(closes, opens) * 1.01,
        "low": np.minimum(closes, opens) * 0.99,
        "close": closes, "volume": 1e6,
    }, index=idx)


def test_next_open_arithmetic_exact():
    """Entry gaps up against the trade, exit gaps down against it: both
    fills computed by hand, and close-fill is the more favorable one."""
    closes = [90, 90, 90, 110, 111, 112, 113, 114, 115, 116, 90, 90]
    opens = [90, 90, 90, 90, 115, 111, 112, 113, 114, 115, 116, 85]
    strat = compile_source(RULES_SRC)
    df = _frame(closes, opens)

    res_close = run_backtest(strat, df)
    res_next = run_backtest(strat, df, fill="next-open")

    # signal fires at bar 3 (close 110), exit signal at bar 10 (close 90)
    assert abs(float(res_close["equity"].iloc[-1]) - 90 / 110) < 1e-12
    expected_next = (111 / 115) * (90 / 111) * (85 / 90)
    assert abs(float(res_next["equity"].iloc[-1]) - expected_next) < 1e-12
    assert float(res_close["equity"].iloc[-1]) > float(res_next["equity"].iloc[-1])
    assert res_close["fill"] == "close"
    assert res_next["fill"] == "next-open"

    # trades priced at the fill, not the signal print
    assert res_close["trades"] == 1
    assert res_next["trades"] == 1
    assert abs(res_close["avg_trade_pct"] - round((90 / 110 - 1) * 100, 3)) < 1e-9
    assert abs(res_next["avg_trade_pct"] - round((85 / 115 - 1) * 100, 3)) < 1e-9


def test_no_gap_data_makes_conventions_identical():
    rng = np.random.default_rng(7)
    closes = 100 * np.cumprod(1 + rng.normal(0.001, 0.02, 120))
    strat = compile_source(RULES_SRC)
    df = _frame(closes)  # opens == prior closes
    a = run_backtest(strat, df)
    b = run_backtest(strat, df, fill="next-open")
    assert np.allclose(a["equity"].to_numpy(), b["equity"].to_numpy(), atol=1e-12)
    assert a["trades"] == b["trades"]


def test_signal_on_final_bar_cannot_fill_next_open():
    """A rule firing on the last bar has no next open — close-fill counts
    a zero-return trade, next-open must not count a trade at all."""
    closes = [90, 90, 90, 110]  # fires on the final bar
    strat = compile_source(RULES_SRC)
    df = _frame(closes)
    assert run_backtest(strat, df)["trades"] == 1
    assert run_backtest(strat, df, fill="next-open")["trades"] == 0


def test_costs_charged_identically_under_both_fills():
    """cost_bps hits |position change| on the same bars either way — the
    fill moves the price, not the turnover."""
    closes = [90, 90, 90, 110, 111, 112, 113, 114, 115, 116, 90, 90]
    strat = compile_source(RULES_SRC)
    df = _frame(closes)  # no gaps: gross returns identical
    a = run_backtest(strat, df, cost_bps=20.0)
    b = run_backtest(strat, df, cost_bps=20.0, fill="next-open")
    assert np.allclose(a["equity"].to_numpy(), b["equity"].to_numpy(), atol=1e-12)
    gross = run_backtest(strat, df)
    assert float(a["equity"].iloc[-1]) < float(gross["equity"].iloc[-1])


def test_ranking_next_open_diverges_only_when_weights_change():
    src = ('strategy "Rank"\n\nuniverse $AAA $BBB\ntimeframe 1d\n'
           'rebalance monthly\nhold top 1 by [momentum 20]\n')
    strat = compile_source(src)
    rng = np.random.default_rng(3)

    def bars(t, drift, gaps):
        closes = 100 * np.cumprod(1 + rng.normal(drift, 0.015, 140))
        opens = np.concatenate([[closes[0]], closes[:-1]])
        if gaps:
            opens = opens * (1 + rng.normal(0.0, 0.01, len(opens)))
        f = _frame(closes, opens)
        f["ticker"] = t
        return f

    # gappy data: conventions must disagree (weights change at rebalances)
    df = pd.concat([bars("AAA", 0.002, True), bars("BBB", -0.001, True)])
    a = run_ranking_backtest(strat, df)
    b = run_ranking_backtest(strat, df, fill="next-open")
    assert a["fill"] == "close" and b["fill"] == "next-open"
    assert abs(float(a["equity"].iloc[-1]) - float(b["equity"].iloc[-1])) > 1e-9
    # daily returns may differ ONLY on bars where effective weights changed
    ra = a["equity"].pct_change().fillna(0.0)
    rb = b["equity"].pct_change().fillna(0.0)
    w_eff = a["weights"].shift(1).fillna(0.0)
    changed = w_eff.ne(w_eff.shift(1).fillna(0.0)).any(axis=1)
    diff = (ra - rb).abs() > 1e-12
    assert not bool((diff & ~changed).any())

    # gapless data: identical
    df2 = pd.concat([bars("AAA", 0.002, False), bars("BBB", -0.001, False)])
    c = run_ranking_backtest(strat, df2)
    d = run_ranking_backtest(strat, df2, fill="next-open")
    assert np.allclose(c["equity"].to_numpy(), d["equity"].to_numpy(), atol=1e-12)


def test_pair_next_open_gapless_identical_gappy_diverges():
    src = ('strategy "Ratio"\n'
           "when spread($GLD, $GDX) at [lower_bollinger 20]\n"
           "  buy [10% portfolio]\n"
           "sell when spread($GLD, $GDX) at [middle_bollinger 20]\n"
           "  or [after 30 bars]\n")
    strat = compile_source(src)
    rng = np.random.default_rng(11)

    def bars(t, gaps):
        closes = 100 * np.cumprod(1 + rng.normal(0.0005, 0.02, 160))
        opens = np.concatenate([[closes[0]], closes[:-1]])
        if gaps:
            opens = opens * (1 + rng.normal(0.0, 0.008, len(opens)))
        f = _frame(closes, opens)
        f["ticker"] = t
        return f

    df = pd.concat([bars("GLD", False), bars("GDX", False)])
    a = run_pair_backtest(strat, df)
    b = run_pair_backtest(strat, df, fill="next-open")
    assert np.allclose(a["equity"].to_numpy(), b["equity"].to_numpy(), atol=1e-12)

    df2 = pd.concat([bars("GLD", True), bars("GDX", True)])
    c = run_pair_backtest(strat, df2)
    d = run_pair_backtest(strat, df2, fill="next-open")
    if c["trades"]:  # a traded book must show the spread between fills
        assert abs(float(c["equity"].iloc[-1]) - float(d["equity"].iloc[-1])) > 1e-12


def test_portfolio_passes_fill_to_sleeves():
    book = ('portfolio "Book"\n  sleeve 60% "A"\n  sleeve 40% "B"\n'
            '  rebalance never\n\n'
            'strategy "A"\n\nuniverse $AAA\ntimeframe 1d\n\n'
            'when price above 100\n  buy [5% portfolio]\n\n'
            'sell when price below 100 or [after 500 bars]\n\n'
            'strategy "B"\n\nuniverse $BBB\ntimeframe 1d\n\n'
            'when price above 100\n  buy [5% portfolio]\n\n'
            'sell when price below 100 or [after 500 bars]\n')
    doc = compile_source(book)
    rng = np.random.default_rng(5)

    def bars(t):
        closes = 95 + np.cumsum(rng.normal(0.3, 1.5, 90))
        opens = np.concatenate([[closes[0]], closes[:-1]]) * (1 + rng.normal(0, 0.01, 90))
        f = _frame(closes, opens)
        f["ticker"] = t
        return f

    df = pd.concat([bars("AAA"), bars("BBB")])
    a = run_portfolio_backtest(doc, df)
    b = run_portfolio_backtest(doc, df, fill="next-open")
    assert a["fill"] == "close" and b["fill"] == "next-open"
    assert abs(float(a["equity"].iloc[-1]) - float(b["equity"].iloc[-1])) > 1e-12


def test_fill_refusals():
    strat = compile_source(RULES_SRC)
    df = _frame([90, 90, 110, 111, 112])
    with pytest.raises(PriorError, match="fill must be one of"):
        run_backtest(strat, df, fill="sideways")
    with pytest.raises(PriorError, match="no open column"):
        run_backtest(strat, df.drop(columns=["open"]), fill="next-open")

    book = ('portfolio "Book"\n  sleeve 50% "A"\n  sleeve 50% "W"\n'
            '  rebalance never\n\n'
            'strategy "A"\n\nuniverse $AAA\ntimeframe 1d\n\n'
            'when price above 100\n  buy [5% portfolio]\n\n'
            'sell when price below 100 or [after 500 bars]\n\n'
            'strategy "W"\n\nuniverse $AAA\ntimeframe 1d\n\n'
            'wheel [delta=25 dte=45]\n')
    doc = compile_source(book)
    f = _frame(100 + np.arange(60, dtype=float))
    f["ticker"] = "AAA"
    with pytest.raises(PriorError, match="options fill at chain marks"):
        run_portfolio_backtest(doc, f, fill="next-open")
