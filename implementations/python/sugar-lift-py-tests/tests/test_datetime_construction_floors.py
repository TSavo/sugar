from __future__ import annotations

import builtins

import pytest

from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.floor import (
    CallSiteValue,
    GuardedValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.ir import atomic, ctor, formula_term, make_var, num, str_const
from sugar_lift_py_tests.occurrence import occurrence_key
from sugar_lift_py_tests.outcome import Completed
from sugar_lift_py_tests.temporal import TemporalContext
from sugar_lift_py_tests.temporal.builtin_name_bindings import (
    builtin_callable_names,
    builtin_constant_names,
)


def test_builtin_constants_are_derived_as_the_callable_complement() -> None:
    expected = frozenset(
        name for name in dir(builtins) if not callable(getattr(builtins, name))
    )
    assert builtin_constant_names() == expected
    assert builtin_constant_names().isdisjoint(builtin_callable_names())

    value = TemporalContext.empty().value_for("NotImplemented")
    assert value.to_term(owner="test") == ctor(
        "python:builtin", [str_const("NotImplemented")]
    )


def test_truly_undefined_name_still_panics() -> None:
    with pytest.raises(ConstructionPanic, match="definitely_not_a_python_builtin"):
        TemporalContext.empty().value_for("definitely_not_a_python_builtin")


@pytest.mark.parametrize(
    ("method", "operator"),
    (("divide", "/"), ("modulo", "%"), ("floor_divide", "//")),
)
@pytest.mark.parametrize("kind", ("symbolic", "callsite"))
def test_opaque_arithmetic_cites_operator_coordinate(method, operator, kind) -> None:
    left = SymbolicValue(make_var("left"))
    if kind == "callsite":
        left = CallSiteValue("opaque", (), (), ctor("call:opaque", []), None)
    site = "arithmetic.py:1"
    outcome = getattr(left, method)(TermValue(2), site, None)
    # The undecided operand keeps its raise face; the one completed face is
    # the undecided law's result (#7642): the operator and both operands,
    # keyed on this evaluation's occurrence. No ``/``, ``%`` or ``//``
    # coordinate is folded over the operands -- that was the second way.
    (completed,) = [
        exit_ for exit_ in outcome.exits if isinstance(exit_, Completed)
    ]
    assert completed.value.to_term(owner="test") == ctor(
        "python:binary_result",
        [
            str_const(operator),
            left.to_term(owner="test"),
            num(2),
            str_const(occurrence_key(site)),
        ],
    )


def test_guarded_value_projects_one_conditional_term_and_post() -> None:
    guard = atomic("choose", [make_var("p")])
    value = GuardedValue(guard, TermValue(1), TermValue(2))

    assert value.to_term(owner="test") == ctor(
        "py.conditional", [formula_term(guard), num(1), num(2)]
    )
    post = value.post_formula(make_var("out"))
    assert "implies" in repr(post)
    assert "out" in repr(post)
