from __future__ import annotations

import ast
from pathlib import Path

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import (
    ExceptionalExitValue,
    NativeCallableValue,
    PredicateValue,
    RaiseValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.ir import ctor, eq, make_var, num
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def _outcome(expression: str):
    node = ast.parse(expression, mode="eval").body
    ctx = FactoryBuildContext(filename="operator.py", catalog=default_catalog())
    return ctx.build_body(node, SugarRole.TERM).reduce(ctx)


@pytest.mark.parametrize(
    ("expression", "expected"),
    (
        ("3 & 1", 1),
        ("3 ^ 1", 2),
        ("~2", -3),
        ("1 << 2", 4),
        ("1 + 2", 3),
        ("5 // 2", 2),
        ("5 % 2", 1),
        ("-3", -3),
        ("5 - 2", 3),
    ),
)
def test_ground_operator_result_folds(expression: str, expected: int) -> None:
    assert _outcome(expression).value == TermValue(expected)


def test_ground_bitwise_or_result_folds() -> None:
    site = SourceFragment.from_source("1 | 2", "operator.py")

    assert TermValue(1).bitwise_or(TermValue(2), site) == Complete(TermValue(3))


@pytest.mark.parametrize("expression", ("5 // 0", "5 % 0"))
def test_ground_zero_divisor_constructs_exact_exit(expression: str) -> None:
    outcome = _outcome(expression)

    assert isinstance(outcome.value, RaiseValue)
    assert outcome.value.effect.exception_name == "ZeroDivisionError"
    assert outcome.value.effect.blame == "operator.py:1:0"
    assert outcome.value.exception is not None
    assert outcome.value.exception.exception_name == "ZeroDivisionError"


def test_true_and_predicate_constructs_predicate() -> None:
    site = SourceFragment.from_source("True & p", "operator.py")
    predicate = PredicateValue(eq(make_var("p"), num(1)), site)

    outcome = TrueBoolLiteralSugar(site=site).bitwise_and(predicate, site)

    assert outcome == Complete(predicate)


def test_false_and_predicate_constructs_false() -> None:
    site = SourceFragment.from_source("False & p", "operator.py")
    predicate = PredicateValue(eq(make_var("p"), num(1)), site)

    outcome = FalseBoolLiteralSugar(site=site).bitwise_and(predicate, site)

    assert isinstance(outcome.value, FalseBoolLiteralSugar)


def test_boolean_invert_folds_to_python_integer() -> None:
    site = SourceFragment.from_source("~True", "operator.py")

    assert TrueBoolLiteralSugar(site=site).bitwise_invert(site) == Complete(
        TermValue(-2)
    )
    assert FalseBoolLiteralSugar(site=site).bitwise_invert(site) == Complete(
        TermValue(-1)
    )


def test_predicate_or_symbolic_constructs_exact_coordinate() -> None:
    site = SourceFragment.from_source("p | q", "operator.py")
    predicate = PredicateValue(eq(make_var("p"), num(1)), site)
    symbolic = SymbolicValue(make_var("q"))

    outcome = predicate.bitwise_or(symbolic, site)

    assert isinstance(outcome.value, SymbolicValue)
    assert "|" in repr(outcome.value.term)


def test_existing_exceptional_exit_propagates_through_floor_divide() -> None:
    site = SourceFragment.from_source("raised // 2", "operator.py")
    exceptional = ExceptionalExitValue(
        RaiseEffect("ValueError", str(site), "source-digest")
    )

    assert exceptional.floor_divide(TermValue(2), site) == Complete(exceptional)


@pytest.mark.parametrize(
    "operation",
    (
        lambda value, site: value.bitwise_or(TermValue(1), site),
        lambda value, site: value.bitwise_and(TermValue(1), site),
        lambda value, site: value.bitwise_xor(TermValue(1), site),
        lambda value, site: value.bitwise_invert(site),
        lambda value, site: value.left_shift(TermValue(1), site),
        lambda value, site: value.add(TermValue(1), site),
        lambda value, site: value.floor_divide(TermValue(1), site),
        lambda value, site: value.modulo(TermValue(1), site),
        lambda value, site: value.subtract(TermValue(1), site),
    ),
)
def test_unbuilt_native_value_operator_stays_loud(operation) -> None:
    site = SourceFragment.from_source("native", "operator.py")
    native = NativeCallableValue("vendor.native_constant", "vendor.so")

    with pytest.raises(FactoryPanic):
        operation(native, site)


def test_native_value_unary_minus_constructs_exact_coordinate() -> None:
    site = SourceFragment.from_source("-native", "operator.py")
    native = NativeCallableValue("vendor.native_constant", "vendor.so")

    outcome = native.unary_minus(site)

    assert outcome == Complete(
        SymbolicValue(
            ctor(
                "py.neg",
                [native.to_term(owner=str(site))],
            )
        )
    )


def test_ground_operator_family_witness_truthful_sat_lying_unsat(
    tmp_path: Path,
) -> None:
    prefix = (
        "def A(z):\n"
        "    if z < 0:\n"
        "        return 1 // 0\n"
        "    return ((1 | 2) + (3 & 1) + (3 ^ 1) + (1 << 2)"
        " + (5 + 2) + (5 // 2) + (5 % 2) + (-3) + (5 - 2) + (~1))\n"
        "\n"
    )
    truthful = run_source_through_real_solver(
        tmp_path / "truthful",
        prefix + "def test_a():\n    assert A(5) == 18\n",
    )
    lying = run_source_through_real_solver(
        tmp_path / "lying",
        prefix + "def test_a():\n    assert A(5) == 19\n",
    )

    assert {"AddOpSugar", "FloorDivideOpSugar"}.issubset(set(truthful.selected_sugars))
    assert truthful.verdict == "sat"
    assert lying.verdict == "unsat"
