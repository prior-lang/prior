"""The published JSON Schema must accept every real strategy and reject junk.

`spec/strategy.schema.json` is what an integrating pipeline validates against
before its generated strategies ever reach the compiler (SPEC.md section 11).
If it drifts from what the compiler actually emits, that pipeline starts
rejecting valid strategies, or worse, passing invalid ones through.

jsonschema is not a runtime dependency of prior_lang, so these skip when it
is absent rather than forcing it on every install.
"""

import copy
import glob
import json
from pathlib import Path

import pytest

from prior_lang import compile_source

jsonschema = pytest.importorskip("jsonschema")

_ROOT = Path(__file__).parents[2]
_SCHEMA_PATH = _ROOT / "spec" / "strategy.schema.json"


def _schema():
    return json.loads(_SCHEMA_PATH.read_text())


def _validator():
    return jsonschema.Draft202012Validator(_schema())


def _compiled_examples():
    out = []
    for path in sorted(glob.glob(str(_ROOT / "examples" / "*.prior"))):
        ir = compile_source(Path(path).read_text())
        out.append((Path(path).name, json.loads(json.dumps(ir))))
    return out


def test_schema_is_itself_valid():
    jsonschema.Draft202012Validator.check_schema(_schema())


def test_every_example_validates():
    """The executable spec is the fixture set. All of it must pass."""
    v = _validator()
    failures = []
    for name, obj in _compiled_examples():
        errs = list(v.iter_errors(obj))
        if errs:
            failures.append(f"{name}: {errs[0].message}")
    assert not failures, "schema rejects real strategies:\n" + "\n".join(failures)


def test_examples_were_actually_found():
    """Guard against the previous test passing vacuously."""
    assert len(_compiled_examples()) >= 25


@pytest.mark.parametrize(
    "label,mutate",
    [
        ("missing version", lambda o: o.pop("version", None)),
        ("universe type typo", lambda o: o["universe"].__setitem__("type", "prebuit")),
        ("match_logic invalid", lambda o: o["entry"].__setitem__("match_logic", "both")),
        ("negative stop", lambda o: o["exit"].__setitem__("stop_loss_pct", -5)),
        ("sizing method typo", lambda o: o["position_sizing"].__setitem__("method", "pct")),
        ("condition missing its name", lambda o: o["entry"]["conditions"][0].pop("condition")),
        ("unknown top-level block shape", lambda o: o.__setitem__("entry", {"conditions": []})),
    ],
)
def test_malformed_objects_are_rejected(label, mutate):
    """A structural gate that accepts anything is not a gate."""
    base = next(
        obj for _, obj in _compiled_examples()
        if {"entry", "exit", "position_sizing"} <= set(obj)
    )
    obj = copy.deepcopy(base)
    mutate(obj)
    assert list(_validator().iter_errors(obj)), f"schema failed to catch: {label}"
