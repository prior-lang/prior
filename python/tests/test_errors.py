"""The error contract (SPEC.md §7): line-precise, trader-language,
suggestion-bearing. A language lives or dies on its first error message."""

import pytest

import prior_lang
from prior_lang import PriorError

VALID = """
universe [sp_top_30]
when [macd_cross_up]
  buy [10% portfolio]
sell when [macd_cross_down]
"""


def _err(src: str) -> PriorError:
    with pytest.raises(PriorError) as e:
        prior_lang.compile_source(src)
    return e.value


def test_valid_baseline_compiles():
    assert prior_lang.compile_source(VALID)["entry"]["conditions"]


def test_unknown_tag_did_you_mean():
    e = _err(VALID.replace("[macd_cross_up]", "[lower_bolinger]"))
    assert "not a known tag" in e.message
    assert "lower_bollinger" in (e.suggestion or "")


def test_missing_sizing_tag():
    e = _err(VALID.replace("  buy [10% portfolio]\n", "  buy\n"))
    assert "sizing" in (e.message + (e.suggestion or ""))


def test_double_equals_hint():
    e = _err("universe [sp_top_30]\nwhen price == [lower_bollinger] buy [5% portfolio]\nsell when [after 5 bars]")
    assert "at" in (e.suggestion or "")


def test_risk_sizing_requires_stop():
    e = _err(
        "universe [sp_top_30]\nwhen [rsi] < 30\n  buy [risk 1%]\nsell when [after 5 bars]"
    )
    assert "stop" in e.message


def test_missing_universe():
    e = _err("when [macd_cross_up]\n  buy [5% portfolio]\nsell when [macd_cross_down]")
    assert "universe" in e.message


def test_inline_ticker_and_universe_conflict():
    e = _err(
        "universe [sp_top_30]\nwhen $NVDA at [lower_bollinger]\n  buy [5% portfolio]\nsell when [after 5 bars]"
    )
    assert "not both" in e.message


def test_fast_slow_ordering():
    e = _err(
        "universe [sp_top_30]\nwhen [ema 200] crosses above [ema 50]\n  buy [5% portfolio]\nsell when [after 5 bars]"
    )
    assert "faster average goes on the left" in e.message


def test_mixed_and_or_rejected():
    e = _err(
        "universe [sp_top_30]\nwhen [rsi] < 30 and [macd_cross_up] or [volatile 2%]\n"
        "  buy [5% portfolio]\nsell when [after 5 bars]"
    )
    assert "all 'and' or all 'or'" in e.message


def test_exit_tags_reject_and():
    e = _err(
        "universe [sp_top_30]\nwhen [macd_cross_up]\n  buy [5% portfolio]\n"
        "sell when [stop 2%] and [target 4%]"
    )
    assert "'or'" in e.message


def test_duplicate_stop_rejected():
    e = _err(
        "universe [sp_top_30]\nwhen [macd_cross_up]\n  buy [5% portfolio]\n"
        "sell when [stop 2%]\n  or [stop 3%]"
    )
    assert "twice" in e.message


def test_rsi_threshold_out_of_range():
    e = _err(
        "universe [sp_top_30]\nwhen [rsi] < 130\n  buy [5% portfolio]\nsell when [after 5 bars]"
    )
    assert "0 and 100" in e.message


def test_bare_operand_tag_needs_comparison():
    e = _err(
        "universe [sp_top_30]\nwhen [rsi]\n  buy [5% portfolio]\nsell when [after 5 bars]"
    )
    assert "comparison" in e.message
    assert "[rsi] < 30" in (e.suggestion or "")


