"""The trade log (`prior backtest --trades`): the toolchain's answer to
logging. compile_strategy(trace=True) emits generate_signals_traced,
which records entries, and — because exit precedence is deterministic —
WHICH exit branch fired. The signals themselves are identical to the
untraced build.

Leak-note (S7): everything here prints values from the caller's own
data frame; the OSS toolchain has no path to licensed data.
"""

import math
import subprocess
import sys

import pytest

import prior_lang
from prior_lang.codegen import compile_strategy

pd = pytest.importorskip("pandas")
import numpy as np  # noqa: E402


def _run_traced(src, closes):
    strategy = prior_lang.compile_source(src)
    namespace = {"pd": pd, "np": np, "math": math}
    exec(compile_strategy(strategy, trace=True), namespace)
    days = pd.date_range("2026-01-05", periods=len(closes), freq="B")
    df = pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": 0},
        index=days,
    )
    return namespace, df


SRC_STOP_TARGET = (
    "universe $T\nwhen [rsi 2] < 10\n  buy [10% portfolio]\n"
    "sell when [stop 3%]\n  or [target 6%]\n  or [after 5 bars]\n"
)


def test_exit_reasons_stop_and_time():
    closes = [100] * 10 + [90, 88, 86, 92, 96, 100, 104, 108, 112, 100] + [100] * 20
    ns, df = _run_traced(SRC_STOP_TARGET, closes)
    sig, events = ns["generate_signals_traced"](df)
    reasons = [e["reason"] for e in events if e["event"] == "exit"]
    assert reasons[0] == "stop"          # 90 -> 86 is -4.4%, through the 3% stop
    assert "time" in reasons or "target" in reasons
    # Traced signals are identical to the untraced contract
    assert (ns["generate_signals"](df) == sig).all()


def test_trade_log_rows():
    from prior_lang.backtest import trade_log

    closes = [100] * 10 + [90, 88, 86, 92, 96, 100, 104, 108, 112, 100] + [100] * 20
    strategy = prior_lang.compile_source(SRC_STOP_TARGET)
    days = pd.date_range("2026-01-05", periods=len(closes), freq="B")
    df = pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": 0},
        index=days,
    )
    trades = trade_log(strategy, df)
    assert trades, "expected at least one trade"
    first = trades[0]
    assert first["direction"] == "long"
    assert first["exit_reason"] == "stop"
    assert first["return_pct"] < 0
    assert first["bars_held"] == first_bars_held(days, first)
    assert set(first) >= {"entry_date", "exit_date", "entry_price", "exit_price",
                          "bars_held", "return_pct", "exit_reason"}


def first_bars_held(days, trade):
    i0 = list(days.astype(str)).index(trade["entry_date"])
    i1 = list(days.astype(str)).index(trade["exit_date"])
    return i1 - i0


def test_mixed_trades_carry_direction():
    src = (
        "universe $T\nwhen price above 100\n  buy [10% portfolio]\n"
        "when price below 90\n  short [10% portfolio]\n"
        "sell when [after 4 bars]\ncover when [after 4 bars]\n"
    )
    closes = [99, 103, 104, 107, 108, 106, 89, 88, 84, 83, 82, 81]
    ns, df = _run_traced(src, closes)
    _sig, events = ns["generate_signals_traced"](df)
    entries = [e for e in events if e["event"] == "entry"]
    assert [e["dir"] for e in entries] == [1, -1]


def test_open_trade_reported_as_open():
    from prior_lang.backtest import trade_log

    src = "universe $T\nwhen price above 100\n  buy [10% portfolio]\nsell when [after 50 bars]\n"
    closes = [99] * 5 + [105] * 10  # enters, never exits inside the data
    strategy = prior_lang.compile_source(src)
    days = pd.date_range("2026-01-05", periods=len(closes), freq="B")
    df = pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": 0},
        index=days,
    )
    trades = trade_log(strategy, df)
    assert len(trades) == 1
    assert trades[0]["exit_reason"] == "open"


def test_ranking_trace_refused():
    s = prior_lang.compile_source(
        "universe [etf_sectors]\nrebalance monthly\nhold top 3 by [momentum 126]\n"
    )
    with pytest.raises(prior_lang.PriorError, match="rebalance"):
        compile_strategy(s, trace=True)


def test_cli_trades_flag():
    src = "universe $T\nwhen price above 105\n  buy [10% portfolio]\nsell when [after 5 bars]\n"
    import os, tempfile
    closes = np.array([100.0] * 10 + [106.0] * 10 + [100.0] * 10 + [106.0] * 30)
    days = pd.date_range("2026-01-05", periods=60, freq="B")
    with tempfile.TemporaryDirectory() as tmp:
        data = os.path.join(tmp, "bars.csv")
        pd.DataFrame({"date": days, "close": closes, "volume": 1000}).to_csv(data, index=False)
        strat = os.path.join(tmp, "s.prior")
        with open(strat, "w") as f:
            f.write(src)
        proc = subprocess.run(
            [sys.executable, "-m", "prior_lang.cli", "backtest", strat,
             "--data", data, "--trades"],
            capture_output=True, text=True,
        )
        assert proc.returncode == 0, proc.stderr
        assert "EXIT" in proc.stdout and "time" in proc.stdout


def test_date_range_slices_the_backtest(tmp_path):
    import os
    closes = np.array([100.0] * 10 + [106.0] * 10 + [100.0] * 10 + [106.0] * 30)
    days = pd.date_range("2026-01-05", periods=60, freq="B")
    data = os.path.join(tmp_path, "bars.csv")
    pd.DataFrame({"date": days, "close": closes, "volume": 1000}).to_csv(data, index=False)
    strat = os.path.join(tmp_path, "s.prior")
    with open(strat, "w") as f:
        f.write("universe $T\nwhen price above 105\n  buy [10% portfolio]\nsell when [after 5 bars]\n")

    full = subprocess.run(
        [sys.executable, "-m", "prior_lang.cli", "backtest", strat, "--data", data],
        capture_output=True, text=True)
    sliced = subprocess.run(
        [sys.executable, "-m", "prior_lang.cli", "backtest", strat, "--data", data,
         "--from", "2026-02-16", "--to", "2026-03-16"],
        capture_output=True, text=True)
    assert sliced.returncode == 0, sliced.stderr
    assert "date range: 2026-02-16 to 2026-03-16" in sliced.stdout
    assert "21 of 60 rows" in sliced.stdout
    assert full.stdout != sliced.stdout  # different window, different metrics

    empty = subprocess.run(
        [sys.executable, "-m", "prior_lang.cli", "backtest", strat, "--data", data,
         "--from", "2030-01-01"],
        capture_output=True, text=True)
    assert empty.returncode == 1
    assert "no bars between" in empty.stderr
