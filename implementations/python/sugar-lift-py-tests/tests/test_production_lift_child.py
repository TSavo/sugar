"""The shared production-lift child (the floors' one construction door).

Planted twins proving the outcome taxonomy the floors depend on:
  - a clean file -> ``completed`` (non-failure),
  - an intentional typed source-tree gap -> ``typed-gap`` (non-failure),
  - a genuinely bare-excepting construction -> the exception PROPAGATES
    (the child never swallows it, so the parent sees a bare exception),
  - the bootstrap check returns None when the production door is importable
    (so an infra failure is reported ONCE, never multiplied per file).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_KIT = Path(__file__).resolve().parents[1]
_MOD_PATH = _KIT / "scripts" / "_production_lift_child.py"
_SPEC = importlib.util.spec_from_file_location("_production_lift_child", _MOD_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_CHILD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_CHILD)


def _write(tmp_path: Path, source: str) -> Path:
    path = tmp_path / "mod.py"
    path.write_text(source, encoding="utf-8")
    return path


def test_clean_file_completes(tmp_path: Path, capsys) -> None:
    path = _write(tmp_path, "def a(z):\n    return z\n")
    assert _CHILD.run_production_lift_child(path, "mod.py") == 0
    terminal = _CHILD.terminal_outcome(capsys.readouterr().out)
    assert terminal == _CHILD.OUTCOME_COMPLETED
    assert terminal in _CHILD.NON_FAILURE_OUTCOMES


def test_intentional_typed_gap_is_typed_gap_not_failure(tmp_path: Path, capsys) -> None:
    # A construct with no written sugar raises SugarNotWritten -- the sanctioned
    # typed loud gap. The child marks the file typed-gap and exits 0; the floors
    # must NOT count this as a bare exception.
    path = _write(tmp_path, "def a():\n    with open('x'):\n        pass\n")
    assert _CHILD.run_production_lift_child(path, "mod.py") == 0
    terminal = _CHILD.terminal_outcome(capsys.readouterr().out)
    assert terminal == _CHILD.OUTCOME_TYPED_GAP
    assert terminal in _CHILD.NON_FAILURE_OUTCOMES


def test_kit_construction_panic_is_typed_gap_not_failure(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    # Kit ConstructionPanic is a sanctioned typed gap alongside SugarNotWritten.
    # The child must mark typed-gap and exit 0 — never misclassify as bare exception.
    from sugar_lift_py_tests.gap.info import ConstructionGap, GapKind, GapLocus
    from sugar_lift_py_tests.gap.panic import ConstructionPanic
    import sugar_source_tree.nodes as nodes_mod

    def _boom(self, *a, **k):
        raise ConstructionPanic(
            ConstructionGap(
                owner="planted",
                blame="t.py:1:0",
                observed="planted",
                requested="typed construction",
                fix="none",
                gap_kind=GapKind.FLOOR,
                gap_locus=GapLocus.CONSTRUCTION,
            )
        )

    monkeypatch.setattr(nodes_mod.FunctionDef, "sugar", _boom)
    path = _write(tmp_path, "def a():\n    return 1\n")
    assert _CHILD.run_production_lift_child(path, "mod.py") == 0
    terminal = _CHILD.terminal_outcome(capsys.readouterr().out)
    assert terminal == _CHILD.OUTCOME_TYPED_GAP
    assert terminal in _CHILD.NON_FAILURE_OUTCOMES


def test_preconstruction_panic_is_typed_gap_not_failure(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    from sugar_lift_py_tests.gap.info import ConstructionGap, GapKind, GapLocus
    from sugar_lift_py_tests.gap.panic import ConstructionPanic
    import _production_source_file as production_source_file

    def _typed_gap(*_args, **_kwargs):
        raise ConstructionPanic(
            ConstructionGap(
                owner="renamed-preconstruction-door",
                blame="arbitrary.py:1:0",
                observed="constructed value without a floor",
                requested="typed construction",
                fix="implement the missing floor",
                gap_kind=GapKind.FLOOR,
                gap_locus=GapLocus.CONSTRUCTION,
            )
        )

    monkeypatch.setattr(production_source_file, "production_source_file", _typed_gap)
    path = _write(tmp_path, "def a():\n    return 1\n")

    assert _CHILD.run_production_lift_child(path, "arbitrary.py") == 0
    assert _CHILD.terminal_outcome(capsys.readouterr().out) == _CHILD.OUTCOME_TYPED_GAP


def test_preconstruction_unwritten_is_typed_gap_not_failure(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    from sugar_source_tree.panic import SugarNotWritten
    import _production_source_file as production_source_file

    def _typed_gap(*_args, **_kwargs):
        raise SugarNotWritten(
            owner="RenamedNode.sugar",
            observed="renamed node has no construction",
            requested="a constructed sugar object",
            fix="write its construction",
        )

    monkeypatch.setattr(production_source_file, "production_source_file", _typed_gap)
    path = _write(tmp_path, "def a():\n    return 1\n")

    assert _CHILD.run_production_lift_child(path, "arbitrary.py") == 0
    assert _CHILD.terminal_outcome(capsys.readouterr().out) == _CHILD.OUTCOME_TYPED_GAP


def test_bare_exception_propagates_never_swallowed(tmp_path: Path, monkeypatch) -> None:
    # If construction raises a non-typed-gap exception, the child must let
    # it propagate (so the parent's subprocess exits nonzero = bare exception).
    # We force a bare exception from the production door and assert it escapes.
    def _boom(*a, **k):
        raise RuntimeError("planted bare exception in construction")

    import sys

    production_source_file = sys.modules.get("_production_source_file")
    if production_source_file is None:
        import _production_source_file as production_source_file
    monkeypatch.setattr(production_source_file, "production_source_file", _boom)
    path = _write(tmp_path, "def a():\n    return 1\n")
    with pytest.raises(RuntimeError, match="planted bare exception"):
        _CHILD.run_production_lift_child(path, "mod.py")


def test_bootstrap_check_is_green_when_door_present() -> None:
    # The production door is importable here, so no infra failure -- the floors
    # scan the corpus rather than reporting one multiplied import failure.
    assert _CHILD.production_lift_bootstrap_error() is None


def test_terminal_outcome_none_is_the_silent_axis() -> None:
    # No terminal row in stdout == the silent / missing-result axis.
    assert _CHILD.terminal_outcome("no json here\n{}\n") is None
