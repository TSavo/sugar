"""A float literal (`3.5`) is a PrimitiveLiteral on the collapsed Number floor.
IntLiteralSugar owns only `type(...) is int`; this sugar owns `type(...) is float`.
Two literal syntaxes, one number -- and ordering/equals ride for free."""

from __future__ import annotations

import ast

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar


def _build_term(source: str):
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse(source, mode="eval").body
    return build_node(node, filename="t.py", role=SugarRole.TERM, ctx=ctx).sugar, ctx


def _condition(source: str):
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse(source).body[0]
    sugar = build_node(node, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx).sugar
    return sugar.condition.reduce(ctx)


def test_float_literal_builds_and_desugars_to_term_value() -> None:
    sugar, ctx = _build_term("3.5")
    from sugar_lift_py_tests.sugar.float_literal_sugar import FloatLiteralSugar

    assert isinstance(sugar, FloatLiteralSugar)
    assert sugar.desugar(ctx) == Complete(TermValue(3.5))




def test_float_less_than_folds_to_true() -> None:
    # the collapsed Number rides the ordering floor for free
    assert isinstance(
        _condition("if 1.5 < 2.5:\n    pass").value, TrueBoolLiteralSugar
    )


def test_float_equality_folds_to_true() -> None:
    assert isinstance(
        _condition("if 3.5 == 3.5:\n    pass").value, TrueBoolLiteralSugar
    )
