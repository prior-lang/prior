"""Portfolio sleeves: multiple strategy blocks composed by a portfolio
block into one combined curve.

The one assumption a combined curve cannot avoid making — when sleeves
true up — is mandatory in the grammar, never defaulted. Sleeves compose
as return streams; costs hit true-up turnover; overlap and correlation
are reported, never assumed away.
"""

import json

import numpy as np
import pandas as pd
import pytest

from prior_lang import compile_source, format_source
from prior_lang.backtest import run_portfolio_backtest, _rebalance_dates
from prior_lang.canonical import strategy_digest
from prior_lang.decompile import strategy_to_source
from prior_lang.errors import PriorError
from prior_lang.explain import explain_strategy

S_A = ('strategy "A"\n\nuniverse $AAA\ntimeframe 1d\n\n'
       'when [rsi] < 30\n  buy [5% portfolio]\n\nsell when [after 5 bars]\n')
S_B = ('strategy "B"\n\nuniverse $BBB\ntimeframe 1d\n\n'
       'when [down_days 2]\n  buy [5% portfolio]\n\nsell when [after 5 bars]\n')


def _book(rebalance="never", w=(60, 40)):
    return (f'portfolio "Book"\n  sleeve {w[0]}% "A"\n  sleeve {w[1]}% "B"\n'
            f'  rebalance {rebalance}\n\n{S_A}\n{S_B}')


def _bars(ticker, rets, start="2023-01-02"):
    """Deterministic OHLCV for one ticker from a list of daily returns."""
    close = 100 * np.cumprod(1 + np.asarray(rets))
    idx = pd.date_range(start, periods=len(close), freq="B")
    return pd.DataFrame({
        "ticker": ticker,
        "open": close, "high": close * 1.01, "low": close * 0.99,
        "close": close, "volume": 1e6,
    }, index=idx)


def _always_on_doc(rebalance):
    """Two always-in sleeves (rsi has no data to refuse; use price > 0
    style via down_days 0? Simplest honest trick: entry fires bar 2 and
    the exit never does, so each sleeve is long from bar 3 on)."""
    src = (f'portfolio "Book"\n  sleeve 60% "A"\n  sleeve 40% "B"\n'
           f'  rebalance {rebalance}\n\n'
           'strategy "A"\n\nuniverse $AAA\ntimeframe 1d\n\n'
           'when price above 1\n  buy [5% portfolio]\n\nsell when price below 1 or [after 500 bars]\n\n'
           'strategy "B"\n\nuniverse $BBB\ntimeframe 1d\n\n'
           'when price above 1\n  buy [5% portfolio]\n\nsell when price below 1 or [after 500 bars]\n')
    return compile_source(src)


def test_drift_book_is_weighted_terminal_growth():
    """rebalance never: the book's terminal value equals the weighted
    sum of each sleeve's own compounded growth, exactly."""
    n = 60
    ra = [0.01] * n          # steady riser
    rb = [-0.002] * n        # steady faller
    df = pd.concat([_bars("AAA", ra), _bars("BBB", rb)])
    doc = _always_on_doc("never")
    res = run_portfolio_backtest(doc, df)
    eq = res["equity"]
    # Sleeves are flat for the first 2 bars (signal shifts one bar), so
    # compare against each sleeve's own equity path rather than raw rets.
    from prior_lang.backtest import run_backtest
    sub_a = run_backtest(doc["portfolio"]["sleeves"][0]["strategy"],
                         _bars("AAA", ra).drop(columns=["ticker"]))
    sub_b = run_backtest(doc["portfolio"]["sleeves"][1]["strategy"],
                         _bars("BBB", rb).drop(columns=["ticker"]))
    expected = 0.6 * float(sub_a["equity"].iloc[-1]) + 0.4 * float(sub_b["equity"].iloc[-1])
    assert abs(float(eq.iloc[-1]) - expected) < 1e-9
    assert res["rebalances"] == 0


def test_monthly_trueup_differs_from_drift_and_charges_costs():
    n = 130  # ~6 months of business days
    rng = np.random.default_rng(7)
    ra = list(rng.normal(0.004, 0.01, n))
    rb = list(rng.normal(-0.001, 0.01, n))
    df = pd.concat([_bars("AAA", ra), _bars("BBB", rb)])
    drift = run_portfolio_backtest(_always_on_doc("never"), df)
    monthly = run_portfolio_backtest(_always_on_doc("monthly"), df)
    assert monthly["rebalances"] > 3
    assert drift["total_return_pct"] != monthly["total_return_pct"]
    # With a diverging winner, drift lets the winner run: drift > monthly.
    assert drift["total_return_pct"] > monthly["total_return_pct"]
    # Costs on true-up turnover only: a costed monthly run returns less
    # than the free one, and the free drift run is unaffected by costs
    # (no position changes after entry, no true-ups).
    monthly_c = run_portfolio_backtest(_always_on_doc("monthly"), df, cost_bps=50)
    assert monthly_c["total_return_pct"] < monthly["total_return_pct"]


