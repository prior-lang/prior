"""A tag written without its brackets must be refused, never crashed on.

Found in production: a hosted model wrote `write csp delta=25 dte=45`
and the parser died on a bare assert instead of raising PriorError,
which killed a hundred-iteration research run at attempt 30. Every
place the grammar requires a tag must produce a readable error when
the brackets are missing, because generated code hits exactly these
malformed shapes.
"""

import pytest

from prior_lang import compile_source
from prior_lang.errors import PriorError

OPT = (
    'strategy "T"\n\nuniverse $TEST\n\n'
    "when [rsi] < 40\n  {write_line}\n\n"
    "close at [profit 50%]\n  or [dte 7]\n\n"
    "risk [contracts 1]\n"
)


def test_unbracketed_write_tag_is_a_readable_error():
    with pytest.raises(PriorError) as e:
        compile_source(OPT.format(write_line="write csp delta=25 dte=45"))
    assert "bracket" in str(e.value)


def test_unbracketed_roll_tag_is_a_readable_error():
    src = OPT.format(write_line="write [csp delta=25 dte=45]").replace(
        "close at [profit 50%]", "close at [profit 50%]\nroll at dte 7")
    with pytest.raises(PriorError) as e:
        compile_source(src)
    assert not isinstance(e.value, AssertionError)
    assert "bracket" in str(e.value) or "roll" in str(e.value)


def test_bracketed_forms_still_compile():
    s = compile_source(OPT.format(write_line="write [csp delta=25 dte=45]"))
    assert s.get("options") or s.get("opt_form") or s is not None
