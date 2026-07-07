"""Packaging sanity: the PyPI long-description is a committed copy of the
repo README (setuptools cannot reference files above pyproject) — this
test keeps the two from drifting."""

from pathlib import Path

import prior_lang


def test_pypi_readme_is_synced():
    root = Path(__file__).parents[2]
    assert (root / "python" / "prior_lang_README.md").read_text() == (root / "README.md").read_text(), \
        "run: cp README.md python/prior_lang_README.md"


def test_version_is_launch_grade():
    assert prior_lang.__version__ == "0.7.0"
