from __future__ import annotations

import importlib.metadata
import importlib.util
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from declared_corpus import DeclaredCorpusMissing, require_declared_corpus

from sugar_lift_python_source.lifter import lift_source

PACKAGES = ("numpy", "pandas")
FIXTURE_DIR = Path(__file__).parent / "fixtures"
FIXTURE_PREFIX = "numpy_pandas_honest_zero_counts"

CLOSED_REFUSAL_KINDS = {
    "syntax-error",
    "io-error",
    "path-traversal",
    "async-refused",
    "bare-raise-refused",
    "generator-refused",
    "global-nonlocal-refused",
    "for-else-refused",
    "match-refused",
    "multi-target-assign-refused",
    "decorator-refused",
    "non-literal-default",
    "value-pin-boundary",
    "enum-pin-boundary",
}


@dataclass(frozen=True)
class CorpusScan:
    total_files: int
    package_versions: dict[str, str]
    counts_by_kind: dict[str, int]
    unhandled_syntax: tuple[str, ...]
    opacity_misses: tuple[str, ...]


def test_numpy_pandas_honest_zero_corpus_matches_fixture() -> None:
    package_versions = _installed_package_versions()
    fixture = _load_fixture_for_package_versions(package_versions)
    scan = _scan_numpy_pandas(package_versions=package_versions)

    _assert_scan_matches_fixture(scan, fixture)


def test_fixture_selection_is_keyed_by_package_versions() -> None:
    fixture = _load_fixture_for_package_versions({"numpy": "2.5.1", "pandas": "3.0.3"})

    assert fixture["package_versions"] == {"numpy": "2.5.1", "pandas": "3.0.3"}
    assert fixture["counts_by_kind"]["decorator-refused"] == 8971


def test_unknown_package_version_fails_by_name_rather_than_skipping() -> None:
    """Version drift off the pin is a broken environment, not an absent law.

    ``sugar-build.toml`` pins numpy and pandas, so the pinned versions always
    have a fixture. Skipping here reported green on every machine that had
    drifted -- the law simply stopped running, and the suite went smaller
    rather than red.
    """
    with pytest.raises(DeclaredCorpusMissing) as exc_info:
        _load_fixture_for_package_versions({"numpy": "9.9.9", "pandas": "3.0.3"})

    assert not isinstance(
        exc_info.value, pytest.skip.Exception
    ), "drift off a pinned vendor version must fail, never skip"
    assert "numpy=9.9.9,pandas=3.0.3" in str(exc_info.value)
    assert "numpy_pandas_honest_zero_counts__numpy-9.9.9__pandas-3.0.3.json" in str(
        exc_info.value
    )


def test_gate_logic_rejects_unhandled_syntax_at_stable_zero() -> None:
    fixture = {
        "total_files": 1,
        "package_versions": {"numpy": "test", "pandas": "test"},
        "counts_by_kind": {},
    }
    scan = CorpusScan(
        total_files=1,
        package_versions={"numpy": "test", "pandas": "test"},
        counts_by_kind={"unhandled-syntax": 1},
        unhandled_syntax=("numpy/example.py: new residue",),
        opacity_misses=(),
    )

    with pytest.raises(
        AssertionError,
        match="unhandled-syntax stable-zero regression",
    ) as exc_info:
        _assert_scan_matches_fixture(scan, fixture)

    assert "numpy/example.py: new residue" in str(exc_info.value)


def test_gate_logic_rejects_kind_outside_closed_taxonomy() -> None:
    fixture = {
        "total_files": 1,
        "package_versions": {"numpy": "test", "pandas": "test"},
        "counts_by_kind": {"value-pin-boundary": 1},
    }
    scan = CorpusScan(
        total_files=1,
        package_versions={"numpy": "test", "pandas": "test"},
        counts_by_kind={"surprise-refusal": 1},
        unhandled_syntax=(),
        opacity_misses=(),
    )

    with pytest.raises(AssertionError, match="outside closed taxonomy"):
        _assert_scan_matches_fixture(scan, fixture)


def test_gate_logic_rejects_stale_pinned_count() -> None:
    fixture = {
        "total_files": 1,
        "package_versions": {"numpy": "test", "pandas": "test"},
        "counts_by_kind": {"value-pin-boundary": 2},
    }
    scan = CorpusScan(
        total_files=1,
        package_versions={"numpy": "test", "pandas": "test"},
        counts_by_kind={"value-pin-boundary": 1},
        unhandled_syntax=(),
        opacity_misses=(),
    )

    with pytest.raises(AssertionError, match="refusal count fixture mismatch"):
        _assert_scan_matches_fixture(scan, fixture)


def _scan_numpy_pandas(
    package_versions: dict[str, str] | None = None,
) -> CorpusScan:
    roots = {package: _package_root(package) for package in PACKAGES}
    if package_versions is None:
        package_versions = _installed_package_versions()
    counts_by_kind: Counter[str] = Counter()
    unhandled_syntax: list[str] = []
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
                    unhandled_syntax.append(f"{rel}: {refusal.get('reason')}")
            if _has_opaque_loop_effect(result.ir) and not result.opacity_report:
                opacity_misses.append(rel)
    return CorpusScan(
        total_files=total_files,
        package_versions=package_versions,
        counts_by_kind=dict(sorted(counts_by_kind.items())),
        unhandled_syntax=tuple(sorted(unhandled_syntax)),
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
    if scan.unhandled_syntax:
        raise AssertionError(
            "unhandled-syntax stable-zero regression:\n"
            + "\n".join(scan.unhandled_syntax)
        )
    unexpected_kinds = sorted(
        kind for kind in scan.counts_by_kind if not _is_closed_refusal_kind(kind)
    )
    if unexpected_kinds:
        raise AssertionError(
            "refusal kinds outside closed taxonomy: " + ", ".join(unexpected_kinds)
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


def _load_fixture_for_package_versions(
    package_versions: dict[str, str],
) -> dict[str, Any]:
    fixture_path = _fixture_path_for_package_versions(package_versions)
    if not fixture_path.exists():
        require_declared_corpus(
            f"honest-zero fixture for package_versions "
            f"{_fixture_key(package_versions)} (expected {fixture_path.name})",
            FIXTURE_DIR,
            "sugar-build.toml, which PINS numpy = 2.5.1 and pandas = 3.0.3 -- "
            "so the pinned versions always have a fixture and any other "
            "version means the environment drifted off the pin",
            "install the pinned vendor versions, or add a version-keyed "
            "fixture for the version you intend to gate on. Vendor version is "
            "an explicit corpus input, so never compare against another "
            "vendor version",
        )
    return json.loads(fixture_path.read_text(encoding="utf-8"))


def _fixture_path_for_package_versions(package_versions: dict[str, str]) -> Path:
    suffix = "__".join(f"{package}-{package_versions[package]}" for package in PACKAGES)
    return FIXTURE_DIR / f"{FIXTURE_PREFIX}__{suffix}.json"


def _fixture_key(package_versions: dict[str, str]) -> str:
    return ",".join(f"{package}={package_versions[package]}" for package in PACKAGES)


def _installed_package_versions() -> dict[str, str]:
    return {package: _package_version(package) for package in PACKAGES}


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
