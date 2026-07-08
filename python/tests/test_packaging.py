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
