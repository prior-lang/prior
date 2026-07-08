"""PRIOR Cloud client — hosted full-history backtests.

A thin HTTP client for the hosted backtest service (`prior backtest
--cloud`). Sign in with `prior login` (email code, no password). Free
accounts get a few taster runs; PRIOR Cloud is a paid plan after that.

The client sends your .prior source and receives metrics, a downsampled
equity curve, and a bounded trade list. Bar data never flows through this
code path — the CLI stays a pure language tool.

Uses only the standard library (urllib), like the rest of the core.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_URL = "https://license.autoquant.ai"
CRED_PATH = Path.home() / ".prior" / "credentials.json"
UPGRADE_PAGE = "https://autoquant.ai/prior/cloud"


class CloudError(Exception):
    """A cloud request failed; str(e) is a printable message."""

    def __init__(self, message: str, detail: dict | None = None, status: int = 0):
        super().__init__(message)
        self.detail = detail or {}
        self.status = status


def _base_url() -> str:
    return os.environ.get("PRIOR_CLOUD_URL", DEFAULT_URL).rstrip("/")


def _http(method: str, path: str, payload: dict | None = None,
          token: str | None = None) -> dict:
    url = _base_url() + path
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "prior-cli")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode() or "{}")
        except Exception:
            body = {}
        detail = body.get("detail")
        if isinstance(detail, dict):
            msg = detail.get("message") or detail.get("error") or str(detail)
        else:
            msg = str(detail) if detail else f"HTTP {e.code}"
        raise CloudError(msg, detail if isinstance(detail, dict) else {}, e.code)
    except urllib.error.URLError as e:
        raise CloudError(f"could not reach {_base_url()} ({e.reason})")


# ── Credentials ───────────────────────────────────────────────────

def load_credentials() -> dict | None:
    try:
        return json.loads(CRED_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def save_credentials(creds: dict) -> None:
    CRED_PATH.parent.mkdir(parents=True, exist_ok=True)
    CRED_PATH.write_text(json.dumps(creds, indent=2))
    CRED_PATH.chmod(0o600)


def clear_credentials() -> bool:
    if CRED_PATH.exists():
        CRED_PATH.unlink()
        return True
    return False


def require_token() -> str:
    creds = load_credentials()
    if not creds or not creds.get("token"):
        raise SystemExit(
            "cloud runs need an account — run: prior login\n"
            "(free accounts include taster runs; no password, just an email code)"
        )
    return creds["token"]


# ── API calls ─────────────────────────────────────────────────────

def request_code(email: str) -> None:
    _http("POST", "/prior/auth/request-code", {"email": email})


def verify_code(email: str, code: str) -> dict:
    out = _http("POST", "/prior/auth/verify", {"email": email, "code": code})
    save_credentials({
        "token": out["token"],
        "email": out.get("email", email),
        "expires_at": out.get("expires_at"),
    })
    return out


def get_quota(token: str) -> dict:
    return _http("GET", "/prior/quota", token=token)


def submit_backtest(token: str, source: str, params: dict) -> dict:
    return _http("POST", "/prior/backtest", {"source": source, "params": params}, token=token)


def get_run(token: str, run_id: int) -> dict:
    return _http("GET", f"/prior/runs/{run_id}", token=token)


def checkout_url(token: str) -> str:
    out = _http("POST", "/billing/checkout/create-session", {
        "plan": "prior_cloud",
        "success_url": UPGRADE_PAGE + "?checkout=success",
        "cancel_url": UPGRADE_PAGE + "?checkout=cancelled",
    }, token=token)
    return out["checkout_url"]


def wait_for_result(token: str, run_id: int, timeout: float = 300.0) -> dict:
    """Poll until the run finishes; prints queue progress. Returns the run body."""
    started = time.time()
    last_line = ""
    while True:
        body = get_run(token, run_id)
        status = body["status"]
        if status in ("done", "error"):
            if last_line:
                print()
            return body
        pos = body.get("queue_position")
        line = f"  {status}" + (f" (position {pos})" if status == "queued" and pos else "")
        if line != last_line:
            print(line)
            last_line = line
        if time.time() - started > timeout:
            raise CloudError(
                f"run {run_id} still {status} after {int(timeout)}s — check later "
                f"with: prior cloud runs {run_id}"
            )
        time.sleep(2.0)


# ── Rendering (mirrors the local backtest tables) ─────────────────

def _print_rows(rows: list) -> None:
    width = max(len(label) for label, _ in rows)
    for label, value in rows:
        print(f"  {label:<{width}}  {value}")


def _pct(v):
    return f"{v}%" if v is not None else "n/a"


def _print_trades(trades: list, truncated: int) -> None:
    if not trades:
        print("  no trades")
        return
    print(f"  {'ENTRY':<12} {'EXIT':<12} {'DIR':<6} {'IN':>10} {'OUT':>10} {'BARS':>5} {'RET%':>8}  EXIT")
    for t in trades:
        print(
            f"  {t['entry_date']:<12} {t['exit_date']:<12} {t['direction']:<6}"
            f" {t['entry_price']:>10} {t['exit_price']:>10} {t['bars_held']:>5}"
            f" {float(t['return_pct']):>8.2f}  {t['exit_reason']}"
        )
    if truncated:
        print(f"  (+{truncated} earlier trades not shown)")


def render_result(name: str, body: dict, args) -> int:
    result = body["result"]
    kind = result["kind"]
    m = result["metrics"]
    meta = result.get("meta", {})
    span = f"{meta.get('data_start')} to {meta.get('data_end')}"

    if getattr(args, "as_json", False):
        print(json.dumps(result, indent=2))
        return 0

    if getattr(args, "equity", None) and result.get("equity"):
        with open(args.equity, "w") as f:
            f.write("date,equity\n")
            for d, v in result["equity"]:
                f.write(f"{d},{v}\n")

    if kind == "single":
        print(f"{name} — {m['bars']} bars of cloud history ({span})")
        rows = [
            ("Total return", _pct(m["total_return_pct"])),
            ("Buy & hold", _pct(m["buy_hold_return_pct"])),
            ("CAGR", _pct(m["cagr_pct"])),
            ("Sharpe", m["sharpe"]),
            ("Volatility", _pct(m["volatility_pct"])),
            ("Max drawdown", _pct(m["max_drawdown_pct"])),
            ("Trades", m["trades"]),
            ("Win rate", _pct(m["win_rate_pct"])),
            ("Avg trade", _pct(m["avg_trade_pct"])),
        ]
        if m.get("capital"):
            rows = [
                ("Starting capital", f"${m['capital']:,.2f}"),
                ("Final equity", f"${m['final_equity_usd']:,.2f}"),
                ("Net P&L", f"${m['net_pnl_usd']:,.2f}"),
            ] + rows
        _print_rows(rows)
        if getattr(args, "trades", False):
            print("\nTrades:")
            _print_trades(result.get("trades") or [], result.get("trades_truncated", 0))

    elif kind == "universe":
        rows = m.get("per_ticker") or []
        print(f"{name} — {len(rows)} tickers, cloud history ({span}, independent runs)")
        print(f"  {'TICKER':<9} {'RETURN':>8} {'B&H':>8} {'SHARPE':>7} {'MAXDD':>7} {'TRADES':>6} {'WIN%':>6}")
        for r in sorted(rows, key=lambda x: x["total_return_pct"], reverse=True):
            win = f"{r['win_rate_pct']:.0f}" if r.get("win_rate_pct") is not None else "–"
            print(
                f"  {r['ticker']:<9} {r['total_return_pct']:>7.2f}% {r['buy_hold_return_pct']:>7.2f}%"
                f" {r['sharpe']:>7.3f} {r['max_drawdown_pct']:>6.2f}% {r['trades']:>6} {win:>6}"
            )
        print(f"  {'':<9} {'-------':>8}")
        print(f"  {'average':<9} {m['avg_return_pct']:>7.2f}%{'':<17} total trades: {m['total_trades']}")
        if meta.get("missing_tickers"):
            print(f"\n  no cloud data yet for: {', '.join(meta['missing_tickers'])}")

    elif kind == "pair":
        print(f"{name} — {m['pair']} spread (price {m['form']}), cloud history ({span})")
        _print_rows([
            ("Total return", _pct(m["total_return_pct"])),
            ("CAGR", _pct(m["cagr_pct"])),
            ("Sharpe", m["sharpe"]),
            ("Max drawdown", _pct(m["max_drawdown_pct"])),
            ("Spread start → end", f"{m['spread_start']} → {m['spread_end']}"),
            ("Trades", m["trades"]),
            ("Win rate", _pct(m["win_rate_pct"])),
            ("Avg trade", _pct(m["avg_trade_pct"])),
        ])
        if getattr(args, "trades", False):
            print("\nTrades (IN/OUT are spread values):")
            _print_trades(result.get("trades") or [], result.get("trades_truncated", 0))

    elif kind == "ranking":
        print(f"{name} — portfolio of {m['tickers']} tickers, cloud history ({span})")
        rows = [
            ("Total return", _pct(m["total_return_pct"])),
            ("Equal-weight universe", _pct(m["equal_weight_universe_pct"])),
            ("CAGR", _pct(m["cagr_pct"])),
            ("Sharpe", m["sharpe"]),
            ("Max drawdown", _pct(m["max_drawdown_pct"])),
            ("Rebalances", m["rebalances"]),
            ("Avg turnover", _pct(m["avg_turnover_pct"])),
        ]
        _print_rows(rows)
        if m.get("holdings"):
            pretty = ", ".join(f"{t} {float(w) * 100:.0f}%" for t, w in m["holdings"])
            print(f"  {'Current holdings':<22}  {pretty}")

    else:
        print(json.dumps(result, indent=2))

    if getattr(args, "equity", None) and result.get("equity"):
        print(f"\n  equity curve written to {args.equity}")
    return 0
