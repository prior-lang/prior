"""Packaging sanity: the PyPI long-description is a committed copy of the
repo README (setuptools cannot reference files above pyproject) — this
test keeps the two from drifting."""

from pathlib import Path

import prior_lang


def test_pypi_readme_is_synced():
    root = Path(__file__).parents[2]
    assert (root / "python" / "prior_lang_README.md").read_text() == (root / "README.md").read_text(), \
        "run: cp README.md python/prior_lang_README.md"


def test_version_matches_pyproject():
    # __init__.__version__ and pyproject must move together or PyPI lies
    root = Path(__file__).parents[2]
    pyproject = (root / "python" / "pyproject.toml").read_text()
    assert f'version = "{prior_lang.__version__}"' in pyproject


def test_bundled_schema_is_synced():
    """Same constraint as the README: setuptools cannot reach spec/ from
    the build root, so the wheel carries a committed copy."""
    root = Path(__file__).parents[2]
    assert prior_lang.schema_path().read_text() == (root / "spec" / "strategy.schema.json").read_text(), \
        "run: cp spec/strategy.schema.json python/prior_lang/strategy.schema.json"


def test_schema_is_declared_as_package_data():
    """Present on disk is not the same as shipped in the wheel."""
    root = Path(__file__).parents[2]
    pyproject = (root / "python" / "pyproject.toml").read_text()
    assert "[tool.setuptools.package-data]" in pyproject
    assert "strategy.schema.json" in pyproject


def test_load_schema_returns_usable_json():
    schema = prior_lang.load_schema()
    assert schema["$schema"].startswith("https://json-schema.org/draft/2020-12")
    assert "universe" in schema["properties"]
