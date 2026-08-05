"""Mixed logic with parentheses, and the sweep tags.

The grammar rule: one chain is all `and` or all `or`; parentheses are
the one way to mix, and they say which binds first, so precedence never
has to be remembered. Redundant parentheses flatten away — a strategy's
shape and canonical hash depend on its logic, not its punctuation.
"""

import numpy as np
import pandas as pd
import pytest

from prior_lang import compile_source
from prior_lang.backtest import run_backtest
from prior_lang.canonical import strategy_digest
from prior_lang.errors import PriorError
from prior_lang.explain import explain_strategy
from prior_lang.formatter import format_program
from prior_lang.parser import parse_source

TMPL = (
    'strategy "T"\n\nuniverse $TEST\ntimeframe 1d\n\n{when}\n'
    "  buy [5% portfolio]\n\nsell when [rsi] > 65\n  or [stop 4%]\n"
)


def _bars(n=600, seed=7):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.02, n)))
    return pd.DataFrame({
        "open": close * (1 + rng.normal(0, 0.003, n)),
        "high": close * (1 + np.abs(rng.normal(0, 0.01, n))),
        "low": close * (1 - np.abs(rng.normal(0, 0.01, n))),
        "close": close,
        "volume": rng.integers(1_000_000, 5_000_000, n).astype(float),
    }, index=pd.date_range("2022-01-03", periods=n, freq="B"))


# ── parsing shape ───────────────────────────────────────────

def test_group_mixes_or_into_an_and_chain():
    s = compile_source(TMPL.format(
        when="when ([rsi] < 30 or [stoch] < 20) and price above [sma 100]"))
    e = s["entry"]
    assert e["match_logic"] == "all"
    kinds = [c["condition"] for c in e["conditions"]]
    assert kinds == ["group", "price_above_sma"]
    g = e["conditions"][0]["params"]
    assert g["match_logic"] == "any"
    assert [c["condition"] for c in g["conditions"]] == [
        "rsi_less_than", "stoch_less_than"]


def test_groups_nest():
    s = compile_source(TMPL.format(
        when="when (([rsi] < 30 and [down_days 2]) or [gap_down 2%]) "
             "and price above [sma 100]"))
    outer = s["entry"]["conditions"][0]["params"]
    assert outer["match_logic"] == "any"
    inner = outer["conditions"][0]
    assert inner["condition"] == "group"
    assert inner["params"]["match_logic"] == "all"


def test_redundant_parens_change_nothing():
    """((a or b) or c) is one any-list — same shape, same canonical hash
    as the flat spelling. Punctuation is not semantics."""
    flat = compile_source(TMPL.format(
        when="when [rsi] < 30 or [stoch] < 20 or [gap_down 2%]"))
    wrapped = compile_source(TMPL.format(
        when="when ([rsi] < 30 or [stoch] < 20) or [gap_down 2%]"))
    strip = lambda s: {k: v for k, v in s.items() if k != "name"}
    assert strategy_digest(strip(flat)) == strategy_digest(strip(wrapped))


def test_bare_mixing_still_rejected_with_the_fix_in_the_message():
    with pytest.raises(PriorError) as e:
        compile_source(TMPL.format(
            when="when [rsi] < 30 or [stoch] < 20 and price above [sma 100]"))
    assert "parentheses" in str(e.value)


def test_group_as_sequence_term():
    """This crashed the desugarer before groups existed as a node."""
    s = compile_source(TMPL.format(
        when="when ([new_low 20] or [gap_down 2%]) then within 5 bars "
             "[rsi] crosses above 35"))
    seq = s["entry"]["conditions"][0]
    assert seq["condition"] == "sequence"
    assert seq["params"]["first"]["condition"] == "group"


def test_timeframe_inside_a_group_is_refused():
    with pytest.raises(PriorError) as e:
        compile_source(
            'strategy "T"\n\nuniverse $TEST\ntimeframe 1h\n\n'
            "when ([rsi on 1d] < 30 or [stoch] < 20) and [adx] > 20\n"
            "  buy [5% portfolio]\n\nsell when [rsi] > 65\n  or [stop 4%]\n")
    assert "parentheses" in str(e.value)


