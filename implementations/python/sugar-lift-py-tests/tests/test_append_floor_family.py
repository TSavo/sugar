from __future__ import annotations

from sugar_lift_py_tests.effect import AppendRuntimeEffect
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import (
    GuardedValue,
    ListValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.ir import make_var, py_truthy
from sugar_lift_py_tests.outcome import Complete, Incomplete


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
