"""`A then within N bars B` — the windowed sequence operator.

The setup shape this exists for: something arms (a sweep, a cross), then you
watch a bounded number of later bars for a confirmation. Expressed declaratively
so nobody hand-rolls a state machine, and — the part that matters — the window
counts BACKWARDS from the current bar, so lookahead stays impossible.
"""

import math

import pandas as pd
import pytest

import prior_lang
from prior_lang import strategy_to_source
from prior_lang.codegen import compile_strategy

# hold=1 makes the emitted signal equal the raw entry edge, so assertions below
# read the exact bar a sequence fired on.
BOILER = (
    "universe $TEST\ntimeframe 1d\n"
    "when {cond}\n  buy [5% portfolio]\nsell when [after 1 bars]\n"
)


def _df(closes, opens=None):
    idx = pd.date_range("2026-01-01", periods=len(closes), freq="D")
    close = pd.Series(closes, index=idx, dtype=float)
    open_ = pd.Series(opens if opens is not None else closes, index=idx, dtype=float)
    hi = pd.concat([open_, close], axis=1).max(axis=1) * 1.01
    lo = pd.concat([open_, close], axis=1).min(axis=1) * 0.99
    return pd.DataFrame(
        {"open": open_, "high": hi, "low": lo, "close": close, "volume": 1e6},
        index=idx,
    )


def _signals(cond: str, df: pd.DataFrame):
    strategy = prior_lang.compile_source(BOILER.format(cond=cond))
    ns = {"pd": pd, "np": __import__("numpy"), "math": math}
    exec(compile_strategy(strategy), ns)
    return ns["generate_signals"](df)


# ── shape, precedence, round-trip ──────────────────────────────

def test_sequence_parses_into_nested_ir():
    s = prior_lang.compile_source(BOILER.format(
        cond="price above 100 then within 5 bars price below 20"))
    [c] = s["entry"]["conditions"]
    assert c["condition"] == "sequence"
    assert c["params"]["window"] == 5
    assert c["params"]["first"]["condition"] == "price_above_level"
    assert c["params"]["second"]["condition"] == "price_below_level"


def test_sequence_binds_tighter_than_and():
    # (A then within N B) and C  — not A then within N (B and C)
    s = prior_lang.compile_source(BOILER.format(
        cond="price above 100 then within 5 bars price below 20 and [rsi] < 40"))
    conds = s["entry"]["conditions"]
    assert [c["condition"] for c in conds] == ["sequence", "rsi_less_than"]
    assert s["entry"]["match_logic"] == "all"


def test_sequence_roundtrips_through_source():
    s = prior_lang.compile_source(BOILER.format(
        cond="price above 100 then within 3 bars price below 20"))
    assert "then within 3 bars" in strategy_to_source(s)
    assert prior_lang.compile_source(strategy_to_source(s)) == s


def test_sequence_singular_bar_reads_naturally():
    s = prior_lang.compile_source(BOILER.format(
        cond="price above 100 then within 1 bar price below 20"))
    assert "then within 1 bar " in strategy_to_source(s)


def test_sequence_formats_idempotently():
    src = BOILER.format(cond="price above 100 then within 5 bars price below 20")
    once = prior_lang.format_source(src)
    assert "then within 5 bars" in once
    assert prior_lang.format_source(once) == once


# ── runtime semantics ──────────────────────────────────────────

def test_fires_when_confirmation_lands_inside_the_window():
    #        bar:   0    1     2    3    4    5    6    7    8    9
    # A (>100):     F    T     F    F    F    F    F    F    F    F   arm @1
    # B (<20):      F    F     F    T    F    F    F    F    F    T
    df = _df([50, 150, 60, 10, 60, 60, 60, 60, 60, 15])
    sig = _signals("price above 100 then within 5 bars price below 20", df)
    assert sig.iloc[3] == 1          # 2 bars after the arm, inside the window


