#!/usr/bin/env python3
"""R_silent — permanent baseline-free source-accounting floor.

Every checked source file must speak through all three independent accounting
surfaces:

* assertion coverage: no silently-unaccounted assertion / conservation delta;
* source ledger: no unclassified source locus;
* source→factory conservation: no vanished body-owning source locus.

A typed FactoryPanic is loud testimony and is therefore not silent. Any other
exception remains process-terminal. Exit 1 whenever R_silent > 0; there is no
baseline or allowlist.
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
    factory_panics: int
    timeouts: int
    non_native_red: int
    native_crashes: int
    offenders: tuple[SilentOffender, ...]


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _integer(mapping: Mapping[str, Any], key: str) -> int:
    value = mapping.get(key, 0)
    return value if isinstance(value, int) else 0


def silent_offenders(
    report: Mapping[str, Any], *, file: str
) -> list[SilentOffender]:
    coverage = _mapping(report.get("liftCoverage"))
    ledger = _mapping(report.get("sourceLedger"))
    factory_summary = _mapping(report.get("factoryAuditSummary"))
    conservation = _mapping(factory_summary.get("sourceFactoryConservation"))

    if not coverage or not ledger or not conservation:
        return [
            SilentOffender(
                file=file,
                kind="missing-accounting-testimony",
                count=1,
                note=(
                    "report must emit liftCoverage, sourceLedger, and "
                    "sourceFactoryConservation; missing testimony is silent"
                ),
            )
        ]

    offenders: list[SilentOffender] = []
    totals = _mapping(coverage.get("totals"))
    coverage_conservation = _mapping(coverage.get("conservation"))
    silent_assertions = _integer(totals, "silently_unaccounted")
    delta = _integer(coverage_conservation, "delta")
    assertion_residue = max(silent_assertions, abs(delta))
    if assertion_residue:
        offenders.append(
            SilentOffender(
                file=file,
                kind="silent-assertion",
                count=assertion_residue,
                note=(
                    "independent on-disk assertions must equal lifted+cited plus "
                    "refused-loud accounting"
                ),
            )
        )

    unclassified_source = _integer(ledger, "unclassified_source")
    if unclassified_source:
        offenders.append(
            SilentOffender(
                file=file,
                kind="unclassified-source",
                count=unclassified_source,
                note=(
                    "every source locus must be warranted, support, inactive, "
                    "boundary, unresolved-loud, or typed effect"
                ),
            )
        )

    violations = conservation.get("violations")
    if isinstance(violations, list):
        for raw in violations:
            locus = (
                str(raw.get("locus") or file)
                if isinstance(raw, Mapping)
                else file
            )
            reason = (
                str(raw.get("reason") or "")
                if isinstance(raw, Mapping)
                else ""
            )
            offenders.append(
                SilentOffender(
                    file=locus,
                    kind="unclassified-source-owner",
                    count=1,
                    note=(
                        reason
                        or "source body owner disappeared before factory classification"
                    ),
                )
            )
    return offenders


def r_silent(offenders: Sequence[SilentOffender]) -> int:
    return sum(row.count for row in offenders)


def format_report(offenders: Sequence[SilentOffender]) -> str:
    lines = [
        f"R_silent = {r_silent(offenders)}",
        (
            "Replacement: every source locus speaks as warranted, support, "
            "inactive, typed effect, or loud FactoryPanic."
        ),
        "",
        "Loci:",
    ]
    for row in offenders:
        lines.append(f"{row.file}:{row.kind}:count={row.count} — {row.note}")
    return "\n".join(lines)


def _audit_file(path: Path, *, rel: str) -> tuple[str, tuple[SilentOffender, ...]]:
    from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
    from sugar_lift_py_tests.idd.lift_coverage_accounting import (
        account_lift_coverage,
    )
    from sugar_lift_py_tests.idd.lift_coverage_census import census_source
    from sugar_lift_py_tests.lift_rpc import lift_file_payload

    source = path.read_text(encoding="utf-8", errors="replace")
    try:
        payload = lift_file_payload(source, rel)
    except FactoryPanic:
        return "factory-panic", ()
    report = payload.to_rpc()
    report["liftCoverage"] = account_lift_coverage(
        census_source(source, file=rel),
        report,
    ).to_json()
    return "completed", tuple(silent_offenders(report, file=rel))


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
    offenders = tuple(
        offender for row in rows for offender in row.offenders
    )
    for row in rows:
        if row.category in {"factory-panic", "timeout", "non-native-red", "native-crash"}:
            print(f"LOUD {row.category} row: {row.file}", flush=True)
    return AuditSummary(
        discovered=len(rows),
        completed=sum(row.category == "completed" for row in rows),
        factory_panics=sum(row.category == "factory-panic" for row in rows),
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
        default=list(production_roots(repo_root)),
    )
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
        paths = require_python_paths(args.paths)
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
        f"discovered={summary.discovered} completed={summary.completed} "
        f"factory_panics={summary.factory_panics} "
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
