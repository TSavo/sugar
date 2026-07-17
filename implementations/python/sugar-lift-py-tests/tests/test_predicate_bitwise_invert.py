from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor import (
    GuardedValue,
    PredicateValue,
    StringValue,
)
from sugar_lift_py_tests.ir import atomic, make_var, not_
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.unary_op_sugar import UnaryOpSugar
from sugar_lift_py_tests.sugar.witnesses import SugarWitnessPair
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def _hold_factory_panic(operation):
    try:
        return operation()
    except FactoryPanic as panic:
        return ("factory-panic", panic.info.owner, panic.info.observed)


def test_predicate_bitwise_invert_constructs_logical_negation() -> None:
    callsite = object()
    formula = atomic("positive", [make_var("value")])
    predicate = PredicateValue(
        formula,
        site="predicate-site",
        operand_callsites=(callsite,),
    )

    outcome = _hold_factory_panic(lambda: predicate.bitwise_invert("invert-site"))

    assert isinstance(outcome, Complete)
    assert outcome.value == PredicateValue(
        not_(formula),
        site="predicate-site",
        operand_callsites=(callsite,),
    )


def test_guarded_bitwise_invert_distributes_into_both_constructed_faces() -> None:
    guard = atomic("guard", [make_var("choice")])
    left = atomic("left", [make_var("value")])
    right = atomic("right", [make_var("value")])
    value = GuardedValue(
        guard,
        PredicateValue(left),
        PredicateValue(right),
    )

    outcome = _hold_factory_panic(lambda: value.bitwise_invert("invert-site"))

    assert isinstance(outcome, Complete)
    assert outcome.value == GuardedValue(
        guard,
        PredicateValue(not_(left)),
        PredicateValue(not_(right)),
    )


def test_unsupported_ground_bitwise_invert_stays_loud() -> None:
    with pytest.raises(FactoryPanic, match="owner=bitwise_invert"):
        StringValue("not an integer").bitwise_invert("invert-site")


def test_predicate_bitwise_invert_truthful_and_lying_twins_refute(
    tmp_path: Path,
) -> None:
    witnesses = UnaryOpSugar.witnesses()
    pairs = witnesses if isinstance(witnesses, tuple) else (witnesses,)
    pair = next(
        witness
        for witness in pairs
        if isinstance(witness, SugarWitnessPair)
        and witness.name == "predicate_bitwise_invert_return"
    )

    truthful = run_source_through_real_solver(
        tmp_path / "truthful", pair.truthful.source
    )
    lying = run_source_through_real_solver(tmp_path / "lying", pair.lying.source)

    assert truthful.verdict == pair.truthful.expected == "sat"
    assert lying.verdict == pair.lying.expected == "unsat"
    assert "UnaryOpSugar" in truthful.selected_sugars
    assert "UnaryOpSugar" in lying.selected_sugars
