"""StringValue.splitlines — construction gap drain (Part of #3809).

Lift-probe (before):

    assert "a\\nb".splitlines() == ["a", "b"]

Refuse: FactoryGap · CallSugar · observed=StringValue.splitlines
· requested=string builtin method floor
· fix=add StringValue method floor for `splitlines`.

Mechanism: missing floor totalizer on the concrete string coordinate —
not a missing AST recognizer (CallSugar already selects MethodCallStrategy).
Sibling of join/strip/split (#3961).

Fix: fold when keepends is static; mint call:splitlines(self, …) with
computed=None when keepends is opaque (never fabricate).

Discrimination: dual-assert unsat via witness EXECUTION.
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory import factory_panic
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor.array_literal import ArrayLiteral
from sugar_lift_py_tests.floor.opaque_op_callsite import OpaqueOpCallsite
from sugar_lift_py_tests.floor.string_value import StringValue
from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.operations import MethodCallOperation, perform_operation
from sugar_lift_py_tests.outcome import Complete, complete_value
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def _reduce_expr(expr: str):
    import ast

    mod = ast.parse(f"def t():\n    return {expr}\n")
    frag = SourceFragment.from_node(mod.body[0].body[0].value, "t.py")
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    body = ctx.build_body(frag, SugarRole.TERM)
    return body.reduce(ctx)


def test_splitlines_zero_arg_folds() -> None:
    outcome = _reduce_expr('"a\\nb".splitlines()')
    value = complete_value(outcome, owner="probe")
    assert isinstance(value, ArrayLiteral)
    assert value.items == (StringValue("a"), StringValue("b"))


def test_splitlines_keepends_true_folds() -> None:
    value = complete_value(_reduce_expr('"a\\nb".splitlines(True)'), owner="p")
    assert isinstance(value, ArrayLiteral)
    assert value.items == (StringValue("a\n"), StringValue("b"))


def test_splitlines_no_construction_gap() -> None:
    try:
        outcome = _reduce_expr('"x\\ny".splitlines()')
    except FactoryGap as exc:  # pragma: no cover - regression
        raise AssertionError(f"still construction gap: {exc.info}") from exc
    value = complete_value(outcome, owner="probe")
    assert isinstance(value, ArrayLiteral)


def test_opaque_keepends_mints_coordinate() -> None:
    op = MethodCallOperation(
        name="splitlines",
        arguments=(SymbolicValue(make_var("k")),),
        owner="probe",
        blame="t.py:1",
    )
    outcome = perform_operation(
        owner="probe",
        blame="t.py:1",
        receiver=StringValue("a\nb"),
        operation=op,
        ctx=None,
    )
    value = complete_value(outcome, owner="probe")
    assert isinstance(value, OpaqueOpCallsite)
    assert value.callee == "splitlines"
    assert value.computed is None


def test_splitlines_dual_assert_refutes_lie_via_witness(tmp_path: Path) -> None:
    src = (
        "def t_true():\n"
        '    assert "a\\nb".splitlines() == ["a", "b"]\n'
        "def t_lie():\n"
        '    assert "a\\nb".splitlines() == ["x"]\n'
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    assert "add StringValue method floor for `splitlines`" not in repr(report.payload)

    result = run_source_through_real_solver(tmp_path / "splitlines-dual", src)
    statuses = [row.get("status") for row in result.prove_doc.get("rows", [])]
    assert result.verdict == "unsat", (result.verdict, statuses)
    assert "refused" not in statuses
