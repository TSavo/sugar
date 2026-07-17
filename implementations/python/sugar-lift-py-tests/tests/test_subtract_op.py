"""The `-` operator (SubtractOpSugar): reduce left, reduce right, ask left to
subtract right (the subtraction floor). Concrete numbers fold to a TermValue;
strings do not stand on the floor and the default panics."""

from __future__ import annotations

import ast

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.effect import SubtractRuntimeEffect
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import (
    CallSiteValue,
    ComprehensionValue,
    NativeCallableValue,
    SetValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.ir import ctor, make_var, num
from sugar_lift_py_tests.outcome import Complete, Incomplete
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


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


def test_numeric_symbolic_subtraction_uses_native_coordinate() -> None:
    site = SourceFragment.from_source("4 - runtime_n\n", "t.py").statements()[0]

    outcome = TermValue(4).subtract(SymbolicValue(make_var("runtime_n")), site)

    assert outcome == Complete(
        SymbolicValue(ctor("-", [num(4), make_var("runtime_n")]))
    )


def test_concrete_set_difference_constructs_exact_members() -> None:
    site = SourceFragment.from_source("left - right\n", "t.py").statements()[0]
    left = SetValue((TermValue(1), TermValue(2), TermValue(3)))
    right = SetValue((TermValue(2), TermValue(4)))

    outcome = left.subtract(right, site)

    assert outcome == Complete(SetValue((TermValue(1), TermValue(3))))


@pytest.mark.parametrize(
    "left",
    (
        TermValue(4),
        ComprehensionValue(ctor("python:set_comprehension", [make_var("item")])),
        NativeCallableValue("pandas.NaT", "/native/pandas.so"),
    ),
)
def test_opaque_call_result_subtraction_is_a_witnessed_runtime_effect(left) -> None:
    site = SourceFragment.from_source("left - runtime_right()\n", "t.py").statements()[
        0
    ]
    right = CallSiteValue(
        target_name="runtime_right",
        arg_values=(),
        parameters=(),
        term=ctor("call:runtime_right", []),
        body=None,
        site=site,
    )

    outcome = left.subtract(right, site)

    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, SubtractRuntimeEffect)
    operand = ctor("-", [left.to_term(owner="test"), right.to_term(owner="test")])
    assert outcome.effect.witness.operand == operand
    assert outcome.effect.witness.operation == ctor("py.subtract", [operand])
    assert outcome.effect.witness.locus == "t.py:1:0"


def test_subtract_truthful_and_lying_twins_reach_opposite_verdicts(tmp_path) -> None:
    prefix = "def A():\n    return 7 - 2\n\n"
    truthful = run_source_through_real_solver(
        tmp_path / "truthful", prefix + "def test_a():\n    assert A() == 5\n"
    )
    lying = run_source_through_real_solver(
        tmp_path / "lying", prefix + "def test_a():\n    assert A() == 6\n"
    )

    assert truthful.verdict == "sat"
    assert lying.verdict == "unsat"
    assert "SubtractOpSugar" in truthful.selected_sugars
    assert "SubtractOpSugar" in lying.selected_sugars
