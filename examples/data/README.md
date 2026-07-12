# Sample dataset

`sample_universe.csv` — **synthetic** OHLCV bars for every ticker in every
prebuilt universe (69 tickers): ~2 years of daily bars for equities and
ETFs, 2 years of calendar-day bars for crypto pairs.

This is NOT market data. It is generated (geometric brownian motion,
deterministic per ticker — see `scripts/generate_sample_data.py`) so the
toolchain is testable offline, in seconds, with zero data-licensing
strings attached. Ticker symbols are real; their prices here are not.

Try it:

```
prior backtest examples/mega_tech_capitulation.prior --data examples/data/sample_universe.csv
prior backtest examples/semis_trend_rider.prior      --data examples/data/sample_universe.csv
```

For real research, bring your own bars (`--data` accepts CSV, Parquet,
JSON, and JSONL from any source — broker exports, your own API pulls), or
run it in AutoQuant, where licensed full history is built in.
