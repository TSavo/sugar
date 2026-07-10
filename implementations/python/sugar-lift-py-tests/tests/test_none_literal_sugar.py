"""The `None` literal (NoneLiteralSugar): the None-ness IS the type -- no value
field. It reduces to NoneValue. `None == None` folds True; cross-type equals
panics until a ruling lands."""

from __future__ import annotations

import ast

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
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


def test_none_equals_int_panics_on_the_floor() -> None:
    sugar, ctx = _build_term("None == 5")
    with pytest.raises(FactoryPanic):
        sugar.desugar(ctx)
