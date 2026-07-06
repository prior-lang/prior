"""Cloud-only tags: parse everywhere, evaluate only on hosted data."""

import pytest

import prior_lang
from prior_lang import strategy_to_source
from prior_lang.codegen import compile_strategy

GATED = (
    "universe $F\n"
    "when [ivrank] > 50 and [no_earnings_within 7 days]\n"
    "  write [csp delta=25 dte=45]\n"
    "close at [profit 50%]\n"
)


def test_cloud_tags_parse_and_roundtrip():
    s = prior_lang.compile_source(GATED)
    conds = {c["condition"] for c in s["options"]["entry"]["conditions"]}
    assert conds == {"iv_rank_greater_than", "no_earnings_within"}
    assert prior_lang.compile_source(strategy_to_source(s)) == s


def test_local_compile_refuses_with_pointer():
    s = prior_lang.compile_source(GATED)
    with pytest.raises(prior_lang.PriorError, match="hosted"):
        compile_strategy(s)


def test_cloud_compile_emits_evaluator_hook():
    s = prior_lang.compile_source(GATED)
    code = compile_strategy(s, allow_cloud=True)
    assert "_prior_cloud(df, 'iv_rank_greater_than'" in code


def test_short_interest_in_equity_rules():
    s = prior_lang.compile_source(
        "universe [sp_top_30]\n"
        "when [short_interest] > 20 and [rsi] < 30\n  buy [5% portfolio]\n"
        "sell when [after 10 bars]\n"
    )
    conds = [c["condition"] for c in s["entry"]["conditions"]]
    assert "short_interest_greater_than" in conds
    with pytest.raises(prior_lang.PriorError, match="hosted"):
        compile_strategy(s)
    assert "_prior_cloud" in compile_strategy(s, allow_cloud=True)


def test_explain_marks_hosted_data():
    from prior_lang.explain import explain_strategy
    text = explain_strategy(prior_lang.compile_source(GATED))
    assert "IV rank is above 50 (hosted data)" in text
    assert "no earnings within 7 days (hosted data)" in text


def test_validate_and_fmt_work_locally():
    from prior_lang.cli import main
    import tempfile, os
    f = tempfile.NamedTemporaryFile("w", suffix=".prior", delete=False)
    f.write(GATED); f.close()
    try:
        assert main(["validate", f.name]) == 0
        assert main(["fmt", f.name]) == 0
    finally:
        os.unlink(f.name)
