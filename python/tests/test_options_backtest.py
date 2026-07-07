"""Options slice 3c: the BYO-chains reference backtester.

The OSS toolchain never bundles chain data; it runs on chains the user
brings. These tests bring tiny synthetic chains and check the cash
ledger to the dollar.
"""

import math
import subprocess
import sys

import pytest

import prior_lang
from prior_lang.options_backtest import load_chains, run_options_backtest

pd = pytest.importorskip("pandas")


def _underlying(days, px=100.0):
    closes = [px] * len(days) if not hasattr(px, "__len__") else list(px)
    return pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": 0},
        index=days,
    )


def _chains(days, expiry, px_series=None):
    rows = []
    for i, d in enumerate(days):
        dte = (expiry - d).days
        if dte < 0:
            continue
        px = 100.0 if px_series is None else float(px_series[i])
        for strike in range(80, 121, 5):
            for right in ("P", "C"):
                if right == "P":
                    delta = max(1.0, min(99.0, 50.0 - (px - strike) * 2.5))
                    intrinsic = max(0.0, strike - px)
                else:
                    delta = max(1.0, min(99.0, 50.0 - (strike - px) * 2.5))
                    intrinsic = max(0.0, px - strike)
                tv = 0.02 * delta * (dte / 40.0)
                rows.append({"date": d, "expiry": expiry, "strike": float(strike),
                             "right": right, "delta": delta, "mid": round(intrinsic + tv, 4)})
    return pd.DataFrame(rows)


def test_put_spread_profit_take_to_the_dollar():
    days = pd.date_range("2026-01-05", periods=45, freq="D")
    df = _underlying(days)
    strategy = prior_lang.compile_source(
        "universe $SPY\nwhen price above 1\n  write [put_spread delta=25 width=5 dte=30]\n"
        "close at [profit 50%]\nrisk [contracts 2]\n"
    )
    res = run_options_backtest(strategy, df, _chains(days, days[40]))
    assert res["cycles"] == 1
    assert res["premium_collected"] == 50.0     # 0.25 net credit x 100 x 2
    assert res["net_pnl"] == 25.0               # closed at 50% of the credit
    assert res["win_rate_pct"] == 100.0
    assert res["final_shares"] == 0


def test_csp_assignment_carries_stock():
    # Underlying at 100, then drops to 85 before expiry: the ~25-delta
    # put (strike 90) finishes ITM -> assigned, shares held at the end.
    days = pd.date_range("2026-01-05", periods=45, freq="D")
    closes = [100.0] * 35 + [85.0] * 10
    df = _underlying(days, closes)
    # Chains priced off a flat 100 so the entry picks strike 90; the
    # assignment decision uses the real underlying close.
    strategy = prior_lang.compile_source(
        "universe $SPY\nwhen price above 1\n  write [csp delta=25 dte=30]\n"
        "close at [loss 900%]\n"
    )
    res = run_options_backtest(strategy, df, _chains(days, days[40]))
    assert res["final_shares"] == 100           # assigned 1 contract
    # Paid strike 90 for stock now marked at 85: stock leg lost money,
    # premium cushions it.
    assert res["stock_pnl"] == pytest.approx((85.0 - 90.0) * 100, abs=1e-6)
    assert res["option_pnl"] > 0                # kept the premium


def test_chains_loader_validates_columns(tmp_path):
    bad = tmp_path / "chains.csv"
    bad.write_text("date,strike\n2026-01-05,100\n")
    with pytest.raises(SystemExit, match="missing column"):
        load_chains(str(bad))
    with pytest.raises(SystemExit, match="no such chains file"):
        load_chains(str(tmp_path / "nope.csv"))


def test_chains_loader_normalizes(tmp_path):
    f = tmp_path / "chains.csv"
    f.write_text(
        "date,expiry,strike,right,delta,mid\n"
        "2026-01-05,2026-02-14,90,put,-0.25,1.5\n"
        "2026-01-05,2026-02-14,110,CALL,0.25,1.2\n"
    )
    ch = load_chains(str(f))
    assert sorted(ch["right"]) == ["C", "P"]
    assert (ch["delta"] > 0).all()              # signed deltas -> absolute


def test_cli_refusal_mentions_chains(tmp_path):
    strat = tmp_path / "w.prior"
    strat.write_text(
        "universe $F\nwheel [delta=25 dte=45]\nclose at [profit 50%]\n"
    )
    data = tmp_path / "bars.csv"
    days = pd.date_range("2026-01-05", periods=10, freq="B")
    pd.DataFrame({"date": days, "close": 12.0, "volume": 0}).to_csv(data, index=False)
    proc = subprocess.run(
        [sys.executable, "-m", "prior_lang.cli", "backtest", str(strat), "--data", str(data)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 1
    assert "--chains" in proc.stderr
    assert "AutoQuant" in proc.stderr
