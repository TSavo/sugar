"""Ownership-law instrument: owns without honest construction is debt."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_KIT = Path(__file__).resolve().parents[1]
_SCANNER_PATH = _KIT / "scripts" / "factory_ownership_law.py"
_SPEC = importlib.util.spec_from_file_location("factory_ownership_law", _SCANNER_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_SCANNER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_SCANNER)


def test_scanner_flags_owns_without_witnesses(tmp_path: Path) -> None:
    sugar = tmp_path / "sugar"
    sugar.mkdir()
    (sugar / "demo_sugar.py").write_text(
        """
class DemoSugar:
    @classmethod
    def owns(cls, site):
        return site.observed == "Call"

    def desugar(self, ctx=None):
        return None
""",
        encoding="utf-8",
    )
    offenders = _SCANNER.scan_sugar_tree(sugar)
    kinds = {(row.kind, row.sugar) for row in offenders}
    assert ("unenrolled-owns", "DemoSugar") in kinds
    assert ("broad-unenrolled-owns", "DemoSugar") in kinds


def test_ownership_law_stable_zero() -> None:
    """R_ownership_law > 0 ⇒ red until every owns arm is enrolled honestly."""
    offenders = _SCANNER.scan_sugar_tree(
        _KIT / "src" / "sugar_lift_py_tests" / "sugar"
    )
    assert offenders == [], (
        "Ownership law: selected Sugar must construct or typed-red under twin; "
        f"R_ownership_law={len(offenders)}; enroll witnesses / narrow owns:\n"
        + _SCANNER.format_report(offenders)
    )
