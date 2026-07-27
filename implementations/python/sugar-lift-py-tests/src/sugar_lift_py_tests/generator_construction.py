"""Typed suspended-generator construction and transition algebra."""

from __future__ import annotations

from dataclasses import dataclass, replace

from sugar_lift_python_source.canonical import cid_of_json

from .effect import Effect, require_effect
from .outcome import ExitSet


@dataclass(frozen=True)
class YieldStepV1:
    value: object


@dataclass(frozen=True)
class ReturnStepV1:
    value: object | None = None


@dataclass(frozen=True)
class OpaqueStepV1:
    observed: str


@dataclass(frozen=True)
class FinallyStepV1:
    statements: tuple[object, ...]


@dataclass(frozen=True)
class IfStepV1:
    """A branch inside a generator body, with each side's own step sequence.

    Carries SOURCE data only -- the guard's sugar, both branches' steps, and the
    `If` statement's own fragment CID. It deliberately does NOT carry a
    partition: the composite key needs the machine's `instance_coordinate`, and
    `allocate` mints that AFTER the producer has built the steps. Minting at
    TRANSITION time instead keeps the step tuple instance-agnostic, so one
    generator's steps can be shared by every instance over it while each mints
    its own partition. That is the property the key exists for.

    Admitted by the producer only when EVERY step in both branches is one the
    vocabulary can already execute. A branch holding a shape we cannot resume --
    `x = yield v`, whose resumed value reaches no name -- keeps the whole `If`
    an `OpaqueStepV1` and loud. Naming a step we cannot resume is worse than an
    honest opaque one.
    """

    guard: object
    then_steps: tuple
    else_steps: tuple
    fragment_cid: str


GeneratorStepV1 = YieldStepV1 | ReturnStepV1 | OpaqueStepV1 | FinallyStepV1 | IfStepV1


@dataclass(frozen=True)
class ResumeBindingV1:
    resume_coordinate: str
    resume_value: object


@dataclass(frozen=True)
class GeneratorTerminationV1:
    return_value: object | None
    binding_state: tuple[object, ...]


@dataclass(frozen=True)
class GeneratorTransitionGapV1:
    owner: str
    observed: str
    requested: str
    fix: str = "construct the transition in GeneratorConstructionV1"


@dataclass(frozen=True)
class YieldEffect:
    value: object
    resume_coordinate: str
    machine: "GeneratorConstructionV1"


