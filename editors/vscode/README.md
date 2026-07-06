# PRIOR for Visual Studio Code

Language support for [PRIOR](https://github.com/prior-lang/prior), the tiny declarative language for trading strategies.

```prior
when $NVDA at [lower_bollinger std=1]
  buy [5% portfolio]

sell when $NVDA at [middle_bollinger]
  or [stop 1.5%]
  or [after 5 bars]
```

## Features

- **Syntax highlighting** for `.prior` files — keywords, tags, tickers, spreads, timeframes
- **Completions** for the full tag vocabulary, with parameter placeholders and per-tag docs
- **Hovers** — what `[lower_bollinger]` actually expands to, every parameter and default, prebuilt universe contents
- **Diagnostics as you type** — the real compiler's errors, line-precise, with did-you-mean suggestions
- **Formatting** — `prior fmt` as the document formatter (canonical statement order and spacing)
- **Snippets** — `strategy-meanreversion`, `strategy-momentum`, `strategy-wheel`, `strategy-pairs`, `strategy-mixed`

## Requirements

Highlighting, completions, and hovers work out of the box. Diagnostics and formatting shell out to the prior CLI so the editor reports exactly what the compiler will say:

```
pip install prior-lang
```

If `prior` isn't on your PATH, the extension falls back to `python3 -m prior_lang.cli`, or set `prior.command` in settings.

## Settings

| Setting | Default | Description |
|---|---|---|
| `prior.command` | `prior` | Command for the prior CLI |
| `prior.validateOnType` | `true` | Validate as you type (debounced); off = validate on save only |

## Learn more

- [Language specification](https://github.com/prior-lang/prior/blob/main/spec/SPEC.md)
- [Tag reference](https://github.com/prior-lang/prior/blob/main/spec/TAGS.md)
- [Guides and tutorials](https://autoquant.ai/prior)

PRIOR is built and stewarded by [AutoQuant](https://autoquant.ai).
