"""Mechanical context-manager consumption of GeneratorConstructionV1."""

from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.generator_construction import (
    GeneratorConstructionV1,
    GeneratorTerminationV1,
    GeneratorTransitionGapV1,
    YieldEffect,
)
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class GeneratorWithSugar(Sugar):
    manager: Sugar
    body: tuple[Sugar, ...]
    enter_slot_id: str | None
    site: object = field(compare=False)

    @classmethod
    def witnesses(cls):
        from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing

        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="ExitSet",
            reason="generator manager mechanics route already-constructed body faces",
        )

    def desugar(self, ctx=None) -> Outcome:
        from sugar_lift_py_tests.outcome.resource_bindings import (
            EnterResultBinding,
            prepend_facts_to_exitset,
        )
        from sugar_lift_py_tests.sugar.exit_set_routing import (
            exitset_to_outcome,
            sugar_outcome_to_exitset,
        )
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            reduce_block_to_exitset,
        )

        manager_es = sugar_outcome_to_exitset(self.manager.desugar(ctx))
        routed = []
        for manager_exit in manager_es.exits:
            if isinstance(manager_exit, Halted):
                routed.append(ExitSet((manager_exit,)))
                continue
            machine = manager_exit.value
            if not isinstance(machine, GeneratorConstructionV1):
                self._loud(
                    "manager did not construct GeneratorConstructionV1",
                    "opaque generator transition",
                )
            routed.append(
                self._consume_enter_outcome(machine.resume(), manager_exit, ctx)
            )

        if not routed:
            return exitset_to_outcome(ExitSet(()))
        result = routed[0]
        for part in routed[1:]:
            result = result.union(part)
        return exitset_to_outcome(result)

    def _consume_enter_outcome(self, entered, manager_exit, ctx):
        """Route first-resume of a generator manager, including open enter faces."""
        from sugar_lift_py_tests.outcome.exit_set import Completed, Halted
        from sugar_lift_py_tests.outcome.resource_bindings import (
            EnterResultBinding,
            prepend_facts_to_exitset,
        )
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            reduce_block_to_exitset,
        )

        if isinstance(entered, ExitSet):
            parts = []
            for face in entered.exits:
                if isinstance(face, Halted):
                    parts.append(ExitSet((face,)).guarded(manager_exit.guard))
                    continue
                if isinstance(face, Completed):
                    parts.append(
                        self._consume_enter_outcome(
                            face.value, manager_exit, ctx
                        ).guarded(face.guard)
                    )
                    continue
                self._loud(type(face).__name__, "opaque generator transition")
            if not parts:
                return ExitSet(())
            result = parts[0]
            for part in parts[1:]:
                result = result.union(part)
            return result
        if isinstance(entered, GeneratorTerminationV1):
            return self._entry_refusal_exit(manager_exit, entered)
        if isinstance(entered, GeneratorTransitionGapV1):
            self._loud(entered.observed, "opaque generator transition")
        if not isinstance(entered, YieldEffect):
            self._loud(type(entered).__name__, "opaque generator transition")

        body_es = reduce_block_to_exitset(self.body, ctx).guarded(manager_exit.guard)
        exits = []
        for body_exit in body_es.exits:
            if isinstance(body_exit, Halted):
                thrown = entered.machine.throw(body_exit.effect).guarded(body_exit.guard)
                exits.extend(thrown.exits)
                continue
            after = entered.machine.resume()
            if isinstance(after, ExitSet):
                exits.extend(after.guarded(body_exit.guard).exits)
                continue
            if isinstance(after, YieldEffect):
                self._loud("generator yielded during exit", "second yield")
            if isinstance(after, GeneratorTransitionGapV1):
                self._loud(after.observed, "opaque generator transition")
            if not isinstance(after, GeneratorTerminationV1):
                self._loud(type(after).__name__, "opaque generator transition")
            exits.append(Completed(body_exit.guard, body_exit.value))
        result = ExitSet(tuple(exits)).normalize()
        facts = ()
        if self.enter_slot_id is not None:
            facts = EnterResultBinding(self.enter_slot_id, entered.value).to_facts(
                site=self.site
            )
        return prepend_facts_to_exitset(result, facts)

    @staticmethod
    def _entry_refusal_exit(manager_exit, termination: GeneratorTerminationV1):
        """Turn first-resume termination into the authenticated raise ExitSet arm.

        Observation lives in ``generator_entry_refusal`` (vendor conversion).
        This consumer only asks for it — no vendor module name here
        (``generator_construction_law``).
        """
        from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
        from sugar_lift_py_tests.generator_entry_refusal import observed_entry_refusal
        from sugar_lift_py_tests.outcome.exit_set import Halted

        refusal = observed_entry_refusal()
        blame = str(manager_exit.value.instance_coordinate)
        effect = RaiseEffect.for_builtin(
            refusal.exception_name,
            occurrence=f"generator-entry-refusal:{blame}",
            blame=blame,
            raised_value=refusal.message,
        )
        return ExitSet(
            (
                Halted(
                    manager_exit.guard,
                    effect,
                    termination,
                    manager_exit.faces,
                ),
            )
        )

    def _loud(self, observed: str, label: str):
        from sugar_source_tree.panic import SugarNotWritten

        raise SugarNotWritten(
            blame=self.site,
            owner="GeneratorWithSugar.desugar",
            observed=f"{label}: {observed}",
            requested="an exhaustive GeneratorConstructionV1 transition",
            fix="construct the transition or retain this typed loud boundary",
        )
