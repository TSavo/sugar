"""Instrument: swallowed honorable throws as second mechanisms.

Discrimination twins plant the sin class and assert detection. Live production
scan pins the drained sin-cluster-4 sites absent and reports residual R for
offenders this shot does not retire. Silence only at stable zero of all axes.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_KIT = Path(__file__).resolve().parents[1]
_SCANNER_PATH = _KIT / "scripts" / "swallowed_throw_second_mechanism_law.py"
_SPEC = importlib.util.spec_from_file_location(
    "swallowed_throw_second_mechanism_law", _SCANNER_PATH
)
assert _SPEC is not None and _SPEC.loader is not None
_SCANNER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_SCANNER)

_PYTHON_ROOT = _KIT.parent  # implementations/python


def _write_pkg(tmp_path: Path, rel: str, source: str) -> Path:
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


def test_lying_construction_panic_continue_is_detected(tmp_path: Path) -> None:
    """Lying twin: except ConstructionPanic: continue must red."""
    root = tmp_path / "python"
    _write_pkg(
        root,
        "sugar-lift-python-source/src/sugar_lift_python_source/bad.py",
        """
from sugar_lift_py_tests.gap.panic import ConstructionPanic

def seal(prefix):
    cids = []
    for item in prefix:
        try:
            cids.append(item.to_term(owner="o"))
        except ConstructionPanic:
            continue
    return cids
""",
    )
    for pkg in (
        "sugar-source-tree/src",
        "sugar-lift-py-tests/src",
    ):
        (root / pkg).mkdir(parents=True, exist_ok=True)

    offenders = _SCANNER.scan_python_root(root)
    kinds = {(o.kind, o.axis) for o in offenders}
    assert (
        "construction-panic-soft-continue",
        "R_construction_panic_soft_continue",
    ) in kinds


def test_lying_exception_soft_continue_is_detected(tmp_path: Path) -> None:
    """Lying twin: except Exception: continue manufactures absence."""
    root = tmp_path / "python"
    _write_pkg(
        root,
        "sugar-lift-py-tests/src/sugar_lift_py_tests/bad.py",
        """
def enumerate_targets(names, rows_of):
    out = []
    for name in names:
        try:
            rows = rows_of(name)
        except Exception:
            continue
        out.append(rows)
    return out
""",
    )
    for pkg in (
        "sugar-source-tree/src",
        "sugar-lift-python-source/src",
    ):
        (root / pkg).mkdir(parents=True, exist_ok=True)

    offenders = _SCANNER.scan_python_root(root)
    assert any(o.kind == "exception-soft-continue" for o in offenders)


def test_lying_exception_soft_none_on_construction_door_is_detected(
    tmp_path: Path,
) -> None:
    """Lying twin: except Exception around _require_narrow_cm_ref → soft-None."""
    root = tmp_path / "python"
    _write_pkg(
        root,
        "sugar-source-tree/src/sugar_source_tree/bad.py",
        """
def door(self, item):
    try:
        resolved_ref = self._require_narrow_cm_ref(item)
    except Exception:
        resolved_ref = None
    return resolved_ref
""",
    )
    for pkg in (
        "sugar-lift-python-source/src",
        "sugar-lift-py-tests/src",
    ):
        (root / pkg).mkdir(parents=True, exist_ok=True)

    offenders = _SCANNER.scan_python_root(root)
    assert any(o.kind == "exception-soft-continue" for o in offenders)


def test_lying_soft_unresolved_return_is_detected(tmp_path: Path) -> None:
    root = tmp_path / "python"
    _write_pkg(
        root,
        "sugar-source-tree/src/sugar_source_tree/bad.py",
        """
from sugar_lift_py_tests.sugar.soft_unresolved_with_sugar import SoftUnresolvedWithSugar

def sugar(self):
    return SoftUnresolvedWithSugar(site=self.fragment)
