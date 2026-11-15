from __future__ import annotations

import re
from pathlib import Path


from sugar_lift_py_tests.repo_root import resolve_repo_root

ROOT = resolve_repo_root()


def test_black_format_check_is_installed_and_required_by_make_ci() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    pyproject = (
        ROOT / "implementations/python/sugar-lift-py-tests/pyproject.toml"
    ).read_text(encoding="utf-8")

    # The kit installs black as a versioned requirement (today an exact pin);
    # the gate is that it is installed, whatever the version reads.
    assert re.search(r'^\s*"black\s*(==|>=|~=)\s*\d[^"]*",?\s*$', pyproject, re.MULTILINE)
    assert ".PHONY: test-python-format" in makefile
    assert "test-python-format:" in makefile
    assert "$(PYTHON_KIT) -m black --check $(PYTHON_FORMAT_PATHS)" in makefile

    ci_target = re.search(r"^ci:(?P<deps>.*)$", makefile, re.MULTILINE)
    assert ci_target is not None
    assert "test-python-format" in ci_target.group("deps").split()
