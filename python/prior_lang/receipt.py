"""Backtest receipts: make a result say what produced it.

`prior backtest --json` reports metrics and nothing else, so a result is
unattributable — the numbers do not record which strategy ran, on which
bars, or under what costs. Publish that and a reader has to take all three
on trust, which is the gap between "the code is honest" and "the claim is
honest".

A receipt binds them together: a digest of the strategy, a digest of the
data, the cost assumptions, the window, and the metrics.

The strategy digest is taken over the **canonical source with comments
stripped** (SPEC §8), not over the interchange JSON. Two reasons. Canonical
text carries no floats — `[stop 3%]` stays the characters `3%` rather than
becoming 0.03, which has no exact binary representation — so the digest
reproduces across implementations. And it is door-independent: the same
strategy hashes identically whether it arrived as `.prior` text or as JSON,
because both render to the same canonical form. Comments are documentation
rather than semantics, so they are excluded; two strategies that differ
only in commentary are the same strategy.

This is a claim about provenance, not about honesty. A receipt says these
metrics came from this strategy on this data at these costs. It cannot say
how many other strategies you tried first — see LIMITS.md §5.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

_CHUNK = 1 << 20


def file_digest(path: str) -> str:
    """SHA-256 of a file's bytes, streamed so large bar files are fine."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(_CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def strategy_digest(program) -> str:
    """SHA-256 of the canonical source, comments stripped.

    Takes a parsed Program so the caller cannot accidentally hash
    non-canonical text.
    """
    from .formatter import format_program

    canonical = format_program(program, include_comments=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_receipt(
    *,
    program,
    strategy: dict,
    data_path: str,
    metrics: dict,
    prior_version: str,
    capital=None,
    fee_bps=None,
    slippage_bps=None,
    contract_fee=None,
    date_from=None,
    date_to=None,
    bars=None,
    first_bar=None,
    last_bar=None,
) -> dict:
    return {
        "receipt": "prior/1",
        "prior_version": prior_version,
        "strategy": {
            "name": strategy.get("name"),
            "digest": f"sha256:{strategy_digest(program)}",
            "timeframe": strategy.get("timeframe"),
            "direction": strategy.get("direction"),
        },
        "data": {
            "file": Path(data_path).name,
            "digest": f"sha256:{file_digest(data_path)}",
            "bars": bars,
            "first_bar": first_bar,
            "last_bar": last_bar,
        },
        "assumptions": {
            "capital": capital,
            "fee_bps": fee_bps,
            "slippage_bps": slippage_bps,
            "contract_fee": contract_fee,
            "window_from": date_from,
            "window_to": date_to,
        },
        "metrics": metrics,
    }
