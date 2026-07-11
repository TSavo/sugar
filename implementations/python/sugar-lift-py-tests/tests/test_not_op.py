"""The `not` operator (NotOpSugar): reduce the operand, ask it to negate itself.
Bool literals flip; values that do not stand on the negate floor panic for free."""

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


def _term(source: str):
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse(source, mode="eval").body
    sugar = build_node(node, filename="t.py", role=SugarRole.TERM, ctx=ctx).sugar
    return sugar.desugar(ctx)


def test_not_folds_to_true_when_negating_false() -> None:
    assert isinstance(
        _condition("if not 1 == 2:\n    pass").value, TrueBoolLiteralSugar
    )


def test_not_folds_to_false_when_negating_true() -> None:
    assert isinstance(
        _condition("if not 1 == 1:\n    pass").value, FalseBoolLiteralSugar
    )


def test_not_on_number_folds_via_truth_floor() -> None:
    # Python `not 5` is False: truth floor then negate (UnaryOpSugar).
    assert isinstance(_term("not 5").value, FalseBoolLiteralSugar)
