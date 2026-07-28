"""Source-derived ProtocolResource routing over constructed protocol testimony."""

from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class WithSourceResourceSugar(Sugar):
    manager: Sugar
    protocol: object
    summary: object
    body: tuple[Sugar, ...]
    manager_slot_id: str
    enter_slot_id: str | None
    exit_face_id: str
    site: object = field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.outcome import outcome_to_exitset
        from sugar_lift_py_tests.outcome.exit_set import ExitSet, Halted
        from sugar_lift_py_tests.outcome.resource_bindings import (
            EnterResultBinding,
            ExitFaceBinding,
            ManagerBinding,
            prepend_facts_to_exitset,
        )
        from sugar_lift_py_tests.sugar.exit_set_routing import (
            promote_raise_halts,
            sugar_outcome_to_exitset,
        )
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            reduce_block_to_exitset,
        )

        manager_es = sugar_outcome_to_exitset(self.manager.desugar(ctx))
        parts = []
        for manager_face in manager_es.exits:
            if isinstance(manager_face, Halted):
                parts.append(ExitSet((manager_face,)))
                continue
            manager_facts = ManagerBinding(
                self.manager_slot_id, manager_face.value
            ).to_facts(site=self.site)
            enter_es = outcome_to_exitset(self.protocol.enter_resource_outcome(ctx))
            for enter_face in enter_es.exits:
                guard = _and(manager_face.guard, enter_face.guard)
                if isinstance(enter_face, Halted):
                    parts.append(ExitSet((Halted(guard, enter_face.effect),)))
                    continue
                entered = enter_face.value
                enter_value = _returned_value(entered.enter_value)
                enter_facts = ()
                if self.enter_slot_id is not None and enter_value is not None:
                    enter_facts = EnterResultBinding(
                        self.enter_slot_id, enter_value
                    ).to_facts(site=self.site)
                body_es = promote_raise_halts(
                    reduce_block_to_exitset(self.body)
                ).guarded(guard)
                exit_es = outcome_to_exitset(
                    self.protocol.exit_outcome_for(entered, ctx)
                )
                for body_face in body_es.exits:
                    face_facts = ExitFaceBinding.from_body_exit(
                        self.exit_face_id, body_face
                    ).to_facts(site=self.site, guard=body_face.guard)
                    routed = ExitSet((body_face,)).and_exit(
                        exit_es,
                        disposition=self.summary.semantics.exit.disposition,
                    )
                    parts.append(
                        prepend_facts_to_exitset(
                            routed, (*manager_facts, *enter_facts, *face_facts)
                        )
                    )
        if not parts:
            from sugar_source_tree.panic import SugarNotWritten

        raise SugarNotWritten(
            blame=self.site,
            owner="WithSourceResourceSugar.desugar",
            observed="constructed manager protocol produced no face",
            requested="one completed or halted source-derived manager face",
            fix="keep empty protocol testimony loud",
        )
        result = parts[0]
        for part in parts[1:]:
            result = result.union(part)
        return result.normalize()


def _returned_value(value):
    from sugar_lift_py_tests.floor import BlockValue, ReturnValue

    if isinstance(value, BlockValue) and value.statements:
        last = value.statements[-1]
        if isinstance(last, ReturnValue):
            return last.value
    return value


def _and(left, right):
    from sugar_lift_py_tests.ir import and_
    from sugar_lift_py_tests.outcome.exit_set import true_guard

    if left == true_guard():
        return right
    if right == true_guard():
        return left
    if left == right:
        return left
    return and_([left, right])