def test_silent_when_confirmation_lands_outside_the_window():
    df = _df([50, 150, 60, 10, 60, 60, 60, 60, 60, 15])
    sig = _signals("price above 100 then within 5 bars price below 20", df)
    assert sig.iloc[9] == 0          # 8 bars after the arm — window long expired


def test_same_bar_confirmation_does_not_fire():
    # Bar 1 gaps up AND closes above 100, so both terms are true on one bar.
    # "then" means afterwards, so that bar must not fire — but the next bar,
    # with the arm still open, does.
    df = _df(closes=[90, 110, 105], opens=[90, 95, 110])
    sig = _signals("[gap_up 2%] then within 5 bars price above 100", df)
    assert sig.iloc[1] == 0
    assert sig.iloc[2] == 1


def test_rearming_starts_a_fresh_window():
    #        bar:  0    1     2   3    4     5   6   7
    # A (>100):    F    T     F   F    T     F   F   F   arms @1 and @4
    # B (<20):     F    F     F   F    F     F   F   T
    # window=3: the first arm covers bars 2-4, the second covers 5-7.
    df = _df([50, 150, 50, 50, 150, 50, 50, 10])
    sig = _signals("price above 100 then within 3 bars price below 20", df)
    assert sig.iloc[7] == 1          # only reachable via the second arm


def test_expiry_leaves_no_state_behind():
    # A arms once, nothing confirms, and a later lone B must stay silent.
    df = _df([50, 150, 60, 60, 60, 60, 60, 60, 10])
    sig = _signals("price above 100 then within 2 bars price below 20", df)
    assert sig.sum() == 0


# ── the guarantee ──────────────────────────────────────────────

def test_generated_code_only_reads_closed_bars():
    s = prior_lang.compile_source(BOILER.format(
        cond="price above 100 then within 5 bars price below 20"))
    code = compile_strategy(s)
    assert "_seq_arm" in code and "_seq_open" in code
    # The window looks backwards from now. A forward shift would be the only
    # way to peek, and there is none.
    assert "shift(-" not in code
    assert ".rolling(5, min_periods=1)" in code


# ── errors ─────────────────────────────────────────────────────

def test_then_without_within_is_an_error():
    with pytest.raises(prior_lang.PriorError, match="within"):
        prior_lang.compile_source(BOILER.format(
            cond="price above 100 then price below 20"))


def test_window_needs_the_word_bars():
    with pytest.raises(prior_lang.PriorError, match="bars"):
        prior_lang.compile_source(BOILER.format(
            cond="price above 100 then within 5 price below 20"))


def test_window_must_be_a_whole_number_of_bars():
    with pytest.raises(prior_lang.PriorError, match="whole number"):
        prior_lang.compile_source(BOILER.format(
            cond="price above 100 then within 2.5 bars price below 20"))


def test_window_must_be_at_least_one_bar():
    with pytest.raises(prior_lang.PriorError, match="at least 1"):
        prior_lang.compile_source(BOILER.format(
            cond="price above 100 then within 0 bars price below 20"))


def test_three_step_chaining_is_rejected_for_now():
    with pytest.raises(prior_lang.PriorError, match="more than two steps"):
        prior_lang.compile_source(BOILER.format(
            cond="price above 100 then within 3 bars price below 20 "
                 "then within 3 bars price above 200"))


def test_timeframe_inside_a_sequence_is_rejected_for_now():
    with pytest.raises(prior_lang.PriorError, match="not supported"):
        prior_lang.compile_source(
            "universe $TEST\ntimeframe 1h\n"
            "when [rsi on 4h] < 30 then within 3 bars price below 20\n"
            "  buy [5% portfolio]\nsell when [after 1 bars]\n")


# ── readback ───────────────────────────────────────────────────

def test_explain_reads_the_sequence_in_english():
    from prior_lang.explain import _condition_text_inner
    s = prior_lang.compile_source(BOILER.format(
        cond="price above 100 then within 5 bars price below 20"))
    text = _condition_text_inner(s["entry"]["conditions"][0])
    assert "then within the next 5 bars" in text
    assert "later bar" in text
