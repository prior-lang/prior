"""A receipt has to be worth binding to.

`--json` reports metrics alone, so a published result cannot say which
strategy produced it, on which bars, at what cost. The receipt closes that,
but only if the digests hold three properties: stable across runs,
independent of whether the strategy arrived as text or JSON, and sensitive
to any change that alters what actually ran.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from prior_lang.parser import parse_source
from prior_lang.receipt import build_receipt, file_digest, strategy_digest

_ROOT = Path(__file__).parents[2]
_SRC = """strategy "Digest Probe"

universe $SPY
timeframe 1d

when [rsi] < 30
  buy [risk 1%]

sell when [rsi] > 55
  or [stop 3%]
"""


def _digest(src: str) -> str:
    return strategy_digest(parse_source(src, "<test>"))


def test_digest_is_stable():
    assert len({_digest(_SRC) for _ in range(10)}) == 1


def test_digest_ignores_comments_and_formatting():
    """Comments are documentation. Two files differing only in commentary
    or whitespace are the same strategy and must commit identically."""
    commented = "# a note nobody else needs\n" + _SRC.replace(
        "when [rsi] < 30", "when   [rsi]   <   30"
    )
    assert _digest(commented) == _digest(_SRC)


def test_digest_is_door_independent():
    """Same strategy via the JSON door must produce the same commitment."""
    from prior_lang.decompile import strategy_from_json

    ir = json.loads(json.dumps(parse_source(_SRC, "<test>").to_json()))
    via_json = parse_source(strategy_from_json(ir), "<json>")
    assert strategy_digest(via_json) == _digest(_SRC)


@pytest.mark.parametrize(
    "label,changed",
    [
        ("threshold", _SRC.replace("< 30", "< 25")),
        ("stop", _SRC.replace("[stop 3%]", "[stop 2%]")),
        ("sizing", _SRC.replace("[risk 1%]", "[risk 2%]")),
        ("universe", _SRC.replace("$SPY", "$QQQ")),
        ("timeframe", _SRC.replace("1d", "4h")),
    ],
)
def test_digest_changes_when_the_strategy_changes(label, changed):
    """A commitment that survives an edit is worthless."""
    assert _digest(changed) != _digest(_SRC), label


def test_data_digest_detects_a_changed_bar(tmp_path):
    a = tmp_path / "a.csv"
    a.write_text("date,open,high,low,close,volume\n2024-01-02,1,2,0.5,1.5,100\n")
    before = file_digest(str(a))
    a.write_text("date,open,high,low,close,volume\n2024-01-02,1,2,0.5,1.6,100\n")
    assert file_digest(str(a)) != before


def test_receipt_shape(tmp_path):
    bars = tmp_path / "bars.csv"
    bars.write_text("date,open,high,low,close,volume\n2024-01-02,1,2,0.5,1.5,100\n")
    program = parse_source(_SRC, "<test>")
    r = build_receipt(
        program=program, strategy=program.to_json(), data_path=str(bars),
        metrics={"sharpe": 1.0}, prior_version="0.0.0", capital=1000.0,
        fee_bps=5.0, slippage_bps=5.0,
    )
    assert r["receipt"] == "prior/1"
    assert r["strategy"]["digest"].startswith("sha256:")
    assert r["data"]["digest"].startswith("sha256:")
    assert r["data"]["file"] == "bars.csv"
    assert r["assumptions"]["fee_bps"] == 5.0
    assert r["metrics"]["sharpe"] == 1.0


def test_receipt_does_not_leak_the_absolute_path(tmp_path):
    """A receipt is meant to be published; it should not carry the author's
    directory layout."""
    bars = tmp_path / "private_research" / "bars.csv"
    bars.parent.mkdir()
    bars.write_text("date,open,high,low,close,volume\n2024-01-02,1,2,0.5,1.5,100\n")
    program = parse_source(_SRC, "<test>")
    r = build_receipt(
        program=program, strategy=program.to_json(), data_path=str(bars),
        metrics={}, prior_version="0.0.0",
    )
    assert "private_research" not in json.dumps(r)


def test_cli_emits_a_receipt_without_needing_json_flag():
    """--receipt alone must not silently print the human table."""
    data = _ROOT / "python" / "tests" / "fixtures"
    strat = Path(_ROOT / "examples" / "golden_cross.prior")
    if not strat.exists():
        pytest.skip("example missing")
    import tempfile
    import pandas as pd
    with tempfile.TemporaryDirectory() as d:
        csv = Path(d) / "bars.csv"
        idx = pd.date_range("2020-01-01", periods=400, freq="D")
        pd.DataFrame({
            "date": idx.strftime("%Y-%m-%d"),
            "open": range(1, 401), "high": range(2, 402),
            "low": range(0, 400), "close": range(1, 401),
            "volume": [1000] * 400,
        }).to_csv(csv, index=False)
        out = subprocess.run(
            [sys.executable, "-m", "prior_lang.cli", "backtest", str(strat),
             "--data", str(csv), "--receipt"],
            capture_output=True, text=True, cwd=str(_ROOT / "python"),
        )
        assert out.returncode == 0, out.stderr
        payload = json.loads(out.stdout)
        assert payload["receipt"] == "prior/1"
        assert payload["strategy"]["digest"].startswith("sha256:")
