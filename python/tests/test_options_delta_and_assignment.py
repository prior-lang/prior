"""Contract selection units, and life after assignment.

Two production bugs, one QA run. First: strategies say delta=25 in
trader units while chain data stores 0.25, and the nearest-|delta| sort
made |1.00 - 25| the best gap — every backtest quietly traded the
deepest in-the-money contract. Second: a bare CSP that got assigned
entered a state no entry rule fires from, so one assignment turned the
rest of the backtest into unmanaged buy-and-hold. Together they capped
every options attempt at a handful of meaningless cycles.
"""

import numpy as np
import pandas as pd

from prior_lang import compile_source
from prior_lang.options_backtest import run_options_backtest

CSP = (
    'strategy "T"\n\nuniverse $TEST\n\n'
    "when [rsi] > 1\n  write [csp delta=25 dte=7]\n\n"
    "close at [profit 50%]\n  or [loss 150%]\n\n"
    "risk [contracts 1]\n"
)


def _flat_bars(n=120, price=100.0):
    idx = pd.date_range("2024-01-02", periods=n, freq="B")
    # A perfectly flat close makes RSI undefined (no losses to average),
    # which silently closes the entry gate. Wiggle keeps it defined.
    wiggle = 1 + 0.004 * np.sin(np.arange(n))
    close = price * wiggle
    return pd.DataFrame({
        "open": close, "high": close * 1.002, "low": close * 0.998,
        "close": close, "volume": 1e6,
    }, index=idx)


def _chains(bars, strikes_deltas, dte=7, put_mid=0.50):
    """One expiry `dte` days out per session, given (strike, delta) puts."""
    rows = []
    for d in bars.index:
        expiry = d + pd.Timedelta(days=dte)
        for strike, delta in strikes_deltas:
            rows.append({"date": d, "expiry": expiry, "strike": strike,
                         "right": "P", "delta": -abs(delta), "mid": put_mid})
    return pd.DataFrame(rows)


def test_delta_25_picks_the_quarter_delta_not_the_deepest_itm():
    bars = _flat_bars()
    # 130-strike put on a 100 stock: delta ~ -1.0. The old sort chose it.
    chains = _chains(bars, [(90.0, 0.25), (98.0, 0.45), (130.0, 0.98)])
    s = compile_source(CSP)
    m = run_options_backtest(s, bars, chains)
    sells = m["orders"][m["orders"]["action"] == "sell_put"]
    assert len(sells) > 0
    assert set(sells["strike"]) == {90.0}


def test_csp_program_survives_assignment_and_keeps_cycling():
    # Price collapses mid-test so the short put finishes ITM and assigns.
    bars = _flat_bars(n=90)
    bars.iloc[30:, :] = bars.iloc[30:, :] * 0.80   # -20% gap, stays down
    chains = _chains(bars, [(92.0, 0.25)], put_mid=0.60)
    s = compile_source(CSP)
    m = run_options_backtest(s, bars, chains)
    acts = m["orders"]["action"].tolist()
    assert "assigned" in acts
    i = acts.index("assigned")
    rest = acts[i + 1:]
    # The shares leave at the next close and the puts resume after.
    assert "sell_stock" in rest
    assert "sell_put" in rest[rest.index("sell_stock"):]
    # And the ledger is flat on shares at the end.
    assert m["final_shares"] == 0