""",
    )
    for pkg in (
        "sugar-lift-python-source/src",
        "sugar-lift-py-tests/src",
    ):
        (root / pkg).mkdir(parents=True, exist_ok=True)

    offenders = _SCANNER.scan_python_root(root)
    assert any(o.kind == "soft-unresolved-sugar-return" for o in offenders)


def test_lying_literal_eval_raw_substitution_is_detected(tmp_path: Path) -> None:
    root = tmp_path / "python"
    _write_pkg(
        root,
        "sugar-source-tree/src/sugar_source_tree/bad.py",
        """
import ast as _pyast

def decode(text):
    try:
        value = _pyast.literal_eval(text)
    except Exception:
        value = text
    return value
""",
    )
    for pkg in (
        "sugar-lift-python-source/src",
        "sugar-lift-py-tests/src",
    ):
        (root / pkg).mkdir(parents=True, exist_ok=True)

    offenders = _SCANNER.scan_python_root(root)
    assert any(o.kind == "literal-eval-raw-source-substitution" for o in offenders)


def test_truthful_bare_projection_and_reraise_are_clean(tmp_path: Path) -> None:
    """Truthful twin: bare projection / pure re-raise is not the sin class."""
    root = tmp_path / "python"
    _write_pkg(
        root,
        "sugar-lift-python-source/src/sugar_lift_python_source/ok.py",
        """
from sugar_lift_py_tests.gap.panic import ConstructionPanic

def seal(prefix, owner):
    return tuple(item.to_term(owner=owner) for item in prefix)

def boundary():
    try:
        raise ConstructionPanic(None)
    except ConstructionPanic:
        raise
""",
    )
    _write_pkg(
        root,
        "sugar-source-tree/src/sugar_source_tree/ok.py",
        """
import ast as _pyast

def decode(text):
    value = _pyast.literal_eval(text)
    return value
""",
    )
    _write_pkg(
        root,
        "sugar-lift-py-tests/src/sugar_lift_py_tests/ok.py",
        """
def rows_of(name):
    return name
