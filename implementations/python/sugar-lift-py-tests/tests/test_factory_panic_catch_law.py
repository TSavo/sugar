"""Permanent floor: FactoryPanic catches only at audit membrane."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_KIT = Path(__file__).resolve().parents[1]
_SCANNER_PATH = _KIT / "scripts" / "factory_panic_catch_law.py"
_SPEC = importlib.util.spec_from_file_location("factory_panic_catch_law", _SCANNER_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_SCANNER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_SCANNER)


def test_scanner_flags_soft_factory_panic_catch(tmp_path: Path) -> None:
    pkg = tmp_path / "sugar_lift_py_tests"
    pkg.mkdir()
    (pkg / "bad.py").write_text(
        """
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic

def dig():
    try:
        raise FactoryPanic(None)
    except FactoryPanic as panic:
        return None
""",
        encoding="utf-8",
    )
    offenders = _SCANNER.scan_package(pkg)
    assert any(o.kind == "factory-panic-catch-outside-audit" for o in offenders)


def test_scanner_allows_pure_reraise(tmp_path: Path) -> None:
    pkg = tmp_path / "sugar_lift_py_tests"
    pkg.mkdir()
    (pkg / "ok.py").write_text(
        """
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic

def dig():
    try:
        raise FactoryPanic(None)
    except FactoryPanic:
        raise
""",
        encoding="utf-8",
    )
    offenders = _SCANNER.scan_package(pkg)
    assert offenders == []


def test_current_package_factory_panic_catch_law() -> None:
    """R_factory_panic_catches_outside_audit > 0 ⇒ red until production soft catches die."""
    offenders = _SCANNER.scan_package(_KIT / "src" / "sugar_lift_py_tests")
    assert offenders == [], (
        "Only audit membrane may catch FactoryPanic for a loud red row; "
        f"R_factory_panic_catches_outside_audit={len(offenders)}:\n"
        + _SCANNER.format_report(offenders)
    )
