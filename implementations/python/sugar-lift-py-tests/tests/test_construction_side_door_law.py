"""Permanent floor: construction-path side doors stay measured at stable zero.

Green only when meaning is tree + prebound authenticated contract refs only.
This suite proves the instrument discriminates planted twins, stays quiet on
clean trees / adapters, and holds every live production root at R=0. Any planted
side door still makes the same scanner and CLI report red; zero is measured,
never inferred from a missing run.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


_KIT = Path(__file__).resolve().parents[1]
_SCANNER_PATH = _KIT / "scripts" / "construction_side_door_law.py"
_SPEC = importlib.util.spec_from_file_location(
    "construction_side_door_law", _SCANNER_PATH
)
assert _SPEC is not None and _SPEC.loader is not None
_SCANNER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_SCANNER)


def test_discrimination_self_test_is_green() -> None:
    assert _SCANNER.discrimination_self_test() is True
    assert _SCANNER.main(["--self-test"]) == 0


def test_planted_membrane_admission_trips_floor(tmp_path: Path) -> None:
    pkg = tmp_path / "sugar_lift_py_tests"
    pkg.mkdir()
    (pkg / "with_membrane.py").write_text(
        """
from sugar_lift_py_tests.manifest_membrane import (
    contract_for_manager,
    default_community_manifest,
)

def admit(manager):
    return contract_for_manager(default_community_manifest(), manager)

MANIFEST = "community_context_managers.json"
""",
        encoding="utf-8",
    )
    offenders = _SCANNER.scan_roots((pkg,))
    kinds = {row.kind for row in offenders}
    axes = {row.axis for row in offenders if row.kind in _SCANNER._SIDE_DOOR_KINDS}
    assert "membrane-admission-api" in kinds
    assert "membrane-spelling-manifest" in kinds
    assert "membrane-admission" in axes
    assert _SCANNER.r_construction_side_doors(offenders) >= 2


def test_planted_foreign_ast_import_trips_floor(tmp_path: Path) -> None:
    pkg = tmp_path / "sugar_lift_py_tests"
    pkg.mkdir()
    (pkg / "import_binding.py").write_text(
        "import ast\n\ndef f():\n    return ast.parse('x')\n",
        encoding="utf-8",
    )
    (pkg / "contract_expression.py").write_text(
        "from ast import parse\n\ndef g(s):\n    return parse(s, mode='eval')\n",
        encoding="utf-8",
    )
    offenders = _SCANNER.scan_roots((pkg,))
    foreign = [row for row in offenders if row.kind == "foreign-ast-import"]
    assert len(foreign) >= 2
    assert all(row.axis == "foreign-ast-import" for row in foreign)
    assert _SCANNER.r_by_axis(offenders)["foreign-ast-import"] >= 2
    assert any("import ast" in row.expression for row in foreign)
    assert any("from ast" in row.expression for row in foreign)


def test_planted_ast_semantic_above_adapter_trips_floor(tmp_path: Path) -> None:
    pkg = tmp_path / "sugar_lift_py_tests"
    pkg.mkdir()
    (pkg / "exit_disposition_proof.py").write_text(
        """
import ast

def prove(source: str):
    tree = ast.parse(source)
    class V(ast.NodeVisitor):
        pass
    for node in ast.walk(tree):
        pass
    return tree
""",
        encoding="utf-8",
    )
    offenders = _SCANNER.scan_roots((pkg,))
    kinds = {row.kind for row in offenders}
    assert "foreign-ast-import" in kinds
    assert "ast-semantic-parse" in kinds
    assert "ast-semantic-walk" in kinds
    assert "ast-semantic-visitor" in kinds
    assert _SCANNER.r_construction_side_doors(offenders) >= 4
    assert all(
        row.axis == "ast-semantic-above-adapter"
        for row in offenders
        if row.kind.startswith("ast-semantic-")
    )
    assert all(
        row.axis == "foreign-ast-import"
        for row in offenders
        if row.kind == "foreign-ast-import"
    )


def test_adapter_ast_use_does_not_trip_foreign_or_semantic_axis(tmp_path: Path) -> None:
    pkg = tmp_path / "sugar_source_tree"
    pkg.mkdir()
    (pkg / "cpython_adapter.py").write_text(
        """
import ast

def parse_unit(source, filename):
    return ast.parse(source, filename=filename)
""",
        encoding="utf-8",
    )
    (pkg / "tree_sitter_python_adapter.py").write_text(
        """
import ast as _pyast

def parse_unit(source, filename):
    return _pyast.parse(source, filename=filename)
""",
        encoding="utf-8",
    )
    offenders = _SCANNER.scan_roots((pkg,))
    assert [
        row
        for row in offenders
        if row.kind == "foreign-ast-import" or row.kind.startswith("ast-semantic-")
    ] == []


def test_clean_tree_plus_prebound_refs_is_green(tmp_path: Path) -> None:
    pkg = tmp_path / "sugar_source_tree"
    pkg.mkdir()
    (pkg / "nodes.py").write_text(
        """
