"""The ordering floor under the fold/emit/panic contract: fold when both sides
are ground, EMIT a PredicateValue py.lt(l, r) when either side stands on the
term floor, panic only inside to_term when a side cannot enter FOL at all.
Mirrors the landed equals emit with py.lt instead of py.eq."""

from __future__ import annotations

import pytest

from factory_reduce import reduce_value

from sugar_lift_py_tests.floor import PredicateValue, SymbolicValue
from sugar_lift_py_tests.ir import make_var, not_, num, py_lt
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar


def test_symbolic_left_less_than_emits_the_formula() -> None:
    value = reduce_value("z < 1", binds={"z": SymbolicValue(make_var("z"))})
    assert isinstance(value, PredicateValue)
    assert value.formula == py_lt(make_var("z"), num(1))


def test_concrete_left_less_than_symbolic_right_emits_too() -> None:
    # `1 < z`: the concrete left cannot fold against a symbolic right; the
    # ordering floor emits -- never a false panic, nothing is missing here.
    value = reduce_value("1 < z", binds={"z": SymbolicValue(make_var("z"))})
    assert isinstance(value, PredicateValue)
    assert value.formula == py_lt(num(1), make_var("z"))


def test_greater_than_emits_swapped_less_than() -> None:
    # `>` is `b < a` with the operands swapped; emission preserves that.
    value = reduce_value("z > 1", binds={"z": SymbolicValue(make_var("z"))})
    assert isinstance(value, PredicateValue)
    assert value.formula == py_lt(num(1), make_var("z"))


def test_less_equal_emits_negated_swapped_less_than() -> None:
    # `<=` is `not (b < a)`: the floor emits py.lt(1, z), then PredicateValue.negate.
    value = reduce_value("z <= 1", binds={"z": SymbolicValue(make_var("z"))})
    assert isinstance(value, PredicateValue)
    assert value.formula == not_(py_lt(num(1), make_var("z")))


def test_ground_sides_still_fold_not_emit() -> None:
    assert isinstance(reduce_value("1 < 2"), TrueBoolLiteralSugar)


def test_ground_none_ordering_is_the_typeerror_effect() -> None:
    # Python raises TypeError for None < 5 -- a recognized runtime fact under
    # the gap/fact discriminator: Incomplete(TypeErrorRuntimeEffect), not emit.
    import ast

    from sugar_lift_py_tests.claim import SugarRole
    from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
    from sugar_lift_py_tests.effect import TypeErrorRuntimeEffect
    from sugar_lift_py_tests.factory.build import build_node, default_catalog
    from sugar_lift_py_tests.outcome import Incomplete

    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse("None < 5", mode="eval").body
    sugar = build_node(node, filename="t.py", role=SugarRole.TERM, ctx=ctx).sugar
    outcome = sugar.desugar(ctx)
    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, TypeErrorRuntimeEffect)

