"""Generate the bundled sample dataset: examples/data/sample_universe.csv

SYNTHETIC data — geometric brownian motion with per-asset-class drift and
volatility, deterministic per ticker (seeded from the ticker name), so
regenerating always produces the identical file. Covers every ticker in
every prebuilt universe, so all example strategies run out of the box:

    prior backtest examples/mega_tech_capitulation.prior \\
        --data examples/data/sample_universe.csv

This is NOT market data. It exists so the toolchain is testable offline
in seconds. For real research, bring your own bars (--data) or run it in
AutoQuant, where licensed full history is built in.

Regenerate:  python scripts/generate_sample_data.py
"""

from __future__ import annotations

import sys
import zlib
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1] / "python"))
from prior_lang.tags import UNIVERSE_TICKERS  # noqa: E402

END_DATE = "2026-07-03"          # fixed so output is stable
EQUITY_BARS = 504                # ~2 trading years
CRYPTO_BARS = 730                # 2 calendar years, 24/7

OUT = Path(__file__).parents[1] / "examples" / "data" / "sample_universe.csv"


def _series(ticker: str, is_crypto: bool, is_etf: bool) -> pd.DataFrame:
    seed = zlib.crc32(ticker.encode())
    rng = np.random.default_rng(seed)

    if is_crypto:
        n, freq = CRYPTO_BARS, "D"
        mu, sigma = 0.0006, rng.uniform(0.030, 0.065)
        price0 = rng.uniform(0.1, 400) if ticker != "BTC-USD" else 60_000.0
    elif is_etf:
        n, freq = EQUITY_BARS, "B"
        mu, sigma = 0.0003, rng.uniform(0.008, 0.014)
        price0 = rng.uniform(30, 220)
    else:
        n, freq = EQUITY_BARS, "B"
        mu, sigma = 0.0004, rng.uniform(0.012, 0.026)
        price0 = rng.uniform(20, 600)

    close = price0 * np.exp(np.cumsum(rng.normal(mu, sigma, n)))
    gap = rng.normal(0, sigma / 3, n)
    intra = np.abs(rng.normal(0, sigma / 2, n))
    open_ = np.empty(n)
    open_[0] = close[0]
    open_[1:] = close[:-1] * (1 + gap[1:])
    high = np.maximum(open_, close) * (1 + intra)
    low = np.minimum(open_, close) * (1 - intra)
    volume = (rng.lognormal(13.5, 0.6, n)).astype(np.int64)

    dates = pd.date_range(end=END_DATE, periods=n, freq=freq)
    return pd.DataFrame({
        "date": dates.strftime("%Y-%m-%d"),
        "ticker": ticker,
        "open": np.round(open_, 4),
        "high": np.round(high, 4),
        "low": np.round(low, 4),
        "close": np.round(close, 4),
        "volume": volume,
    })


def main() -> None:
    tickers: dict[str, tuple[bool, bool]] = {}
    for key, members in UNIVERSE_TICKERS.items():
        for t in members:
            tickers.setdefault(t, (key == "crypto_majors", key == "etf_sectors"))

    frames = [
        _series(t, is_crypto, is_etf)
        for t, (is_crypto, is_etf) in sorted(tickers.items())
    ]
    df = pd.concat(frames, ignore_index=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT, index=False)
    print(f"wrote {OUT} — {len(tickers)} tickers, {len(df):,} rows, "
          f"{OUT.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
