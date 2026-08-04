#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
"""Live instrument: package-owned repo-root imports in repo-level tests.

Repo-level tests run at entrances where ``sugar_lift_py_tests`` is not yet
installed.  They must ask the package-free ``tools/sugar_repo_root.py`` twin
for the checkout root instead of importing ``sugar_lift_py_tests.repo_root``.

R_repo_test_package_root_import — wrong-door imports under repo ``tests/``.
Exit 1 while R > 0.  Rescans the live tree; no hand-authored offender list.
"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path

FORBIDDEN_MODULE = "sugar_lift_py_tests.repo_root"


def forbidden_import_lines(path: Path) -> tuple[int, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == FORBIDDEN_MODULE:
            lines.append(node.lineno)
        if isinstance(node, ast.Import) and any(
            alias.name == FORBIDDEN_MODULE for alias in node.names
        ):
            lines.append(node.lineno)
    return tuple(sorted(lines))


def scan(tests_root: Path) -> list[tuple[Path, tuple[int, ...]]]:
    return [
        (path, lines)
        for path in sorted(tests_root.rglob("*.py"))
        if (lines := forbidden_import_lines(path))
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tests-root",
        type=Path,
        default=Path("tests"),
        help="repo-level tests directory (default: tests)",
    )
    args = parser.parse_args(argv)
    tests_root = args.tests_root.resolve()
    hits = scan(tests_root)
    count = sum(len(lines) for _path, lines in hits)
    print(f"R_repo_test_package_root_import={count}")
    for path, lines in hits:
        for line in lines:
            print(f"{path.relative_to(tests_root)}:{line}: {FORBIDDEN_MODULE}")
    return 1 if hits else 0


if __name__ == "__main__":
    raise SystemExit(main())
