from __future__ import annotations

import builtins

import pytest

from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor import (
    CallSiteValue,
    GuardedValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.ir import atomic, ctor, formula_term, make_var, num, str_const
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
    with pytest.raises(FactoryPanic, match="definitely_not_a_python_builtin"):
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
    outcome = getattr(left, method)(TermValue(2), "arithmetic.py:1")
    assert outcome.value.to_term(owner="test") == ctor(
        operator, [left.to_term(owner="test"), num(2)]
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
