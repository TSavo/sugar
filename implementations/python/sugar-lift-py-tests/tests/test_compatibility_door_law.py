"""Discrimination for R_compatibility_door (Criterion 4 recognition).

Report-first instrument: planted twins red, clean trees quiet, live R measured.
No drain in this suite — recognition only.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_KIT = Path(__file__).resolve().parents[1]
_SCANNER_PATH = _KIT / "scripts" / "compatibility_door_law.py"
_SPEC = importlib.util.spec_from_file_location("compatibility_door_law", _SCANNER_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_SCANNER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_SCANNER)

_PYTHON_ROOT = _KIT.parent  # implementations/python


def test_discrimination_self_test_is_green() -> None:
    assert _SCANNER.discrimination_self_test() is True
    assert _SCANNER.main(["--self-test"]) == 0


def test_lying_comment_marked_second_entry_is_detected(tmp_path: Path) -> None:
    root = tmp_path / "python"
    pkg = root / "sugar-lift-py-tests/src/sugar_lift_py_tests"
    pkg.mkdir(parents=True)
    (root / "sugar-source-tree/src").mkdir(parents=True)
    (root / "sugar-lift-python-source/src").mkdir(parents=True)
    (pkg / "shim.py").write_text(
        """
# Legacy helper -- kept for backward compatibility with existing callers.
def open_legacy(path):
    return open_source_file_for_construction(path)
""",
        encoding="utf-8",
    )
    offenders = _SCANNER.scan_python_root(root)
    assert any(o.kind == "comment-marked-second-entry" for o in offenders)
    assert any(o.name == "open_legacy" for o in offenders)


def test_lying_name_marked_second_entry_is_detected(tmp_path: Path) -> None:
    root = tmp_path / "python"
    pkg = root / "sugar-lift-py-tests/src/sugar_lift_py_tests"
    pkg.mkdir(parents=True)
    (root / "sugar-source-tree/src").mkdir(parents=True)
    (root / "sugar-lift-python-source/src").mkdir(parents=True)
    (pkg / "shim.py").write_text(
        """
def legacy_construct(path):
    return SourceFile.from_path(path).sugar()
""",
        encoding="utf-8",
    )
    offenders = _SCANNER.scan_python_root(root)
    assert any(
        o.kind == "name-marked-second-entry" and o.name == "legacy_construct"
        for o in offenders
    )


def test_prose_legacy_without_second_entry_is_quiet(tmp_path: Path) -> None:
    root = tmp_path / "python"
    pkg = root / "sugar-lift-py-tests/src/sugar_lift_py_tests"
    pkg.mkdir(parents=True)
    (root / "sugar-source-tree/src").mkdir(parents=True)
    (root / "sugar-lift-python-source/src").mkdir(parents=True)
    (pkg / "wire.py").write_text(
        """
# Historical note: the legacy wire field was renamed.
def project(row):
    return row["exitPartitionArity"]
""",
        encoding="utf-8",
    )
    offenders = _SCANNER.scan_python_root(root)
    assert offenders == [], _SCANNER.format_report(offenders)


def test_sole_door_without_marker_is_quiet(tmp_path: Path) -> None:
    root = tmp_path / "python"
    pkg = root / "sugar-lift-py-tests/src/sugar_lift_py_tests"
    pkg.mkdir(parents=True)
    (root / "sugar-source-tree/src").mkdir(parents=True)
    (root / "sugar-lift-python-source/src").mkdir(parents=True)
    (pkg / "door.py").write_text(
        """
def open_tree(path):
    return open_source_file_for_construction(path)
""",
        encoding="utf-8",
    )
    offenders = _SCANNER.scan_python_root(root)
    assert offenders == [], _SCANNER.format_report(offenders)


def test_live_scan_reports_named_axes() -> None:
    """Live R is measured output — may be zero (honest absence)."""
    offenders = _SCANNER.scan_python_root(_PYTHON_ROOT)
    counts = _SCANNER.axis_counts(offenders)
    for axis in _SCANNER._AXES:
        assert axis in counts
    report = _SCANNER.format_report(offenders)
    assert "compatibility_door_law" in report
    assert "R_compat_comment_marked_entry" in report
