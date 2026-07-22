#!/usr/bin/env python3
"""R_bare_exceptions — permanent baseline-free untyped-failure floor.

Every production source file is lifted in an isolated child through the current
production construction door (``_production_lift_child``). An intentional typed
source-tree gap (``SugarNotWritten``) is a distinct, sanctioned ``typed-gap``
outcome, not a failure. Signal deaths and timeouts remain distinct axes. Every
other non-successful child is a bare Python exception and makes this floor red.
A one-time production-lift bootstrap failure is reported ONCE as scanner
infrastructure failure, never multiplied into one bogus source failure per file.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping, NamedTuple, Sequence

# The floors share ``_production_lift_child`` (this directory). Ensure the
# scripts dir is importable whether run standalone, as a child, or spec-loaded
# by a test.
sys.path.insert(0, str(Path(__file__).resolve().parent))


class BareExceptionOffender(NamedTuple):
    file: str
    returncode: int
    stderr_tail: str


class ChildResult(NamedTuple):
    file: str
    category: str
    offender: BareExceptionOffender | None


def _terminal(stdout: str) -> Mapping[str, Any] | None:
    for line in reversed(stdout.splitlines()):
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, Mapping) and row.get("kind") == "lift-terminal":
            return row
    return None


def bare_exception_offender(
    *, file: str, result: subprocess.CompletedProcess[str]
) -> BareExceptionOffender | None:
    from _production_lift_child import NON_FAILURE_OUTCOMES

    if result.returncode < 0:
        return None
    testimony = _terminal(result.stdout)
    if testimony is not None and testimony.get("outcome") in NON_FAILURE_OUTCOMES:
        return None
    if result.returncode == 0:
        return None
    return BareExceptionOffender(file, result.returncode, result.stderr[-2000:])


def r_bare_exceptions(offenders: Sequence[BareExceptionOffender]) -> int:
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


def _run_isolated(
    path: Path, *, root: Path, file_timeout: int
) -> ChildResult:
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
    except subprocess.TimeoutExpired:
        return ChildResult(rel, "timeout", None)
    offender = bare_exception_offender(file=rel, result=result)
    if offender is not None:
        return ChildResult(rel, "bare-exception", offender)
    if result.returncode < 0:
        return ChildResult(rel, "native-crash", None)
    testimony = _terminal(result.stdout)
    if testimony is None:
        # Exit 0 with no terminal row: the silent / missing-result axis. Not a
        # bare exception (offender already None), but named distinctly.
        return ChildResult(rel, "silent", None)
    return ChildResult(rel, str(testimony.get("outcome")), None)


def _run_child(path: Path, rel: str) -> int:
    from _production_lift_child import run_production_lift_child

    return run_production_lift_child(path, rel)


def main() -> int:
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
        # ONE infrastructure failure -- never multiplied into a bogus bare
        # exception per source file.
        print(
            "BARE-EXCEPTION SCANNER INFRASTRUCTURE FAILURE: the production lift "
            f"door did not bootstrap: {boot_error}"
        )
        return 2
    try:
        paths = require_python_paths(args.paths)
    except ValueError as error:
        print(f"BARE-EXCEPTION ZERO-TOLERANCE RED: {error}")
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
        "BARE-EXCEPTION SURFACE: "
        f"discovered={len(rows)} "
        f"completed={sum(row.category == 'completed' for row in rows)} "
        f"typed_gaps={sum(row.category == 'typed-gap' for row in rows)} "
        f"native_crashes={sum(row.category == 'native-crash' for row in rows)} "
        f"timeouts={sum(row.category == 'timeout' for row in rows)} "
        f"silent={sum(row.category == 'silent' for row in rows)}"
    )
    print(f"R_bare_exceptions = {len(offenders)}")
    for row in offenders:
        tail = (row.stderr_tail.splitlines() or ["no stderr"])[-1]
        print(f"{row.file}:returncode={row.returncode}:bare-exception — {tail}")
    return 1 if offenders else 0


if __name__ == "__main__":
    raise SystemExit(main())
