"""Free sample market data for instant starts.

`prior sample` lists the catalog; `prior sample crypto` downloads real,
redistributable bars so a first backtest works out of the gate with no
account and no API keys. Sources are chosen for licensing cleanliness:

- crypto: Binance public market data (real spot bars; USDT pairs
  relabeled to the -USD form the [crypto_majors] universe uses)
- stocks: Stooq daily history (sample/evaluation use)
- forex:  ECB reference rates (public domain; daily closes, so
  open/high/low equal close)

These are samples for trying the language, not research-grade datasets.
Full history, intraday, and options data live in AutoQuant.
"""

from __future__ import annotations

import os
import urllib.request
from pathlib import Path

BASE_URL = os.environ.get("PRIOR_SAMPLES_URL", "https://samples.autoquant.ai")
DEST_DIR = "prior-samples"

# (category, timeframe) -> catalog entry. Default timeframe first.
CATALOG: dict[tuple[str, str], dict] = {
    ("stocks", "1d"): {
        "file": "stocks_1d.csv.gz",
        "desc": "20 US large caps incl. SPY/QQQ, ~5 years of daily bars",
        "try": "universe $NVDA (or [mega_tech] names present in the file)",
    },
    ("crypto", "1d"): {
        "file": "crypto_1d.csv.gz",
        "desc": "The 8 [crypto_majors] pairs, ~5 years of daily bars",
        "try": "universe [crypto_majors]",
    },
    ("crypto", "1h"): {
        "file": "crypto_1h.csv.gz",
        "desc": "The 8 [crypto_majors] pairs, ~2 years of hourly bars",
        "try": "timeframe 1h with on 4h / on 1d gates",
    },
    ("forex", "1d"): {
        "file": "forex_1d.csv.gz",
        "desc": "7 majors (EURUSD, GBPUSD, USDJPY, ...), ~5 years of daily closes",
        "try": "when $EURUSD at [lower_bollinger] ...",
    },
}


def categories() -> list[str]:
    seen: list[str] = []
    for cat, _tf in CATALOG:
        if cat not in seen:
            seen.append(cat)
    return seen


def timeframes(category: str) -> list[str]:
    return [tf for (cat, tf) in CATALOG if cat == category]


def download(category: str, timeframe: str | None = None, dest_dir: str = DEST_DIR) -> Path:
    """Download one sample file into dest_dir; returns the local path."""
    cat = category.lower()
    if cat not in categories():
        raise SystemExit(
            f"no sample category {category!r} — available: {', '.join(categories())}"
            + ("\n(options has no free sample: real chain data cannot be "
               "redistributed, and the local CLI does not backtest options — "
               "options run in AutoQuant)" if cat == "options" else "")
        )
    tf = timeframe or timeframes(cat)[0]
    entry = CATALOG.get((cat, tf))
    if entry is None:
        raise SystemExit(
            f"{cat} samples come in: {', '.join(timeframes(cat))} (not {tf})"
        )
    url = f"{BASE_URL.rstrip('/')}/{entry['file']}"
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / entry["file"]
    req = urllib.request.Request(url, headers={"User-Agent": "prior-cli"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp, open(target, "wb") as f:
            f.write(resp.read())
    except Exception as e:
        raise SystemExit(
            f"could not download {url} ({e}) — check your connection, or set "
            "PRIOR_SAMPLES_URL if you mirror the samples"
        )
    return target
