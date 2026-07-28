from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.floor import FloorValue, GuardedFaces
from sugar_lift_py_tests.ir import atomic, not_
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.function_universe_sugar import reduce_block_to_exitset
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar


@dataclass(frozen=True)
class _OccurrenceStateValue(FloorValue):
    occurrence: object
    state: object


class _CaptureContext(Sugar):
    def __init__(self, seen: list[object]):
        self.seen = seen

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        self.seen.append(ctx)
        return Complete(TrueBoolLiteralSugar(site="capture"))


class _GuardedBindingStatement(Sugar):
    def __init__(self, guard, value):
        self.guard = guard
        self.value = value

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        return Complete(
            GuardedFaces(
                self.guard,
                (),
                then_exits=False,
                else_exits=False,
                guarded_bindings=((self.guard, "result", self.value),),
            )
        )


def test_explicit_reduction_context_reaches_first_statement_unchanged() -> None:
    explicit = ReduceContext.root(owner="explicit-context-twin")
    seen: list[object] = []

    reduce_block_to_exitset((_CaptureContext(seen),), explicit)

    assert seen == [explicit]
    assert seen[0] is explicit


def test_none_entry_is_normalized_before_first_statement() -> None:
    seen: list[object] = []

    reduce_block_to_exitset((_CaptureContext(seen),), None)

    assert len(seen) == 1
    assert isinstance(seen[0], ReduceContext)


def test_guarded_truthful_face_extends_normalized_scope_with_exact_value() -> None:
    guard = atomic("guarded.return.truth", [])
    occurrence = object()
    state = object()
    value = _OccurrenceStateValue(occurrence, state)
    seen: list[object] = []

    reduce_block_to_exitset(
        (_GuardedBindingStatement(guard, value), _CaptureContext(seen)), None
    )

    assert len(seen) == 1
    active = seen[0].temporal.activate_guard(guard)
    retained = active.value_if_bound("result")
    assert retained is value
    assert retained.occurrence is occurrence
    assert retained.state is state


def test_guarded_lying_face_does_not_activate_truthful_scope() -> None:
    guard = atomic("guarded.return.truth", [])
    value = _OccurrenceStateValue(object(), object())
    seen: list[object] = []

    reduce_block_to_exitset(
        (_GuardedBindingStatement(guard, value), _CaptureContext(seen)), None
    )

    lying = seen[0].temporal.activate_guard(not_(guard))
    assert lying.value_if_bound("result") is None
