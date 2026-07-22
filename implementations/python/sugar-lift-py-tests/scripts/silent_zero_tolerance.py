#!/usr/bin/env python3
"""R_silent — independent disk census versus current construction roll call."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping, NamedTuple, Sequence

from sugar_lift_py_tests.idd.lift_coverage_census import DiskCensus


class SilentOffender(NamedTuple):
    file: str
    kind: str
    count: int
    note: str


class ChildResult(NamedTuple):
    file: str
    category: str
    offenders: tuple[SilentOffender, ...]
    returncode: int | None
    stderr_tail: str


class AuditSummary(NamedTuple):
    discovered: int
    completed: int
    construction_panics: int
    timeouts: int
    non_native_red: int
    native_crashes: int
    offenders: tuple[SilentOffender, ...]


def _roll_call_keys(audit: Mapping[str, Any]) -> set[tuple[str, int, int, str]]:
    keys = set()
    for raw in audit.get("loci", []):
        if not isinstance(raw, Mapping):
            continue
        status = raw.get("status")
        locus = raw.get("locus")
        kind = raw.get("kind")
        if status not in {"warranted", "unresolved"} or not isinstance(
            locus, Mapping
        ):
            continue
        file = locus.get("file")
        line = locus.get("line")
        col = locus.get("col")
        if (
            isinstance(file, str)
            and isinstance(line, int)
            and isinstance(col, int)
            and isinstance(kind, str)
        ):
            keys.add((file, line, col, kind))
    return keys


def silent_offenders(
    census: DiskCensus, audit: Mapping[str, Any]
) -> list[SilentOffender]:
    """Return disk loci absent from the construction roll-call roster."""
    constructed_or_gap = _roll_call_keys(audit)
    disk_loci = [
        (locus.file, locus.line, locus.col, "Assert") for locus in census.asserts
    ] + [
        (locus.file, locus.line, locus.col, locus.kind) for locus in census.bodies
    ]
    return [
        SilentOffender(
            file=f"{file}:{line}:{col}",
            kind=f"silent-{kind}",
            count=1,
            note="on-disk source locus is absent from the construction roll call",
        )
        for file, line, col, kind in disk_loci
        if (file, line, col, kind) not in constructed_or_gap
    ]


def r_silent(offenders: Sequence[SilentOffender]) -> int:
    return sum(row.count for row in offenders)


def format_report(offenders: Sequence[SilentOffender]) -> str:
    lines = [
        f"R_silent = {r_silent(offenders)}",
        (
            "Replacement: every source locus speaks as warranted, support, "
            "inactive, typed effect, or loud ConstructionPanic."
        ),
        "",
        "Loci:",
    ]
    for row in offenders:
        lines.append(f"{row.file}:{row.kind}:count={row.count} — {row.note}")
    return "\n".join(lines)


def _audit_file(path: Path, *, rel: str) -> tuple[str, tuple[SilentOffender, ...]]:
    from sugar_lift_py_tests.idd.lift_coverage_census import census_source
    from sugar_lift_py_tests.tree_enumerate import source_audit_from_roll_call

    source = path.read_text(encoding="utf-8", errors="replace")
    census = census_source(source, file=rel)
    audit = source_audit_from_roll_call(path, rel)
    return "completed", tuple(silent_offenders(census, audit))


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


def _parse_child(stdout: str) -> Mapping[str, Any] | None:
    for line in reversed(stdout.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, Mapping) and value.get("kind") == "silent-audit-row":
            return value
    return None


def _run_isolated(
    path: Path,
    *,
    root: Path,
    file_timeout: int,
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
    except subprocess.TimeoutExpired as error:
        return ChildResult(
            rel,
            "timeout",
            (),
            None,
            (error.stderr or "")[-2000:] if isinstance(error.stderr, str) else "",
        )
    if result.returncode < 0:
        return ChildResult(
            rel, "native-crash", (), result.returncode, result.stderr[-2000:]
        )
    testimony = _parse_child(result.stdout)
    if result.returncode or testimony is None:
        return ChildResult(
            rel, "non-native-red", (), result.returncode, result.stderr[-2000:]
        )
    rows = tuple(
        SilentOffender(
            file=str(raw["file"]),
            kind=str(raw["kind"]),
            count=int(raw["count"]),
            note=str(raw["note"]),
        )
        for raw in testimony.get("offenders", [])
        if isinstance(raw, Mapping)
    )
    return ChildResult(
        rel,
        str(testimony.get("category")),
        rows,
        result.returncode,
        "",
    )


def audit_paths(
    paths: Sequence[Path],
    *,
    root: Path,
    file_timeout: int,
    workers: int,
) -> AuditSummary:
    with ThreadPoolExecutor(max_workers=workers) as executor:
        rows = list(
            executor.map(
                lambda path: _run_isolated(
                    path,
                    root=root,
                    file_timeout=file_timeout,
                ),
                sorted(paths),
            )
        )
    offenders = tuple(offender for row in rows for offender in row.offenders)
    for row in rows:
        if row.category in {
            "factory-panic",
            "timeout",
            "non-native-red",
            "native-crash",
        }:
            print(f"LOUD {row.category} row: {row.file}", flush=True)
    return AuditSummary(
        discovered=len(rows),
        completed=sum(row.category == "completed" for row in rows),
        construction_panics=sum(row.category == "factory-panic" for row in rows),
        timeouts=sum(row.category == "timeout" for row in rows),
        non_native_red=sum(row.category == "non-native-red" for row in rows),
        native_crashes=sum(row.category == "native-crash" for row in rows),
        offenders=offenders,
    )


def _run_child(path: Path, rel: str) -> int:
    category, offenders = _audit_file(path, rel=rel)
    print(
        json.dumps(
            {
                "kind": "silent-audit-row",
                "file": rel,
                "category": category,
                "offenders": [row._asdict() for row in offenders],
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


def main() -> int:
    repo_root = Path(__file__).resolve().parents[4]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
    )
    parser.add_argument("--live-root", action="append", type=Path, default=[])
    parser.add_argument("--repo-root", type=Path, default=repo_root)
    parser.add_argument("--file-timeout", type=int, default=30)
    parser.add_argument(
        "--workers",
        type=int,
        default=min(16, max(1, os.cpu_count() or 1)),
    )
    parser.add_argument("--child-file", type=Path)
    parser.add_argument("--child-rel")
    args = parser.parse_args()

    if args.child_file or args.child_rel:
        if args.child_file is None or args.child_rel is None:
            parser.error("child mode requires --child-file and --child-rel")
        return _run_child(args.child_file, args.child_rel)

    try:
        roots = args.live_root or args.paths or list(production_roots(repo_root))
        paths = require_python_paths(roots)
    except ValueError as error:
        print(f"SILENT ZERO-TOLERANCE RED: {error}")
        return 1
    summary = audit_paths(
        paths,
        root=args.repo_root,
        file_timeout=args.file_timeout,
        workers=max(1, args.workers),
    )
    print(
        "SILENT SURFACE: "
        f"files_discovered={summary.discovered} files_completed={summary.completed} "
        f"auditor_errors={summary.non_native_red} "
        f"construction_panics={summary.construction_panics} "
        f"non_native_red={summary.non_native_red} "
        f"native_crashes={summary.native_crashes} timeouts={summary.timeouts}"
    )
    if summary.offenders:
        print("SILENT ZERO-TOLERANCE RED")
        print(format_report(summary.offenders))
        return 1
    print("SILENT ZERO-TOLERANCE GREEN: R_silent = 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
