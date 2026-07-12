from __future__ import annotations

from factory_reduce import compose_block

import pytest

from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor import (
    GuardedRaise,
    InvValue,
    RaisesWithValue,
    SupportValue,
    SymbolicValue,
)
from sugar_lift_py_tests.ir import and_, atomic, implies, make_var
from sugar_lift_py_tests.temporal import TemporalContext


def test_guarded_raise_stacks_outer_guard() -> None:
    inner = atomic("inner", [])
    outer = atomic("outer", [])
    value = GuardedRaise((inner,), RaiseEffect("ValueError"))

    assert value.guarded(outer) == GuardedRaise(
        (outer, inner), RaiseEffect("ValueError")
    )


def test_raises_with_value_projects_guarded_facts() -> None:
    first = atomic("first", [])
    second = atomic("second", [])
    raises_fact = atomic("raises", [])
    body_fact = atomic("body", [])
    value = RaisesWithValue(
        raises_inv=InvValue(raises_fact),
        body_entries=(InvValue(body_fact),),
    )

    guarded = value.guarded(second).guarded(first)

    guard = and_([first, second])
    assert guarded.inv_contribution() == (
        implies(guard, raises_fact),
        implies(guard, body_fact),
    )


def test_guarded_raises_as_binding_is_not_definite_in_continuation() -> None:
    original = FactoryBuildContext(
        filename="t.py",
        catalog=default_catalog(),
        temporal=TemporalContext.empty(),
    )
    guarded = RaisesWithValue(
        raises_inv=InvValue(atomic("raises", [])),
        body_entries=(),
        as_name="exc_info",
        as_value=SymbolicValue(make_var("exc_info")),
    ).guarded(atomic("branch", []))

    assert guarded.extend_scope(original) is original


def test_symbolic_if_with_pytest_raises_constructs_guarded_fact() -> None:
    block = compose_block(
        "    if p:\n"
        "        with pytest.raises(ValueError):\n"
        "            raise ValueError()\n",
        {"p": SymbolicValue(make_var("p"))},
    )

    formulas = block.inv_contribution()
    assert formulas
    assert all("implies" in repr(formula) for formula in formulas)


def test_unrepresentable_guard_context_stays_loud() -> None:
    with pytest.raises(FactoryPanic, match="observed=SupportValue"):
        SupportValue().guarded(atomic("guard", []))
