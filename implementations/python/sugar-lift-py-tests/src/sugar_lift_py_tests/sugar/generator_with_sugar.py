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
            entered = machine.resume()
            if isinstance(entered, GeneratorTerminationV1):
                # Never-yield / premature-return at enter: Python's manager
                # protocol raises. Type and message come from the observed
                # vendor conversion (generator_entry_refusal), not a transcribed
                # string and not a SugarNotWritten refusal of a real outcome.
                routed.append(
                    self._entry_refusal_exit(
                        manager_exit,
                        entered,
                    )
                )
                continue
            if isinstance(entered, GeneratorTransitionGapV1):
                self._loud(entered.observed, "opaque generator transition")
            if not isinstance(entered, YieldEffect):
                self._loud(type(entered).__name__, "opaque generator transition")

            body_es = reduce_block_to_exitset(self.body, ctx).guarded(
                manager_exit.guard
            )
            exits = []
            for body_exit in body_es.exits:
                if isinstance(body_exit, Halted):
                    thrown = entered.machine.throw(body_exit.effect).guarded(
                        body_exit.guard
                    )
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
            routed.append(prepend_facts_to_exitset(result, facts))

        if not routed:
            return exitset_to_outcome(ExitSet(()))
        result = routed[0]
        for part in routed[1:]:
            result = result.union(part)
        return exitset_to_outcome(result)

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
        effect = RaiseEffect(
            exception_name=refusal.exception_name,
            blame=blame,
            occurrence=f"generator-entry-refusal:{blame}",
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

    @staticmethod
    def _loud(observed: str, label: str):
        from sugar_source_tree.panic import SugarNotWritten

        raise SugarNotWritten(
            owner="GeneratorWithSugar.desugar",
            observed=f"{label}: {observed}",
            requested="an exhaustive GeneratorConstructionV1 transition",
            fix="construct the transition or retain this typed loud boundary",
        )
