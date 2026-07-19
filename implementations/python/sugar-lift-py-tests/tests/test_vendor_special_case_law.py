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
    kinds = {(row.kind, row.vendor) for row in offenders}

    assert ("vendor-name-match", "pandas") in kinds
    assert ("vendor-isinstance", "numpy") in kinds
    # Relocating a logo into a set/dict must still trip — never a green hide.
    assert ("vendor-table-literal", "requests") in kinds
    assert _SCANNER.r_vendor_special_case(offenders) >= 3


def test_planted_mapping_literal_twin_trips_floor(tmp_path: Path) -> None:
    """Moving a vendor name from == into a dispatch dict cannot green the floor."""
    sugar = tmp_path / "sugar"
    sugar.mkdir()
    (sugar / "registry.py").write_text(
        """
# No comparisons — only a recognition-style registry initializer.
_CALL_SHAPES = {
    "numpy.arange": "RANGE_ARRAY",
    "sqlalchemy.orm.registry": "SQLALCHEMY_ORM_REGISTRY",
}
_IDENTITY = {("pandas.api.extensions", "register_series_accessor")}
_FIXTURE = {"pytest.fixture"}
""",
        encoding="utf-8",
    )

    offenders = _SCANNER.scan_roots((sugar,))
    kinds = {(row.kind, row.vendor, row.expression) for row in offenders}

    assert ("vendor-table-literal", "numpy", "'numpy.arange'") in kinds
    assert (
        "vendor-table-literal",
        "sqlalchemy",
        "'sqlalchemy.orm.registry'",
    ) in kinds
    assert ("vendor-table-literal", "pandas", "'pandas.api.extensions'") in kinds
    assert ("vendor-table-literal", "pytest", "'pytest.fixture'") in kinds
    assert _SCANNER.r_vendor_special_case(offenders) >= 4
    # Pure mapping hide: no compare / isinstance required
    assert all(row.kind == "vendor-table-literal" for row in offenders)


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


def test_language_protocol_string_without_vendor_root_stays_quiet(
    tmp_path: Path,
) -> None:
    """stdlib / language coordinates are not scanned vendor roots."""
    sugar = tmp_path / "sugar"
    sugar.mkdir()
    (sugar / "lang.py").write_text(
        """
_LANG = {
    "functools.wraps": "IMPLEMENTATION_PRESERVING_DECORATOR",
    "pathlib.Path": "PATH",
    "re.compile": "REGEX_PATTERN",
    "dataclasses.dataclass": True,
}
""",
        encoding="utf-8",
    )

    assert _SCANNER.scan_roots((sugar,)) == []


def test_unreadable_or_invalid_source_is_structured_not_crash(tmp_path: Path) -> None:
    """Windows portability: auditor must not process-crash on bad files (#5253)."""
    sugar = tmp_path / "sugar"
    sugar.mkdir()
    bad = sugar / "binaryish.py"
    bad.write_bytes(b"\xff\xfe\x00not-valid-python\x00")
    (sugar / "syntax_error.py").write_text("def (\n", encoding="utf-8")
    missing = tmp_path / "does-not-exist"

    offenders = _SCANNER.scan_roots((sugar, missing))
    kinds = {row.kind for row in offenders}
    assert "auditor-parse-error" in kinds or "auditor-read-error" in kinds
    assert "auditor-root-error" in kinds
    assert _SCANNER.r_vendor_special_case(offenders) == 0
    assert _SCANNER.r_auditor_errors(offenders) >= 1
    code = _SCANNER.main([str(sugar), str(missing)])
    assert code == 1
