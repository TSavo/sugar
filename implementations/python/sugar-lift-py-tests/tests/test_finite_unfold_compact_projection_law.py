"""Discrimination for the finite_unfold compact-projection residual instrument."""

from __future__ import annotations

import importlib.util
from pathlib import Path


from sugar_lift_py_tests.repo_root import sugar_lift_py_tests_package_root

_KIT = sugar_lift_py_tests_package_root()
_PATH = _KIT / "scripts" / "finite_unfold_compact_projection_law.py"
_SPEC = importlib.util.spec_from_file_location("finite_unfold_compact_law", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
_SCANNER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_SCANNER)


def _scan(source: str):
    return _SCANNER.scan_source(source, path="sugar/planted.py")


def test_planted_for_over_cap_panic_trips() -> None:
    rows = _scan("""
def finish(elements, site):
    if element_count > limit:
        finite_unfold_cap_panic(
            construction="ForSugar finite iterable",
            site=site,
            observed="iterable cardinality=12",
            limit=limit,
        )
    return unfold(elements)
""")
    assert [row.kind for row in rows] == ["for-over-cap-panic"]


def test_planted_for_nonground_while_panic_trips() -> None:
    rows = _scan("""
def finish(elements, site):
    if body_has_while and while_reads_non_ground:
        finite_unfold_cap_panic(
            construction="ForSugar finite for/while non-ground outer",
            site=site,
            observed="iterable cardinality=10 with non-ground while body",
            limit=1024,
        )
    return unfold(elements)
""")
    assert [row.kind for row in rows] == ["for-nonground-while-panic"]


def test_planted_range_over_cap_panic_trips() -> None:
    rows = _scan("""
def range_call(cardinality, site):
    if cardinality > STATIC_UNFOLD_LIMIT:
        finite_unfold_cap_panic(
            construction="CallSugar range",
            site=site,
            observed=f"range cardinality={cardinality}",
            limit=STATIC_UNFOLD_LIMIT,
        )
    return ListValue(span)
""")
    assert [row.kind for row in rows] == ["range-over-cap-panic"]


def test_overflow_and_unrelated_panics_stay_green() -> None:
    assert _scan("""
def range_call(site):
    finite_unfold_cap_panic(
        construction="CallSugar range",
        site=site,
        observed="range cardinality exceeds sys.maxsize",
        limit=STATIC_UNFOLD_LIMIT,
    )
""") == []
    assert _scan("""
def finish(site):
    finite_unfold_cap_panic(
        construction="ForSugar finite iterable length",
        site=site,
        observed="finite iterable length overflow",
        limit=STATIC_UNFOLD_LIMIT,
    )
""") == []
    assert _scan("""
def multiply(site):
    finite_unfold_cap_panic(
        construction="ListValue repetition",
        site=site,
        observed="list repetition cardinality=99999",
        limit=STATIC_UNFOLD_LIMIT,
    )
""") == []


def test_compact_projection_source_stays_green() -> None:
    assert _scan("""
def finish(elements, iterable, ctx, site):
    if element_count > limit or nonground_while:
        return self._project_compact_finite(iterable, ctx)
    return self._unfold_values(elements, ctx)

def range_call(cardinality, accumulated):
    if cardinality <= STATIC_UNFOLD_LIMIT:
        return Complete(ListValue(tuple(TermValue(v) for v in span)))
    # over-cap falls through to CallSiteValue projection
""") == []


def test_bad_parse_and_missing_root_are_structured(tmp_path: Path) -> None:
    bad = tmp_path / "bad.py"
    bad.write_text("def (\n", encoding="utf-8")
    rows = _SCANNER.scan_roots((tmp_path, tmp_path / "missing"))
    assert {row.kind for row in rows} == {
        "auditor-parse-error",
        "auditor-root-error",
    }
    assert _SCANNER.r_auditor_errors(rows) == 2
    assert _SCANNER.main([str(tmp_path), str(tmp_path / "missing")]) == 1
