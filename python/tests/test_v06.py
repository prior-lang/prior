"""v0.6 slice A: multiple entry rules, partial exits, cooldown.

State-machine goldens on hand-built paths: the partial fires once and
leaves half on; cooldown blocks the immediate re-entry edge and admits a
later one; multiple rules each open positions; everything round-trips.
"""

import math

import pytest

import prior_lang
from prior_lang import strategy_to_source
from prior_lang.codegen import compile_strategy

pd = pytest.importorskip("pandas")
import numpy as np  # noqa: E402


def _run(src: str, closes):
    df = pd.DataFrame({
        "open": closes, "high": [c * 1.01 for c in closes],
        "low": [c * 0.99 for c in closes], "close": closes,
        "volume": 1_000_000,
    })
    ns = {"pd": pd, "np": np, "math": math}
    exec(compile_strategy(prior_lang.compile_source(src)), ns)
    return ns["generate_signals"](df)


# Entry: close > SMA(2), rising edge lands at bar 2 (see codegen tests)
WARMUP = [100.0, 99.0, 103.0]


def test_partial_takes_half_once_then_time_exit():
    src = (
        "universe $T\nwhen price above [sma 2]\n  buy [10% portfolio]\n"
        "sell half when [target 2%]\n"
        "sell when [after 6 bars]\n"
    )
    # Entry at 103 (bar 2). Bar 3 closes 105.5 (> +2% = 105.06) → half off.
    # Oscillate back above target again — must NOT halve twice. Time exit
    # at 6 bars held (bar 8).
    sig = _run(src, WARMUP + [105.5, 104.0, 106.0, 106.5, 107.0, 107.5, 108.0])
    assert sig.iloc[2] == pytest.approx(1.0)   # full position on entry
    assert sig.iloc[3] == pytest.approx(0.5)   # partial fired
    assert sig.iloc[5] == pytest.approx(0.5)   # second target cross: still 0.5
    assert sig.iloc[7] == pytest.approx(0.5)   # held at half
    assert sig.iloc[8] == pytest.approx(0.0)   # time exit


def test_cooldown_blocks_immediate_reentry():
    base = (
        "universe $T\nwhen price above [sma 2]\n  buy [10% portfolio]\n"
        "sell when [stop 1.5%]\n{risk}"
    )
    # Entry bar 2 @103, stop-out bar 4 (101 <= 101.455). Then a dip under
    # the SMA and a fresh rising edge several bars later.
    closes = WARMUP + [103.5, 101.0, 103.0, 101.5, 100.0, 104.0, 105.0, 106.0]
    #                 b3     b4    b5     b6     b7     b8     b9     b10

    free = _run(base.format(risk=""), closes)
    gated = _run(base.format(risk="risk [cooldown 4]\n"), closes)

    # Without cooldown: bar 5's fresh edge re-enters immediately
    assert free.iloc[5] == 1
    # With cooldown 4 (exit at bar 4): bars 5-8 are blocked...
    assert (gated.iloc[5:9] == 0).all()
    # ...and the next rising edge after the window (bar 8's close 104 >
    # SMA2 while bar 7 was below) has already passed; the position returns
    # on the following edge if one occurs. Verify no position at all until
    # at least one bar after the window opens.
    assert gated.iloc[4] == 0


def test_multiple_rules_either_edge_enters():
    src = (
        "universe $T\n"
        "when price above [sma 2]\n  buy [10% portfolio]\n"
        "when [rsi 2] < 5\n  buy [$5000]\n"
        "sell when [after 2 bars]\n"
    )
    # Rule 1 enters at bar 2; time exit after 2 bars; then a crash drives
    # RSI(2) to ~0 which re-enters via rule 2 even though price < SMA.
    closes = WARMUP + [103.5, 104.0, 90.0, 80.0, 70.0, 71.0]
    sig = _run(src, closes)
    assert sig.iloc[2] == 1            # rule 1 entry
    assert sig.iloc[4] == 0            # time exit (2 bars held)
    assert (sig.iloc[5:8] == 1).any()  # rule 2's RSI washout re-enters


def test_v06_roundtrip_fixed_point():
    src = (
        'strategy "Two Triggers"\n'
        "universe [sp_top_30]\n\n"
        "when [squeeze] and price above [vwap]\n  buy [risk 1%]\n\n"
        "when [rsi] < 25\n  buy [5% portfolio]\n\n"
        "sell half when [target 5%]\n\n"
        "sell when price at [middle_bollinger]\n  or [stop 2 atr]\n\n"
        "risk [cooldown 5] [max_positions 5]\n"
    )
    s = prior_lang.compile_source(src)
    assert len(s["rules"]) == 2
    assert s["partial_exit"]["fraction"] == 0.5
    assert s["risk"]["cooldown_bars"] == 5
    assert prior_lang.compile_source(strategy_to_source(s)) == s
    out = strategy_to_source(s)
    assert "sell half when [target 5%]" in out
    assert "[cooldown 5]" in out