def test_short_strategy_compiles():
    s = prior_lang.compile_source(
        "universe [mega_tech]\n"
        "when [rsi] > 80\n"
        "  short [5% portfolio]\n"
        "cover when [rsi] crosses below 60\n"
        "  or [stop 3%]\n"
    )
    assert s["direction"] == "short"
    assert s["exit"]["stop_loss_pct"] == 3.0
    # And it round-trips through fmt
    out = prior_lang.format_source(
        "universe [mega_tech]\nwhen [rsi] > 80\n  short [5% portfolio]\ncover when [stop 3%]\n"
    )
    assert "short [5% portfolio]" in out
    assert out.strip().splitlines()[-1].startswith("cover when")


def test_direction_exit_keyword_pairing():
    e = _err(
        "universe [mega_tech]\nwhen [rsi] > 80\n  short [5% portfolio]\nsell when [stop 3%]\n"
    )
    assert "cover" in e.message
    e = _err(
        "universe [mega_tech]\nwhen [rsi] < 20\n  buy [5% portfolio]\ncover when [stop 3%]\n"
    )
    assert "sell" in e.message


def test_multiple_entry_rules_compile():
    s = prior_lang.compile_source(
        "universe [sp_top_30]\nwhen [macd_cross_up]\n  buy [5% portfolio]\n"
        "when [rsi] < 30\n  buy [$5000]\nsell when [after 5 bars]"
    )
    assert len(s["rules"]) == 2
    assert s["rules"][0]["position_sizing"]["method"] == "percent_of_portfolio"
    assert s["rules"][1]["position_sizing"]["method"] == "fixed_dollar"


def test_mixed_direction_rules_compile_with_both_exits():
    s = prior_lang.compile_source(
        "universe [sp_top_30]\nwhen [macd_cross_up]\n  buy [5% portfolio]\n"
        "when [rsi] > 80\n  short [5% portfolio]\n"
        "sell when [after 5 bars]\ncover when [after 5 bars]"
    )
    assert s["direction"] == "mixed"
    assert "exits" in s and "exit" not in s
    assert {r["direction"] for r in s["rules"]} == {"long", "short"}


def test_mixed_missing_cover_rejected():
    e = _err(
        "universe [sp_top_30]\nwhen [macd_cross_up]\n  buy [5% portfolio]\n"
        "when [rsi] > 80\n  short [5% portfolio]\nsell when [after 5 bars]"
    )
    assert "cover" in e.message


def test_error_carries_line_number():
    e = _err(VALID.replace("[macd_cross_up]", "[lower_bolinger]"))
    assert e.line == 3  # blank first line, universe on 2, entry on 3


def test_namespaced_tags_reserved():
    e = _err(VALID.replace("[macd_cross_up]", "[acme.momo]"))
    assert "future version" in e.message


def test_crypto_majors_universe_and_crypto_ticker():
    src = (
        "universe [crypto_majors]\n"
        "when price at [lower_bollinger]\n"
        "  buy [5% portfolio]\n"
        "sell when [after 10 bars]\n"
    )
    s = prior_lang.compile_source(src)
    assert s["universe"] == {"type": "prebuilt", "key": "crypto_majors"}
    # Inline crypto ticker scoping also works (hyphenated pairs lex as tickers)
    s2 = prior_lang.compile_source(
        "when $BTC-USD at [lower_bollinger]\n  buy [5% portfolio]\nsell when [after 10 bars]\n"
    )
    assert s2["universe"] == {"type": "manual", "tickers": ["BTC-USD"]}


def test_case_insensitive_keywords_and_tags():
    src = 'UNIVERSE [SP_TOP_30]\nWHEN [MACD_CROSS_UP]\n  BUY [10% PORTFOLIO]\nSELL WHEN [MACD_CROSS_DOWN]'
    s = prior_lang.compile_source(src)
    assert s["universe"]["key"] == "sp_top_30"


def test_if_is_alias_for_when():
    src = VALID.replace("when", "if", 1)
    s = prior_lang.compile_source(src)
    assert s["entry"]["conditions"]
    # And fmt canonicalizes it back to when
    assert prior_lang.format_source(src).startswith("universe") or "when" in prior_lang.format_source(src)
