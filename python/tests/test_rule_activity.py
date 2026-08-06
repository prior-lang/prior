"""Whole-run fire counts, and the labeled report.

The bug class these guard: a rule that never fires and a rule that
fires and changes nothing produce identical equity curves, so the
report itself is the only place a dead rule can become visible. And a
bare Sharpe or a silent zero-cost default lets a backtest tell the
truth about lookahead while lying about everything else.
"""

import numpy as np
import pandas as pd

from prior_lang import compile_source
from prior_lang.backtest import run_backtest
from prior_lang.trace import fire_counts

TMPL = (
    'strategy "T"\n\nuniverse $TEST\ntimeframe 1d\n\n{when}\n'
    "  buy [5% portfolio]\n\nsell when [rsi] > 65\n  or [stop 4%]\n"
)


def _bars(n=600, seed=7):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.02, n)))
    open_ = np.empty(n)
    open_[0] = close[0]
    open_[1:] = close[:-1]  # every bar opens at the prior close: no gaps
    return pd.DataFrame({
        "open": open_,
        "high": close * (1 + np.abs(rng.normal(0, 0.01, n))),
        "low": close * (1 - np.abs(rng.normal(0, 0.01, n))),
        "close": close,
        "volume": rng.integers(1_000_000, 5_000_000, n).astype(float),
    }, index=pd.date_range("2022-01-03", periods=n, freq="B"))


def test_dead_rule_shows_zero_of_n():
    """A gap condition on gapless data: 0 of N, stated, not silent."""
    s = compile_source(TMPL.format(when="when [gap_down 8%]"))
    rows = fire_counts(s, _bars())
    entry = [r for r in rows if r["where"] == "when"]
    assert len(entry) == 1
    assert entry[0]["true"] == 0
    assert entry[0]["bars"] == 600


def test_live_rule_counts_and_exit_is_walked_too():
    s = compile_source(TMPL.format(when="when [rsi] < 40"))
    rows = fire_counts(s, _bars())
    entry = next(r for r in rows if r["where"] == "when")
    assert entry["true"] > 0
    # The rsi > 65 exit condition is a pure series and gets a count;
    # the [stop 4%] lives on the exit spec, not in conditions, so no
    # bogus row appears for it.
    exits = [r for r in rows if r["where"] == "sell when"]
    assert len(exits) == 1 and exits[0]["true"] > 0


def test_grouped_and_sequenced_conditions_do_not_break_it():
    s = compile_source(TMPL.format(
        when="when ([rsi] < 40 or [stoch] < 30) and price above [sma 50]"))
    rows = fire_counts(s, _bars())
    assert any(r["where"] == "when" for r in rows)
    s2 = compile_source(TMPL.format(
        when="when [new_low 20] then within 5 bars [rsi] crosses above 35"))
    assert isinstance(fire_counts(s2, _bars()), list)  # never raises


def test_report_states_its_conventions():
    s = compile_source(TMPL.format(when="when [rsi] < 40"))
    m0 = run_backtest(s, _bars(), capital=100_000.0)
    assert m0["cost_bps"] == 0.0                # the default is visible
    assert "sqrt(252)" in m0["sharpe_note"]     # the convention is named
    m1 = run_backtest(s, _bars(), capital=100_000.0, cost_bps=25.0)
    assert m1["cost_bps"] == 25.0
    # Costs must actually bite, or the printed number is decoration.
    assert m1["total_return_pct"] <= m0["total_return_pct"]
