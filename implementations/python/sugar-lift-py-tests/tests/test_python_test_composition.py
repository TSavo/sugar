from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def test_primary_python_suite_installs_its_source_table_owner() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    target = re.search(
        r"^test-python: build-python\n(?P<body>.*?)(?=^\.PHONY:)",
        makefile,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert target is not None
    primary_suite = target.group("body").split(
        "implementations/python/sugar-emit-python-pytest", 1
    )[0]

    assert "-e ../sugar-lift-python-source" in primary_suite, (
        "test-python creates an isolated sugar-lift-py-tests environment without "
        "its imported source-table owner; observed=ModuleNotFoundError: "
        "sugar_lift_python_source; replacement=install both repository packages "
        "editable in the primary Python suite environment"
    )
