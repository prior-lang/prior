"""The canonical encoding is a commitment format, so its guarantees are
the whole point: two implementations must agree, the digest must not move
unless the strategy moves, and it must not depend on how the strategy was
stored.

Scale is 10**6, chosen with the integrator who has to match it in an
integer-faithful circuit. Below a basis point, so sizing finer than PRIOR
currently expresses will not force existing commitments to be re-minted.
"""

import glob
import json
from pathlib import Path

import pytest

from prior_lang import compile_source
from prior_lang.canonical import (
    SCALE, canonical_bytes, canonical_obj, strategy_digest,
)
from prior_lang.decompile import strategy_from_json
from prior_lang.parser import parse_source

_ROOT = Path(__file__).parents[2]
_SRC = """strategy "Canon"

universe $SPY
timeframe 1d

when [rsi] < 30
  buy [risk 1%]

sell when [rsi] > 55
  or [stop 3%]
"""


def _ir(src=_SRC):
    return json.loads(json.dumps(parse_source(src, "<t>").to_json()))


def test_scale_is_a_million():
    """Locked with the integrator. Changing it invalidates every
    commitment already minted, so it is a test, not a constant."""
    assert SCALE == 10**6


def test_every_example_encodes_exactly():
    """A value the scale cannot represent raises rather than silently
    rounding. None of the real corpus may raise."""
    files = sorted(glob.glob(str(_ROOT / "examples" / "*.prior")))
    assert len(files) >= 25
    for f in files:
        canonical_bytes(json.loads(json.dumps(compile_source(Path(f).read_text()))))


def test_no_floats_survive():
    """An integer-faithful verifier cannot take a float."""
    def walk(o):
        if isinstance(o, dict):
            for v in o.values():
                yield from walk(v)
        elif isinstance(o, list):
            for v in o:
                yield from walk(v)
        else:
            yield o
    for f in sorted(glob.glob(str(_ROOT / "examples" / "*.prior"))):
        obj = canonical_obj(json.loads(json.dumps(compile_source(Path(f).read_text()))))
        assert not [v for v in walk(obj) if isinstance(v, float)], f


def test_counts_are_scaled_too():
    """Uniform rule: the verifier never needs to know which fields are
    fractions. An RSI period of 14 encodes as 14_000_000."""
    obj = canonical_obj(_ir())
    assert obj["entry"]["conditions"][0]["params"]["period"] == 14 * SCALE


def test_sub_basis_point_survives():
    """The reason for 10**6 over 10**4: headroom below a basis point."""
    assert canonical_obj({"x": 0.000001}) == {"x": 1}
    with pytest.raises(ValueError):
        canonical_obj({"x": 0.0000001})   # below the scale, refused not rounded


def test_digest_is_stable_and_order_insensitive():
    ir = _ir()
    assert len({strategy_digest(ir) for _ in range(20)}) == 1
    shuffled = {k: ir[k] for k in reversed(list(ir))}
    assert strategy_digest(shuffled) == strategy_digest(ir)


def test_digest_is_door_independent():
    """Same strategy as text and as JSON must commit identically."""
    ir = _ir()
    via_json = parse_source(strategy_from_json(ir), "<json>").to_json()
    assert strategy_digest(json.loads(json.dumps(via_json))) == strategy_digest(ir)


def test_digest_ignores_comments_and_whitespace():
    noisy = "# not part of the strategy\n" + _SRC.replace("when [rsi] < 30", "when   [rsi]  <  30")
    assert strategy_digest(_ir(noisy)) == strategy_digest(_ir())


@pytest.mark.parametrize(
    "label,changed",
    [
        ("threshold", _SRC.replace("< 30", "< 29")),
        ("stop", _SRC.replace("[stop 3%]", "[stop 3.5%]")),
        ("sizing", _SRC.replace("[risk 1%]", "[risk 1.5%]")),
        ("universe", _SRC.replace("$SPY", "$QQQ")),
        ("timeframe", _SRC.replace("1d", "4h")),
        ("exit threshold", _SRC.replace("> 55", "> 56")),
    ],
)
def test_digest_moves_when_the_strategy_moves(label, changed):
    assert strategy_digest(_ir(changed)) != strategy_digest(_ir()), label


def test_canonical_bytes_are_compact_and_sorted():
    b = canonical_bytes(_ir()).decode()
    assert ", " not in b and '": ' not in b      # no insignificant whitespace
    keys = [k for k in ("direction", "entry", "exit", "name") if f'"{k}":' in b]
    assert keys == sorted(keys)
