"""The JSON door is held to the same standard as the text door.

`strategy_to_source` renders what it recognizes and ignores the rest. That
made the interchange format quietly permissive: `[rsi tol=0.5%]` is a
compile error when written as text, but the same parameter arriving inside
JSON used to be dropped in silence. SPEC §1.4 says all validation happens
at compile time with a line-precise message, and §1 says violating an
invariant is a spec bug, so that gap was one.

`strategy_from_json` closes it by enforcing the round-trip the spec already
promises (§1.5): anything that does not survive JSON → source → JSON was
never expressible, and is now an error naming the offending path.
"""

import copy
import glob
import json
from pathlib import Path

import pytest

from prior_lang import compile_source
from prior_lang.decompile import strategy_from_json
from prior_lang.errors import PriorError

_ROOT = Path(__file__).parents[2]


def _example_ir():
    src = (_ROOT / "examples" / "sweep_then_reclaim.prior").read_text()
    return json.loads(json.dumps(compile_source(src)))


def test_every_example_still_loads_through_the_strict_door():
    """The check must not reject anything real. All of them, not a sample."""
    files = sorted(glob.glob(str(_ROOT / "examples" / "*.prior")))
    assert len(files) >= 25, "examples missing; this test would pass vacuously"
    for f in files:
        ir = json.loads(json.dumps(compile_source(Path(f).read_text())))
        strategy_from_json(ir)  # must not raise


def test_numeric_widening_is_not_a_rejection():
    """20 and 20.0 are the same period. A JSON producer using floats is fine."""
    ir = _example_ir()
    ir["entry"]["conditions"][0]["params"]["first"]["params"]["period"] = 20.0
    strategy_from_json(ir)


@pytest.mark.parametrize(
    "label,mutate",
    [
        # each of these was silently ACCEPTED before the fix
        ("bogus param on a real tag",
         lambda o: o["entry"]["conditions"][0]["params"]["first"]
                    .setdefault("params", {}).__setitem__("tol", "0.5%")),
        ("unknown top-level key",
         lambda o: o.__setitem__("lookahead_bars", 5)),
        ("match_logic garbage",
         lambda o: o["entry"].__setitem__("match_logic", "sometimes")),
    ],
)
def test_unrepresentable_content_is_rejected(label, mutate):
    ir = _example_ir()
    mutate(ir)
    with pytest.raises(PriorError) as e:
        strategy_from_json(ir)
    assert "cannot express" in str(e.value), label


def test_the_error_names_the_offending_path():
    """A message that says 'something is wrong' is not line-precise."""
    ir = _example_ir()
    ir["lookahead_bars"] = 5
    with pytest.raises(PriorError) as e:
        strategy_from_json(ir)
    assert "lookahead_bars" in str(e.value)


def test_invented_condition_still_refused():
    """Already refused before the fix; guard against a regression."""
    ir = _example_ir()
    ir["entry"]["conditions"][0]["params"]["first"]["condition"] = "teleport_from_future"
    with pytest.raises(PriorError):
        strategy_from_json(ir)