def test_rebalance_calendar_boundaries():
    idx = pd.date_range("2023-01-02", periods=70, freq="B")
    dates = _rebalance_dates(idx, "monthly")
    # last business day of each month in the window is a true-up date
    assert pd.Timestamp("2023-01-31") in dates
    assert pd.Timestamp("2023-02-28") in dates
    assert _rebalance_dates(idx, "never") == set()


def test_refusals():
    with pytest.raises(PriorError, match="portfolio block that allocates"):
        compile_source(S_A + "\n" + S_B)
    with pytest.raises(PriorError, match="rebalance policy"):
        compile_source('portfolio "Book"\n  sleeve 60% "A"\n  sleeve 40% "B"\n\n'
                       + S_A + "\n" + S_B)
    with pytest.raises(PriorError, match="sum to 100"):
        compile_source(_book(w=(60, 60)))
    with pytest.raises(PriorError, match="names no strategy block"):
        compile_source('portfolio "Book"\n  sleeve 60% "A"\n  sleeve 40% "Z"\n'
                       '  rebalance never\n\n' + S_A + "\n" + S_B)
    with pytest.raises(PriorError, match="has no sleeve"):
        compile_source(_book() + "\n" + S_B.replace('"B"', '"C"'))
    with pytest.raises(PriorError, match="churn"):
        compile_source(_book(rebalance="daily"))
    with pytest.raises(PriorError, match="one bar clock"):
        compile_source(_book() .replace('strategy "B"\n\nuniverse $BBB\ntimeframe 1d',
                                        'strategy "B"\n\nuniverse $BBB\ntimeframe 1h'))
    with pytest.raises(PriorError, match="one instrument"):
        compile_source(_book().replace("universe $AAA", "universe [mega_tech]"))
    with pytest.raises(PriorError, match="undefined risk"):
        compile_source(
            'portfolio "Book"\n  sleeve 60% "A"\n  sleeve 40% "Vol"\n'
            '  rebalance never\n\n' + S_A + "\n"
            'strategy "Vol"\n\nuniverse $BBB\ntimeframe 1d\n\n'
            'when [quiet 5%]\n  write [strangle dte=21]\n\n'
            'close at [profit 50%]\n')


def test_overlap_reported_including_opposed():
    n = 80
    ra = [0.001] * n
    df = pd.concat([_bars("AAA", ra), _bars("BBB", ra)])
    # Both sleeves on the SAME ticker, one long one short.
    src = ('portfolio "Book"\n  sleeve 50% "L"\n  sleeve 50% "S"\n'
           '  rebalance never\n\n'
           'strategy "L"\n\nuniverse $AAA\ntimeframe 1d\n\n'
           'when price above 1\n  buy [5% portfolio]\n\nsell when price below 1 or [after 500 bars]\n\n'
           'strategy "S"\n\nuniverse $AAA\ntimeframe 1d\n\n'
           'when price above 1\n  short [5% portfolio]\n\ncover when price below 1 or [after 500 bars]\n')
    res = run_portfolio_backtest(compile_source(src), df)
    assert len(res["overlap"]) == 1
    o = res["overlap"][0]
    assert o["ticker"] == "AAA"
    assert o["both_pct"] > 90
    assert o["opposed_pct"] > 90
    assert res["overlap_unavailable"] == []


def test_roundtrip_format_decompile_digest():
    src = _book(rebalance="monthly")
    doc = compile_source(src)
    f1 = format_source(src)
    assert format_source(f1) == f1
    rt = strategy_to_source(doc)
    doc2 = compile_source(rt)
    assert json.dumps(doc, sort_keys=True) == json.dumps(doc2, sort_keys=True)
    assert strategy_digest(doc) == strategy_digest(compile_source(src))


def test_explain_reads_the_book():
    text = explain_strategy(compile_source(_book(rebalance="monthly")))
    assert "book of 2 sleeves" in text.lower()
    assert "true up" in text
    assert "60% in A" in text
    never = explain_strategy(compile_source(_book(rebalance="never")))
    assert "never trued up" in never


def test_min_shared_bars_refused():
    df = pd.concat([_bars("AAA", [0.01] * 20), _bars("BBB", [0.01] * 20)])
    with pytest.raises(PriorError, match="fewer than 40"):
        run_portfolio_backtest(_always_on_doc("never"), df)


def test_weekly_trues_up_more_often_than_monthly():
    n = 130
    rng = np.random.default_rng(11)
    ra = list(rng.normal(0.003, 0.01, n))
    rb = list(rng.normal(-0.001, 0.01, n))
    df = pd.concat([_bars("AAA", ra), _bars("BBB", rb)])
    weekly = run_portfolio_backtest(_always_on_doc("weekly"), df)
    monthly = run_portfolio_backtest(_always_on_doc("monthly"), df)
    assert weekly["rebalances"] > monthly["rebalances"] > 3


