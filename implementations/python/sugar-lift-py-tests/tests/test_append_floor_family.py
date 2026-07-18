from __future__ import annotations

from sugar_lift_py_tests.effect import AppendRuntimeEffect
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import (
    ComprehensionValue,
    GuardedValue,
    ListValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.ir import ctor, make_var, num, py_truthy
from sugar_lift_py_tests.outcome import Complete, Incomplete
from sugar_lift_py_tests.sugar.append_call_sugar import AppendCallSugar
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def _site() -> SourceFragment:
    return SourceFragment.from_source("xs.append(3)", "append.py")


def test_guarded_concrete_lists_append_on_both_faces() -> None:
    guard = py_truthy(make_var("condition"))
    receiver = GuardedValue(
        guard,
        ListValue((TermValue(1),)),
        ListValue((TermValue(2),)),
    )

    outcome = receiver.append_with(TermValue(3), _site())

    assert outcome == Complete(
        GuardedValue(
            guard,
            ListValue((TermValue(1), TermValue(3))),
            ListValue((TermValue(2), TermValue(3))),
        )
    )


def test_symbolic_append_is_a_named_runtime_effect() -> None:
    outcome = SymbolicValue(make_var("xs")).append_with(TermValue(3), _site())

    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, AppendRuntimeEffect)
    assert outcome.effect.witness.operation.name == "py.append"


def test_comprehension_append_constructs_list_post_state() -> None:
    receiver = ComprehensionValue(ctor("py.listcomp", [make_var("runtime_items")]))

    outcome = receiver.append_with(TermValue(3), _site())

    assert outcome == Complete(
        ComprehensionValue(
            ctor(
                "py.list_append",
                [receiver.term, num(3)],
            )
        )
    )


def test_comprehension_append_truthful_and_lying_twins_reach_opposite_verdicts(
    tmp_path,
) -> None:
    pair = next(
        pair
        for pair in AppendCallSugar.witnesses()
        if pair.name == "append_comprehension_return"
    )

    truthful = run_source_through_real_solver(
        tmp_path / "truthful", pair.truthful.source
    )
    lying = run_source_through_real_solver(tmp_path / "lying", pair.lying.source)

    assert truthful.verdict == pair.truthful.expected == "sat"
    assert lying.verdict == pair.lying.expected == "unsat"
    assert "AppendCallSugar" in truthful.selected_sugars
    assert "AppendCallSugar" in lying.selected_sugars


def test_finite_cast_append_truthful_and_lying_twins_reach_opposite_verdicts(
    tmp_path,
) -> None:
    pair = next(
        pair
        for pair in AppendCallSugar.witnesses()
        if pair.name == "append_finite_cast_return"
    )

    truthful = run_source_through_real_solver(
        tmp_path / "truthful", pair.truthful.source
    )
    lying = run_source_through_real_solver(tmp_path / "lying", pair.lying.source)

    assert truthful.verdict == pair.truthful.expected == "sat"
    assert lying.verdict == pair.lying.expected == "unsat"
    assert "AppendCallSugar" in truthful.selected_sugars
    assert "AppendCallSugar" in lying.selected_sugars
