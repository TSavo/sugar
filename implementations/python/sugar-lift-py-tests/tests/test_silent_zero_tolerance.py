"""Permanent baseline-free R_silent floor."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from sugar_lift_py_tests.idd.lift_coverage_census import census_source

_KIT = Path(__file__).resolve().parents[1]
_SCANNER_PATH = _KIT / "scripts" / "silent_zero_tolerance.py"
_SPEC = importlib.util.spec_from_file_location("silent_zero_tolerance", _SCANNER_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_SCANNER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_SCANNER)


def _locus(status: str, kind: str, line: int, col: int) -> dict:
    return {
        "status": status,
        "kind": kind,
        "name": kind,
        "source_cid": f"cid-{kind}-{line}-{col}",
        "locus": {"file": "sample.py", "line": line, "col": col},
    }


def test_absent_assert_and_body_loci_trip_the_silent_floor() -> None:
    census = census_source("def f():\n    assert True\n", file="sample.py")

    offenders = _SCANNER.silent_offenders(census, {"loci": []})

    assert {(row.kind, row.count) for row in offenders} == {
        ("silent-Assert", 1),
        ("silent-FunctionDef", 1),
    }
    assert _SCANNER.r_silent(offenders) == 2


def test_warranted_and_unresolved_loci_are_both_not_silent() -> None:
    census = census_source("def f():\n    assert True\n", file="sample.py")
    audit = {
        "loci": [
            _locus("warranted", "FunctionDef", 1, 0),
            _locus("unresolved", "Assert", 2, 4),
        ]
    }

    assert _SCANNER.silent_offenders(census, audit) == []


def test_wrong_kind_at_same_coordinate_is_silent() -> None:
    census = census_source("def f():\n    assert True\n", file="sample.py")
    audit = {
        "loci": [
            _locus("warranted", "FunctionDef", 1, 0),
            _locus("warranted", "Expr", 2, 4),
        ]
    }

    offenders = _SCANNER.silent_offenders(census, audit)

    assert [(row.kind, row.count) for row in offenders] == [("silent-Assert", 1)]


def test_production_roots_cover_package_and_corpus_tooling(tmp_path: Path) -> None:
    """Kit roots still exist for intentional self-check — never CLI default."""
    roots = _SCANNER.production_roots(tmp_path)

    assert roots == (
        tmp_path / "implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests",
        tmp_path / "implementations/python/sugar-lift-py-tests/scripts",
    )


def test_empty_scan_roots_are_refused() -> None:
    """Wrong-population door closed: empty args cannot green on kit default."""
    with pytest.raises(ValueError, match="scan roots must be explicit"):
        _SCANNER.require_explicit_scan_roots(())


def test_empty_surface_is_loud(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no Python source files"):
        _SCANNER.require_python_paths((tmp_path / "missing",))
