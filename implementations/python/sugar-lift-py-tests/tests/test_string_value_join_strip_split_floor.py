"""StringValue.join / strip / split — construction gap drain (Part of #3809).

Lift-probe (before):

    assert "  hi  ".strip() == "hi"
    assert ",".join(["a", "b"]) == "a,b"
    assert "a b".split() == ["a", "b"]

Refuse: FactoryGap · CallSugar · observed=StringValue.strip|join|split
· requested=string builtin method floor
· fix=add StringValue method floor for `<name>`.

Mechanism: missing floor totalizer on the concrete string coordinate —
not a missing AST recognizer. CallSugar already selects MethodCallStrategy;
StringValue.call_method_with only owned __int__/__float__/format/__format__.

Fix: fold when args are static floors; mint call:<m>(self, …) with
computed=None when any argument is opaque (never fabricate). Includes
lstrip/rstrip (same strip-family totalizer hole).

Discrimination: dual-assert unsat via witness EXECUTION.
"""

from __future__ import annotations

import re
from pathlib import Path

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory import factory_panic
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor.array_literal import ArrayLiteral
from sugar_lift_py_tests.floor.opaque_op_callsite import OpaqueOpCallsite
from sugar_lift_py_tests.floor.string_value import StringValue
from sugar_lift_py_tests.outcome import Complete, complete_value
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def _reduce_expr(expr: str):
    import ast

    mod = ast.parse(f"def t():\n    return {expr}\n")
    frag = SourceFragment.from_node(mod.body[0].body[0].value, "t.py")
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    body = ctx.build_body(frag, SugarRole.TERM)
    return body.reduce(ctx)


def _calls(report) -> set[str]:
    return set(re.findall(r"call:[A-Za-z_][A-Za-z0-9_.]*", repr(report.payload.ir)))


def test_strip_zero_arg_folds() -> None:
    outcome = _reduce_expr('"  hi  ".strip()')
    assert isinstance(outcome, Complete)
    assert complete_value(outcome, owner="probe") == StringValue("hi")


def test_strip_chars_folds() -> None:
    outcome = _reduce_expr('"xxhi".strip("x")')
    assert complete_value(outcome, owner="probe") == StringValue("hi")


def test_lstrip_rstrip_fold() -> None:
    assert complete_value(_reduce_expr('"  hi".lstrip()'), owner="p") == StringValue(
        "hi"
    )
    assert complete_value(_reduce_expr('"hi  ".rstrip()'), owner="p") == StringValue(
        "hi"
    )


def test_join_list_folds() -> None:
    outcome = _reduce_expr('",".join(["a", "b"])')
    assert complete_value(outcome, owner="probe") == StringValue("a,b")


def test_join_tuple_and_str_iterable_fold() -> None:
    assert complete_value(_reduce_expr('"-".join(("x", "y"))'), owner="p") == StringValue(
        "x-y"
    )
    assert complete_value(_reduce_expr('"".join("ab")'), owner="p") == StringValue("ab")


def test_split_folds_to_array() -> None:
    outcome = _reduce_expr('"a b".split()')
    value = complete_value(outcome, owner="probe")
    assert isinstance(value, ArrayLiteral)
    assert value.items == (StringValue("a"), StringValue("b"))


def test_split_sep_and_maxsplit_fold() -> None:
    value = complete_value(_reduce_expr('"a,b,c".split(",", 1)'), owner="p")
    assert isinstance(value, ArrayLiteral)
    assert value.items == (StringValue("a"), StringValue("b,c"))


def test_no_construction_gap_spelling_in_assert_report() -> None:
    src = (
        "def t():\n"
        '    assert "  hi  ".strip() == "hi"\n'
        '    assert ",".join(["a", "b"]) == "a,b"\n'
        '    assert "a b".split() == ["a", "b"]\n'
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    blob = repr(report.payload)
    assert "requested=string builtin method floor" not in blob
    assert "add StringValue method floor for" not in blob
    assert "StringValue.strip" not in blob or "floor-gap" not in blob


def test_opaque_join_iterable_mints_coordinate_not_gap() -> None:
    """Opaque join iterable → call:join(sep, iterable), computed=None."""
    from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
    from sugar_lift_py_tests.ir import make_var
    from sugar_lift_py_tests.operations import MethodCallOperation, perform_operation

    sep = StringValue(",")
    iterable = SymbolicValue(make_var("xs"))
    op = MethodCallOperation(
        name="join",
        arguments=(iterable,),
        owner="probe",
        blame="t.py:1",
    )
    outcome = perform_operation(
        owner="probe", blame="t.py:1", receiver=sep, operation=op, ctx=None
    )
    value = complete_value(outcome, owner="probe")
    assert isinstance(value, OpaqueOpCallsite)
    assert value.callee == "join"
    assert value.computed is None
    assert value.arg == sep
    assert value.extra_args == (iterable,)


def test_strip_dual_assert_refutes_lie_via_witness(tmp_path: Path) -> None:
    """Dual-assert discrimination: truthful strip vs lie → unsat via EXECUTION."""
    src = (
        "def t_true():\n"
        '    assert "  hi  ".strip() == "hi"\n'
        "def t_lie():\n"
        '    assert "  hi  ".strip() == "xx"\n'
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    # Must not re-raise as construction gap during report build.
    assert "add StringValue method floor for `strip`" not in repr(report.payload)

    result = run_source_through_real_solver(tmp_path / "string-strip-dual", src)
    statuses = [row.get("status") for row in result.prove_doc.get("rows", [])]
    assert result.verdict == "unsat", (result.verdict, statuses)
    assert "refused" not in statuses


def test_join_dual_assert_refutes_lie_via_witness(tmp_path: Path) -> None:
    src = (
        "def t_true():\n"
        '    assert ",".join(["a", "b"]) == "a,b"\n'
        "def t_lie():\n"
        '    assert ",".join(["a", "b"]) == "x"\n'
    )
    result = run_source_through_real_solver(tmp_path / "string-join-dual", src)
    statuses = [row.get("status") for row in result.prove_doc.get("rows", [])]
    assert result.verdict == "unsat", (result.verdict, statuses)
    assert "refused" not in statuses


def test_split_no_factory_gap_on_reduce() -> None:
    """Direct reduce must not FactoryGap (the live residual spelling)."""
    try:
        outcome = _reduce_expr('"a,b".split(",")')
    except FactoryGap as exc:  # pragma: no cover - regression
        raise AssertionError(f"still construction gap: {exc.info}") from exc
    value = complete_value(outcome, owner="probe")
    assert isinstance(value, ArrayLiteral)
    assert value.items == (StringValue("a"), StringValue("b"))
