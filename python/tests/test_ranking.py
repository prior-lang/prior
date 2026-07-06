"""v0.4 ranking: golden-panel tests.

A tiny hand-built panel where every rebalance's ranks are verifiable on
paper: momentum ordering, the tie case (alphabetical), NaN-warmup
ineligibility, where-filter exclusion, shortfall-to-cash, weight caps,
and determinism. Plus parse/roundtrip/explain coverage for the syntax.
"""

import math

import pytest

import prior_lang
from prior_lang import strategy_to_source
from prior_lang.codegen import compile_strategy

pd = pytest.importorskip("pandas")
import numpy as np  # noqa: E402


def _panel(slopes: dict, n=60, start="2026-01-01"):
    """Linear price paths: higher slope = stronger momentum, vol ~ 0."""
    dates = pd.date_range(start, periods=n, freq="B")
    out = {}
    for t, slope in slopes.items():
        closes = pd.Series(100 + slope * np.arange(n, dtype=float), index=dates)
        out[t] = pd.DataFrame({
            "open": closes, "high": closes * 1.001, "low": closes * 0.999,
            "close": closes, "volume": 1_000_000,
        })
    return out


def _weights(src: str, panel):
    strategy = prior_lang.compile_source(src)
    namespace = {"pd": pd, "np": np, "math": math}
    exec(compile_strategy(strategy), namespace)
    return namespace["generate_weights"](panel)


TOP2 = (
    "universe $AAA $BBB $CCC $DDD\n"
    "rebalance monthly\n"
    "hold top 2 by [momentum 20]\n"
)


def test_top_n_picks_strongest_and_holds_between_rebalances():
    panel = _panel({"AAA": 1.0, "BBB": 0.5, "CCC": 0.1, "DDD": -0.5})
    w = _weights(TOP2, panel)
    last = w.iloc[-1]
    assert last["AAA"] == pytest.approx(0.5)
    assert last["BBB"] == pytest.approx(0.5)
    assert last["CCC"] == 0.0 and last["DDD"] == 0.0
    # Held between rebalances: weights constant after the first rebalance
    post = w[(w.sum(axis=1) > 0)]
    assert (post["AAA"] == 0.5).all()


def test_warmup_is_ineligible_and_cash():
    panel = _panel({"AAA": 1.0, "BBB": 0.5, "CCC": 0.1, "DDD": -0.5})
    w = _weights(TOP2, panel)
    # momentum 20 is NaN for the first 20 bars → first month-end rebalance
    # (bar ~21) may qualify, but bar 0..19 rows are all cash
    assert (w.iloc[:19].sum(axis=1) == 0).all()


def test_tie_breaks_alphabetically():
    panel = _panel({"ZZZ": 1.0, "AAA": 1.0, "MMM": 0.1})
    src = TOP2.replace("$AAA $BBB $CCC $DDD", "$ZZZ $AAA $MMM").replace("top 2", "top 1")
    w = _weights(src, panel)
    last = w.iloc[-1]
    assert last["AAA"] == pytest.approx(1.0)   # AAA beats ZZZ on the tie
    assert last["ZZZ"] == 0.0


def test_bottom_selects_lowest():
    panel = _panel({"AAA": 1.0, "BBB": 0.5, "CCC": 0.1, "DDD": -0.5})
    w = _weights(TOP2.replace("top 2", "bottom 1"), panel)
    assert w.iloc[-1]["DDD"] == pytest.approx(1.0)


def test_where_filter_excludes_and_shortfall_goes_to_cash():
    # Filter demands price above 200 — only AAA's path (100 + 3.0*t) gets
    # there inside 60 bars, so a top-2 hold ends up holding just AAA at 50%
    # equal weight of a 2-slot book... no: equal weight over CHOSEN names →
    # 1 name → 100%. Shortfall keeps count at what qualifies.
    panel = _panel({"AAA": 3.0, "BBB": 0.5, "CCC": 0.1, "DDD": -0.5})
    src = (
        "universe $AAA $BBB $CCC $DDD\n"
        "rebalance monthly\n"
        "hold top 2 by [momentum 20]\n"
        "  where price above 200\n"
    )
    w = _weights(src, panel)
    last = w.iloc[-1]
    assert last["AAA"] == pytest.approx(1.0)
    assert last[["BBB", "CCC", "DDD"]].sum() == 0.0


