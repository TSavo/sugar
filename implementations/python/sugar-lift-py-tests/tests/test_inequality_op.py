"""The `!=` operator (InequalityOpSugar): `1 != 2` is True (unequal), `1 != 1` is
False (equal). `!=` is `not (a == b)`: equals, then the bool literal negates itself."""

from __future__ import annotations

import ast

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar


def _condition(source: str):
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse(source).body[0]
    sugar = build_node(node, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx).sugar
    return sugar.condition.reduce(ctx)


def test_not_equal_folds_to_true_when_unequal() -> None:
    assert isinstance(_condition("if 1 != 2:\n    pass").value, TrueBoolLiteralSugar)


def test_not_equal_folds_to_false_when_equal() -> None:
    assert isinstance(_condition("if 1 != 1:\n    pass").value, FalseBoolLiteralSugar)
