"""The `%` operator (ModuloOpSugar): reduce left, reduce right, ask left for the
remainder by right (the modulo floor). Numbers fold; modulo by a concrete zero is
a runtime effect (Incomplete), not a lift-side panic. String formatting stays
unowned for free."""

from __future__ import annotations

import ast

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.effect import ModuloByZeroRuntimeEffect
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.outcome import Incomplete
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


def test_modulo_folds_to_true_when_remainder_matches() -> None:
    assert isinstance(
        _condition("if 7 % 3 == 1:\n    pass").value, TrueBoolLiteralSugar
    )


def test_modulo_folds_to_false_when_remainder_mismatches() -> None:
    assert isinstance(
        _condition("if 7 % 3 == 2:\n    pass").value, FalseBoolLiteralSugar
    )


def test_modulo_folds_collapsed_number() -> None:
    assert isinstance(
        _condition("if 5.5 % 2 == 1.5:\n    pass").value, TrueBoolLiteralSugar
    )


def test_modulo_by_zero_is_runtime_effect() -> None:
    outcome = _term("1 % 0")
    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, ModuloByZeroRuntimeEffect)


def test_unowned_string_modulo_operand_panics_for_free() -> None:
    with pytest.raises(FactoryPanic):
        _term('"%s" % ["b"]')
