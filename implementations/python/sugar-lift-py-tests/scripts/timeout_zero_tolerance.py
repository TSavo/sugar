"""Permanent baseline-free bounded-termination floor primitives."""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple, Sequence


class TimeoutOffender(NamedTuple):
    file: str
    timeout_seconds: float


def timeout_offender(*, file: str, timeout_seconds: float) -> TimeoutOffender:
    return TimeoutOffender(file, timeout_seconds)


def r_timeouts(offenders: Sequence[TimeoutOffender]) -> int:
    return len(offenders)


def _python_paths(roots: Sequence[Path]) -> list[Path]:
    return sorted(
        {
            path
            for root in roots
            for path in (root.rglob("*.py") if root.is_dir() else (root,))
            if path.is_file() and "__pycache__" not in path.parts
        }
    )


def production_roots(repo_root: Path) -> tuple[Path, Path]:
    kit = repo_root / "implementations/python/sugar-lift-py-tests"
    return (kit / "src/sugar_lift_py_tests", kit / "scripts")


def require_python_paths(roots: Sequence[Path]) -> list[Path]:
    paths = _python_paths(roots)
    if not paths:
        raise ValueError(f"no Python source files found under {list(roots)}")
    return paths
