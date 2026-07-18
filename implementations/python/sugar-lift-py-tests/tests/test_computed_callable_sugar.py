from __future__ import annotations

import ast
from pathlib import Path

import pytest

from factory_reduce import reduce_value
from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory.build import build_node
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.recognition.call_identity import CallIdentityRecognition
from sugar_lift_py_tests.sugar.computed_callable_sugar import ComputedCallableSugar
from sugar_lift_py_tests.sugar.witnesses import SugarWitnessPair
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def _site(expression: str) -> SourceFragment:
    node = ast.parse(expression, mode="eval").body
    return SourceFragment.from_node(node, "computed_call.py")


def test_factory_recognizes_conditional_callable_application() -> None:
    assert CallIdentityRecognition.is_computed_callable(
        _site("(left if choose_left else right)(value)")
    )
    assert ComputedCallableSugar.owns(
        _site("(left if choose_left else right)(value)")
    )


def test_factory_recognizes_binary_callable_application() -> None:
    assert CallIdentityRecognition.is_computed_callable(
        _site("(callable_type * count)()")
    )


def test_factory_builds_computed_callable_and_each_operand() -> None:
    node = ast.parse(
        "(left if choose_left else right)(value, named=other)",
        mode="eval",
    ).body

    result = build_node(
        node,
        filename="computed_call.py",
        role=SugarRole.TERM,
    )

    assert isinstance(result.sugar, ComputedCallableSugar)
    assert len(result.sugar.arguments) == 2
    assert result.sugar.keyword_names == ("named",)


def test_unsupported_lambda_callable_remains_unowned() -> None:
    assert not CallIdentityRecognition.is_computed_callable(
        _site("(lambda value: value)(item)")
    )


def test_constructed_non_callable_reaches_a_named_floor_gap() -> None:
    with pytest.raises(
        FactoryPanic,
        match="owner=ComputedCallableSugar.*requested=callable_application_with",
    ):
        reduce_value("(1 * 2)()")


def test_computed_callable_witness_truthful_sat_lying_unsat(
    tmp_path: Path,
) -> None:
    pair = ComputedCallableSugar.witnesses()
    assert isinstance(pair, SugarWitnessPair)

    truthful = run_source_through_real_solver(
        tmp_path / "truthful", pair.truthful.source
    )
    lying = run_source_through_real_solver(tmp_path / "lying", pair.lying.source)

    assert truthful.verdict == pair.truthful.expected == "sat"
    assert lying.verdict == pair.lying.expected == "unsat"