def test_three_sleeve_book_and_capital_dollars():
    src = ('portfolio "Three"\n  sleeve 30% "A"\n  sleeve 30% "B"\n'
           '  sleeve 40% "C"\n  rebalance never\n\n'
           + S_A + "\n" + S_B + "\n"
           + S_B.replace('"B"', '"C"').replace("$BBB", "$CCC"))
    doc = compile_source(src)
    n = 90
    df = pd.concat([_bars("AAA", [0.002] * n), _bars("BBB", [0.001] * n),
                    _bars("CCC", [-0.001] * n)])
    res = run_portfolio_backtest(doc, df, capital=10_000)
    assert len(res["sleeves"]) == 3
    assert len(res["correlations"]) == 3   # 3 choose 2
    assert abs(res["final_equity_usd"]
               - 10_000 * float(res["equity"].iloc[-1])) < 0.01
    assert abs(res["net_pnl_usd"]
               - (res["final_equity_usd"] - 10_000)) < 0.01


def test_ranking_sleeve_composes():
    src = ('portfolio "Mixed"\n  sleeve 50% "Picker"\n  sleeve 50% "A"\n'
           '  rebalance monthly\n\n'
           'strategy "Picker"\n\nuniverse $AAA $BBB $CCC\ntimeframe 1d\n\n'
           'hold top 2 by [momentum 20]\nrebalance monthly\n\n' + S_A)
    doc = compile_source(src)
    n = 130
    rng = np.random.default_rng(3)
    df = pd.concat([_bars(t, list(rng.normal(m, 0.01, n)))
                    for t, m in (("AAA", 0.002), ("BBB", 0.001), ("CCC", -0.001))])
    res = run_portfolio_backtest(doc, df)
    kinds = {s["kind"] for s in res["sleeves"]}
    assert kinds == {"ranking", "rules"}
    # The ranking sleeve exposes per-ticker weights, so overlap with the
    # rules sleeve on AAA is measurable (rules sleeve enters on RSI<30,
    # which may or may not fire — overlap list is valid either way).
    assert res["overlap_unavailable"] == []


def test_pair_sleeve_composes_with_leg_overlap():
    src = ('portfolio "PairBook"\n  sleeve 50% "Spread"\n  sleeve 50% "L"\n'
           '  rebalance never\n\n'
           'strategy "Spread"\n\ntimeframe 1d\n\n'
           'when spread($AAA, $BBB) below [sma 20]\n  buy [5% portfolio]\n\n'
           'sell when [after 10 bars]\n\n'
           'strategy "L"\n\nuniverse $AAA\ntimeframe 1d\n\n'
           'when price above 1\n  buy [5% portfolio]\n\n'
           'sell when price below 1 or [after 500 bars]\n')
    doc = compile_source(src)
    n = 120
    rng = np.random.default_rng(5)
    df = pd.concat([_bars("AAA", list(rng.normal(0.001, 0.012, n))),
                    _bars("BBB", list(rng.normal(0.001, 0.012, n)))])
    res = run_portfolio_backtest(doc, df)
    kinds = {s["kind"] for s in res["sleeves"]}
    assert kinds == {"pair", "rules"}
    # If the spread sleeve ever held, its AAA leg overlaps the long sleeve.
    if any(o["ticker"] == "AAA" for o in res["overlap"]):
        o = next(o for o in res["overlap"] if o["ticker"] == "AAA")
        assert 0 < o["both_pct"] <= 100


def test_sleeve_order_changes_digest():
    a = compile_source(_book(rebalance="never", w=(60, 40)))
    b = compile_source(
        'portfolio "Book"\n  sleeve 40% "B"\n  sleeve 60% "A"\n'
        '  rebalance never\n\n' + S_A + "\n" + S_B)
    assert strategy_digest(a) != strategy_digest(b)


def test_receipt_binds_document_and_sleeve_digests(tmp_path):
    from prior_lang.receipt import build_receipt
    from prior_lang.parser import parse_source
    src = _book(rebalance="monthly")
    prog = parse_source(src)
    doc = prog.to_json()
    data = tmp_path / "bars.csv"
    data.write_text("date,open,high,low,close,volume\n"
                    "2023-01-02,1,1,1,1,1\n")
    r = build_receipt(program=prog, strategy=doc, data_path=str(data),
                      metrics={"total_return_pct": 1.0}, prior_version="test")
    assert r["strategy"]["direction"] == "portfolio"
    assert r["strategy"]["digest"] == f"sha256:{strategy_digest(doc)}"
    assert len(r["strategy"]["sleeves"]) == 2
    for i, s in enumerate(r["strategy"]["sleeves"]):
        sub = doc["portfolio"]["sleeves"][i]["strategy"]
        assert s["digest"] == f"sha256:{strategy_digest(sub)}"
        assert s["name"] == sub["name"]
