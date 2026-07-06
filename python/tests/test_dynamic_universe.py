"""Dynamic universes: `universe [top_volume 50]`.

Membership is computed from the data at run time — top N by trailing
average dollar volume — recomputed on the first bar of each month using
values as of the PRIOR bar. The golden test is the no-repaint check: a
ticker whose volume explodes mid-month must NOT enter the universe until
the next monthly recompute.
"""

import pytest

import prior_lang
from prior_lang import strategy_to_source

SRC = (
    "universe [top_volume 5]\n"
    "when [rsi] < 30\n  buy [10% portfolio]\n"
    "sell when [after 10 bars]\n"
)


def test_dynamic_universe_json_and_roundtrip():
    s = prior_lang.compile_source(SRC)
    assert s["universe"] == {"type": "dynamic", "key": "top_volume",
                             "params": {"count": 5, "period": 20}}
    assert prior_lang.compile_source(strategy_to_source(s)) == s
    # fmt elides the default period
    assert "universe [top_volume 5]" in strategy_to_source(s)


def test_custom_period_survives_roundtrip():
    src = SRC.replace("[top_volume 5]", "[top_volume 5 period=60]")
    s = prior_lang.compile_source(src)
    assert s["universe"]["params"]["period"] == 60
    assert "period=60" in strategy_to_source(s)
    assert prior_lang.compile_source(strategy_to_source(s)) == s


def test_ranking_strategy_accepts_dynamic_universe():
    s = prior_lang.compile_source(
        "universe [top_volume 10]\nrebalance monthly\nhold top 3 by [momentum 63]\n"
    )
    assert s["universe"]["type"] == "dynamic"
    assert prior_lang.compile_source(strategy_to_source(s)) == s


def test_count_must_be_sane():
    with pytest.raises(prior_lang.PriorError, match="between 1 and 500"):
        prior_lang.compile_source(SRC.replace("[top_volume 5]", "[top_volume 0]"))
    with pytest.raises(prior_lang.PriorError, match="between 1 and 500"):
        prior_lang.compile_source(SRC.replace("[top_volume 5]", "[top_volume 5.5]"))


def test_period_must_be_sane():
    with pytest.raises(prior_lang.PriorError, match="between 2 and 252"):
        prior_lang.compile_source(SRC.replace("[top_volume 5]", "[top_volume 5 period=1]"))


def test_explain_mentions_closed_bars():
    from prior_lang.explain import explain_strategy
    text = explain_strategy(prior_lang.compile_source(SRC))
    assert "highest-dollar-volume" in text
    assert "closed" in text


def _panel(pd):
    """Two tickers, Jan–Feb 2026. A dominates dollar volume all of
    January; B's volume explodes on Jan 20 but may only enter at the
    February recompute."""
    days = pd.date_range("2026-01-05", periods=40, freq="B")
    rows = []
    for i, d in enumerate(days):
        rows.append({"date": d, "ticker": "A", "close": 100.0, "volume": 1_000})
        rows.append({"date": d, "ticker": "B", "close": 100.0,
                     "volume": 1_000_000 if d >= pd.Timestamp("2026-01-20") else 10})
    return pd.DataFrame(rows).set_index("date")


def test_golden_membership_no_midmonth_repaint():
    pd = pytest.importorskip("pandas")
    from prior_lang.backtest import dynamic_membership

    src = SRC.replace("[top_volume 5]", "[top_volume 1 period=2]")
    member = dynamic_membership(prior_lang.compile_source(src), _panel(pd))

    # Warmup: no members until the trailing average exists (2 bars + shift).
    assert not member.iloc[0].any() and not member.iloc[1].any()
    # A is the member for ALL of January — including every bar after B's
    # Jan 20 volume explosion. Membership may not repaint mid-month.
    jan = member[member.index.to_period("M") == "2026-01"]
    assert jan["A"].iloc[2:].all()
    assert not jan["B"].any()
    # February's first bar recomputes from January data: B takes the slot.
    feb = member[member.index.to_period("M") == "2026-02"]
    assert feb["B"].all()
    assert not feb["A"].any()


def test_universe_backtest_masks_signals():
    pd = pytest.importorskip("pandas")
    from prior_lang.backtest import run_universe_backtest

    # Always-in entry so any trading at all proves membership gating.
    src = (
        "universe [top_volume 1 period=2]\n"
        "when price above 1\n  buy [10% portfolio]\n"
        "sell when [after 100 bars]\n"
    )
    res = run_universe_backtest(prior_lang.compile_source(src), _panel(pd))
    by_ticker = {r["ticker"]: r for r in res["per_ticker"]}
    # Both tickers held membership at some point, so both run — but each
    # only trades inside its own windows.
    assert set(by_ticker) == {"A", "B"}
    assert all(r["trades"] >= 1 for r in by_ticker.values())


def test_single_ticker_file_refused():
    pd = pytest.importorskip("pandas")
    import subprocess, sys, tempfile, os, json

    days = pd.date_range("2026-01-05", periods=30, freq="B")
    df = pd.DataFrame({"date": days, "close": 100.0, "volume": 1000})
    with tempfile.TemporaryDirectory() as tmp:
        data = os.path.join(tmp, "one.csv")
        df.to_csv(data, index=False)
        strat = os.path.join(tmp, "s.prior")
        with open(strat, "w") as f:
            f.write(SRC)
        proc = subprocess.run(
            [sys.executable, "-m", "prior_lang.cli", "backtest", strat, "--data", data],
            capture_output=True, text=True,
        )
        assert proc.returncode != 0
        assert "multi-ticker" in proc.stderr
