from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def test_black_format_check_is_installed_and_required_by_ci() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    pyproject = (
        ROOT / "implementations/python/sugar-lift-py-tests/pyproject.toml"
    ).read_text(encoding="utf-8")

    assert "black>=25.1.0" in pyproject
    assert ".PHONY: test-python-format" in makefile
    assert "test-python-format:" in makefile
    assert "$(PYTHON_KIT) -m black --check $(PYTHON_FORMAT_PATHS)" in makefile

    ci_target = re.search(r"^ci:(?P<deps>.*)$", makefile, re.MULTILINE)
    assert ci_target is not None
    assert "test-python-format" in ci_target.group("deps").split()

    assert "run: make ci" in workflow
