"""The `/` operator (DivideOpSugar): reduce left, reduce right, ask left to divide
by right (the division floor). True division on the collapsed Number; division by
a concrete zero is a runtime effect (Incomplete), not a lift-side panic."""

from __future__ import annotations

import ast

import pytest
from factory_reduce import compose_block

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.effect import DivisionByZeroRuntimeEffect
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor import BlockValue
from sugar_lift_py_tests.outcome import Incomplete
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
from sugar_lift_py_tests.sugar_body import SugarBody


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


def test_divide_folds_to_true_when_quotient_matches() -> None:
    assert isinstance(
        _condition("if 10 / 2 == 5:\n    pass").value, TrueBoolLiteralSugar
    )


def test_divide_folds_to_false_when_quotient_mismatches() -> None:
    assert isinstance(
        _condition("if 10 / 2 == 4:\n    pass").value, FalseBoolLiteralSugar
    )


def test_divide_is_true_division() -> None:
    assert isinstance(
        _condition("if 1 / 2 == 0.5:\n    pass").value, TrueBoolLiteralSugar
    )


def test_divide_by_zero_is_runtime_effect() -> None:
    outcome = _term("1 / 0")
    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, DivisionByZeroRuntimeEffect)


def test_divide_by_zero_halts_block_like_os_exit() -> None:
    # ExprSugar propagates Incomplete; BlockSugar records it and leaves the rest
    # as raw sugar. compose_block returns the BlockValue (outer is Complete).
    result = compose_block("    1 / 0\n    return 2\n")
    assert isinstance(result, BlockValue)
    assert len(result.statements) == 2
    assert isinstance(result.statements[0], Incomplete)
    assert isinstance(result.statements[0].effect, DivisionByZeroRuntimeEffect)
    assert isinstance(result.statements[1], SugarBody)


def test_string_divide_panics_for_free() -> None:
    with pytest.raises(FactoryPanic):
        _term('"a" / "b"')
