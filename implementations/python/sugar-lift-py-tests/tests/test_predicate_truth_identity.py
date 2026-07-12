"""An already-boolean PredicateValue stands as its own truth condition."""

from __future__ import annotations

from sugar_lift_py_tests.floor import PredicateValue, SymbolicValue
from sugar_lift_py_tests.ir import make_var, num, py_eq, py_truthy
from sugar_lift_py_tests.lift_rpc import audit_lift_file
from sugar_lift_py_tests.outcome import Complete


def test_predicate_truth_is_formula_identity_and_preserves_callsites() -> None:
    callsite = object()
    predicate = PredicateValue(
        py_eq(make_var("value"), num(1)),
        site="predicate-site",
        operand_callsites=(callsite,),
    )

    outcome = predicate.truth("condition-site")

    assert isinstance(outcome, Complete)
    assert outcome.value is predicate
    assert outcome.value.formula == py_eq(make_var("value"), num(1))
    assert outcome.value.operand_callsites == (callsite,)


def test_symbolic_truth_still_adds_python_truthy_once() -> None:
    symbolic = SymbolicValue(make_var("value"))
    outcome = symbolic.truth("condition-site")

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, PredicateValue)
    assert outcome.value.formula == py_truthy(make_var("value"))


def test_real_condition_shape_has_no_predicate_truth_floor_panic() -> None:
    source = """
def accepts(value):
    if not value == 1:
        return 0
    return 1
"""
    recovered = audit_lift_file(source, "core/algorithms.py", recover_panics=True)
    assert all(
        not (
            panic.gap["owner"] == "truth" and panic.gap["observed"] == "PredicateValue"
        )
        for panic in recovered.panics
    )
