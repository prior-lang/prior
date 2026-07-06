"""prior trace — the "why didn't it fire" debugger.

Every condition in a PRIOR strategy is a pure series, so any bar can be
interrogated: this module evaluates each entry/exit condition in
isolation and reports its verdict on the requested date(s), alongside
the position state from the traced signal run.

Window is capped at TRACE_MAX_BARS per report BY DESIGN, not just for
tidiness: the same output contract will serve hosted/licensed data one
day, where an uncapped per-bar dump of verdicts and values would be a
bar-series reconstruction channel (DATA_SECURITY_PLAN S7). Locally the
data is the user's own file — the cap simply keeps the contract
identical everywhere.
"""

from __future__ import annotations

import math

from .codegen import _htf_preamble, _split_condition_blocks, compile_strategy
from .errors import PriorError
from .explain import _condition_text

TRACE_MAX_BARS = 10


def _require_pandas():
    try:
        import numpy as np
        import pandas as pd
        return pd, np
    except ImportError as e:  # pragma: no cover
        raise SystemExit(
            "prior trace needs pandas and numpy: pip install 'prior-lang[backtest]'"
        ) from e


def _cond_series(cond: dict, df):
    """Evaluate ONE condition dict over df -> bool Series."""
    pd, np = _require_pandas()
    c = {"type": cond["condition"], "params": cond.get("params", {}),
         **({"timeframe": cond["timeframe"]} if cond.get("timeframe") else {})}
    helpers, body, expr, tfs = _split_condition_blocks([c], "all", "tc")
    htf = _htf_preamble(tfs)
    code = (
        helpers
        + "def _tcond(df):\n"
        + '    close = df["close"]\n'
        + htf
        + body
        + f"\n    return ({expr}).fillna(False)\n"
    )
    ns = {"pd": pd, "np": np, "math": math}
    exec(code, ns)  # our own generated code
    return ns["_tcond"](df)


def _rules_of(strategy: dict) -> list[dict]:
    if strategy.get("rules"):
        return [
            {"direction": r.get("direction", "long"),
             "match_logic": r.get("match_logic", "all"),
             "conditions": r["conditions"]}
            for r in strategy["rules"]
        ]
    e = strategy["entry"]
    return [{"direction": strategy.get("direction", "long"),
             "match_logic": e.get("match_logic", "all"),
             "conditions": e["conditions"]}]


def _exit_specs(strategy: dict) -> list[tuple[str, dict]]:
    if strategy.get("exits"):
        return [("sell when", strategy["exits"]["long"]),
                ("cover when", strategy["exits"]["short"])]
    kw = "cover when" if strategy.get("direction") == "short" else "sell when"
    return [(kw, strategy.get("exit", {}) or {})]


def trace_report(strategy: dict, df, date=None, last: int = 1) -> dict:
    """Verdict of every condition on the last `last` bars ending at
    `date` (default: the final bar). Returns a dict of per-date rows."""
    pd, np = _require_pandas()
    if strategy.get("options"):
        raise PriorError("trace covers stock strategies — options run in AutoQuant")
    if strategy.get("ranking"):
        raise PriorError(
            "trace inspects when/sell conditions — ranking strategies decide by "
            "rank at rebalances (a rank trace is planned)"
        )

    last = max(1, min(int(last), TRACE_MAX_BARS))

    # Position context from the traced run (signals are the ground truth).
    code = compile_strategy(strategy, trace=True)
    ns = {"pd": pd, "np": np, "math": math}
    exec(code, ns)  # our own generated code
    signals, _events = ns["generate_signals_traced"](df)

    if date is not None:
        ts = pd.Timestamp(date)
        idx = df.index[df.index <= ts]
        if len(idx) == 0:
            raise SystemExit(f"no bars at or before {date} in the data")
        end_pos = df.index.get_loc(idx[-1])
    else:
        end_pos = len(df) - 1
    positions = range(max(0, end_pos - last + 1), end_pos + 1)

    # One isolated series per condition, evaluated once for all dates.
    rule_rows = []
    for r, rule in enumerate(_rules_of(strategy)):
        rule_rows.append({
            "rule": r,
            "direction": rule["direction"],
            "match_logic": rule["match_logic"],
            "conditions": [
                {"text": _condition_text(c), "series": _cond_series(c, df)}
                for c in rule["conditions"]
            ],
        })
    exit_rows = []
    for kw, spec in _exit_specs(strategy):
        conds = spec.get("conditions") or []
        exit_rows.append({
            "keyword": kw,
            "conditions": [
                {"text": _condition_text(c), "series": _cond_series(c, df)}
                for c in conds
            ],
        })

    dates = []
    for pos in positions:
        ts = df.index[pos]
        sig = float(signals.iloc[pos])
        dates.append({
            "date": str(getattr(ts, "date", lambda: ts)()),
            "bar": pos,
            "signal": sig,
            "rules": [
                {
                    "rule": rr["rule"],
                    "direction": rr["direction"],
                    "match_logic": rr["match_logic"],
                    "conditions": [
                        {"text": c["text"], "verdict": bool(c["series"].iloc[pos])}
                        for c in rr["conditions"]
                    ],
                }
                for rr in rule_rows
            ],
            "exits": [
                {
                    "keyword": er["keyword"],
                    "conditions": [
                        {"text": c["text"], "verdict": bool(c["series"].iloc[pos])}
                        for c in er["conditions"]
                    ],
                }
                for er in exit_rows
            ],
        })
    return {"bars": len(df), "dates": dates}
