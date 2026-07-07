"""Options slice 3a: multi-leg credit structures as tags.

Locked design (2026-07-07): option structures are ALWAYS tags
([put_spread], [iron_condor], ...), never the spread() call form —
spread($A, $B) stays reserved for two-ticker pairs trading.
"""

import pytest

import prior_lang
from prior_lang import strategy_to_source
from prior_lang.explain import explain_strategy


def _src(tag: str) -> str:
    return (
        f"universe $SPY\nwhen [rsi] < 90\n  write [{tag}]\n"
        "close at [profit 50%]\n"
    )


@pytest.mark.parametrize("tag,expected", [
    ("put_spread delta=25 width=5 dte=30",
     {"type": "put_spread", "delta": 25.0, "width": 5.0, "dte": 30}),
    ("call_spread width=10",
     {"type": "call_spread", "delta": 25.0, "width": 10.0, "dte": 45}),
    ("iron_condor",
     {"type": "iron_condor", "delta": 20.0, "width": 5.0, "dte": 45}),
    ("straddle dte=30", {"type": "straddle", "dte": 30}),
    ("strangle delta=15", {"type": "strangle", "delta": 15.0, "dte": 45}),
])
def test_structure_json_and_roundtrip(tag, expected):
    s = prior_lang.compile_source(_src(tag))
    assert s["options"]["option"] == expected
    assert prior_lang.compile_source(strategy_to_source(s)) == s


def test_defaults_elided_in_canonical_form():
    s = prior_lang.compile_source(_src("put_spread delta=25 width=5 dte=30"))
    out = strategy_to_source(s)
    # delta=25 and width=5 are defaults; only dte=30 differs from 45
    assert "[put_spread dte=30]" in out


def test_width_must_be_positive():
    with pytest.raises(prior_lang.PriorError, match="strike points"):
        prior_lang.compile_source(_src("put_spread width=0"))


def test_wrong_kind_tag_suggests_structures():
    # a known tag of the wrong kind gets the option-tag suggestion list
    with pytest.raises(prior_lang.PriorError, match="put_spread"):
        prior_lang.compile_source(_src("rsi"))


@pytest.mark.parametrize("tag,phrase", [
    ("put_spread", "max loss is capped at the width minus the credit"),
    ("call_spread", "max loss is capped at the width minus the credit"),
    ("iron_condor", "capped by the wings"),
    ("straddle", "Undefined risk"),
    ("strangle", "Undefined risk"),
])
def test_explain_states_the_risk(tag, phrase):
    text = explain_strategy(prior_lang.compile_source(_src(tag)))
    assert phrase in text


def test_management_reads_back_for_structures():
    s = prior_lang.compile_source(
        "universe $SPY\nwhen [rsi] < 35\n  write [iron_condor]\n"
        "close at [profit 50%]\n  or [loss 200%]\nroll at [dte 21]\n"
    )
    text = explain_strategy(s)
    assert "50% of the credit captured" in text
    assert "roll at 21 DTE" in text
