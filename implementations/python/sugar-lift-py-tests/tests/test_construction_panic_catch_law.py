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


def test_scanner_rejects_conditional_reraise_without_else(tmp_path: Path) -> None:
    pkg = tmp_path / "sugar_lift_py_tests"
    pkg.mkdir()
    (pkg / "bad.py").write_text(
        """
from sugar_lift_py_tests.gap.panic import ConstructionPanic

def dig(flag):
    try:
        raise ConstructionPanic(None)
    except ConstructionPanic:
        if flag:
            raise
    return None
""",
        encoding="utf-8",
    )

    offenders = _SCANNER.scan_package(pkg)

    assert [(row.path, row.kind) for row in offenders] == [
        ("bad.py", "construction-panic-catch-outside-membrane")
    ]


def test_scanner_allows_conditional_reraise_with_terminal_else(
    tmp_path: Path,
) -> None:
    pkg = tmp_path / "sugar_lift_py_tests"
    pkg.mkdir()
    (pkg / "ok.py").write_text(
        """
from sugar_lift_py_tests.gap.panic import ConstructionPanic

def dig(flag):
    try:
        raise ConstructionPanic(None)
    except ConstructionPanic:
        if flag:
            raise
        else:
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


def test_named_membrane_paths_do_not_authorize_soft_handlers(
    tmp_path: Path,
) -> None:
    package = tmp_path / "src" / "sugar_lift_py_tests"
    package.mkdir(parents=True)
    audit_only = package / "audit_only"
    audit_only.mkdir()
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    soft_handler = """
from sugar_lift_py_tests.gap.panic import ConstructionPanic

def audit():
    try:
        raise ConstructionPanic(None)
    except ConstructionPanic:
        return None
"""
    for name in (
        "desugar_repro.py",
        "exit_set_arm_census.py",
        "stablezero_classify.py",
        "_production_lift_child.py",
    ):
        (scripts / name).write_text(soft_handler, encoding="utf-8")
    (audit_only / "collect_construction_gaps.py").write_text(
        soft_handler,
        encoding="utf-8",
    )

    offenders = _SCANNER.scan_repository(tmp_path)

    assert {
        (row.path, row.kind) for row in offenders
    } == {
        (
            "src/sugar_lift_py_tests/audit_only/collect_construction_gaps.py",
            "construction-panic-catch-outside-membrane",
        ),
        (
            "scripts/desugar_repro.py",
            "construction-panic-catch-outside-membrane",
        ),
        (
            "scripts/exit_set_arm_census.py",
            "construction-panic-catch-outside-membrane",
        ),
        (
            "scripts/stablezero_classify.py",
            "construction-panic-catch-outside-membrane",
        ),
        (
            "scripts/_production_lift_child.py",
            "construction-panic-catch-outside-membrane",
        ),
    }


def test_named_membrane_path_does_not_hide_parse_error(tmp_path: Path) -> None:
    package = tmp_path / "src" / "sugar_lift_py_tests"
    package.mkdir(parents=True)
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "desugar_repro.py").write_text("def broken(:\n", encoding="utf-8")

    offenders = _SCANNER.scan_repository(tmp_path)

    assert [(row.path, row.line, row.kind) for row in offenders] == [
        ("scripts/desugar_repro.py", 1, "auditor-parse-error")
    ]


def test_production_membrane_path_does_not_authorize_fabricated_success(
    tmp_path: Path,
) -> None:
    package = tmp_path / "src" / "sugar_lift_py_tests"
    package.mkdir(parents=True)
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "_production_lift_child.py").write_text(
        """
from sugar_lift_py_tests.gap.panic import ConstructionPanic

def _typed_construction_row(error):
    if isinstance(error, ConstructionPanic):
        return {"outcome": "completed", "typed_gaps": []}
    return None
""",
        encoding="utf-8",
    )

    offenders = _SCANNER.scan_repository(tmp_path)

    assert [(row.path, row.kind) for row in offenders] == [
        (
            "scripts/_production_lift_child.py",
            "factory-panic-isinstance-soft-return",
        )
    ]


def test_named_membrane_path_does_not_hide_read_error(
    tmp_path: Path, monkeypatch
) -> None:
    package = tmp_path / "src" / "sugar_lift_py_tests"
    package.mkdir(parents=True)
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    broken = scripts / "desugar_repro.py"
    broken.write_text("pass\n", encoding="utf-8")
    original_read_text = Path.read_text

    def fail_target(path: Path, *args, **kwargs) -> str:
        if path == broken:
            raise OSError("planted unreadable named membrane")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fail_target)

    offenders = _SCANNER.scan_repository(tmp_path)

    assert [(row.path, row.line, row.kind) for row in offenders] == [
        ("scripts/desugar_repro.py", 0, "auditor-read-error")
    ]


def test_current_named_membranes_match_their_exact_handler_shapes() -> None:
    offenders = _SCANNER.scan_repository(_KIT)
    named_membrane_suffixes = (
        "audit_only/collect_construction_gaps.py",
        "scripts/desugar_repro.py",
        "scripts/exit_set_arm_census.py",
        "scripts/stablezero_classify.py",
        "scripts/_production_lift_child.py",
    )

    assert [
        row
        for row in offenders
        if row.path.endswith(named_membrane_suffixes)
    ] == []


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
