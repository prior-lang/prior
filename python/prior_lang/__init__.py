"""PRIOR — a tiny declarative language for trading strategies.

    import prior_lang

    strategy = prior_lang.compile_source(open("my.prior").read())
    # → dict matching the open strategy-JSON interchange format

Public API: parse_source (→ Program), compile_source (→ JSON dict),
format_source (→ canonical text), PriorError.
"""

from .canonical import canonical_bytes, strategy_digest
from .decompile import strategy_from_json, strategy_to_source
from .plugins import PluginTag, load_env_plugins, register as register_plugin
from .errors import PriorError
from .formatter import format_program
from .parser import Program, parse_source

__version__ = "0.12.1"
__all__ = [
    "PriorError", "Program", "parse_source", "compile_source",
    "format_source", "strategy_to_source", "strategy_from_json",
    "strategy_digest", "canonical_bytes",
    "PluginTag", "register_plugin",
    "load_env_plugins", "schema_path", "load_schema", "__version__",
]

# Auto-discover plugin modules named in PRIOR_PLUGINS (comma-separated).
load_env_plugins()


def compile_source(source: str, filename: str = "<string>") -> dict:
    """Parse and validate .prior source, returning the strategy JSON dict."""
    return parse_source(source, filename).to_json()


def format_source(source: str, filename: str = "<string>") -> str:
    """Return the canonical formatting of .prior source."""
    return format_program(parse_source(source, filename))


def schema_path():
    """Path to the bundled JSON Schema for the strategy interchange.

    For pipelines that generate strategies and want a structural check
    before the compiler sees them. Shipped in the wheel, so this works
    from an installed package with no repo checkout.
    """
    from pathlib import Path
    return Path(__file__).with_name("strategy.schema.json")


def load_schema() -> dict:
    """The bundled JSON Schema, parsed.

        import json, jsonschema, prior_lang
        jsonschema.Draft202012Validator(prior_lang.load_schema()).validate(obj)

    Structural only. It cannot know whether a tag exists or whether its
    params are valid — compile_source is the authority. See SPEC.md §11.
    """
    import json
    return json.loads(schema_path().read_text())
