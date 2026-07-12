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
    # comments come first, preserved, then the canonical strategy line
    assert out.startswith("#")
    assert 'strategy "Bollinger Reversal"' in out
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


def test_backtest_multi_ticker_universe(tmp_path, capsys):
    pd = pytest.importorskip("pandas")
    import numpy as np

    # Strategy scoped to a manual two-ticker universe
    strat = tmp_path / "pair.prior"
    strat.write_text(
        "universe $AAPL $MSFT\n"
        "when [macd_cross_up]\n"
        "  buy [10% portfolio]\n"
        "sell when [macd_cross_down]\n"
    )

    # Stacked multi-ticker CSV: AAPL + MSFT (in universe) + TSLA (not)
    rng = np.random.default_rng(3)
    frames = []
    for ticker in ("AAPL", "MSFT", "TSLA"):
        closes = 100 + np.cumsum(rng.normal(0, 1.0, 200))
        frames.append(pd.DataFrame({
            "date": pd.date_range("2025-01-01", periods=200, freq="B"),
            "ticker": ticker, "close": closes, "volume": 1_000_000,
        }))
    data = tmp_path / "universe.csv"
    pd.concat(frames).to_csv(data, index=False)

    assert main(["backtest", str(strat), "--data", str(data)]) == 0
    out = capsys.readouterr().out
    assert "2 tickers" in out            # AAPL + MSFT ran
    assert "AAPL" in out and "MSFT" in out
    assert "skipped (in file, not in universe): TSLA" in out
    assert "average" in out
    assert "independent per-ticker runs" in out


def test_backtest_accepts_json_and_jsonl_data(tmp_path, capsys):
    pd = pytest.importorskip("pandas")
    import numpy as np

    rng = np.random.default_rng(5)
    closes = 100 + np.cumsum(rng.normal(0, 1.0, 150))
    df = pd.DataFrame({
        "date": pd.date_range("2025-01-01", periods=150, freq="B").strftime("%Y-%m-%d"),
        "close": closes, "volume": 1_000_000,
    })
    as_json = tmp_path / "bars.json"
    as_jsonl = tmp_path / "bars.jsonl"
    df.to_json(as_json, orient="records")
    df.to_json(as_jsonl, orient="records", lines=True)

    strat = tmp_path / "s.prior"
    strat.write_text(
        "universe $SPY\nwhen [macd_cross_up]\n  buy [10% portfolio]\nsell when [macd_cross_down]\n"
    )
    for data in (as_json, as_jsonl):
        assert main(["backtest", str(strat), "--data", str(data)]) == 0
        assert "Total return" in capsys.readouterr().out


def test_strategy_json_input_all_verbs(tmp_path, capsys):
    """The interchange .json is a first-class strategy input; fmt converts it to .prior."""
    # Produce JSON from the bollinger example, then feed it back
    out_json = tmp_path / "strategy.json"
    assert main(["compile", BOLLINGER, "--json", "--out", str(out_json)]) == 0
    capsys.readouterr()

    assert main(["validate", str(out_json)]) == 0
    assert "ok" in capsys.readouterr().out

    assert main(["fmt", str(out_json)]) == 0
    out = capsys.readouterr().out
    assert out.startswith('strategy "Bollinger Reversal"')  # JSON → .prior text

    assert main(["compile", str(out_json)]) == 0
    assert "def generate_signals" in capsys.readouterr().out


def test_sample_dataset_runs_example_universe(capsys):
    pytest.importorskip("pandas")
    sample = EXAMPLES / "data" / "sample_universe.csv"
    assert sample.exists()
    strat = str(EXAMPLES / "mega_tech_capitulation.prior")
    assert main(["backtest", strat, "--data", str(sample)]) == 0
    out = capsys.readouterr().out
    assert "15 tickers" in out  # full mega_tech universe present
    assert "average" in out


