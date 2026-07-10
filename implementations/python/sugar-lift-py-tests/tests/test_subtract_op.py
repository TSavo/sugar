"""The `-` operator (SubtractOpSugar): reduce left, reduce right, ask left to
subtract right (the subtraction floor). Concrete numbers fold to a TermValue;
strings do not stand on the floor and the default panics."""

from __future__ import annotations

import ast

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar


def _condition(source: str):
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse(source).body[0]
    sugar = build_node(node, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx).sugar
    return sugar.condition.reduce(ctx)


def _build_term(source: str):
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse(source, mode="eval").body
    return build_node(node, filename="t.py", role=SugarRole.TERM, ctx=ctx).sugar, ctx


def test_subtract_folds_to_true_when_difference_matches() -> None:
    assert isinstance(
        _condition("if 3 - 1 == 2:\n    pass").value, TrueBoolLiteralSugar
    )


def test_subtract_folds_to_false_when_difference_mismatches() -> None:
    assert isinstance(
        _condition("if 3 - 1 == 5:\n    pass").value, FalseBoolLiteralSugar
    )


def test_subtract_floats_on_collapsed_number() -> None:
    # the collapsed Number: float and int share the subtraction floor
    assert isinstance(
        _condition("if 2.5 - 1 == 1.5:\n    pass").value, TrueBoolLiteralSugar
    )


def test_string_subtract_panics_on_the_floor() -> None:
    sugar, ctx = _build_term('"a" - "b"')
    with pytest.raises(FactoryPanic, match="write more Floor"):
        sugar.desugar(ctx)
