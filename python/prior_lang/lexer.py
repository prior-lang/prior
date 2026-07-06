"""Lexer: source text → logical lines of tokens.

Line-oriented per SPEC.md §2. A physical line whose first token is `and`,
`or`, or `buy` continues the previous logical line; indentation is
cosmetic. Keywords and tag names are case-insensitive (lowercased here);
tickers are uppercased.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .errors import PriorError

KEYWORDS = {
    "strategy", "universe", "timeframe", "when", "if", "buy", "sell", "risk",
    "short", "cover",
    "hold", "rebalance", "top", "bottom", "by", "where", "weighted", "equally",
    "and", "or", "at", "above", "below", "crosses", "price", "volume",
}
RESERVED = {"on"}

_TIMEFRAME_RE = re.compile(r"\d+[mhdw]\b")
_NUMBER_RE = re.compile(r"\d+(\.\d+)?")
_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")
_TICKER_RE = re.compile(r"[A-Za-z][A-Za-z0-9\-]*")


@dataclass
class Token:
    kind: str   # word | keyword | string | number | percent | dollar | mult
                # | timeframe | ticker | lbrack | rbrack | lparen | rparen
                # | op | eq
    value: object
    raw: str
    line: int
    col: int


@dataclass
class LogicalLine:
    tokens: list[Token]
    line: int              # first physical line number (1-based)
    source: str            # first physical line text, for error rendering
    sources: dict[int, str] = field(default_factory=dict)  # line no → text


def _lex_line(text: str, lineno: int) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in " \t":
            i += 1
            continue
        if ch == "#":
            break  # comment to end of line
        col = i

        if ch == '"':
            end = text.find('"', i + 1)
            if end == -1:
                raise PriorError(
                    "unterminated string", line=lineno, col=col, source_line=text,
                    suggestion='close the quote: strategy "My Strategy"',
                )
            tokens.append(Token("string", text[i + 1:end], text[i:end + 1], lineno, col))
            i = end + 1
            continue

        if ch == "[":
            tokens.append(Token("lbrack", "[", "[", lineno, col)); i += 1; continue
        if ch == "]":
            tokens.append(Token("rbrack", "]", "]", lineno, col)); i += 1; continue
        if ch == "(":
            tokens.append(Token("lparen", "(", "(", lineno, col)); i += 1; continue
        if ch == ")":
            tokens.append(Token("rparen", ")", ")", lineno, col)); i += 1; continue

        if ch == "$":
            rest = text[i + 1:]
            m = _NUMBER_RE.match(rest)
            if m:  # $10000 — dollar amount
                tokens.append(Token("dollar", float(m.group()), text[i:i + 1 + m.end()], lineno, col))
                i += 1 + m.end()
                continue
            m = _TICKER_RE.match(rest)
            if m:  # $NVDA, $BTC-USD — ticker
                tokens.append(Token("ticker", m.group().upper(), text[i:i + 1 + m.end()], lineno, col))
                i += 1 + m.end()
                continue
            raise PriorError(
                "a '$' must start a ticker ($NVDA) or a dollar amount ($10000)",
                line=lineno, col=col, source_line=text,
            )

        if ch.isdigit():
            m = _TIMEFRAME_RE.match(text, i)
            if m:
                tokens.append(Token("timeframe", m.group(), m.group(), lineno, col))
                i = m.end()
                continue
            m = _NUMBER_RE.match(text, i)
            raw = m.group()
            end = m.end()
            if end < n and text[end] == "%":
                tokens.append(Token("percent", float(raw), raw + "%", lineno, col))
                i = end + 1
                continue
            if end < n and text[end] == "x" and (end + 1 == n or not text[end + 1].isalnum()):
                tokens.append(Token("mult", float(raw), raw + "x", lineno, col))
                i = end + 1
                continue
            tokens.append(Token("number", float(raw), raw, lineno, col))
            i = end
            continue

        if text.startswith("==", i):
            raise PriorError(
                "'==' never fires on real prices — floats are almost never exactly equal",
                line=lineno, col=col, source_line=text,
                suggestion="use 'at' for touch semantics: price at [lower_bollinger]",
            )
        if text.startswith("<=", i) or text.startswith(">=", i):
            tokens.append(Token("op", text[i:i + 2], text[i:i + 2], lineno, col)); i += 2; continue
        if ch in "<>":
            tokens.append(Token("op", ch, ch, lineno, col)); i += 1; continue
        if ch == "=":
            tokens.append(Token("eq", "=", "=", lineno, col)); i += 1; continue

        m = _WORD_RE.match(text, i)
        if m:
            raw = m.group()
            low = raw.lower()
            if "." in low:
                raise PriorError(
                    f"namespaced tags like '{raw}' are reserved for third-party tags in a future version",
                    line=lineno, col=col, source_line=text,
                )
            kind = "keyword" if low in KEYWORDS else "word"
            tokens.append(Token(kind, low, raw, lineno, col))
            i = m.end()
            continue

        raise PriorError(
            f"unexpected character {ch!r}", line=lineno, col=col, source_line=text,
        )
    return tokens


def tokenize(source: str) -> list[LogicalLine]:
    """Lex the whole file into logical lines (continuations merged)."""
    logical: list[LogicalLine] = []
    for lineno, text in enumerate(source.splitlines(), start=1):
        toks = _lex_line(text, lineno)
        if not toks:
            continue
        first = toks[0]
        is_continuation = first.kind == "keyword" and first.value in ("and", "or", "buy", "short", "where", "weighted")
        if is_continuation:
            if not logical:
                raise PriorError(
                    f"'{first.raw}' continues a previous line, but there isn't one",
                    line=lineno, col=first.col, source_line=text,
                )
            logical[-1].tokens.extend(toks)
            logical[-1].sources[lineno] = text
        else:
            logical.append(LogicalLine(tokens=toks, line=lineno, source=text, sources={lineno: text}))
    return logical
