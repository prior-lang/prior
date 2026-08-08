"""risk [after_losses N]: enter only after N consecutive losing trades.

The invariants: the streak is counted on a SHADOW BOOK that takes every
signal, including trades the gate declines (otherwise the gate feeds
back into its own input); outcomes are realized close-to-close fills
known at the exit bar; the traced events match the gated signals; and
the report carries the gate's counts so a gate that admits nothing is
loud, not silent. Specified by Sunil Kumar in review, with the shadow
book named in his spec.
"""

import numpy as np
import pandas as pd
import pytest

from prior_lang import compile_source
from prior_lang.codegen import compile_strategy
from prior_lang.backtest import run_backtest
from prior_lang.decompile import strategy_to_source
from prior_lang.errors import PriorError
from prior_lang.explain import explain_strategy
from prior_lang.formatter import format_program
from prior_lang.parser import parse_source
from prior_lang.canonical import strategy_digest

import math


GATED = (
    'strategy "Gated"\n\nuniverse $TEST\ntimeframe 1d\n\n'
    "when [rsi] < 45\n  buy [5% portfolio]\n\n"
    "sell when [rsi] > 55\n  or [stop 4%]\n\n"
    "risk [after_losses 1]\n"
)
UNGATED = GATED.replace("\nrisk [after_losses 1]\n", "")


def _tape(n=240):
    i = np.arange(n)
    close = 100 * (1 + 0.06 * np.sin(2 * np.pi * i / 14)) \
        * (1 + 0.02 * np.sin(2 * np.pi * i / 47))
    return pd.DataFrame({
        "open": close, "high": close * 1.004, "low": close * 0.996,
        "close": close, "volume": np.full(n, 1e6),
    }, index=pd.date_range("2023-01-02", periods=n, freq="B"))


def _gate_fn():
    s = compile_source(GATED)
    ns = {"pd": pd, "np": np, "math": math}
    exec(compile_strategy(s), ns)
    return ns["_after_losses_gate"]


def test_shadow_book_counts_declined_trades():
    gate = _gate_fn()
    # Six hand-built trades, entry at 4k, exit at 4k+2, outcomes L L W L L L.
    n_bars = 26
    sig = np.zeros(n_bars)
    px = np.full(n_bars, 100.0)
    outcomes = ["L", "L", "W", "L", "L", "L"]
    for k, o in enumerate(outcomes):
        sig[4 * k:4 * k + 2] = 1.0
        px[4 * k + 2] = 95.0 if o == "L" else 105.0
    idx = pd.date_range("2024-01-01", periods=n_bars, freq="B")
    gated, declined, stats = gate(pd.Series(sig, index=idx),
                                  pd.Series(px, index=idx), 2)
    g = gated.to_numpy()
    # Trade 3 (bars 8-9) follows two losses -> admitted. Trade 6 (bars
    # 20-21) is the shadow-book proof: the two losses before it were
    # both DECLINED trades — a counter running on the real book would
    # have seen only trade 3's win and refused it.
    assert list(np.nonzero(g)[0]) == [8, 9, 20, 21]
    assert stats == {"n": 2, "shadow_trades": 6, "admitted": 2, "declined": 4}
    assert declined == {0, 4, 12, 16}


def test_backtest_reports_the_gate_and_trades_match():
    df = _tape()
    base = run_backtest(compile_source(UNGATED), df)
    res = run_backtest(compile_source(GATED), df)
    gate = res["after_losses"]
    assert gate["shadow_trades"] == base["trades"] > 3
    assert gate["admitted"] + gate["declined"] == gate["shadow_trades"]
    assert res["trades"] == gate["admitted"] < gate["shadow_trades"]
    assert "after_losses" not in base


def test_traced_events_match_gated_signals():
    df = _tape()
    s = compile_source(GATED)
    ns = {"pd": pd, "np": np, "math": math}
    exec(compile_strategy(s, trace=True), ns)
    sig, events = ns["generate_signals_traced"](df)
    arr = sig.to_numpy()
    edges = [i for i in range(len(arr))
             if arr[i] != 0 and (i == 0 or arr[i - 1] == 0)]
    assert [e["i"] for e in events if e["event"] == "entry"] == edges
    # And the traced signals are the gated ones, not the shadow book's.
    exec(compile_strategy(s), ns2 := {"pd": pd, "np": np, "math": math})
    assert (ns2["generate_signals"](df).to_numpy() == arr).all()


def test_refused_for_options_and_ranking_and_zero():
    opt = ('strategy "O"\n\nuniverse $SPY\n\nwhen [rsi] > 1\n'
           "  write [csp delta=25 dte=7]\n\nclose at [profit 50%]\n"
           "  or [dte 2]\n\nrisk [after_losses 2]\n")
    with pytest.raises(PriorError) as e:
        compile_source(opt)
    assert "premium" in str(e.value)

    rank = ('strategy "R"\n\nuniverse [sp_top_30]\n\n'
            "hold top 5 by [momentum 126]\n\nrebalance monthly\n\n"
            "risk [after_losses 2]\n")
    with pytest.raises(PriorError) as e:
        compile_source(rank)
    assert "ranking" in str(e.value)

    with pytest.raises(PriorError) as e:
        compile_source(GATED.replace("[after_losses 1]", "[after_losses 0]"))
    assert "positive count" in str(e.value)


def test_sizing_line_error_points_to_the_risk_section():
    src = GATED.replace("buy [5% portfolio]", "buy [after_losses 2]")
    with pytest.raises(PriorError) as e:
        compile_source(src)
    assert "risk tags live on their own line" in str(e.value)


def test_round_trip_readback_and_decompile():
    fmt = format_program(parse_source(GATED))
    assert "risk [after_losses 1]" in fmt
    strip = lambda s: {k: v for k, v in s.items() if k != "name"}
    assert strategy_digest(strip(compile_source(GATED))) == \
        strategy_digest(strip(compile_source(fmt)))
    text = explain_strategy(compile_source(GATED))
    assert "shadow book" in text and "1 consecutive losing trade" in text
    back = strategy_to_source(compile_source(GATED))
    assert "[after_losses 1]" in back