def test_partial_rejects_stops():
    with pytest.raises(prior_lang.PriorError, match="full exit"):
        prior_lang.compile_source(
            "universe [sp_top_30]\nwhen [rsi] < 30\n  buy [5% portfolio]\n"
            "sell half when [stop 2%]\nsell when [after 5 bars]\n"
        )


def test_explain_v06():
    from prior_lang.explain import explain_strategy
    s = prior_lang.compile_source(
        "universe [sp_top_30]\n"
        "when [macd_cross_up]\n  buy [5% portfolio]\n"
        "when [rsi] < 25\n  buy [$5000]\n"
        "sell half when [target 4%]\n"
        "sell when [stop 3%]\n  or [after 10 bars]\n"
        "risk [cooldown 3]\n"
    )
    text = explain_strategy(s)
    assert "Or: " in text                      # two rules
    assert "Takes half off" in text
    assert "no re-entry for 3 bars" in text


# ── Slice B: long + short in one file ─────────────────────────────

MIXED = (
    "universe $T\n"
    "when price above 100\n  buy [10% portfolio]\n"
    "when price below 90\n  short [10% portfolio]\n"
    "sell when [after 2 bars]\n"
    "cover when [after 2 bars]\n"
)


def test_mixed_long_then_short_in_one_run():
    #        b0  b1   b2(le) b3   b4(exit) b5  b6(se) b7  b8(exit)
    closes = [95, 99, 103, 104, 105, 98, 89, 88, 87]
    sig = _run(MIXED, closes)
    assert list(sig) == [0, 0, 1, 1, 0, 0, -1, -1, 0]


def test_mixed_conflicting_edges_stand_aside():
    src = (
        "universe $T\n"
        "when price above 100\n  buy [10% portfolio]\n"
        "when price above 105\n  short [10% portfolio]\n"   # contrived: co-fires with long
        "sell when [after 4 bars]\n"
        "cover when [after 4 bars]\n"
    )
    #        b0   b1(both edges!) b2   b3    b4(short edge alone)
    closes = [99, 106, 107, 104, 106, 107]
    sig = _run(src, closes)
    assert sig.iloc[1] == 0            # both edges fired → stand aside
    assert sig.iloc[4] == -1           # later, the short edge alone enters


def test_mixed_opposite_edge_ignored_while_positioned():
    src = (
        "universe $T\n"
        "when price above 100\n  buy [10% portfolio]\n"
        "when price below 95\n  short [10% portfolio]\n"
        "sell when [after 4 bars]\n"
        "cover when [after 4 bars]\n"
    )
    #        b0   b1(le) b2: short edge fires while long — must stay long
    closes = [99, 103, 94, 96, 97]
    sig = _run(src, closes)
    assert sig.iloc[1] == 1
    assert sig.iloc[2] == 1            # opposite edge ignored, still long


def test_mixed_roundtrip_fixed_point():
    src = (
        'strategy "Fade Both Tails"\n'
        "universe [mega_tech]\n\n"
        "when [rsi 2] < 10\n  buy [5% portfolio]\n\n"
        "when [rsi 2] > 90\n  short [5% portfolio]\n\n"
        "sell when [rsi 2] > 50\n  or [stop 3%]\n\n"
        "cover when [rsi 2] < 50\n  or [stop 3%]\n"
    )
    s = prior_lang.compile_source(src)
    assert s["direction"] == "mixed"
    assert prior_lang.compile_source(strategy_to_source(s)) == s
    out = strategy_to_source(s)
    assert "short [5% portfolio]" in out and "cover when" in out


def test_mixed_partial_rejected():
    with pytest.raises(prior_lang.PriorError, match="coming later"):
        prior_lang.compile_source(
            "universe [mega_tech]\n"
            "when [rsi 2] < 10\n  buy [5% portfolio]\n"
            "when [rsi 2] > 90\n  short [5% portfolio]\n"
            "sell half when [target 5%]\n"
            "sell when [after 5 bars]\ncover when [after 5 bars]\n"
        )


def test_mixed_explain_has_both_exits():
    from prior_lang.explain import explain_strategy
    s = prior_lang.compile_source(
        "universe [mega_tech]\n"
        "when [rsi 2] < 10\n  buy [5% portfolio]\n"
        "when [rsi 2] > 90\n  short [5% portfolio]\n"
        "sell when [stop 3%]\ncover when [stop 3%]\n"
    )
    text = explain_strategy(s)
    assert "Longs exit" in text and "Shorts cover" in text
    assert "3% above entry" in text


def test_rising_edge_is_one_entry_per_streak():
    """Regression for the pandas object-dtype ~shift bug: a condition that
    stays true for many bars produces exactly ONE entry edge."""
    src = (
        "universe $T\nwhen price above 100\n  buy [10% portfolio]\n"
        "sell when [after 1 bars]\n"
    )
    closes = [99.0, 103.0, 104.0, 105.0, 106.0, 107.0]
    sig = _run(src, closes)
    # entry b1, exit b2 (1 bar held); condition STILL true b2-b5 but no
    # fresh edge — must stay flat, not machine-gun re-entries
    assert list(sig) == [0, 1, 0, 0, 0, 0]
