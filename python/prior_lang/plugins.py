"""Third-party tags: the developer escape hatch, below the language.

A plugin registers namespaced condition tags ([acme.momo]) with their own
pandas emitters. The language grammar never grows — plugins extend the
vocabulary, exactly like core tags, and everything else (multi-timeframe
suffixes, and/or logic, explain, fmt) applies to them for free.

    from prior_lang.plugins import PluginTag, register

    register(PluginTag(
        name="acme.momo",
        params=[("period", "number", 20)],
        emit=lambda p: (
            f"mom = close / close.shift({int(p['period'])}) - 1\\n"
            f"    cond = (mom > 0).fillna(False)"
        ),
        readback=lambda p: f"acme momentum({int(p['period'])}) is positive",
    ))

Auto-discovery: every module named in the PRIOR_PLUGINS environment
variable (comma-separated) is imported at package load; importing it
should call register(). Plugin conditions compile locally through the
plugin's emitter — they are a prior-lang runtime feature.

v1 scope: predicate tags only (complete conditions used bare in when/
where/sell expressions). Operand plugins (custom [acme.x] < 5) come
later.
"""

from __future__ import annotations

import importlib
import os
from dataclasses import dataclass, field
from typing import Callable

from .tags import TAGS, Param, TagSpec

# name → PluginTag, for emitters and readbacks
PLUGIN_TAGS: dict[str, "PluginTag"] = {}

_VALUE_KINDS = {"number", "percent", "dollar", "mult", "word"}


@dataclass
class PluginTag:
    name: str                                   # namespaced: "vendor.tag"
    emit: Callable[[dict], str]                 # params → pandas snippet assigning `cond`
    params: list = field(default_factory=list)  # [(name, kind, default)] — default None = required
    readback: Callable[[dict], str] | None = None
    usage: str = "predicate"


def register(tag: PluginTag) -> None:
    if "." not in tag.name:
        raise ValueError(
            f"plugin tags are namespaced: 'vendor.{tag.name}', not '{tag.name}' "
            "(un-dotted names are reserved for the core vocabulary)"
        )
    if tag.usage != "predicate":
        raise ValueError("plugin v1 supports predicate tags only")
    positional = []
    named = {}
    for pname, kind, default in tag.params:
        if kind not in _VALUE_KINDS:
            raise ValueError(f"unknown param kind {kind!r} for {tag.name}.{pname}")
        p = Param(name=pname, kind=kind, default=default, required=default is None)
        positional.append(p)
        named[pname] = p
    TAGS[tag.name] = TagSpec(
        name=tag.name, kind="condition", usage="predicate",
        positional=positional, named=named,
    )
    PLUGIN_TAGS[tag.name] = tag


def load_env_plugins() -> list[str]:
    """Import every module named in PRIOR_PLUGINS (comma-separated)."""
    loaded = []
    for mod in filter(None, (m.strip() for m in os.environ.get("PRIOR_PLUGINS", "").split(","))):
        importlib.import_module(mod)
        loaded.append(mod)
    return loaded
