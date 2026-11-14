"""Protocol-resource routing for a manager whose head is a formal parameter.

Same ExitSet algebra as ``WithSourceResourceSugar``, but enter/exit are the
formal-selected manager protocol, not source ``MethodCallSugar`` definition
coordinates. A formal parameter has no authenticated source for those
coordinates, and inventing them would be a lie.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class WithFormalManagerSugar(Sugar):
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

    def desugar(self, ctx: object = None) -> ExitSet:
        from sugar_lift_py_tests.outcome.exit_set import Halted, _require_exit_set
        from sugar_lift_py_tests.outcome.resource_bindings import (
            EnterResultBinding,
            ExitFaceBinding,
            ManagerBinding,
            prepend_facts_to_exitset,
        )
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            reduce_block_to_exitset,
        )
        from sugar_lift_py_tests.sugar.with_source_resource_sugar import (
            _project_manager_receiver,
            _returned_value,
        )

        # The manager, its construction, its enter and its exit are each
        # routed face by face here: a deferred native-operation carrier at any
        # of them is refused by name.
        manager_out = _require_exit_set(
            self.manager.desugar(ctx), owner="WithFormalManagerSugar.manager"
        )
        manager_es = manager_out.sequence(
            lambda value: _project_manager_receiver(value, ctx)
        )
        construct = getattr(self.protocol, "construct_manager", None)
        if construct is not None:
            manager_es = _require_exit_set(
                manager_es.sequence(lambda value: construct(value, ctx)),
                owner="WithFormalManagerSugar.construct",
            )
        parts = []
        for manager_face in manager_es.exits:
            if isinstance(manager_face, Halted):
                parts.append(ExitSet((manager_face,)))
                continue
            manager_facts = ManagerBinding(
                self.manager_slot_id, manager_face.value
            ).to_facts(site=self.site)
            # The enter runs beneath its manager face and the body beneath its
            # enter face (``ExitSet.sequence``): each takes the face's guard
            # and faces and owes what it owes; the exit routing carries a body
            # face's debts onto every arm it leaves through.
            enter_es = ExitSet((manager_face,)).sequence(
                lambda manager: _require_exit_set(
                    self.protocol.enter_resource_outcome_for(manager, ctx),
                    owner="WithFormalManagerSugar.enter",
                )
            )
            for enter_face in enter_es.exits:
                if isinstance(enter_face, Halted):
                    parts.append(ExitSet((enter_face,)))
                    continue
                entered = enter_face.value
                enter_value = _returned_value(entered.enter_value)
                enter_facts = ()
                if self.enter_slot_id is not None and enter_value is not None:
                    enter_facts = EnterResultBinding(
                        self.enter_slot_id, enter_value
                    ).to_facts(site=self.site)
                # The exit is routed per body face: a body whose carrier
                # ``sequence`` composed is refused by name here.
                body_es = _require_exit_set(
                    ExitSet((enter_face,)).sequence(
                        lambda _entered: reduce_block_to_exitset(self.body, ctx)
                    ),
                    owner="WithFormalManagerSugar.body",
                )
                exit_es = _require_exit_set(
                    self.protocol.exit_outcome_for(entered, ctx),
                    owner="WithFormalManagerSugar.exit",
                )
                for body_face in body_es.exits:
                    face_facts = ExitFaceBinding.from_body_exit(
                        self.exit_face_id, body_face
                    ).to_facts(site=self.site, guard=body_face.guard)
                    routed = _route_body_face(
                        body_face,
                        exit_es,
                        self.summary.semantics.exit.disposition,
                        self.site,
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
                owner="WithFormalManagerSugar.desugar",
                observed="formal manager protocol produced no face",
                requested="one completed or halted formal manager face",
                fix="keep empty protocol testimony loud",
            )
        result = parts[0]
        for part in parts[1:]:
            result = result.union(part)
        return result.normalize()


def _route_body_face(body_face, exit_es, disposition, site):
    """Route one body face through exit under the protocol's typed disposition.

    ``ReturnTruthiness`` is the same law ``WithSourceResourceSugar`` applies:
    an exception (a leaf or a group) is suppressed only under the truth of the
    exit result and re-raised under its falsity; loop control and return are
    not exceptions, so the exit result does not decide them. Neither is a
    ``RuntimeEffect``: it marks an operation whose dispatch exists only at
    runtime and may complete or raise. Decided runtime raises (``1/0``,
    ``{}[k]``) are ``RaiseEffect`` and take the truth split; a boundary stays
    the With's own residue rather than an invented raise handed to exit.
    """
    from sugar_lift_py_tests.context_manager_contract import (
        NeverSuppressesDispositionV1,
        ReturnTruthinessDispositionV1,
    )
    from sugar_lift_py_tests.effect import GroupedRaiseEffect, RaiseEffect
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.outcome.exit_set import ExitSet, Halted
    from sugar_lift_py_tests.sugar.with_source_resource_sugar import (
        _exit_return_values,
    )

    if not isinstance(disposition, ReturnTruthinessDispositionV1):
        return ExitSet((body_face,)).and_exit(exit_es, disposition=disposition)
    if isinstance(body_face, Halted) and not isinstance(
        body_face.effect, (RaiseEffect, GroupedRaiseEffect, UndeterminedRaiseEffect)
    ):
        return ExitSet((body_face,)).and_exit(
            exit_es, disposition=NeverSuppressesDispositionV1()
        )
    return ExitSet((body_face,)).and_exit_truthiness(
        _exit_return_values(exit_es), site=site
    )
