"""Lying twins for the SELF-SEALING INSTRUMENT class auditor."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


from sugar_lift_py_tests.repo_root import resolve_repo_root, sugar_lift_py_tests_package_root

_SCRIPT = sugar_lift_py_tests_package_root() / "scripts" / "self_sealing_instrument_law.py"
_SPEC = importlib.util.spec_from_file_location("self_sealing_instrument_law", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
LAW = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = LAW
_SPEC.loader.exec_module(LAW)


def _classes(source: str) -> set[str]:
    return {
        finding.violation_class
        for finding in LAW.scan_python_source(source, "planted.py")
    }


def test_each_reject_class_has_a_structural_planted_twin() -> None:
    """Lying twin: each subclass is recognized when planted."""
    assert _classes("""
def audit():
    projection_calls = []
    if not projection_calls:
        projection_calls = [
            EvidenceSite(Path(__file__).resolve(), 1, (), audit.__name__)
        ]
    assert projection_calls
""") == {"SYNTHESIZED-EVIDENCE"}

    assert _classes("""
def test_conserves():
    enrolled = 1
    assert enrolled == enrolled
""") == {"TAUTOLOGICAL-ASSERT"}

    assert _classes("""
def test_halt_identity():
    assert halted.effect.exception_type_coordinate is not None
""") == {"PRESENCE-ONLY-IDENTITY"}

    assert _classes("""
def test_occurrence():
""") == {"PRESENCE-ONLY-IDENTITY"}


def test_discrimination_negatives_do_not_false_positive() -> None:
    """Truthful twin: honest discrimination is silent."""
    source = """
def audit():
    projection_calls = [site for site in graph_callers]
    if not projection_calls:
        raise ContractRed("no production projection callers")
    assert projection_calls[0].path == expected_path

def test_conserves():
    assert report.conservation_shortfall == 0
    assert report.outcome_total == enrolled - unaccounted

def test_halt_identity():
    type_error = ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const("TypeError")],
    )
    assert halted.effect.exception_type_coordinate == type_error
    assert halted.effect.occurrence_id == "pandas/example.py:1:4"

def guard():
    if value is not None:
        return value
    return default
"""
    assert LAW.scan_python_source(source, "clean.py") == []


def test_report_names_file_line_class_and_required_fix() -> None:
    findings = LAW.scan_python_source(
        "def t():\n    assert x.exception_type_coordinate is not None\n",
        "teeth/weak.py",
    )
    rendered = LAW.format_report(findings)
    assert "teeth/weak.py:2" in rendered
    assert "PRESENCE-ONLY-IDENTITY" in rendered
    assert "required fix:" in rendered
    assert "R_self_sealing_instruments = 1" in rendered
    assert "rung=auditor" in rendered
    assert "retire_when=" in rendered


def test_sourcefile_construction_door_live_self_seed_is_drained() -> None:
    """Drain pin: construction-door auditor no longer synthesizes projection callers.

    #6958 enrolled R_synthesized_evidence=1 at the projection_calls self-seed.
    This PR deletes that fill-in; empty observation is a contract red, never a
    synthetic site. The planted twin above keeps the detector's teeth.

    Fails when: the self-seed shape returns (if not projection_calls: fill with
    Path(__file__)/auditor). Reachable by reintroducing the fallback.
    """
    # parents: tests -> sugar-lift-py-tests -> python -> implementations -> repo
    repo = resolve_repo_root()
    auditor = repo / "tests" / "sourcefile_construction_door_auditor.py"
    assert auditor.is_file(), auditor
    source = auditor.read_text(encoding="utf-8")
    findings = LAW.scan_python_source(
        source, "tests/sourcefile_construction_door_auditor.py"
    )
    synthesized = [f for f in findings if f.violation_class == "SYNTHESIZED-EVIDENCE"]
    assert synthesized == [], (
        "R_synthesized_evidence regression on sourcefile_construction_door_auditor: "
        "projection callers must not be self-seeded. "
        f"findings={synthesized!r}"
    )
    # Source-shape pin: the exact fallback shell must stay deleted.
    assert "if not projection_calls:" not in source
    assert "EvidenceSite(Path(__file__).resolve(), audit_line" not in source
