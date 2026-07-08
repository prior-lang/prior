"""PRIOR — a tiny declarative language for trading strategies.

    import prior_lang

    strategy = prior_lang.compile_source(open("my.prior").read())
    # → dict matching the open strategy-JSON interchange format

Public API: parse_source (→ Program), compile_source (→ JSON dict),
format_source (→ canonical text), PriorError.
"""

from .decompile import strategy_to_source
from .plugins import PluginTag, load_env_plugins, register as register_plugin
from .errors import PriorError
from .formatter import format_program
from .parser import Program, parse_source

__version__ = "0.8.1"
__all__ = [
    "PriorError", "Program", "parse_source", "compile_source",
    "format_source", "strategy_to_source", "PluginTag", "register_plugin",
    "load_env_plugins", "__version__",
]

# Auto-discover plugin modules named in PRIOR_PLUGINS (comma-separated).
load_env_plugins()


def compile_source(source: str, filename: str = "<string>") -> dict:
    """Parse and validate .prior source, returning the strategy JSON dict."""
    return parse_source(source, filename).to_json()


def format_source(source: str, filename: str = "<string>") -> str:
    """Return the canonical formatting of .prior source."""
    return format_program(parse_source(source, filename))
