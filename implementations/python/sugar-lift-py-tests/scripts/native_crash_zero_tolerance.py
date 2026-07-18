#!/usr/bin/env python3
"""R_native_crashes — permanent baseline-free corpus process floor.

Each source file runs in an isolated Python child with faulthandler enabled.
Only signal termination is a native crash. FactoryPanic, ordinary exceptions,
and timeouts stay loud in their own categories and are never softened into
success or folded into this axis.

Exit 1 whenever R_native_crashes > 0; there is no baseline or allowlist.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import os
import signal
import subprocess
import sys
from typing import NamedTuple, Sequence


class NativeCrashOffender(NamedTuple):
    file: str
    returncode: int
    signal: str
    stderr_tail: str


def native_crash_offender(
    *, file: str, returncode: int, stderr: str
) -> NativeCrashOffender | None:
    if returncode >= 0:
        return None
    signal_number = -returncode
    try:
        signal_name = signal.Signals(signal_number).name
    except ValueError:
        signal_name = f"signal-{signal_number}"
    return NativeCrashOffender(
        file=file,
        returncode=returncode,
        signal=signal_name,
        stderr_tail=stderr[-2000:],
    )


def r_native_crashes(offenders: Sequence[NativeCrashOffender]) -> int:
    return len(offenders)


def format_report(offenders: Sequence[NativeCrashOffender]) -> str:
    lines = [
        f"R_native_crashes = {r_native_crashes(offenders)}",
        (
            "Replacement: corpus children terminate with completed testimony, "
            "typed FactoryPanic, bare-exception row, or loud timeout; never signal."
        ),
        "",
        "Loci:",
    ]
    for row in offenders:
        lines.append(
            f"{row.file}:returncode={row.returncode}:signal={row.signal}"
        )
        if row.stderr_tail:
            lines.append(row.stderr_tail)
    return "\n".join(lines)


def _python_paths(roots: Sequence[Path]) -> list[Path]:
    return sorted(
        {
            path
            for root in roots
            for path in (
                root.rglob("*.py") if root.is_dir() else (root,)
            )
            if path.is_file() and "__pycache__" not in path.parts
        }
    )


def audit_paths(
    paths: Sequence[Path],
    *,
    root: Path,
    file_timeout: int,
) -> list[NativeCrashOffender]:
    script = Path(__file__).resolve()
    offenders: list[NativeCrashOffender] = []
    for path in sorted(paths):
        rel = path.resolve().relative_to(root.resolve()).as_posix()
        env = dict(os.environ)
        env["PYTHONFAULTHANDLER"] = "1"
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
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
            print(
                f"LOUD timeout row: {rel}: exceeded {file_timeout}s",
                flush=True,
            )
            continue
        offender = native_crash_offender(
            file=rel,
            returncode=result.returncode,
            stderr=result.stderr,
        )
        if offender is not None:
            offenders.append(offender)
        elif result.returncode:
            tail = (result.stderr.splitlines() or ["no stderr"])[-1]
            print(
                f"LOUD non-native red row: {rel}: "
                f"returncode={result.returncode}: {tail}",
                flush=True,
            )
    return offenders


def _run_child(path: Path, rel: str) -> int:
    from sugar_lift_py_tests.lift_rpc import lift_file_payload

    source = path.read_text(encoding="utf-8", errors="replace")
    payload = lift_file_payload(source, rel)
    print(
        f"completed row: {rel}: facts={len(payload.ir)} "
        f"effects={len(payload.effects)}",
        flush=True,
    )
    return 0


def main() -> int:
    repo_root = Path(__file__).resolve().parents[4]
    default_corpus = (
        repo_root
        / "implementations"
        / "python"
        / "sugar-lift-py-tests"
        / "tests"
        / "witness_seeds"
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path, default=[default_corpus])
    parser.add_argument("--repo-root", type=Path, default=repo_root)
    parser.add_argument("--file-timeout", type=int, default=30)
    parser.add_argument("--child-file", type=Path)
    parser.add_argument("--child-rel")
    args = parser.parse_args()

    if args.child_file or args.child_rel:
        if args.child_file is None or args.child_rel is None:
            parser.error("child mode requires --child-file and --child-rel")
        return _run_child(args.child_file, args.child_rel)

    offenders = audit_paths(
        _python_paths(args.paths),
        root=args.repo_root,
        file_timeout=args.file_timeout,
    )
    if offenders:
        print("NATIVE-CRASH ZERO-TOLERANCE RED")
        print(format_report(offenders))
        return 1
    print("NATIVE-CRASH ZERO-TOLERANCE GREEN: R_native_crashes = 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
