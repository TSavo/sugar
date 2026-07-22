"""Permanent baseline-free source-accounting floor primitives."""

from __future__ import annotations

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


def silent_offenders(report: Mapping[str, Any], *, file: str) -> list[SilentOffender]:
    coverage = _mapping(report.get("liftCoverage"))
    ledger = _mapping(report.get("sourceLedger"))
    factory_summary = _mapping(report.get("factoryAuditSummary"))
    conservation = _mapping(factory_summary.get("sourceFactoryConservation"))
    if not coverage or not ledger or not conservation:
        return [
            SilentOffender(
                file,
                "missing-accounting-testimony",
                1,
                "report must emit liftCoverage, sourceLedger, and sourceFactoryConservation; missing testimony is silent",
            )
        ]

    offenders: list[SilentOffender] = []
    totals = _mapping(coverage.get("totals"))
    coverage_conservation = _mapping(coverage.get("conservation"))
    residue = max(
        _integer(totals, "silently_unaccounted"),
        abs(_integer(coverage_conservation, "delta")),
    )
    if residue:
        offenders.append(
            SilentOffender(
                file,
                "silent-assertion",
                residue,
                "independent on-disk assertions must equal lifted+cited plus refused-loud accounting",
            )
        )
    unclassified_source = _integer(ledger, "unclassified_source")
    if unclassified_source:
        offenders.append(
            SilentOffender(
                file,
                "unclassified-source",
                unclassified_source,
                "every source locus must be warranted, support, inactive, boundary, unresolved-loud, or typed effect",
            )
        )
    loud_loci = {
        str(row.get("gap_locus"))
        for row in factory_summary.get("factoryWalk", [])
        if isinstance(row, Mapping)
        and row.get("verdict") == "gap"
        and row.get("status") == "unresolved"
        and row.get("gap_kind") == "Conservation"
        and isinstance(row.get("gap_locus"), str)
    }
    violations = conservation.get("violations")
    if isinstance(violations, list):
        for raw in violations:
            locus = str(raw.get("locus") or file) if isinstance(raw, Mapping) else file
            if locus in loud_loci:
                continue
            reason = str(raw.get("reason") or "") if isinstance(raw, Mapping) else ""
            offenders.append(
                SilentOffender(
                    locus,
                    "unclassified-source-owner",
                    1,
                    reason or "source body owner disappeared before factory classification",
                )
            )
    return offenders


def r_silent(offenders: Sequence[SilentOffender]) -> int:
    return sum(row.count for row in offenders)


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