def test_max_position_cap_redistributes_then_cashes():
    panel = _panel({"AAA": 1.0, "BBB": 0.5, "CCC": 0.1})
    src = (
        "universe $AAA $BBB $CCC\n"
        "rebalance monthly\n"
        "hold top 2 by [momentum 20]\n"
        "risk [max_position 30%]\n"
    )
    w = _weights(src, panel)
    last = w.iloc[-1]
    # Equal 50/50 capped at 30 each; excess can't redistribute (both capped)
    assert last["AAA"] == pytest.approx(0.30)
    assert last["BBB"] == pytest.approx(0.30)
    assert last.sum() == pytest.approx(0.60)  # 40% cash — documented behavior


def test_weighted_by_metric():
    panel = _panel({"AAA": 1.0, "BBB": 0.5, "CCC": 0.1})
    src = (
        "universe $AAA $BBB $CCC\n"
        "rebalance monthly\n"
        "hold top 2 by [momentum 20]\n"
        "  weighted by [momentum 20]\n"
    )
    w = _weights(src, panel)
    last = w.iloc[-1]
    assert last["AAA"] > last["BBB"] > 0
    assert last.sum() == pytest.approx(1.0)


def test_determinism():
    panel = _panel({"AAA": 1.0, "BBB": 0.5, "CCC": 0.1, "DDD": -0.5})
    w1 = _weights(TOP2, panel)
    w2 = _weights(TOP2, panel)
    assert w1.equals(w2)


# ── Syntax / interchange / tooling coverage ────────────────────────

def test_hold_json_shape_and_roundtrip():
    src = (
        'strategy "Twelve Minus One"\n'
        "universe [sp_top_30]\n"
        "rebalance monthly\n"
        "hold top 5 by [momentum 252 skip=21]\n"
        "  where price above [sma 200]\n"
        "  weighted by [inverse_volatility 20]\n"
        "risk [max_position 25%]\n"
    )
    s = prior_lang.compile_source(src)
    assert s["rebalance"] == "monthly"
    r = s["ranking"]
    assert r["select"] == "top" and r["count"] == 5
    assert r["metric"] == {"name": "momentum", "params": {"period": 252, "skip": 21}}
    assert r["where"]["conditions"][0]["condition"] == "price_above_sma"
    assert r["weighting"]["method"] == "by_metric"
    assert s["risk"] == {"max_position_pct": 0.25}
    assert prior_lang.compile_source(strategy_to_source(s)) == s


def test_hold_excludes_rules_statements():
    with pytest.raises(prior_lang.PriorError, match="not both"):
        prior_lang.compile_source(
            "universe [semis]\nrebalance monthly\nhold top 3 by [momentum 63]\n"
            "when [rsi] < 30\n  buy [5% portfolio]\nsell when [after 5 bars]\n"
        )


def test_rebalance_requires_hold():
    with pytest.raises(prior_lang.PriorError, match="ranking"):
        prior_lang.compile_source(
            "universe [semis]\nrebalance weekly\nwhen [rsi] < 30\n  buy [5% portfolio]\nsell when [after 5 bars]\n"
        )


def test_bad_metric_did_you_mean():
    with pytest.raises(prior_lang.PriorError) as e:
        prior_lang.compile_source(
            "universe [semis]\nhold top 3 by [momentam 63]\n"
        )
    assert "momentum" in ((e.value.suggestion or "") + e.value.message)


def test_operand_tag_as_metric():
    s = prior_lang.compile_source("universe [semis]\nhold top 3 by [rsi]\n")
    assert s["ranking"]["metric"]["name"] == "rsi"


def test_explain_ranking():
    from prior_lang.explain import explain_strategy
    s = prior_lang.compile_source(
        "universe [etf_sectors]\nrebalance monthly\nhold top 3 by [momentum 126]\n"
    )
    text = explain_strategy(s)
    assert "Each month" in text
    assert "126-bar momentum" in text
    assert "no longer qualify are sold" in text
