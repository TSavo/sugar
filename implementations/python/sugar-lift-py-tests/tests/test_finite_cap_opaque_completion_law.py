"""Discrimination for the baseline-free finite-cap opaque-completion floor."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_KIT = Path(__file__).resolve().parents[1]
_PATH = _KIT / "scripts" / "finite_cap_opaque_completion_law.py"
_SPEC = importlib.util.spec_from_file_location("finite_cap_law", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
_SCANNER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_SCANNER)


def _scan(source: str):
    return _SCANNER.scan_source(source, path="sugar/planted.py")


def test_planted_opaque_complete_trips() -> None:
    rows = _scan("""
def reduce(values):
    if len(values) > MATERIALIZE_LIMIT:
        return Complete(CallSiteValue(body=None, term=exact_term))
    return build_all(values)
""")
    assert [row.kind for row in rows] == ["finite-cap-opaque-complete"]


def test_planted_under_cap_early_return_then_opaque_fallthrough_trips() -> None:
    rows = _scan("""
def reduce(values):
    if len(values) <= MATERIALIZE_LIMIT:
        return build_all(values)
    return Complete(CallSiteValue(body=None, term=exact_term))
""")
    assert [row.kind for row in rows] == ["finite-cap-opaque-complete"]


def test_planted_novel_opaque_complete_is_closed_by_default() -> None:
    rows = _scan("""
def reduce(values):
    if len(values) > MATERIALIZE_LIMIT:
        return Complete(FutureOpaqueSuccess(source_shape=values[0]))
    return Complete(ListValue(tuple(build(value) for value in values)))
""")
    assert [row.kind for row in rows] == ["finite-cap-opaque-complete"]


def test_planted_coordinate_fallback_trips() -> None:
    rows = _scan("""
def reduce(parts):
    if len(parts) > 1024:
        return opaque_coordinate()
    return build_all(parts)
""")
    assert [row.kind for row in rows] == ["finite-cap-opaque-coordinate"]


def test_planted_force_curry_trips() -> None:
    rows = _scan("""
def reduce(elements):
    if len(elements) > cap:
        return bind(elements, force_curry=True)
    return unfold(elements)
""")
    assert [row.kind for row in rows] == ["finite-cap-force-curry"]


def test_planted_finite_semantic_short_circuit_force_curry_trips() -> None:
    rows = _scan("""
def reduce(iterable):
    elements = finite_elements(iterable)
    if elements is not None:
        if body_reads_runtime_outer():
            return bind(iterable, force_curry=True)
        return unfold(elements)
    return runtime_coordinate(iterable)
""")
    assert [row.kind for row in rows] == ["finite-cap-force-curry"]


def test_cardinality_attribute_cap_force_curry_trips() -> None:
    rows = _scan("""
def reduce(values):
    if values.cardinality > cap:
        return bind(values, force_curry=True)
    return unfold(values)
""")
    assert [row.kind for row in rows] == ["finite-cap-force-curry"]


def test_cap_helper_delegation_trips() -> None:
    rows = _scan("""
def opaque_helper(values):
    return bind(values, force_curry=True)

def reduce(values):
    if len(values) > cap:
        return opaque_helper(values)
    return unfold(values)
""")
    assert [row.kind for row in rows] == ["finite-cap-force-curry"]


def test_cap_none_success_trips() -> None:
    rows = _scan("""
def reduce(values):
    if len(values) > cap:
        return None
    return unfold(values)
""")
    assert [row.kind for row in rows] == ["finite-cap-none-success"]


def test_loud_terminal_and_exact_symbolic_stay_green() -> None:
    assert _scan("""
def reduce(values):
    if len(values) > MATERIALIZE_LIMIT:
        return construction_panic_gap(owner="finite_unfold", observed=len(values))
    return build_all(values)
""") == []
    assert _scan("""
def reduce(values):
    if len(values) > MATERIALIZE_LIMIT:
        return Complete(GroundSequenceRepetitionValue(values, exact_count))
    return build_all(values)
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
