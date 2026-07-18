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
from pathlib import Path
from typing import Any, Mapping, NamedTuple, Sequence


class SilentOffender(NamedTuple):
    file: str
    kind: str
    count: int
    note: str


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
    assertion_residue = max(silent_assertions, delta)
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
    violation_count = len(violations) if isinstance(violations, list) else 0
    if violation_count:
        offenders.append(
            SilentOffender(
                file=file,
                kind="unclassified-source-owner",
                count=violation_count,
                note="source body owner disappeared before factory classification",
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


def audit_paths(paths: Sequence[Path], *, root: Path) -> list[SilentOffender]:
    from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
    from sugar_lift_py_tests.idd.lift_coverage_accounting import (
        account_lift_coverage,
    )
    from sugar_lift_py_tests.idd.lift_coverage_census import census_source
    from sugar_lift_py_tests.lift_rpc import lift_file_payload

    offenders: list[SilentOffender] = []
    for path in sorted(paths):
        rel = path.resolve().relative_to(root.resolve()).as_posix()
        source = path.read_text(encoding="utf-8", errors="replace")
        try:
            payload = lift_file_payload(source, rel)
        except FactoryPanic as panic:
            print(
                f"LOUD factory-panic row: {rel}: {panic.info.to_json()}",
                flush=True,
            )
            continue
        report = payload.to_rpc()
        report["liftCoverage"] = account_lift_coverage(
            census_source(source, file=rel),
            report,
        ).to_json()
        offenders.extend(silent_offenders(report, file=rel))
    return offenders


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


def main() -> int:
    repo_root = Path(__file__).resolve().parents[4]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        default=[
            repo_root
            / "implementations"
            / "python"
            / "sugar-lift-py-tests"
            / "tests"
            / "witness_seeds"
        ],
    )
    parser.add_argument("--repo-root", type=Path, default=repo_root)
    args = parser.parse_args()

    offenders = audit_paths(
        _python_paths(args.paths),
        root=args.repo_root,
    )
    if offenders:
        print("SILENT ZERO-TOLERANCE RED")
        print(format_report(offenders))
        return 1
    print("SILENT ZERO-TOLERANCE GREEN: R_silent = 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
