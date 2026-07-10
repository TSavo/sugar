"""AnnAssignSugar — construction gap drain (Part of #3809).

Lift-probe (before):

    def make():
        x: int = 1
        return x + 1
    assert make() == 2

Refuse: FactoryGap · owner=python.factory · observed=AnnAssign
· requested=statement
· fix=create sugar_lift_py_tests.sugar.ann_assign.ann_assign_sugar

Mechanism: missing AST recognizer for AnnAssign (empty STATEMENT catalog
candidates) — not a missing floor totalizer. Annotation is type metadata;
valued form is the same binding as AssignSugar.

Discrimination: dual-assert unsat via witness EXECUTION.
"""

from __future__ import annotations

import ast
from pathlib import Path

from factory_reduce import compose_block

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report
from sugar_lift_py_tests.floor import BoundVar, ReturnValue, SupportValue, TermValue
from sugar_lift_py_tests.floor import BlockValue
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.sugar.ann_assign_sugar import AnnAssignSugar
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def _build_ann(src: str) -> AnnAssignSugar:
    node = ast.parse(src).body[0]
    if isinstance(node, ast.FunctionDef):
        node = next(s for s in node.body if isinstance(s, ast.AnnAssign))
    ctx = FactoryBuildContext(filename="f.py", catalog=default_catalog())
    result = build_node(node, filename="f.py", role=SugarRole.STATEMENT, ctx=ctx)
    assert isinstance(result.sugar, AnnAssignSugar)
    return result.sugar


def test_ann_assign_selects_ann_assign_sugar() -> None:
    sugar = _build_ann("x: int = 5")
    assert sugar.name == "x"
    assert sugar.value is not None
    assert sugar.annotation_kind in {"Name", "Constant", "Attribute", "Subscript"}


def test_valued_ann_assign_is_bound_var() -> None:
    sugar = _build_ann("x: int = 5")
    ctx = FactoryBuildContext(filename="f.py", catalog=default_catalog())
    bound = complete_value(sugar.desugar(ctx), owner="ann")
    assert isinstance(bound, BoundVar)
    assert bound.name == "x"


def test_annotation_only_ann_assign_is_support() -> None:
    sugar = _build_ann("x: int")
    ctx = FactoryBuildContext(filename="f.py", catalog=default_catalog())
    value = complete_value(sugar.desugar(ctx), owner="ann")
    assert isinstance(value, SupportValue)


def test_ann_assign_then_return_recomposes_like_assign() -> None:
    assert compose_block("    y: int = 5\n    return y\n") == BlockValue(
        (ReturnValue(TermValue(5)),)
    )


def test_body_dig_ann_assign_no_construction_gap() -> None:
    src = (
        "def make():\n"
        "    x: int = 1\n"
        "    return x + 1\n"
        "\n"
        "def t():\n"
        "    assert make() == 2\n"
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    blob = repr(report.payload)
    assert "ann_assign.ann_assign_sugar" not in blob
    assert "observed=AnnAssign" not in blob
    diags = report.payload.diagnostics or []
    for d in diags:
        if isinstance(d, dict) and d.get("kind") == "dig-boundary":
            assert "AnnAssign" not in str(d.get("reason", "")), d


def test_np_style_ann_assign_digs_without_gap() -> None:
    src = (
        "import numpy as np\n"
        "def make():\n"
        "    codes: np.ndarray = np.array([1, 2])\n"
        "    return codes.shape\n"
        "\n"
        "def t():\n"
        "    assert make() == (2,)\n"
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    blob = repr(report.payload)
    assert "requested=statement" not in blob or "AnnAssign" not in blob
    assert "create sugar_lift_py_tests.sugar.ann_assign" not in blob


def test_attr_ann_assign_still_unowned() -> None:
    """Attribute AnnAssign is not this drain — Name targets only."""
    from sugar_lift_py_tests.factory import factory_panic

    src = "class C:\n    def m(self):\n        self.x: int = 1\n"
    mod = ast.parse(src)
    ann = next(n for n in ast.walk(mod) if isinstance(n, ast.AnnAssign))
    ctx = FactoryBuildContext(filename="f.py", catalog=default_catalog())
    try:
        build_node(ann, filename="f.py", role=SugarRole.STATEMENT, ctx=ctx)
        raise AssertionError("expected FactoryGap for Attribute AnnAssign")
    except FactoryGap as exc:
        assert exc.info.observed == "AnnAssign"
        assert "ann_assign" in exc.info.fix


def test_ann_assign_dual_assert_refutes_lie_via_witness(tmp_path: Path) -> None:
    src = (
        "def A(z):\n"
        "    x: int = z\n"
        "    return x\n"
        "\n"
        "def t_true():\n"
        "    assert A(1) == 1\n"
        "\n"
        "def t_lie():\n"
        "    assert A(1) == 2\n"
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    assert "create sugar_lift_py_tests.sugar.ann_assign" not in repr(report.payload)

    result = run_source_through_real_solver(tmp_path / "ann-assign-dual", src)
    statuses = [row.get("status") for row in result.prove_doc.get("rows", [])]
    assert result.verdict == "unsat", (result.verdict, statuses)
    assert "refused" not in statuses
