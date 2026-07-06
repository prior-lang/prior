"""Editor tooling contracts: the VS Code extension's data file must stay
in sync with the tag registry, and the CLI's --stdin/--json modes are the
wire format editors depend on."""

import json
import subprocess
import sys
from pathlib import Path

import prior_lang
from prior_lang.tags import TAGS

# tools/ lives beside prior_lang/ but is not an installed package
sys.path.insert(0, str(Path(__file__).parents[1]))

DATA = Path(__file__).parents[2] / "editors" / "vscode" / "data" / "tags.json"

VALID = (
    "universe [sp_top_30]\nwhen [macd_cross_up]\n  buy [10% portfolio]\n"
    "sell when [macd_cross_down]\n"
)
BROKEN = VALID.replace("[macd_cross_up]", "[lower_bolinger]")


def test_tags_json_matches_registry():
    """Every core tag appears in the editor data with its exact params —
    regenerate with `python -m tools.gen_editor_tags` after adding tags."""
    from tools.gen_editor_tags import build

    assert json.loads(DATA.read_text()) == build()


def test_every_core_tag_has_a_description():
    from tools.gen_editor_tags import DESCRIPTIONS

    core = {n for n in TAGS if "." not in n}
    assert core == set(DESCRIPTIONS), (
        "registry and editor descriptions diverge — update DESCRIPTIONS in "
        "tools/gen_editor_tags.py and regenerate tags.json"
    )


def _cli(args, stdin):
    return subprocess.run(
        [sys.executable, "-m", "prior_lang.cli", *args],
        input=stdin, capture_output=True, text=True,
    )


def test_validate_stdin_json_ok():
    proc = _cli(["validate", "--stdin", "--json"], VALID)
    assert proc.returncode == 0
    assert json.loads(proc.stdout) == {"ok": True, "errors": []}


def test_validate_stdin_json_error_carries_position_and_suggestion():
    proc = _cli(["validate", "--stdin", "--json"], BROKEN)
    assert proc.returncode == 1
    report = json.loads(proc.stdout)
    assert report["ok"] is False
    [err] = report["errors"]
    assert err["line"] == 2
    assert "not a known tag" in err["message"]
    assert "lower_bollinger" in err["suggestion"]


def test_fmt_stdin_prints_canonical_text():
    messy = 'WHEN [MACD_CROSS_UP]\n  BUY [10% PORTFOLIO]\nSELL WHEN [MACD_CROSS_DOWN]\nuniverse [sp_top_30]\n'
    proc = _cli(["fmt", "--stdin"], messy)
    assert proc.returncode == 0
    assert proc.stdout.startswith("universe [sp_top_30]")
    assert prior_lang.compile_source(proc.stdout) == prior_lang.compile_source(messy)


def test_fmt_stdin_parse_error_exits_nonzero():
    proc = _cli(["fmt", "--stdin"], BROKEN)
    assert proc.returncode == 1
    assert "lower_bolinger" in proc.stderr
