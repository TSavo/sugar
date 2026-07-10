"""SymbolicValue.add_with — construction gap drain (Part of #3809).

Lift-probe (before):

    assert list(bpl.add(np.arange(5, 0, -1))) == [5, 5, 5, 5, 5]

Refuse: FactoryGap · owner=AddSugar · observed=SymbolicValue
· requested=add_with

Mechanism: missing **floor totalizer** — not a missing AST recognizer.
"""

from __future__ import annotations

from sugar_lift_py_tests.factory import factory_panic
from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report
from sugar_lift_py_tests.floor.opaque_op_callsite import OpaqueOpCallsite
from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
from sugar_lift_py_tests.floor.term_value import TermValue
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.operations.add_operation import AddOperation
from sugar_lift_py_tests.outcome import Complete, complete_value


def test_symbolic_add_term_routes_through_plus() -> None:
    """Free z.add(1) is +(z, 1) — proof-bearing for AddSugar witness seed."""
    from sugar_lift_py_tests.ir import _Ctor

    receiver = SymbolicValue(make_var("z"))
    outcome = receiver.add_with(
        AddOperation(operand=TermValue(1), owner="AddSugar", blame="t.py:1"),
        ctx=None,
    )
    assert isinstance(outcome, Complete)
    value = complete_value(outcome, owner="probe")
    assert isinstance(value, SymbolicValue)
    assert isinstance(value.term, _Ctor)
    assert value.term.name == "+"


def test_symbolic_add_opaque_operand_mints_call_add() -> None:
    """Vendor array operand: call:add, never invent a placement sum."""
    receiver = SymbolicValue(make_var("bpl"))
    operand = OpaqueOpCallsite(
        callee="numpy.arange",
        arg=TermValue(5),
        computed=None,
    )
    # force non-(Term/Symbolic/Opaque) path via ArrayLiteral-like Fake
    from sugar_lift_py_tests.floor.array_literal import ArrayLiteral

    arr = ArrayLiteral((TermValue(1), TermValue(2)))
    outcome = receiver.add_with(
        AddOperation(operand=arr, owner="AddSugar", blame="t.py:1"),
        ctx=None,
    )
    assert isinstance(outcome, Complete)
    value = complete_value(outcome, owner="probe")
    assert isinstance(value, OpaqueOpCallsite)
    assert value.callee == "add"
    assert value.computed is None
    assert value.extra_args == (arr,)


def test_symbolic_add_body_dig_no_add_with_gap() -> None:
    src = (
        "def t(z):\n"
        "    out = z.add(1)\n"
        "    assert out is not None\n"
    )
    try:
        report = build_literal_call_report(
            source=src, filename="t.py", memento_file="t.py"
        )
    except FactoryGap as exc:  # pragma: no cover
        raise AssertionError(f"still construction gap: {exc.info}") from exc
    assert report is not None
    blob = repr(report.payload)
    assert "requested=add_with" not in blob
