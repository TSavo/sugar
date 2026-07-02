from __future__ import annotations

import importlib.metadata
import importlib.util
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from sugar_lift_python_source.lifter import lift_source

PACKAGES = ("numpy", "pandas")
FIXTURE = Path(__file__).parent / "fixtures/numpy_pandas_honest_zero_counts.json"

CLOSED_REFUSAL_KINDS = {
    "syntax-error",
    "io-error",
    "path-traversal",
    "async-refused",
    "generator-refused",
    "global-nonlocal-refused",
    "for-else-refused",
    "match-refused",
    "multi-target-assign-refused",
    "decorator-refused",
    "non-literal-default",
    "value-pin-refused",
    "enum-pin-refused",
}


@dataclass(frozen=True)
class CorpusScan:
    total_files: int
    package_versions: dict[str, str]
    counts_by_kind: dict[str, int]
    unhandled_reasons: dict[str, int]
    opacity_misses: tuple[str, ...]


def test_numpy_pandas_honest_zero_corpus_matches_fixture() -> None:
    fixture = _load_fixture()
    scan = _scan_numpy_pandas()

    _assert_scan_matches_fixture(scan, fixture)


def test_gate_logic_rejects_unhandled_syntax_increase() -> None:
    fixture = {
        "total_files": 1,
        "package_versions": {"numpy": "test", "pandas": "test"},
        "counts_by_kind": {"unhandled-syntax": 1},
        "expected_unhandled": {"total": 1, "reasons": {"old residue": 1}},
    }
    scan = CorpusScan(
        total_files=1,
        package_versions={"numpy": "test", "pandas": "test"},
        counts_by_kind={"unhandled-syntax": 2},
        unhandled_reasons={"old residue": 1, "new residue": 1},
        opacity_misses=(),
    )

    with pytest.raises(AssertionError, match="unhandled-syntax residue changed"):
        _assert_scan_matches_fixture(scan, fixture)


def test_gate_logic_rejects_kind_outside_closed_taxonomy() -> None:
    fixture = {
        "total_files": 1,
        "package_versions": {"numpy": "test", "pandas": "test"},
        "counts_by_kind": {"value-pin-refused": 1},
        "expected_unhandled": {"total": 0, "reasons": {}},
    }
    scan = CorpusScan(
        total_files=1,
        package_versions={"numpy": "test", "pandas": "test"},
        counts_by_kind={"surprise-refusal": 1},
        unhandled_reasons={},
        opacity_misses=(),
    )

    with pytest.raises(AssertionError, match="outside closed taxonomy"):
        _assert_scan_matches_fixture(scan, fixture)


def test_gate_logic_rejects_stale_pinned_count() -> None:
    fixture = {
        "total_files": 1,
        "package_versions": {"numpy": "test", "pandas": "test"},
        "counts_by_kind": {"value-pin-refused": 2},
        "expected_unhandled": {"total": 0, "reasons": {}},
    }
    scan = CorpusScan(
        total_files=1,
        package_versions={"numpy": "test", "pandas": "test"},
        counts_by_kind={"value-pin-refused": 1},
        unhandled_reasons={},
        opacity_misses=(),
    )

    with pytest.raises(AssertionError, match="refusal count fixture mismatch"):
        _assert_scan_matches_fixture(scan, fixture)


def _scan_numpy_pandas() -> CorpusScan:
    roots = {package: _package_root(package) for package in PACKAGES}
    package_versions = {package: _package_version(package) for package in PACKAGES}
    counts_by_kind: Counter[str] = Counter()
    unhandled_reasons: Counter[str] = Counter()
    opacity_misses: list[str] = []
    total_files = 0
    for package in PACKAGES:
        root = roots[package]
        for path in _python_files(root):
            total_files += 1
            rel = f"{package}/{path.relative_to(root).as_posix()}"
            try:
                source = path.read_text(encoding="utf-8")
            except OSError as exc:
                counts_by_kind["io-error"] += 1
                continue
            except UnicodeDecodeError:
                source = path.read_text(encoding="utf-8", errors="replace")
            result = lift_source(source, rel)
            for refusal in result.refusals:
                kind = str(refusal.get("kind"))
                counts_by_kind[kind] += 1
                if kind == "unhandled-syntax":
                    unhandled_reasons[str(refusal.get("reason"))] += 1
            if _has_opaque_loop_effect(result.ir) and not result.opacity_report:
                opacity_misses.append(rel)
    return CorpusScan(
        total_files=total_files,
        package_versions=package_versions,
        counts_by_kind=dict(sorted(counts_by_kind.items())),
        unhandled_reasons=dict(sorted(unhandled_reasons.items())),
        opacity_misses=tuple(opacity_misses),
    )


