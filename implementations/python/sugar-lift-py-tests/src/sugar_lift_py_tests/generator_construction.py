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
    """A body statement the step vocabulary cannot yet name.

    ``carries_suspension`` is the discrimination that makes this row
    dispatchable. Without it, ``x = 1`` and ``x = yield 1`` are the SAME row --
    ``OpaqueStepV1("Assign")`` -- and they are not the same obligation:

    * an opaque statement that owns NO suspension owes ordinary statement
      execution inside a generator frame;
    * an opaque statement that OWNS one owes a generator-protocol law (the
      resumed value's binding, a branched suspension's partition).

    Bucketing them together is why the two suspension owners read as one
    undifferentiated mass. The flag is read from ``_owns_yield``, the same
    authenticated predicate the step builder already uses to decide whether a
    body is a generator at all -- never from the statement's spelling.
    """

    observed: str
    carries_suspension: bool = False

    def gap_observed(self) -> str:
        """What the transition gap should NAME as unconsumed.

        The statement kind alone (``Assign``, ``If``, ``Expr``) names the
        shape of the container, not the thing that could not be consumed, so a
        board keyed on it cannot tell generator-protocol work from ordinary
        unsupported statements.
        """
        if not self.carries_suspension:
            return self.observed
        return f"{self.observed} carrying a suspension"


@dataclass(frozen=True)
class FinallyStepV1:
    statements: tuple[object, ...]


GeneratorStepV1 = YieldStepV1 | ReturnStepV1 | OpaqueStepV1 | FinallyStepV1


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
            return self._gap(requested, step.gap_observed())
        if isinstance(step, FinallyStepV1):
            cleanup = self._reduce_finally(step)
            from sugar_lift_py_tests.outcome import Completed, Halted

            if any(isinstance(exit_, Halted) for exit_ in cleanup.exits):
                return cleanup
            machine = replace(self, cursor=self.cursor + 1)
            return machine._transition(requested)
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
