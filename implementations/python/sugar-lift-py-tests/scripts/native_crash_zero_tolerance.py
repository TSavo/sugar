"""Permanent baseline-free native-crash floor primitives."""

from __future__ import annotations

from pathlib import Path
import signal
from typing import NamedTuple, Sequence


class NativeCrashOffender(NamedTuple):
    file: str
    returncode: int
    signal: str
    stderr_tail: str


def native_crash_offender(*, file: str, returncode: int, stderr: str) -> NativeCrashOffender | None:
    if returncode >= 0:
        return None
    signal_number = -returncode
    try:
        signal_name = signal.Signals(signal_number).name
    except ValueError:
        signal_name = f"signal-{signal_number}"
    return NativeCrashOffender(file, returncode, signal_name, stderr[-2000:])


def r_native_crashes(offenders: Sequence[NativeCrashOffender]) -> int:
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
