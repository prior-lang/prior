"""Malformed tag parameters must fail readably, never with a traceback.

Found in field testing by Gabriel Murillo: a word where a number was
expected crashed the error formatter itself (an eager dict of f-strings
evaluated the numeric branches on the word). The zero-window cases are
the same probe from the other side — they used to compile into rules
that could never fire, the silently dead rule the activity table exists
to catch, now refused at compile.
"""

import pytest

from prior_lang import compile_source
from prior_lang.errors import PriorError

TMPL = (
    'strategy "T"\n\nuniverse $TEST\ntimeframe 1d\n\n{when}\n'
    "  buy [5% portfolio]\n\nsell when [rsi] > 65\n  or [stop 4%]\n"
)


def _err(when: str) -> str:
    with pytest.raises(PriorError) as e:
        compile_source(TMPL.format(when=when))
    return str(e.value)


def test_word_where_number_expected_is_a_readable_error():
    msg = _err("when [rsi abc] < 30")
    assert "expects a number" in msg and "abc" in msg
    assert "Traceback" not in msg


def test_zero_windows_are_refused_not_silently_dead():
    assert "positive period" in _err("when [rsi 0] < 30")
    assert "positive period" in _err("when price above [sma 0]")
    assert "positive count" in _err("when [up_days 0]")
    assert "positive lookback" in _err("when [squeeze 0]")
    assert "positive wing" in _err("when price above [fractal_high 0]")


def test_heavy_volume_word_is_checked():
    assert "heavy_volume top" in _err("when [heavy_volume bottom 10%]")


def test_valid_defaults_still_compile():
    s = compile_source(TMPL.format(when="when [rsi] < 30"))
    assert s["entry"]["conditions"]
