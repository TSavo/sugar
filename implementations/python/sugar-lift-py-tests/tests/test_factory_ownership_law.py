"""Ownership-law instrument: owns without honest construction is debt."""

from __future__ import annotations

import importlib.util
from pathlib import Path


from sugar_lift_py_tests.repo_root import sugar_lift_py_tests_package_root

_KIT = sugar_lift_py_tests_package_root()
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
    assert "R_ownership = 2" in _SCANNER.format_report(offenders)


def test_scanner_flags_untyped_incomplete_after_owns(tmp_path: Path) -> None:
    sugar = tmp_path / "sugar"
    sugar.mkdir()
    (sugar / "demo_sugar.py").write_text(
        """
class DemoSugar:
    @classmethod
    def owns(cls, site):
        return site.observed == "Call"

    @classmethod
    def witnesses(cls):
        return [object()]

    def desugar(self, ctx=None):
        return Incomplete("unsupported construction")
""",
        encoding="utf-8",
    )

    offenders = _SCANNER.scan_sugar_tree(sugar)
    assert {(row.kind, row.sugar) for row in offenders} == {
        ("untyped-incomplete-after-owns", "DemoSugar")
    }


def test_typed_runtime_effect_without_bad_twin_is_ownership_debt(
    tmp_path: Path,
) -> None:
    sugar = tmp_path / "sugar"
    sugar.mkdir()
    (sugar / "demo_sugar.py").write_text(
        """
class DemoSugar:
    @classmethod
    def owns(cls, site):
        return site.observed == "Call"

    @classmethod
    def witnesses(cls):
        return [object()]

    def desugar(self, ctx=None):
        return Incomplete(DemoRuntimeEffect("runtime operand"))
""",
        encoding="utf-8",
    )

    offenders = _SCANNER.scan_sugar_tree(sugar)
    assert {(row.kind, row.sugar) for row in offenders} == {
        ("unwitnessed-runtime-effect-after-owns", "DemoSugar")
    }


def test_typed_runtime_effect_with_bad_twin_is_not_ownership_debt(
    tmp_path: Path,
) -> None:
    sugar = tmp_path / "sugar"
    sugar.mkdir()
    (sugar / "demo_sugar.py").write_text(
        """
class DemoSugar:
    @classmethod
    def owns(cls, site):
        return site.observed == "Call"

    @classmethod
    def witnesses(cls):
        return typed_red_effect_witness(
            name="demo",
            owner_sugar="DemoSugar",
            source="def A(): pass",
            effect_class="DemoRuntimeEffect",
            reason_needle="runtime",
            blame_needle="demo.py:1",
            wrong_reason_needle="owner=WrongSugar",
        )

    def desugar(self, ctx=None):
        return Incomplete(DemoRuntimeEffect("runtime operand"))
""",
        encoding="utf-8",
    )

    assert _SCANNER.scan_sugar_tree(sugar) == []


def test_ownership_law_stable_zero() -> None:
    """R_ownership_law > 0 ⇒ red until every owns arm is enrolled honestly."""
    offenders = _SCANNER.scan_sugar_tree(_KIT / "src" / "sugar_lift_py_tests" / "sugar")
    assert offenders == [], (
        "Ownership law: selected Sugar must construct or typed-red under twin; "
        f"R_ownership={len(offenders)}; enroll witnesses / narrow owns:\n"
        + _SCANNER.format_report(offenders)
    )


def test_scanner_reports_missing_root_as_auditor_error(tmp_path: Path) -> None:
    offenders = _SCANNER.scan_sugar_tree(tmp_path / "missing")

    assert [(row.line, row.kind, row.sugar) for row in offenders] == [
        (0, "auditor-root-error", "-")
    ]


def test_scanner_reports_parse_error_as_auditor_error(tmp_path: Path) -> None:
    sugar = tmp_path / "sugar"
    sugar.mkdir()
    (sugar / "broken.py").write_text("def broken(:\n", encoding="utf-8")

    offenders = _SCANNER.scan_sugar_tree(sugar)

    assert [(row.path, row.line, row.kind) for row in offenders] == [
        ("sugar/broken.py", 1, "auditor-parse-error")
    ]


def test_scanner_reports_read_error_as_auditor_error(
    tmp_path: Path, monkeypatch
) -> None:
    sugar = tmp_path / "sugar"
    sugar.mkdir()
    broken = sugar / "broken.py"
    broken.write_text("pass\n", encoding="utf-8")
    original_read_text = Path.read_text

    def fail_target(path: Path, *args, **kwargs) -> str:
        if path == broken:
            raise OSError("planted unreadable source")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fail_target)

    offenders = _SCANNER.scan_sugar_tree(sugar)

    assert [(row.path, row.line, row.kind) for row in offenders] == [
        ("sugar/broken.py", 0, "auditor-read-error")
    ]
