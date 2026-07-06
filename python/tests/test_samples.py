"""prior sample: free redistributable starter data (stocks/crypto/forex).

Downloads are mocked — these tests never touch the network.
"""

import gzip
import io
import subprocess
import sys
from unittest.mock import patch

import pytest

from prior_lang import samples

CSV = (
    "date,ticker,open,high,low,close,volume\n"
    "2026-01-05,BTC-USD,100,101,99,100.5,1000\n"
    "2026-01-06,BTC-USD,100.5,102,100,101.5,1100\n"
)


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_catalog_covers_the_three_categories():
    assert samples.categories() == ["stocks", "crypto", "forex"]
    assert samples.timeframes("crypto") == ["1d", "1h", "15m", "5m", "1m"]
    assert samples.timeframes("stocks") == ["1d", "1h", "15m", "5m", "1m"]


def test_download_writes_file(tmp_path):
    payload = gzip.compress(CSV.encode())
    with patch("urllib.request.urlopen", return_value=_FakeResponse(payload)):
        path = samples.download("crypto", None, dest_dir=str(tmp_path))
    assert path.name == "crypto_1d.csv.gz"
    assert gzip.decompress(path.read_bytes()).decode() == CSV


def test_downloaded_file_loads_as_bars(tmp_path):
    pd = pytest.importorskip("pandas")
    from prior_lang.backtest import load_bars

    payload = gzip.compress(CSV.encode())
    with patch("urllib.request.urlopen", return_value=_FakeResponse(payload)):
        path = samples.download("crypto", None, dest_dir=str(tmp_path))
    df = load_bars(str(path))
    assert "ticker" in df.columns
    assert len(df) == 2


def test_unknown_category_lists_options_hint():
    with pytest.raises(SystemExit, match="AutoQuant"):
        samples.download("options")
    with pytest.raises(SystemExit, match="stocks, crypto, forex"):
        samples.download("bonds")


def test_unknown_timeframe_lists_available():
    with pytest.raises(SystemExit, match="1d"):
        samples.download("stocks", "3h")


def test_cli_lists_catalog():
    proc = subprocess.run(
        [sys.executable, "-m", "prior_lang.cli", "sample"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0
    for word in ("stocks", "crypto", "forex", "prior-samples"):
        assert word in proc.stdout
    assert "AutoQuant" in proc.stdout  # the options explanation
