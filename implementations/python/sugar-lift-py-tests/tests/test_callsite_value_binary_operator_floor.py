"""CallSiteValue.binary_operator_with — construction gap drain (Part of #3809).

Lift-probe (before):

    assert (x + y).substitute({x: z}) == y + z   # numpy f2py residual

Refuse: FactoryGap · owner=BinOpSugar · observed=CallSiteValue
· requested=binary_operator_with

Mechanism: missing **floor totalizer** — sibling of unary_operator_with.
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
