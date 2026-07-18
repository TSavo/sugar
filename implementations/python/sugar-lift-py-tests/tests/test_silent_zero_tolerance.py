"""Permanent baseline-free R_silent floor."""

from __future__ import annotations

import importlib.util
from pathlib import Path


_KIT = Path(__file__).resolve().parents[1]
_SCANNER_PATH = _KIT / "scripts" / "silent_zero_tolerance.py"
_SPEC = importlib.util.spec_from_file_location("silent_zero_tolerance", _SCANNER_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_SCANNER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_SCANNER)


def test_planted_silent_residue_trips_floor() -> None:
    report = {
        "sourceLedger": {"unclassified_source": 1},
        "liftCoverage": {
            "totals": {"silently_unaccounted": 2},
            "conservation": {"delta": 2},
        },
        "factoryAuditSummary": {
            "sourceFactoryConservation": {
                "violations": [
                    {
                        "locus": "planted.py:3:0:FunctionDef",
                        "reason": "source body owner disappeared",
                    }
                ]
            }
        },
    }

    offenders = _SCANNER.silent_offenders(report, file="planted.py")

    assert {offender.kind for offender in offenders} == {
        "silent-assertion",
        "unclassified-source",
        "unclassified-source-owner",
    }
    assert _SCANNER.r_silent(offenders) == 4


def test_fully_spoken_report_is_zero() -> None:
    report = {
        "sourceLedger": {"unclassified_source": 0},
        "liftCoverage": {
            "totals": {"silently_unaccounted": 0},
            "conservation": {"delta": 0},
        },
        "factoryAuditSummary": {
            "sourceFactoryConservation": {"violations": []}
        },
    }

    assert _SCANNER.silent_offenders(report, file="spoken.py") == []


def test_missing_accounting_is_silent() -> None:
    offenders = _SCANNER.silent_offenders({}, file="missing.py")

    assert [(row.kind, row.count) for row in offenders] == [
        ("missing-accounting-testimony", 1)
    ]