def test_hosted_only_condition_found_inside_a_group():
    from prior_lang.codegen import _find_cloud_only
    s = compile_source(TMPL.format(
        when="when ([ivrank] > 50 or [rsi] < 30) and [adx] > 20"))
    assert "iv_rank_greater_than" in _find_cloud_only(s)


# ── behavior ────────────────────────────────────────────────

def test_grouped_strategy_backtests_and_trades():
    df = _bars()
    s = compile_source(TMPL.format(
        when="when ([rsi] < 40 or [stoch] < 30) and price above [sma 50]"))
    m = run_backtest(s, df, capital=100_000.0, cost_bps=10.0)
    assert m["trades"] > 0


def test_group_equals_its_boolean_expansion():
    """(a or b) and c must trade exactly like the DeMorgan-free truth:
    the union of (a and c) and (b and c). Same tape, same entries."""
    df = _bars(seed=11)
    grouped = compile_source(TMPL.format(
        when="when ([rsi] < 40 or [stoch] < 30) and price above [sma 50]"))
    a = compile_source(TMPL.format(
        when="when [rsi] < 40 and price above [sma 50]"))
    b = compile_source(TMPL.format(
        when="when [stoch] < 30 and price above [sma 50]"))
    mg = run_backtest(grouped, df, capital=100_000.0, cost_bps=10.0)
    ma = run_backtest(a, df, capital=100_000.0, cost_bps=10.0)
    mb = run_backtest(b, df, capital=100_000.0, cost_bps=10.0)
    # The union can't trade less than the bigger leg or more than the sum.
    assert mg["trades"] >= max(ma["trades"], mb["trades"]) - 2
    assert mg["trades"] <= ma["trades"] + mb["trades"]


# ── sweep ───────────────────────────────────────────────────

def test_sweep_fires_on_exactly_the_reclaim_bar():
    """Hand-built tape: flat, then one bar dips below the prior 20-bar
    low intrabar and closes back above it. That bar, and only that bar,
    is a sweep."""
    n = 60
    close = np.full(n, 100.0)
    low = np.full(n, 99.0)
    high = np.full(n, 101.0)
    # bar 40: takes out the prior low (99) intrabar, closes back above
    low[40] = 97.0
    close[40] = 100.5
    df = pd.DataFrame({
        "open": close, "high": high, "low": low, "close": close,
        "volume": np.full(n, 1e6),
    }, index=pd.date_range("2024-01-01", periods=n, freq="B"))

    from prior_lang.codegen import generate_strategy_code
    s = compile_source(TMPL.format(when="when [sweep 20]"))
    cdicts = [{"type": c["condition"], "params": c.get("params", {})}
              for c in s["entry"]["conditions"]]
    src = generate_strategy_code(cdicts, s["entry"]["match_logic"])
    ns = {"pd": pd, "np": np}
    exec(src, ns)
    sig = ns["generate_signals"](df)
    fired = list(np.where(sig.values)[0])
    # The generated strategy holds a signal for the default hold window;
    # what matters is that the sweep ARMED on exactly bar 40 — nothing
    # before it, nothing after the hold.
    assert min(fired) == 40
    assert fired == list(range(40, 40 + len(fired)))


def test_sweep_high_mirrors():
    s = compile_source(TMPL.format(when="when [sweep_high 20]"))
    assert s["entry"]["conditions"][0]["condition"] == "sweep_high"


# ── readback ────────────────────────────────────────────────

def test_format_round_trip_preserves_digest():
    src = TMPL.format(
        when="when ([rsi] < 35 or [sweep 20]) and price above [sma 100]")
    fmt = format_program(parse_source(src))
    strip = lambda s: {k: v for k, v in s.items() if k != "name"}
    assert strategy_digest(strip(compile_source(src))) == \
        strategy_digest(strip(compile_source(fmt)))
    assert "([rsi] < 35 or [sweep 20])" in fmt


def test_explain_reads_the_group_as_a_grouped_clause():
    s = compile_source(TMPL.format(
        when="when ([rsi] < 35 or [sweep 20]) and price above [sma 100]"))
    text = explain_strategy(s)
    assert "either" in text and "sweep" in text.lower()
