"""Ground cross-type ordering is lift-time decidable and therefore panics.
It cannot mint RuntimeEffect evidence. String-vs-string folds; symbolic still
emits."""

from __future__ import annotations

import ast

import pytest
from factory_reduce import compose_block, reduce_value

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor import BlockValue, PredicateValue, SymbolicValue
from sugar_lift_py_tests.ir import make_var, num, py_lt
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar


def _term(source: str):
    # Mirror test_divide_op: Incomplete must not pass through complete_value.
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse(source, mode="eval").body
    sugar = build_node(node, filename="t.py", role=SugarRole.TERM, ctx=ctx).sugar
    return sugar.desugar(ctx)


def test_none_less_than_number_ground_wrong_twin_panics() -> None:
    with pytest.raises(FactoryPanic):
        _term("None < 5")


def test_string_less_than_number_ground_wrong_twin_panics() -> None:
    with pytest.raises(FactoryPanic):
        _term('"a" < 1')


def test_string_less_than_string_folds() -> None:
    assert isinstance(reduce_value('"a" < "b"'), TrueBoolLiteralSugar)


def test_number_less_than_number_still_folds() -> None:
    assert isinstance(reduce_value("1 < 2"), TrueBoolLiteralSugar)


def test_symbolic_still_emits_py_lt() -> None:
    value = reduce_value("z < 1", binds={"z": SymbolicValue(make_var("z"))})
    assert isinstance(value, PredicateValue)
    assert value.formula == py_lt(make_var("z"), num(1))


def test_assign_of_unorderable_does_not_halt_until_reduced() -> None:
    # BoundVar aliases the SOURCE unreduced: `x = None < 5` threads a let and
    # contributes nothing. The TypeError only fires when the comparison is
    # actually reduced (assert, expr-stmt, condition) -- not on assign alone.
    result = compose_block("    x = None < 5\n    return 1\n")
    assert isinstance(result, BlockValue)
    assert len(result.statements) == 1  # just the return; the let was support
