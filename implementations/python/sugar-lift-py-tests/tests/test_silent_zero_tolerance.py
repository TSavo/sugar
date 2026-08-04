"""Permanent baseline-free R_silent floor."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from sugar_lift_py_tests.idd.lift_coverage_census import census_source


from sugar_lift_py_tests.repo_root import sugar_lift_py_tests_package_root

_KIT = sugar_lift_py_tests_package_root()
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


def test_empty_disk_census_skips_with_zero_silent(tmp_path: Path) -> None:
    """No asserts/bodies → R_silent=0 by predicate; no construction required."""
    path = tmp_path / "emptyish.py"
    path.write_text("x = 1\n", encoding="utf-8")
    category, offenders = _SCANNER._audit_file(path, rel="emptyish.py")
    assert category == "completed"
    assert offenders == ()
    assert _SCANNER.disk_census_empty(
        census_source(path.read_text(encoding="utf-8"), file="emptyish.py")
    )


def test_register_only_matches_discharge_silent_offenders(tmp_path: Path) -> None:
    """Identity twin: register-only membership ≡ full discharge for silent.

    Proves the fast path did not change what the floor measures.
    """
    samples = {
        "plain.py": "def f():\n    assert True\n",
        "multi.py": (
            "def a():\n    assert 1\n\n"
            "async def b():\n    assert 2\n\n"
            "class C:\n    def m(self):\n        assert 3\n"
        ),
        "module_level.py": "assert True\nx = 1\n",
        "no_assert_body.py": "def f():\n    return 1\n",
        "empty_disk.py": "x = 1\n",
    }
    for name, source in samples.items():
        path = tmp_path / name
        path.write_text(source, encoding="utf-8")
        _, reg = _SCANNER._audit_file(path, rel=name)
        _, dis = _SCANNER._audit_file_discharge(path, rel=name)
        assert reg == dis, f"{name}: register-only {reg!r} != discharge {dis!r}"


def test_register_only_matches_discharge_on_small_kit_file() -> None:
    """Identity twin on one small live kit file (full corpus is CI floors)."""
    path = _KIT / "src" / "sugar_lift_py_tests" / "filename.py"
    if not path.is_file():
        pytest.skip("kit filename.py missing")
    rel = "filename.py"
    _, reg = _SCANNER._audit_file(path, rel=rel)
    _, dis = _SCANNER._audit_file_discharge(path, rel=rel)
    assert reg == dis, f"register-only != discharge\n{reg!r}\n{dis!r}"
