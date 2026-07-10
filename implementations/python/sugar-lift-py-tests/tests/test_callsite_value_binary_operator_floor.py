"""CallSiteValue.binary_operator_with — construction gap drain (Part of #3809).

Lift-probe (before):

    assert (x + y).substitute({x: z}) == y + z   # numpy f2py residual
    neg_offset = offset * -1                     # pandas offsets residual

Refuse: FactoryGap · owner=BinOpSugar · observed=CallSiteValue
· requested=binary_operator_with
· fix=add binary_operator_with to CallSiteValue or emit a real effect

Mechanism: missing **floor totalizer** on the CallSiteValue binary-op path —
not a missing AST recognizer. Sibling of unary_operator_with (dig then
re-dispatch).

After: dig callsite floor when possible; undiggable → SymbolicValue(term)
then BinaryOperatorOperation mints joinable symbolic op. Never fabricate.
"""

from __future__ import annotations

from sugar_lift_py_tests.factory import FactoryGap
from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report
from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
from sugar_lift_py_tests.floor.term_value import TermValue
from sugar_lift_py_tests.ir import ctor, make_var
from sugar_lift_py_tests.operations.binary_operator_operation import (
    BinaryOperatorOperation,
)
from sugar_lift_py_tests.outcome import Complete, complete_value


def test_callsite_binary_on_undiggable_mints_symbolic_op() -> None:
    site = CallSiteValue(
        target_name="as_symbol",
        arg_values=(),
        parameters=(),
        term=ctor("call:as_symbol", [make_var("x")]),
        body=None,
    )
    outcome = site.binary_operator_with(
        BinaryOperatorOperation(
            operator="+",
            right=TermValue(1),
            owner="BinOpSugar",
            blame="t.py:1",
        ),
        ctx=None,
    )
    assert isinstance(outcome, Complete)
    value = complete_value(outcome, owner="probe")
    assert isinstance(value, SymbolicValue)


def test_callsite_binary_mul_undiggable() -> None:
    """pandas residual shape: offset * -1 with undiggable offset callsite."""
    site = CallSiteValue(
        target_name="offset",
        arg_values=(),
        parameters=(),
        term=ctor("call:offset", []),
        body=None,
    )
    outcome = site.binary_operator_with(
        BinaryOperatorOperation(
            operator="*",
            right=TermValue(-1),
            owner="BinOpSugar",
            blame="t.py:1",
        ),
        ctx=None,
    )
    assert isinstance(outcome, Complete)
    value = complete_value(outcome, owner="probe")
    assert isinstance(value, SymbolicValue)


def test_callsite_binop_body_dig_no_binary_operator_gap() -> None:
    src = (
        "def f():\n"
        "    return 1\n"
        "def t():\n"
        "    assert f() + 1 == 2\n"
    )
    try:
        report = build_literal_call_report(
            source=src, filename="t.py", memento_file="t.py"
        )
    except FactoryGap as exc:  # pragma: no cover
        raise AssertionError(f"still construction gap: {exc.info}") from exc
    assert report is not None
    blob = repr(report.payload)
    assert "requested=binary_operator_with" not in blob
    assert "observed=CallSiteValue" not in blob or "binary_operator_with" not in blob


def test_symbolic_plus_callsite_right_emits_joinable_term() -> None:
    """numpy residual after dig: SymbolicValue + CallSiteValue right operand."""
    from sugar_lift_py_tests.ir import _Ctor
    from sugar_lift_py_tests.operations.perform_operation import perform_operation

    left = SymbolicValue(make_var("x"))
    right = CallSiteValue(
        target_name="as_symbol",
        arg_values=(),
        parameters=(),
        term=ctor("call:as_symbol", [make_var("y")]),
        body=None,
    )
    outcome = perform_operation(
        owner="BinOpSugar",
        blame="t.py:1",
        receiver=left,
        operation=BinaryOperatorOperation(
            operator="+",
            right=right,
            owner="BinOpSugar",
            blame="t.py:1",
        ),
        ctx=None,
    )
    assert isinstance(outcome, Complete)
    value = complete_value(outcome, owner="probe")
    assert isinstance(value, SymbolicValue)
    assert isinstance(value.term, _Ctor)
    assert value.term.name == "+"


def test_block_value_binary_redispatches_single_exit() -> None:
    """Revealed successor: dug body is BlockValue(ReturnValue(...))."""
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.floor.return_value import ReturnValue
    from sugar_lift_py_tests.operations.perform_operation import perform_operation

    block = BlockValue((ReturnValue(TermValue(3)),))
    outcome = perform_operation(
        owner="BinOpSugar",
        blame="t.py:1",
        receiver=block,
        operation=BinaryOperatorOperation(
            operator="+",
            right=TermValue(2),
            owner="BinOpSugar",
            blame="t.py:1",
        ),
        ctx=None,
    )
    assert isinstance(outcome, Complete)
    assert complete_value(outcome, owner="probe") == TermValue(5)
