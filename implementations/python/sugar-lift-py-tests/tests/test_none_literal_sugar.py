"""The `None` literal (NoneLiteralSugar): the None-ness IS the type -- no value
field. It reduces to NoneValue. `None == None` folds True; cross-type equals
emits eq(None, other) once None projects to a term."""

from __future__ import annotations

import ast

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.floor import PredicateValue
from sugar_lift_py_tests.ir import ctor, eq, num
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


def test_none_literal_builds_and_desugars_to_none_value() -> None:
    sugar, ctx = _build_term("None")
    from sugar_lift_py_tests.floor import NoneValue
    from sugar_lift_py_tests.sugar.none_literal_sugar import NoneLiteralSugar

    assert isinstance(sugar, NoneLiteralSugar)
    assert sugar.desugar(ctx) == Complete(NoneValue())


def test_none_equals_none_folds_to_true() -> None:
    assert isinstance(
        _condition("if None == None:\n    pass").value, TrueBoolLiteralSugar
    )


def test_none_equals_ground_folds_false() -> None:
    # Ground vs ground FOLDS -- an emitted py.eq(None, 5) atom would be
    # unconstrained by any universe and vacuously SAT-able (a lying twin
    # asserting None == 5 would pass). Python says False; the fold says False.
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
        FalseBoolLiteralSugar,
    )

    sugar, ctx = _build_term("None == 5")
    outcome = sugar.desugar(ctx)
    assert isinstance(outcome.value, FalseBoolLiteralSugar)
