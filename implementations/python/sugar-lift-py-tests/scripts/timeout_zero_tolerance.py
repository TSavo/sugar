#!/usr/bin/env python3
"""R_timeouts — permanent baseline-free bounded-termination floor.

Every production source file is lifted in an isolated child under a fixed wall
clock bound. A child exceeding that bound is one timeout offender. Completed,
ConstructionPanic, bare-exception, and native-crash terminals remain separate axes.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import subprocess
import sys

# Floors share ``_production_lift_child`` (this directory); make it
# importable whether run standalone, as a child, or spec-loaded by a test.
from pathlib import Path as _P

sys.path.insert(0, str(_P(__file__).resolve().parent))
from typing import NamedTuple, Sequence


class TimeoutOffender(NamedTuple):
    file: str
    timeout_seconds: float


class ChildResult(NamedTuple):
    file: str
    category: str
    offender: TimeoutOffender | None


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


def _run_isolated(path: Path, *, root: Path, file_timeout: int) -> ChildResult:
    rel = path.resolve().relative_to(root.resolve()).as_posix()
    env = dict(os.environ)
    env["PYTHONFAULTHANDLER"] = "1"
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--child-file",
                str(path),
                "--child-rel",
                rel,
            ],
            text=True,
            capture_output=True,
            timeout=file_timeout,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        return ChildResult(
            rel,
            "timeout",
            timeout_offender(file=rel, timeout_seconds=error.timeout),
        )
    if result.returncode < 0:
        return ChildResult(rel, "native-crash", None)
    if result.returncode:
        return ChildResult(rel, "non-native-red", None)
    return ChildResult(rel, "completed", None)


def _run_child(path: Path, rel: str) -> int:
    from _production_lift_child import run_production_lift_child

    return run_production_lift_child(path, rel)


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    repo_root = Path(__file__).resolve().parents[4]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths", nargs="*", type=Path, default=list(production_roots(repo_root))
    )
    parser.add_argument("--repo-root", type=Path, default=repo_root)
    parser.add_argument("--file-timeout", type=int, default=30)
    parser.add_argument(
        "--workers", type=int, default=min(16, max(1, os.cpu_count() or 1))
    )
    parser.add_argument("--child-file", type=Path)
    parser.add_argument("--child-rel")
    args = parser.parse_args()
    if args.child_file or args.child_rel:
        if args.child_file is None or args.child_rel is None:
            parser.error("child mode requires --child-file and --child-rel")
        return _run_child(args.child_file, args.child_rel)
    from _production_lift_child import production_lift_bootstrap_error

    boot_error = production_lift_bootstrap_error()
    if boot_error is not None:
        # ONE infrastructure failure -- never multiplied per source file.
        print(
            "TIMEOUT SCANNER INFRASTRUCTURE FAILURE: the production "
            f"lift door did not bootstrap: {boot_error}"
        )
        return 2
    try:
        paths = require_python_paths(args.paths)
    except ValueError as error:
        print(f"TIMEOUT ZERO-TOLERANCE RED: {error}")
        return 1
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        rows = list(
            executor.map(
                lambda path: _run_isolated(
                    path, root=args.repo_root, file_timeout=args.file_timeout
                ),
                paths,
            )
        )
    offenders = tuple(row.offender for row in rows if row.offender is not None)
    print(
        "TIMEOUT SURFACE: "
        f"discovered={len(rows)} "
        f"completed={sum(row.category == 'completed' for row in rows)} "
        f"non_native_red={sum(row.category == 'non-native-red' for row in rows)} "
        f"native_crashes={sum(row.category == 'native-crash' for row in rows)}"
    )
    print(f"R_timeouts = {len(offenders)}")
    for row in offenders:
        print(f"{row.file}:timeout>{row.timeout_seconds}s")
    return 1 if offenders else 0


if __name__ == "__main__":
    raise SystemExit(main())
