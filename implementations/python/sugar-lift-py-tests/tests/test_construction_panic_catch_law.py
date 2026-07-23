"""Permanent floor: ConstructionPanic catches only at audit membrane."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_KIT = Path(__file__).resolve().parents[1]
_SCANNER_PATH = _KIT / "scripts" / "construction_panic_catch_law.py"
_SPEC = importlib.util.spec_from_file_location(
    "construction_panic_catch_law", _SCANNER_PATH
)
assert _SPEC is not None and _SPEC.loader is not None
_SCANNER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_SCANNER)


def test_scanner_flags_soft_construction_panic_catch(tmp_path: Path) -> None:
    pkg = tmp_path / "sugar_lift_py_tests"
    pkg.mkdir()
    (pkg / "bad.py").write_text(
        """
from sugar_lift_py_tests.gap.panic import ConstructionPanic

def dig():
    try:
        raise ConstructionPanic(None)
    except ConstructionPanic as panic:
        return None
""",
        encoding="utf-8",
    )
    offenders = _SCANNER.scan_package(pkg)
    assert any(o.kind == "construction-panic-catch-outside-membrane" for o in offenders)


def test_scanner_allows_pure_reraise(tmp_path: Path) -> None:
    pkg = tmp_path / "sugar_lift_py_tests"
    pkg.mkdir()
    (pkg / "ok.py").write_text(
        """
from sugar_lift_py_tests.gap.panic import ConstructionPanic

def dig():
    try:
        raise ConstructionPanic(None)
    except ConstructionPanic:
        raise
""",
        encoding="utf-8",
    )
    offenders = _SCANNER.scan_package(pkg)
    assert offenders == []


def test_scanner_flags_corpus_tooling_catch(tmp_path: Path) -> None:
    package = tmp_path / "src" / "sugar_lift_py_tests"
    package.mkdir(parents=True)
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "bad_corpus_tool.py").write_text(
        """
from sugar_lift_py_tests.gap.panic import ConstructionPanic

def audit():
    try:
        raise ConstructionPanic(None)
    except ConstructionPanic:
        return []
""",
        encoding="utf-8",
    )

    offenders = _SCANNER.scan_repository(tmp_path)

    assert [(row.path, row.kind) for row in offenders] == [
        (
            "scripts/bad_corpus_tool.py",
            "construction-panic-catch-outside-membrane",
        )
    ]


def test_current_repository_construction_panic_catch_law() -> None:
    """R_construction_panic_catches_outside_audit > 0 ⇒ red until production soft catches die."""
    offenders = _SCANNER.scan_repository(_KIT)
    assert offenders == [], (
        "Only sanctioned membranes may catch ConstructionPanic "
        "(audit enumeration or production typed-gap classification); "
        f"R_construction_panic_catches_outside_membrane={len(offenders)}:\n"
        + _SCANNER.format_report(offenders)
    )


def test_scanner_reports_missing_root_as_auditor_error(tmp_path: Path) -> None:
    offenders = _SCANNER.scan_repository(tmp_path / "missing")

    assert {(row.path, row.line, row.kind) for row in offenders} == {
        ("src/sugar_lift_py_tests", 0, "auditor-root-error"),
        ("scripts", 0, "auditor-root-error"),
    }


def test_scanner_reports_parse_error_as_auditor_error(tmp_path: Path) -> None:
    package = tmp_path / "src" / "sugar_lift_py_tests"
    package.mkdir(parents=True)
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "broken.py").write_text("def broken(:\n", encoding="utf-8")

    offenders = _SCANNER.scan_repository(tmp_path)

    assert [(row.path, row.line, row.kind) for row in offenders] == [
        ("scripts/broken.py", 1, "auditor-parse-error")
    ]


def test_scanner_reports_read_error_as_auditor_error(
    tmp_path: Path, monkeypatch
) -> None:
    package = tmp_path / "src" / "sugar_lift_py_tests"
    package.mkdir(parents=True)
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    broken = scripts / "broken.py"
    broken.write_text("pass\n", encoding="utf-8")
    original_read_text = Path.read_text

    def fail_target(path: Path, *args, **kwargs) -> str:
        if path == broken:
            raise OSError("planted unreadable source")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fail_target)

    offenders = _SCANNER.scan_repository(tmp_path)

    assert [(row.path, row.line, row.kind) for row in offenders] == [
        ("scripts/broken.py", 0, "auditor-read-error")
    ]
