"""The `+` operator (AddOpSugar): reduce left, reduce right, ask left to add right
(the addition floor). The value owns what addition means -- numbers fold, strings
concatenate, mixed types hit the honest floor gap."""

from __future__ import annotations

import ast

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor import StringValue
from sugar_lift_py_tests.effect import SequenceConcatenationRuntimeEffect
from sugar_lift_py_tests.floor import OpaqueOpCallsite, SymbolicValue
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.outcome import Incomplete
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.outcome import Complete
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


def test_add_folds_to_true_when_sum_equals() -> None:
    assert isinstance(
        _condition("if 1 + 1 == 2:\n    pass").value, TrueBoolLiteralSugar
    )


def test_add_folds_to_false_when_sum_differs() -> None:
    assert isinstance(
        _condition("if 1 + 1 == 3:\n    pass").value, FalseBoolLiteralSugar
    )


def test_add_folds_collapsed_number_float() -> None:
    assert isinstance(
        _condition("if 1.5 + 1 == 2.5:\n    pass").value, TrueBoolLiteralSugar
    )


def test_add_string_concatenates() -> None:
    sugar, ctx = _build_term('"a" + "b"')
    assert sugar.desugar(ctx) == Complete(StringValue("ab"))


def test_string_add_runtime_str_is_named() -> None:
    site = SourceFragment.from_source('"prefix" + str(value)', "t.py")

    outcome = StringValue("prefix").add(
        OpaqueOpCallsite("str", SymbolicValue(make_var("value"))), site
    )

    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, SequenceConcatenationRuntimeEffect)


def test_add_mixed_number_string_panics() -> None:
    sugar, ctx = _build_term('3 + "a"')
    with pytest.raises(FactoryPanic):
        sugar.desugar(ctx)
