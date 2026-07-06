"""prior trace: per-bar condition verdicts (the "why didn't it fire"
debugger). Window hard-capped at TRACE_MAX_BARS by design — the output
contract must never be usable as a bar-series dump (S7)."""

import subprocess
import sys

import pytest

import prior_lang
from prior_lang.trace import TRACE_MAX_BARS, trace_report

pd = pytest.importorskip("pandas")

SRC = (
    "universe $T\nwhen [rsi 2] < 10\n  buy [10% portfolio]\n"
    "sell when [rsi 2] > 90\n  or [after 5 bars]\n"
)


def _df(closes):
    days = pd.date_range("2026-01-05", periods=len(closes), freq="B")
    return pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": 0},
        index=days,
    )


def test_verdicts_flip_on_the_dip_bar():
    closes = [100] * 10 + [90, 85, 80] + [100] * 10
    df = _df(closes)
    strategy = prior_lang.compile_source(SRC)

    # On the crash bar RSI(2) is pinned low: the entry condition is true.
    on_dip = trace_report(strategy, df, date=str(df.index[12].date()))
    [d] = on_dip["dates"]
    assert d["rules"][0]["conditions"][0]["verdict"] is True
    # Ten bars earlier, flat tape: it is false.
    before = trace_report(strategy, df, date=str(df.index[5].date()))
    [d0] = before["dates"]
    assert d0["rules"][0]["conditions"][0]["verdict"] is False


def test_signal_state_reported():
    closes = [100] * 10 + [90, 85, 80] + [100] * 10
    strategy = prior_lang.compile_source(SRC)
    df = _df(closes)
    rep = trace_report(strategy, df, date=str(df.index[13].date()))
    assert rep["dates"][0]["signal"] == 1.0  # in the position the dip opened


def test_window_capped_at_max_bars():
    closes = [100.0] * 40
    strategy = prior_lang.compile_source(SRC)
    rep = trace_report(strategy, _df(closes), last=50)
    assert TRACE_MAX_BARS == 10
    assert len(rep["dates"]) == TRACE_MAX_BARS


def test_ranking_refused():
    s = prior_lang.compile_source(
        "universe [etf_sectors]\nrebalance monthly\nhold top 3 by [momentum 126]\n"
    )
    with pytest.raises(prior_lang.PriorError, match="rank"):
        trace_report(s, _df([100.0] * 30))


def test_cli_trace_smoke():
    import os, tempfile
    closes = [100] * 10 + [90, 85, 80] + [100] * 10
    df = _df(closes).reset_index().rename(columns={"index": "date"})
    with tempfile.TemporaryDirectory() as tmp:
        data = os.path.join(tmp, "bars.csv")
        df.to_csv(data, index=False)
        strat = os.path.join(tmp, "s.prior")
        with open(strat, "w") as f:
            f.write(SRC)
        proc = subprocess.run(
            [sys.executable, "-m", "prior_lang.cli", "trace", strat,
             "--data", data, "--date", "2026-01-21", "--last", "2"],
            capture_output=True, text=True,
        )
        assert proc.returncode == 0, proc.stderr
        assert "✓" in proc.stdout and "✗" in proc.stdout
        assert "RSI" in proc.stdout or "rsi" in proc.stdout