def _assert_scan_matches_fixture(scan: CorpusScan, fixture: dict[str, Any]) -> None:
    if scan.total_files != fixture["total_files"]:
        raise AssertionError(
            f"corpus file count changed: expected={fixture['total_files']} "
            f"actual={scan.total_files}"
        )
    if scan.package_versions != fixture["package_versions"]:
        raise AssertionError(
            "corpus package versions changed:\n"
            + _format_diff(scan.package_versions, fixture["package_versions"])
        )
    unexpected_kinds = sorted(
        kind
        for kind in scan.counts_by_kind
        if not _is_closed_refusal_kind(kind) and kind != "unhandled-syntax"
    )
    if unexpected_kinds:
        raise AssertionError(
            "refusal kinds outside closed taxonomy: " + ", ".join(unexpected_kinds)
        )
    expected_unhandled = fixture["expected_unhandled"]
    actual_unhandled_total = scan.counts_by_kind.get("unhandled-syntax", 0)
    if actual_unhandled_total != expected_unhandled["total"]:
        raise AssertionError(
            "unhandled-syntax residue changed:\n"
            f"expected={expected_unhandled['total']} "
            f"actual={actual_unhandled_total}\n"
            + _format_diff(scan.unhandled_reasons, expected_unhandled["reasons"])
        )
    if scan.unhandled_reasons != expected_unhandled["reasons"]:
        raise AssertionError(
            "unhandled-syntax residue reasons changed:\n"
            + _format_diff(scan.unhandled_reasons, expected_unhandled["reasons"])
        )
    if scan.counts_by_kind != fixture["counts_by_kind"]:
        raise AssertionError(
            "refusal count fixture mismatch:\n"
            + _format_diff(scan.counts_by_kind, fixture["counts_by_kind"])
        )
    if scan.opacity_misses:
        raise AssertionError(
            "opaque-loop effects missing opacity_report entries:\n"
            + "\n".join(scan.opacity_misses)
        )


def _load_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _package_root(package: str) -> Path:
    spec = importlib.util.find_spec(package)
    if spec is None or spec.origin is None:
        pytest.fail(f"corpus not found at site-packages/{package}")
    root = Path(spec.origin).resolve().parent
    if not root.exists():
        pytest.fail(f"corpus not found at {root}")
    return root


def _package_version(package: str) -> str:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        pytest.fail(f"corpus not found at site-packages/{package}")


def _python_files(root: Path) -> list[Path]:
    return sorted(
        path for path in root.rglob("*.py") if "__pycache__" not in path.parts
    )


def _has_opaque_loop_effect(obj: Any) -> bool:
    stack = [obj]
    seen: set[int] = set()
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            current_id = id(current)
            if current_id in seen:
                continue
            seen.add(current_id)
            if current.get("kind") == "opaque_loop":
                return True
            stack.extend(current.values())
        elif isinstance(current, list):
            current_id = id(current)
            if current_id in seen:
                continue
            seen.add(current_id)
            stack.extend(current)
    return False


def _is_closed_refusal_kind(kind: str) -> bool:
    return kind in CLOSED_REFUSAL_KINDS or (
        kind.startswith("callee-") and kind.endswith("-refused")
    )


def _format_diff(actual: dict[str, Any], expected: dict[str, Any]) -> str:
    lines = []
    for key in sorted(set(actual) | set(expected)):
        actual_value = actual.get(key, 0)
        expected_value = expected.get(key, 0)
        if actual_value != expected_value:
            lines.append(f"{key}: expected={expected_value} actual={actual_value}")
    return "\n".join(lines)
