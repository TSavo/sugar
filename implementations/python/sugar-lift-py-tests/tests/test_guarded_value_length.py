from dataclasses import dataclass

import pytest

from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.floor import FloorValue, GuardedValue, TermValue, TupleValue
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.ir import and_, atomic, not_
from sugar_lift_py_tests.outcome import Complete, ExitSet
from sugar_lift_py_tests.outcome.exit_set import Completed, Halted, true_guard


GUARD = atomic("choose_length_arm", ())


@dataclass(frozen=True)
class _Demand:
    demand_cid: str


@dataclass(frozen=True)
class _DemandEntry:
    demands: tuple[_Demand, ...]


def test_guarded_length_distributes_to_both_truthful_arms():
    value = GuardedValue(
        GUARD,
        TupleValue((TermValue(1), TermValue(2))),
        TupleValue((TermValue(3),)),
    )

    outcome = value.length("length-site")

    assert outcome == Complete(GuardedValue(GUARD, TermValue(2), TermValue(1)))


def test_guarded_length_preserves_halt_guards_and_pending_contracts():
    completed_guard = atomic("length_completed", ())
    halted_guard = atomic("length_halted", ())
    pending = _DemandEntry((_Demand("length-demand"),))

    class PartitionedLength(FloorValue):
        def length(self, site):
            del site
            return ExitSet(
                (
                    Completed(
                        completed_guard,
                        TermValue(4),
                        pending_contracts=(pending,),
                    ),
                    Halted(
                        halted_guard,
                        RaiseEffect(exception_name="TypeError", blame="length-site"),
                        state="pre-length-state",
                        pending_contracts=(pending,),
                    ),
                )
            )

    outcome = GuardedValue(
        GUARD,
        PartitionedLength(),
        TupleValue((TermValue(9),)),
    ).length("length-site")

    assert isinstance(outcome, ExitSet)
    halted = next(face for face in outcome.exits if isinstance(face, Halted))
    assert halted.guard == and_((GUARD, halted_guard))
    assert halted.state == "pre-length-state"
    assert halted.pending_contracts == (pending,)
    completed = tuple(face for face in outcome.exits if isinstance(face, Completed))
    assert any(
        face.guard == and_((GUARD, completed_guard))
        and face.pending_contracts == (pending,)
        for face in completed
    )
    assert any(
        face.guard == and_((not_(GUARD), true_guard()))
        and face.value == TermValue(1)
        for face in completed
    )


def test_guarded_length_keeps_an_arm_without_length_loud():
    class NoLength(FloorValue):
        pass

    value = GuardedValue(GUARD, TupleValue(()), NoLength())

    with pytest.raises(ConstructionPanic) as raised:
        value.length("lying-length-site")

    assert raised.value.info.owner == "length"
    assert raised.value.info.observed == "NoLength"
