"""Permanent baseline-free R_vendor_special_case floor."""

from __future__ import annotations

import importlib.util
from pathlib import Path


_KIT = Path(__file__).resolve().parents[1]
_SCANNER_PATH = _KIT / "scripts" / "vendor_special_case_law.py"
_SPEC = importlib.util.spec_from_file_location(
    "vendor_special_case_law", _SCANNER_PATH
)
assert _SPEC is not None and _SPEC.loader is not None
_SCANNER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_SCANNER)


def test_planted_vendor_name_and_class_checks_trip_floor(tmp_path: Path) -> None:
    sugar = tmp_path / "sugar"
    sugar.mkdir()
    (sugar / "bad.py").write_text(
        """
import numpy

_VENDOR_TYPES = {"requests.Session"}

def owns(value):
    if value.import_target == "pandas.DataFrame":
        return True
    if value.target_name in _VENDOR_TYPES:
        return True
    return isinstance(value, numpy.ndarray)
""",
        encoding="utf-8",
    )

    offenders = _SCANNER.scan_roots((sugar,))

    assert [(row.kind, row.vendor) for row in offenders] == [
        ("vendor-name-match", "pandas"),
        ("vendor-name-match", "requests"),
        ("vendor-isinstance", "numpy"),
    ]
    assert _SCANNER.r_vendor_special_case(offenders) == 3


def test_shape_checks_do_not_trip_floor(tmp_path: Path) -> None:
    sugar = tmp_path / "sugar"
    sugar.mkdir()
    (sugar / "ok.py").write_text(
        """
def owns(value):
    return value.observed == "Call" and isinstance(value, CallSiteValue)
""",
        encoding="utf-8",
    )

    assert _SCANNER.scan_roots((sugar,)) == []
