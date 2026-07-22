"""Permanent baseline-free bare-exception floor primitives."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any, Mapping, NamedTuple, Sequence


class BareExceptionOffender(NamedTuple):
    file: str
    returncode: int
    stderr_tail: str


def _terminal(stdout: str) -> Mapping[str, Any] | None:
    for line in reversed(stdout.splitlines()):
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, Mapping) and row.get("kind") == "lift-terminal":
            return row
    return None


def bare_exception_offender(*, file: str, result: subprocess.CompletedProcess[str]) -> BareExceptionOffender | None:
    if result.returncode < 0:
        return None
    testimony = _terminal(result.stdout)
    if testimony is not None and testimony.get("outcome") in {"completed", "factory-panic"}:
        return None
    if result.returncode == 0:
        return None
    return BareExceptionOffender(file, result.returncode, result.stderr[-2000:])


def r_bare_exceptions(offenders: Sequence[BareExceptionOffender]) -> int:
    return len(offenders)


def _python_paths(roots: Sequence[Path]) -> list[Path]:
    return sorted({path for root in roots for path in (root.rglob("*.py") if root.is_dir() else (root,)) if path.is_file() and "__pycache__" not in path.parts})


def production_roots(repo_root: Path) -> tuple[Path, Path]:
    kit = repo_root / "implementations/python/sugar-lift-py-tests"
    return (kit / "src/sugar_lift_py_tests", kit / "scripts")


def require_python_paths(roots: Sequence[Path]) -> list[Path]:
    paths = _python_paths(roots)
    if not paths:
        raise ValueError(f"no Python source files found under {list(roots)}")
    return paths
