"""The `*` operator (MultiplyOpSugar): reduce left, reduce right, ask left to
multiply by right (the multiplication floor). Numbers fold to a TermValue product;
string repetition is absent -- it panics for free until someone asks for it."""

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


def test_multiply_folds_to_true_when_product_matches() -> None:
    assert isinstance(
        _condition("if 2 * 3 == 6:\n    pass").value, TrueBoolLiteralSugar
    )


def test_multiply_folds_to_false_when_product_mismatches() -> None:
    assert isinstance(
        _condition("if 2 * 3 == 7:\n    pass").value, FalseBoolLiteralSugar
    )


def test_multiply_folds_collapsed_number() -> None:
    assert isinstance(
        _condition("if 0.5 * 4 == 2:\n    pass").value, TrueBoolLiteralSugar
    )


def test_string_repetition_panics_for_free() -> None:
    with pytest.raises(FactoryPanic):
        _term('"ab" * 2')
