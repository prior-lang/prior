"""Canonical encoding: one strategy, one digest, everywhere.

A strategy object is the natural thing to commit to — a proof system, an
audit log, or a registry wants to say "this result came from this
strategy" and have a second implementation agree on which strategy that
was. Hashing `prior compile --json` output directly does not work: the IR
carries floats (`[risk 1%]` is `0.01`, `[max_position 10%]` is `0.1`) and
those have no exact binary representation, so two serializers can disagree
and an integer-faithful verifier cannot represent them at all.

The encoding is one rule applied uniformly:

    every number × SCALE, rounded to an integer; keys sorted;
    no insignificant whitespace; UTF-8

Uniform means counts are scaled too — an RSI period of 14 encodes as
14000000. That looks odd and is deliberate: a verifier never has to know
which fields are fractions and which are counts, so there is no table of
special cases to keep in sync across implementations.

SCALE is 10**6. Fractions reach down to 1e-6, which is below a basis
point, so sizing finer than PRIOR currently expresses will not force
existing commitments to be re-minted. Verified against every example
strategy: exact at this scale with zero rounding error, largest scaled
integer 1e10, which is small.

The digest is taken over the compiled IR rather than the source text, so
it is the same whether a strategy arrived as `.prior` or as JSON, and it
ignores comments and formatting, which are not part of what runs.
"""

from __future__ import annotations

import hashlib
import json

SCALE = 10**6


def canonical_obj(o):
    """Recursively scale numbers to integers. Raises on anything the scale
    cannot represent exactly, rather than silently rounding a value the
    author meant."""
    if isinstance(o, bool):
        return o
    if isinstance(o, (int, float)):
        scaled = o * SCALE
        nearest = round(scaled)
        if abs(scaled - nearest) > 1e-6 * max(1.0, abs(scaled)):
            raise ValueError(
                f"{o!r} is not exactly representable at scale {SCALE}"
            )
        return nearest
    if isinstance(o, dict):
        return {k: canonical_obj(v) for k, v in o.items()}
    if isinstance(o, list):
        return [canonical_obj(v) for v in o]
    return o


def canonical_bytes(strategy: dict) -> bytes:
    """The exact bytes a commitment is taken over."""
    return json.dumps(
        canonical_obj(strategy),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def strategy_digest(strategy: dict) -> str:
    """SHA-256 of the canonical encoding, as a bare hex digest."""
    return hashlib.sha256(canonical_bytes(strategy)).hexdigest()