@dataclass(frozen=True)
class GeneratorConstructionV1:
    """One allocated generator instance and its suspended frame state."""

    allocation_coordinate: str
    frame_coordinate: str
    binding_state: tuple[object, ...]
    steps: tuple[GeneratorStepV1, ...]
    instance_coordinate: str
    cursor: int = 0
    suspended_resume_coordinate: str | None = None

    @classmethod
    def allocate(
        cls,
        *,
        allocation_coordinate: str,
        frame_coordinate: str,
        binding_state: tuple[object, ...],
        steps: tuple[GeneratorStepV1, ...],
    ) -> "GeneratorConstructionV1":
        instance_coordinate = cid_of_json(
            {
                "kind": "python-generator-instance",
                "schemaVersion": "1",
                "allocationCoordinate": allocation_coordinate,
                "frameCoordinate": frame_coordinate,
                "bindingState": [repr(item) for item in binding_state],
            }
        )
        return cls(
            allocation_coordinate=allocation_coordinate,
            frame_coordinate=frame_coordinate,
            binding_state=binding_state,
            steps=tuple(steps),
            instance_coordinate=instance_coordinate,
        )

    def resume(self):
        return self._transition("resume")

    def send(self, value: object):
        if self.suspended_resume_coordinate is None:
            return self._gap("send", "generator is not suspended at a yield")
        machine = replace(
            self,
            binding_state=(
                *self.binding_state,
                ResumeBindingV1(self.suspended_resume_coordinate, value),
            ),
            suspended_resume_coordinate=None,
        )
        return machine._transition("send")

    def throw(self, effect: Effect) -> ExitSet:
        require_effect(effect)
        incoming = ExitSet.halted(effect, state=self)
        if self.cursor < len(self.steps) and isinstance(
            self.steps[self.cursor], FinallyStepV1
        ):
            step = self.steps[self.cursor]
            return incoming.and_finally(lambda: self._reduce_finally(step))
        return incoming

    def close(self):
        if self.cursor < len(self.steps) and isinstance(
            self.steps[self.cursor], FinallyStepV1
        ):
            cleanup = self._reduce_finally(self.steps[self.cursor])
            return cleanup.sequence(
                lambda state: ExitSet.completed(
                    GeneratorTerminationV1(None, self.binding_state)
                )
            )
        return GeneratorTerminationV1(None, self.binding_state)

    def _transition(self, requested: str):
        if self.cursor >= len(self.steps):
            return GeneratorTerminationV1(None, self.binding_state)
        step = self.steps[self.cursor]
        if isinstance(step, OpaqueStepV1):
            return self._gap(requested, step.observed)
        if isinstance(step, FinallyStepV1):
            cleanup = self._reduce_finally(step)
            from sugar_lift_py_tests.outcome import Completed, Halted

            if any(isinstance(exit_, Halted) for exit_ in cleanup.exits):
                return cleanup
            machine = replace(self, cursor=self.cursor + 1)
            return machine._transition(requested)
        if isinstance(step, IfStepV1):
            return self._transition_branch(step, requested)
        if isinstance(step, ReturnStepV1):
            value = self._reduce_value(step.value, requested)
            if isinstance(value, GeneratorTransitionGapV1):
                return value
            return GeneratorTerminationV1(value, self.binding_state)
        value = self._reduce_value(step.value, requested)
        if isinstance(value, GeneratorTransitionGapV1):
            return value
        resume_coordinate = f"{self.instance_coordinate}:resume:{self.cursor + 1}"
        machine = replace(
            self,
            cursor=self.cursor + 1,
            suspended_resume_coordinate=resume_coordinate,
        )
        return YieldEffect(value, resume_coordinate, machine)

    def _transition_branch(self, step: "IfStepV1", requested: str):
        """A branch is a two-face partition, or a splice when the guard decides.

        A DECIDED guard is not a partition: exactly one side runs, so its steps
        are spliced into this machine's sequence and nothing is minted. Minting
        a family over a route the producer does not actually decide would assert
        an exhaustiveness that is not true.

        An UNDECIDED guard is a genuine two-face split. Each face is a distinct
        successor machine with its own cursor -- the partition lives in the
        `ExitSet`, never in the machine, which is why no `faces` field is needed
        here. `factor_completed` then moves the partition from the exit level
        (where `sequence` multiplies it, m ** k over k steps) to the value level
        (one arm carrying a `GuardedValue` chain, which composes).

        THE KEY IS COMPOSITE. `("generator.branch", instance_coordinate,
        fragment_cid)`: the fragment gives reproducibility -- two reads of one
        instance's branch mint the same partition -- and the instance
        coordinate keeps two live generators over one source branch from
        looking like two sides of ONE split. `_faces_exclusive` never reads the
        arms' guards, so a source-only key would let the algebra declare two
        unrelated executions exclusive and re-attribute one's value to the
        negation of the other's guard. Same shape as the loop carrier's
        `targetCid` occurrence (see
        `test_two_occurrences_with_identical_faces_are_different_states`).
        """
        from dataclasses import replace as _replace

        from sugar_lift_py_tests.outcome.exit_set import Completed, ExitSet, partition

        decided = self._decide_guard(step.guard)
        if decided is True:
            return self._spliced(step.then_steps)._transition(requested)
        if decided is False:
            return self._spliced(step.else_steps)._transition(requested)

        guard_formula = self._guard_formula(step.guard)
        if guard_formula is None:
            return self._gap(requested, "If carrying a suspension")

        then_face, else_face = partition(
            ("generator.branch", self.instance_coordinate, step.fragment_cid)
        )
        from sugar_lift_py_tests.ir import not_

        return ExitSet(
            (
                Completed(
                    guard_formula,
                    self._spliced(step.then_steps),
                    frozenset({then_face}),
                    (),
                ),
                Completed(
                    not_(guard_formula),
                    self._spliced(step.else_steps),
                    frozenset({else_face}),
                    (),
                ),
            )
        ).factor_completed()

    def _spliced(self, branch_steps: tuple) -> "GeneratorConstructionV1":
        """This machine with the branch's steps in place of the `If`."""
        from dataclasses import replace as _replace

        steps = (
            *self.steps[: self.cursor],
            *branch_steps,
            *self.steps[self.cursor + 1 :],
        )
        return _replace(self, steps=steps)

    def _guard_truth(self, guard: object):
        """The guard's TRUTH as a floor value, or None if it cannot stand.

        A branch guard is not the operand -- it is the operand's truth, which
        is exactly what `FloorValue.truth` already states for every value that
        can answer it. Reading the operand's type directly would be a second,
        weaker copy of that law: `NoneValue.truth` is False, a container's is
        its non-emptiness, and a symbolic value's is a predicate. Routing
        through `truth` keeps one owner for the question.
        """
        from sugar_lift_py_tests.outcome import Complete
        from sugar_lift_py_tests.sugar.sugar_base import Sugar

        value = guard
        if isinstance(guard, Sugar):
            outcome = guard.desugar()
            if not isinstance(outcome, Complete):
                return None
            value = outcome.value
        truth = getattr(value, "truth", None)
        if truth is None:
            return None
        try:
            outcome = truth(self.instance_coordinate)
        except BaseException:
            return None
        if not isinstance(outcome, Complete):
            return None
        return outcome.value

    def _decide_guard(self, guard: object):
        """True/False when the guard's truth is ground, None when it is not."""
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        truth = self._guard_truth(guard)
        if isinstance(truth, TrueBoolLiteralSugar):
            return True
        if isinstance(truth, FalseBoolLiteralSugar):
            return False
        return None

    def _guard_formula(self, guard: object):
        """The guard's truth as a Formula, or None when it cannot stand."""
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue

        truth = self._guard_truth(guard)
        if isinstance(truth, PredicateValue):
            return truth.formula
        to_formula = getattr(truth, "to_formula", None)
        if to_formula is not None:
            try:
                return to_formula()
            except BaseException:
                return None
        return None

    def _reduce_value(self, value: object, requested: str):
        if value is None:
            return None
        from sugar_lift_py_tests.outcome import Complete
        from sugar_lift_py_tests.sugar.sugar_base import Sugar

        if not isinstance(value, Sugar):
            return value
        outcome = value.desugar()
        if isinstance(outcome, Complete):
            return outcome.value
        return self._gap(requested, type(outcome).__name__)

    @staticmethod
    def _reduce_finally(step: FinallyStepV1) -> ExitSet:
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            reduce_block_to_exitset,
        )

        return reduce_block_to_exitset(step.statements)

    @staticmethod
    def _gap(requested: str, observed: str) -> GeneratorTransitionGapV1:
        return GeneratorTransitionGapV1(
            owner="GeneratorConstructionV1.transition",
            observed=observed,
            requested=requested,
        )