""",
    )

    offenders = _SCANNER.scan_python_root(root)
    assert offenders == [], _SCANNER.format_report(offenders)


def test_drained_sin_cluster_4_sites_are_absent_on_live_tree() -> None:
    """Fix-forward pin: the four drained membranes must not reappear.

    Residual offenders outside this drain remain measured by the CLI (exit 1
    until stable zero). This tooth fails if a drained site regrows.
    """
    offenders = _SCANNER.scan_python_root(_PYTHON_ROOT)

    # Content pins: drained patterns must be gone from production source text.
    manager = (
        _PYTHON_ROOT
        / "sugar-lift-python-source/src/sugar_lift_python_source/manager_construction.py"
    ).read_text(encoding="utf-8")
    assert "kept_prefix" not in manager
    assert "never panic the door" not in manager

    nodes = (
        _PYTHON_ROOT / "sugar-source-tree/src/sugar_source_tree/nodes.py"
    ).read_text(encoding="utf-8")
    assert "return SoftUnresolvedWithSugar" not in nodes
    assert (
        "from sugar_lift_py_tests.sugar.soft_unresolved_with_sugar import" not in nodes
    )
    assert "return SoftUnresolvedTrySugar" not in nodes
    assert (
        "from sugar_lift_py_tests.sugar.soft_unresolved_try_sugar import" not in nodes
    )

    parso = (
        _PYTHON_ROOT / "sugar-source-tree/src/sugar_source_tree/parso_adapter.py"
    ).read_text(encoding="utf-8")
    assert "value = text" not in parso
    assert "value = unit.source[start:end]" not in parso

    ts = (
        _PYTHON_ROOT
        / "sugar-source-tree/src/sugar_source_tree/tree_sitter_python_adapter.py"
    ).read_text(encoding="utf-8")
    assert "value = text" not in ts
    assert "value = unit.source[span.start : span.end]" not in ts

    lift = (
        _PYTHON_ROOT / "sugar-lift-py-tests/src/sugar_lift_py_tests/lift_rpc.py"
    ).read_text(encoding="utf-8")
    marker = "def_memento, rows = _tree.function_contract_rows(fn, file_rel)"
    # First implications arm (target_candidates) has no try wrapping the call.
    idx = lift.index(marker)
    window = lift[idx - 120 : idx + 80]
    assert "except Exception" not in window

    # Scanner pins: drained kinds absent at drained loci (Try soft residual may remain).
    assert not any(
        o.path.endswith("parso_adapter.py")
        and o.kind == "literal-eval-raw-source-substitution"
        for o in offenders
    ), _SCANNER.format_report(offenders)
    assert not any(
        o.path.endswith("tree_sitter_python_adapter.py")
        and o.kind == "literal-eval-raw-source-substitution"
        for o in offenders
    ), _SCANNER.format_report(offenders)
    assert not any(
        o.path.endswith("nodes.py") and o.kind == "soft-unresolved-sugar-return"
        for o in offenders
    ), _SCANNER.format_report(offenders)
    assert not any(
        o.path.endswith("manager_construction.py")
        and o.kind == "construction-panic-soft-continue"
        for o in offenders
    ), _SCANNER.format_report(offenders)
    assert not any(
        o.path.endswith("bind_lifter.py") and o.kind == "exception-soft-continue"
        for o in offenders
    ), _SCANNER.format_report(offenders)
    assert not any(
        o.path.endswith("bench_backends.py") and o.kind == "exception-soft-continue"
        for o in offenders
    ), _SCANNER.format_report(offenders)
    # Permanent membrane residual: multi-file corpus census only.
    residual = [o for o in offenders if o.kind == "exception-soft-continue"]
    assert all(o.path.endswith("census.py") for o in residual), _SCANNER.format_report(
        offenders
    )


def test_live_scan_reports_named_axes_and_residual_is_nonzero_until_drained() -> None:
    """Live R is measured output: axes named; residual is census membrane only."""
    offenders = _SCANNER.scan_python_root(_PYTHON_ROOT)
    counts = _SCANNER.axis_counts(offenders)
    for axis in _SCANNER._AXES:
        assert axis in counts
    assert counts["R_literal_eval_raw_substitution"] == 0
    assert counts["R_soft_unresolved_sugar_return"] == 0
    assert counts["R_construction_panic_soft_continue"] == 0
    # Permanent open-domain membrane: multi-file census defect enumeration.
    assert counts["R_exception_soft_continue"] == 1
    assert all(o.path.endswith("census.py") for o in offenders), _SCANNER.format_report(
        offenders
    )
    report = _SCANNER.format_report(offenders)
    assert "R_construction_panic_soft_continue" in report
    assert "R_exception_soft_continue" in report


def test_cli_exit_code_tracks_residual(tmp_path: Path) -> None:
    """CLI exits 1 while any axis > 0; exits 0 on a clean tree."""
    clean = tmp_path / "clean"
    for pkg in _SCANNER._PRODUCTION_PACKAGE_SRC:
        (clean / pkg).mkdir(parents=True, exist_ok=True)
        (clean / pkg / "empty.py").write_text("# clean\n", encoding="utf-8")
    assert _SCANNER.main(["--python-root", str(clean)]) == 0

    dirty = tmp_path / "dirty"
    for pkg in _SCANNER._PRODUCTION_PACKAGE_SRC:
        (dirty / pkg).mkdir(parents=True, exist_ok=True)
    (dirty / "sugar-source-tree/src/bad.py").write_text(
        """
import ast as _pyast
def decode(text):
    try:
        value = _pyast.literal_eval(text)
    except Exception:
        value = text
    return value
""",
        encoding="utf-8",
    )
    assert _SCANNER.main(["--python-root", str(dirty)]) == 1
