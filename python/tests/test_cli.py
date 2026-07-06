"""CLI smoke tests — every verb, driven through main() directly."""

from pathlib import Path

import pytest

from prior_lang.cli import main

EXAMPLES = Path(__file__).parents[2] / "examples"
BOLLINGER = str(EXAMPLES / "bollinger_reversal.prior")


def test_validate_ok(capsys):
    assert main(["validate", BOLLINGER]) == 0
    assert "ok" in capsys.readouterr().out


def test_validate_bad_file_exits_1(tmp_path, capsys):
    bad = tmp_path / "bad.prior"
    bad.write_text("universe [sp_top_30]\nwhen [lower_bolinger]\n  buy [5% portfolio]\nsell when [after 5 bars]\n")
    assert main(["validate", str(bad)]) == 1
    err = capsys.readouterr().err
    assert "line 2" in err
    assert "lower_bollinger" in err  # did-you-mean


def test_fmt_prints_canonical(capsys):
    assert main(["fmt", BOLLINGER]) == 0
    out = capsys.readouterr().out
    assert out.startswith('strategy "Bollinger Reversal"')
    assert "  buy [5% portfolio]" in out


def test_compile_python(capsys):
    assert main(["compile", BOLLINGER]) == 0
    out = capsys.readouterr().out
    assert "def generate_signals(df):" in out
    assert "POSITION_SIZING" in out


def test_compile_json(capsys):
    assert main(["compile", BOLLINGER, "--json"]) == 0
    out = capsys.readouterr().out
    assert '"condition": "price_at_bollinger_band"' in out


def test_explain_shows_all_layers(capsys):
    assert main(["explain", BOLLINGER]) == 0
    out = capsys.readouterr().out
    assert "lower Bollinger band" in out          # English
    assert '"match_logic"' in out                  # JSON
    assert "def generate_signals" in out           # Python
    assert "stop loss 1.5% below entry" in out


def test_backtest_on_synthetic_csv(tmp_path, capsys):
    pd = pytest.importorskip("pandas")
    import numpy as np

    rng = np.random.default_rng(11)
    closes = 100 + np.cumsum(rng.normal(0, 0.9, 300))
    df = pd.DataFrame({
        "date": pd.date_range("2025-01-01", periods=300, freq="B"),
        "open": closes, "high": closes * 1.01, "low": closes * 0.99,
        "close": closes, "volume": 1_000_000,
    })
    data = tmp_path / "bars.csv"
    df.to_csv(data, index=False)

    assert main(["backtest", BOLLINGER, "--data", str(data)]) == 0
    out = capsys.readouterr().out
    assert "Total return" in out
    assert "Sharpe" in out
    assert "Trades" in out


def test_backtest_cloud_stub(capsys):
    assert main(["backtest", BOLLINGER, "--cloud"]) == 0
    assert "coming soon" in capsys.readouterr().out.lower()
