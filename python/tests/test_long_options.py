"""Long options: the verb picks the side. buy [call] pays a debit, and
the debit IS the capital base — an all-long position is not free, it
costs exactly what it can lose. Management percentages read against the
debit (profit 100% = the position doubled), expiry settles by intrinsic,
and a debit vertical's capital is the debit, never the width.
"""

import math

import numpy as np
import pandas as pd
import pytest

from prior_lang import compile_source
from prior_lang.decompile import strategy_to_source
from prior_lang.errors import PriorError
from prior_lang.explain import explain_strategy
from prior_lang.formatter import format_program
from prior_lang.options_backtest import run_options_backtest
from prior_lang.parser import parse_source
from prior_lang.canonical import strategy_digest


def _bars(n=14, px=100.0):
    idx = pd.date_range("2024-03-01", periods=n, freq="B")
    close = np.full(n, px)
    return pd.DataFrame({"open": close, "high": close + 1, "low": close - 1,
                         "close": close, "volume": 1e6}, index=idx)


def _chains(idx, call_mids, put_mid=1.5, expiry_i=9):
    """Chain fixture: strikes 95/100/105 both rights, one expiry.
    call_mids maps day index -> mid for the K=100 call (the pick target).
    The K=105 call is priced at a fixed fraction so spreads have a wing."""
    expiry = idx[expiry_i]
    rows = []
    for i, d in enumerate(idx):
        k100 = call_mids.get(i, call_mids[max(k for k in call_mids if k <= i)])
        for strike, right, delta, mid in [
            (95.0, "C", 0.55, k100 * 2.2), (100.0, "C", 0.30, k100),
            (105.0, "C", 0.12, round(k100 * 0.4, 2)),
            (95.0, "P", 0.15, put_mid * 0.5), (100.0, "P", 0.30, put_mid),
            (105.0, "P", 0.60, put_mid * 2.0),
        ]:
            rows.append({"date": d, "expiry": expiry, "strike": strike,
                         "right": right, "delta": delta, "mid": mid})
    return pd.DataFrame(rows)


LC = ('strategy "LC"\n\nuniverse $TST\n\nwhen price above 1\n'
      "  buy [call delta=30 dte=7]\n\nclose at [profit 100%]\n"
      "  or [loss 50%]\n\nrisk [contracts 1]\n")


def test_parse_side_and_round_trips():
    s = compile_source(LC)
    opt = s["options"]["option"]
    assert opt["type"] == "call" and opt["side"] == "long" and opt["delta"] == 30.0
    fmt = format_program(parse_source(LC))
    assert "buy [call delta=30 dte=7]" in fmt
    strip = lambda x: {k: v for k, v in x.items() if k != "name"}
    assert strategy_digest(strip(compile_source(LC))) == \
        strategy_digest(strip(compile_source(fmt)))
    back = strategy_to_source(compile_source(LC))
    assert "buy [call" in back and "write" not in back
    text = explain_strategy(compile_source(LC))
    assert "Buy the ~30-delta call" in text and "debit" in text


def test_refusals_read_well():
    with pytest.raises(PriorError) as e:
        compile_source(LC.replace("buy [call delta=30 dte=7]",
                                  "write [call delta=30 dte=7]"))
    assert "bought, not written" in str(e.value)
    with pytest.raises(PriorError) as e:
        compile_source(LC.replace("buy [call delta=30 dte=7]", "buy [csp]"))
    assert "premium structure" in str(e.value)
    with pytest.raises(PriorError) as e:
        compile_source(LC.replace("buy [call delta=30 dte=7]", "short [call]"))
    assert "short is for stock" in str(e.value)


def test_long_call_profit_cycle_and_debit_capital():
    df = _bars()
    # K=100 call opens at 2.00 and doubles by day 4: profit 100% closes.
    chains = _chains(df.index, {0: 2.00, 3: 3.00, 4: 4.20})
    res = run_options_backtest(compile_source(LC), df, chains)
    orders = res["orders"]
    assert list(orders["action"][:2]) == ["open", "close"]
    assert orders.iloc[0]["side"] == "long"
    assert res["cycles"] >= 1 and res["wins"] >= 1
    # First cycle pays 200 and closes at 420; the always-true gate then
    # re-enters at 4.20, so the capital base is the LARGEST debit any
    # cycle put at risk — the same high-water convention the credit side
    # uses for collateral.
    assert res["capital_base"] == pytest.approx(420.0)
    assert res["sharpe"] is not None
    # Cycle 1: paid 200, closed 420 (+220). Cycle 2: paid 420, expired
    # worthless at spot 100 (-420). The engine reports the whole truth.
    assert res["net_pnl"] == pytest.approx(-200.0)
    assert res["total_return_pct"] == pytest.approx(-47.62, abs=0.05)
    # ledger consistency: the daily-marked curve ends at realized P&L
    assert res["equity"].iloc[-1] == pytest.approx(res["net_pnl"], abs=1e-6)


def test_long_call_loss_trigger():
    df = _bars()
    chains = _chains(df.index, {0: 2.00, 3: 0.90})   # value <= 50% of debit
    res = run_options_backtest(compile_source(LC), df, chains)
    first = res["orders"][res["orders"]["group"] == 1]
    assert list(first["action"]) == ["open", "close"]
    assert first.iloc[1]["price"] == pytest.approx(0.90)


def test_long_call_expiry_settles_intrinsic():
    src = LC.replace("close at [profit 100%]\n  or [loss 50%]",
                     "close at [profit 900%]")
    df = _bars(px=104.0)
    chains = _chains(df.index, {0: 2.00})
    res = run_options_backtest(compile_source(src), df, chains)
    settles = res["orders"][res["orders"]["action"] == "settle"]
    assert len(settles) >= 1
    # K=100 call, spot 104 -> intrinsic 4.00
    assert settles.iloc[0]["price"] == pytest.approx(4.0)


def test_debit_spread_capital_is_debit_not_width():
    src = ('strategy "DCS"\n\nuniverse $TST\n\nwhen price above 1\n'
           "  buy [call_spread delta=30 width=5 dte=7]\n\n"
           "close at [profit 900%]\n\nrisk [contracts 1]\n")
    df = _bars(px=104.0)
    chains = _chains(df.index, {0: 2.00})   # long K100 @2.00, short K105 @0.80
    s = compile_source(src)
    assert s["options"]["option"]["side"] == "long"
    res = run_options_backtest(s, df, chains)
    opens = res["orders"][res["orders"]["action"] == "open"]
    assert set(opens["side"]) == {"long", "short"}
    assert sorted(opens["strike"]) == [100.0, 105.0]
    # capital = net debit (2.00 - 0.80) * 100 = 120, NOT width * 100 = 500
    assert res["capital_base"] == pytest.approx(120.0)
    # settle at spot 104: long leg 4.00, short leg 0 -> net +400 - 120 paid
    assert res["net_pnl"] == pytest.approx(280.0)


def test_short_structures_unchanged():
    src = ('strategy "PCS"\n\nuniverse $TST\n\nwhen price above 1\n'
           "  write [put_spread delta=30 width=5 dte=7]\n\n"
           "close at [profit 900%]\n\nrisk [contracts 1]\n")
    df = _bars(px=100.0)
    chains = _chains(df.index, {0: 2.00})
    res = run_options_backtest(compile_source(src), df, chains)
    opens = res["orders"][res["orders"]["action"] == "open"]
    assert len(opens) == 2
    # credit spread still reserves the width
    assert res["capital_base"] == pytest.approx(500.0)
