"""The plugin system: namespaced tags as the developer escape hatch."""

import sys

import pytest

import prior_lang
from prior_lang import PluginTag, register_plugin
from prior_lang.codegen import compile_strategy
from prior_lang.plugins import PLUGIN_TAGS
from prior_lang.tags import TAGS


@pytest.fixture
def momo_plugin():
    register_plugin(PluginTag(
        name="acme.momo",
        params=[("period", "number", 20)],
        emit=lambda p: (
            f"mom = close / close.shift({int(p['period'])}) - 1\n"
            f"    cond = (mom > 0).fillna(False)"
        ),
        readback=lambda p: f"acme momentum({int(p['period'])}) is positive",
    ))
    yield
    TAGS.pop("acme.momo", None)
    PLUGIN_TAGS.pop("acme.momo", None)


BOILER = "universe [sp_top_30]\nwhen {cond}\n  buy [5% portfolio]\nsell when [after 10 bars]\n"


def test_plugin_full_loop(momo_plugin):
    s = prior_lang.compile_source(BOILER.format(cond="[acme.momo 10] and [rsi] < 60"))
    assert s["entry"]["conditions"][0] == {"condition": "acme.momo", "params": {"period": 10.0}}
    assert prior_lang.compile_source(prior_lang.strategy_to_source(s)) == s
    code = compile_strategy(s)
    assert "close.shift(10)" in code
    from prior_lang.explain import explain_strategy
    assert "acme momentum(10) is positive" in explain_strategy(s)


def test_plugin_defaults_apply(momo_plugin):
    s = prior_lang.compile_source(BOILER.format(cond="[acme.momo]"))
    assert s["entry"]["conditions"][0]["params"] == {"period": 20}


def test_plugin_works_with_mtf(momo_plugin):
    src = (
        "universe [sp_top_30]\ntimeframe 1h\n"
        "when [acme.momo 10 on 1d]\n  buy [5% portfolio]\nsell when [after 10 bars]\n"
    )
    s = prior_lang.compile_source(src)
    assert s["entry"]["conditions"][0]["timeframe"] == "1d"
    code = compile_strategy(s)
    assert "_prior_htf_cond_0" in code and "close.shift(10)" in code


def test_unregistered_dotted_tag_helpful_error():
    with pytest.raises(prior_lang.PriorError) as e:
        prior_lang.compile_source(BOILER.format(cond="[nobody.home]"))
    assert "plugin" in e.value.message
    assert "PRIOR_PLUGINS" in (e.value.suggestion or "")


def test_undotted_plugin_name_rejected():
    with pytest.raises(ValueError, match="namespaced"):
        register_plugin(PluginTag(name="momo", emit=lambda p: "cond = close > 0"))


def test_env_plugin_loading(tmp_path, monkeypatch):
    mod = tmp_path / "my_prior_plugin.py"
    mod.write_text(
        "from prior_lang.plugins import PluginTag, register\n"
        "register(PluginTag(name='envco.up', params=[],\n"
        "    emit=lambda p: 'cond = (close.diff() > 0).fillna(False)'))\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setenv("PRIOR_PLUGINS", "my_prior_plugin")
    from prior_lang.plugins import load_env_plugins
    assert load_env_plugins() == ["my_prior_plugin"]
    try:
        s = prior_lang.compile_source(BOILER.format(cond="[envco.up]"))
        assert s["entry"]["conditions"][0]["condition"] == "envco.up"
    finally:
        TAGS.pop("envco.up", None)
        PLUGIN_TAGS.pop("envco.up", None)
        sys.modules.pop("my_prior_plugin", None)