class With:
    def _construct_sugar(self):
        # meaning is tree + prebound refs only
        ref = self.unit.construction_context.contract_refs.require(self.coordinate)
        return self._sugar_from_ref(ref)
""",
        encoding="utf-8",
    )
    assert _SCANNER.scan_roots((pkg,)) == []


def test_planted_dual_old_lifter_on_enumerate_path_trips(tmp_path: Path) -> None:
    pkg = tmp_path / "sugar_lift_py_tests"
    pkg.mkdir()
    (pkg / "lift_rpc.py").write_text(
        """
from sugar_lift_python_source.lifter import lift_source

def handle_enumerate(source, path):
    return lift_source(source, path)
""",
        encoding="utf-8",
    )
    offenders = _SCANNER.scan_roots((pkg,))
    assert any(row.kind == "dual-old-lifter" for row in offenders)
    assert _SCANNER.r_by_axis(offenders)["dual-old-lifter"] >= 1


def test_default_roots_include_lift_python_source() -> None:
    roots = _SCANNER.default_production_roots()
    names = [p.name for p in roots]
    assert "sugar_lift_py_tests" in names
    assert "sugar_source_tree" in names
    assert "sugar_lift_python_source" in names


def test_sole_path_roots_exclude_dual_body() -> None:
    sole = _SCANNER.sole_path_roots()
    names = [p.name for p in sole]
    assert "sugar_lift_py_tests" in names
    assert "sugar_source_tree" in names
    assert "sugar_lift_python_source" not in names


def test_sole_path_packages_are_green() -> None:
    """Post-#6120/#6122/#6123: sole path is tree + prebound refs only."""
    roots = _SCANNER.sole_path_roots()
    offenders = _SCANNER.scan_roots(roots)
    r = _SCANNER.r_construction_side_doors(offenders)
    err = _SCANNER.r_auditor_errors(offenders)
    assert err == 0, _SCANNER.format_report(offenders)
    assert r == 0, (
        "sole-path packages must stay at R=0; residual:\n"
        + _SCANNER.format_report(offenders)
    )
    # Drained sole-path modules must not reintroduce foreign ast.
    sole_foreign = [
        row
        for row in offenders
        if row.kind == "foreign-ast-import"
        and (
            "import_binding" in row.path
            or "contract_expression" in row.path
            or "verify_dialect" in row.path
        )
    ]
    assert sole_foreign == []


def test_live_repository_is_green_at_stable_zero() -> None:
    """Default roots stay green only while every measured axis is empty."""
    roots = _SCANNER.default_production_roots()
    offenders = _SCANNER.scan_roots(roots)
    r = _SCANNER.r_construction_side_doors(offenders)
    err = _SCANNER.r_auditor_errors(offenders)
    axes = _SCANNER.r_by_axis(offenders)

    assert err == 0, _SCANNER.format_report(offenders)
    assert r == 0, _SCANNER.format_report(offenders)
    assert offenders == []
    assert all(value == 0 for value in axes.values())

    code = _SCANNER.main([])
    assert code == 0


def test_main_json_reports_green_zero_and_empty_offenders(capsys) -> None:
    code = _SCANNER.main([])
    assert code == 0
    captured = capsys.readouterr()
    # Last non-empty line is the JSON summary.
    lines = [line for line in captured.out.splitlines() if line.strip()]
    summary = json.loads(lines[-1])
    assert summary["instrument"] == "R_construction_side_doors"
    assert summary["ok"] is True
    assert summary["R_construction_side_doors"] == 0
    assert summary["R_sole_path_construction_side_doors"] == 0
    assert summary["R_foreign_ast_import"] == 0
    assert summary["R_ast_semantic_above_adapter"] == 0
    assert summary["R_membrane_admission"] == 0
    assert summary["R_dual_old_lifter"] == 0
    assert summary["auditor_errors"] == 0
    assert summary["offenders"] == []


def test_main_json_turns_red_for_planted_side_door(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    pkg = tmp_path / "sugar_lift_py_tests"
    pkg.mkdir()
    (pkg / "import_binding.py").write_text(
        "import ast\n\ndef parse_again(source):\n    return ast.parse(source)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        _SCANNER, "default_production_roots", lambda _repo=None: (pkg,)
    )

    code = _SCANNER.main([])
    assert code == 1
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    summary = json.loads(lines[-1])
    assert summary["ok"] is False
    assert summary["R_construction_side_doors"] > 0
    assert summary["R_foreign_ast_import"] > 0
    assert summary["offenders"]
    assert any(
        row["axis"] == "foreign-ast-import" for row in summary["offenders"]
    )


def test_missing_root_is_auditor_error_not_crash(tmp_path: Path) -> None:
    offenders = _SCANNER.scan_roots((tmp_path / "missing",))
    assert any(row.kind == "auditor-root-error" for row in offenders)
    assert _SCANNER.r_construction_side_doors(offenders) == 0
    assert _SCANNER.r_auditor_errors(offenders) >= 1
