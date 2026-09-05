"""``with`` over a CITED manager: Python's law kept, the manager's law open.

Constructed only from an authenticated ``OpaqueCitedContextManagerRefV1``.
The producer seated that ref because it authenticated WHICH callee stands at
the ``with`` head and then found the callee off-population -- cited, never
materialized.  This node is what ``With`` builds over that citation.

What this node asserts, exactly:

* the manager expression was evaluated (its own outcome comes from its own
  sugar, unchanged by this node);
* ``__enter__`` was attempted;
* the body ran ONLY on the face where ``__enter__`` completed;
* ``__exit__`` ran over EVERY outgoing body edge.

That is Python's ``with`` law, which holds whatever the manager is.  What this
node does NOT assert -- and must never be read as asserting:

* that ``__enter__`` completes;
* what ``__enter__`` projects;
* that ``__exit__`` suppresses an exceptional body edge, or that it does not;
* that ``__exit__`` itself completes.

Each of those rides an open per-occurrence coordinate from
``floor/opaque_manager_protocol_coordinate.py`` with both faces retained.  The
suppression question in particular is handed to ``ExitSet.and_exit_truthiness``
exactly as a source-derived exit's REAL return value is: because the
coordinate is undecidable, that router emits the completed face under its
truth and restores the body's original effect under its falsity, and neither
face is discarded.  A downstream claim that depends on suppression therefore
cannot be discharged in either direction -- it reaches the emitted FOL as an
undischarged obligation.

This runs the SAME ExitSet algebra as ``WithResourceSugar``.  It is not a
second control model and not a soft survival arm: the refusal is not rescued
here, it was replaced upstream by a positive seated citation.  Compare
``SoftUnresolvedWithSugar``, which dresses a gap as an ``Incomplete`` and is
forbidden in production for exactly that reason.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class WithOpaqueCitedManagerSugar(Sugar):
    """Resource-shaped ``with`` whose manager protocol is cited, not known."""

    manager: Sugar
    body: tuple
    contract_ref: object
    enter_slot_id: str | None = None
    site: object = dataclass_field(compare=False, default=None)

    def __post_init__(self) -> None:
        from sugar_lift_py_tests.context_manager_resolution import (
            OpaqueCitedContextManagerRefV1,
            PartitionedOpaqueCitedContextManagerRefV1,
        )

        if type(self.contract_ref) not in (
            OpaqueCitedContextManagerRefV1,
            PartitionedOpaqueCitedContextManagerRefV1,
        ):
            raise ValueError(
                "WithOpaqueCitedManagerSugar requires an authenticated "
                "OpaqueCitedContextManagerRefV1; a cited manager is never "
                "inferred from the absence of a contract"
            )

    @classmethod
    def witnesses(cls):
        """Both arms epistemic-red: neither may be guessed.

        A cited manager's suppression is undecidable, so a body that halts
        leaves as both faces.  Any harness that reported ``sat`` or ``unsat``
        for a claim standing behind such a ``with`` would be reasoning as if
        the manager were transparent -- which is the one outcome this node
        exists to prevent.  ``unwitnessed`` is the honest verdict on BOTH
        arms, and that is what makes this pair lawful rather than a missing
        discrimination.
        """
        from sugar_lift_py_tests.sugar.witnesses import (
            SugarUnwitnessedPair,
            WitnessSource,
        )

        prefix = "import pytest\n\ndef A(z):\n    with pytest.raises(ValueError):\n        pass\n    return z\n\n"
        return SugarUnwitnessedPair(
            name="with_opaque_cited_manager_suppression_undecided",
            owner_sugar="WithOpaqueCitedManagerSugar",
            family="opaque-cited-manager-unwitnessed",
            truthful=WitnessSource(
                source=prefix + "def test_a():\n    assert A(1) == 1\n",
                expected="unwitnessed",
            ),
            lying=WitnessSource(
                source=prefix + "def test_a():\n    assert A(1) == 2\n",
                expected="unwitnessed",
            ),
        )

    def _manager_term(self, manager_value):
        """The manager's own authenticated term, or refuse.

        The coordinates are authenticated BY the callee they name.  A manager
        value that cannot project a term cannot authenticate a coordinate, and
        minting one anyway would produce a symbol that two different managers
        would share.
        """
        from sugar_source_tree.panic import SugarNotWritten

        project = getattr(manager_value, "to_term", None)
        if project is None:
            raise SugarNotWritten(
                blame=self.site,
                owner="WithOpaqueCitedManagerSugar.desugar",
                observed=(
                    "cited manager value projects no term, so its open "
                    "enter/exit coordinates cannot be authenticated by the "
                    "callee they name"
                ),
                requested=(
                    "a manager value with to_term, so the opaque protocol "
                    "coordinates name this callee and no other"
                ),
                fix=(
                    "keep an unprojectable cited manager loud; never mint a "
                    "protocol coordinate that two managers would share"
                ),
            )
        return project(owner="WithOpaqueCitedManagerSugar")

    def _enter_exitset(self, manager_value):
        """Enter: completed under ``g``, halted under ``not g``.  Both kept."""
        from sugar_lift_py_tests.effect import ContextManagerEnterRuntimeEffect
        from sugar_lift_py_tests.effect.runtime_effect import runtime_effect_evidence
        from sugar_lift_py_tests.floor.opaque_manager_protocol_coordinate import (
            opaque_completed_guard,
            opaque_enter_completed_coordinate,
            opaque_enter_result_coordinate,
            opaque_halted_guard,
        )
        from sugar_lift_py_tests.outcome.exit_set import Completed, ExitSet, Halted

        manager_term = self._manager_term(manager_value)
        completed = opaque_enter_completed_coordinate(manager_term, self.site)
        result = opaque_enter_result_coordinate(manager_term, self.site)
        effect = ContextManagerEnterRuntimeEffect(
            reason=(
                "__enter__ of cited manager "
                f"{self.contract_ref.target_name!r} may halt: the callee is "
                "off-population, so its enter semantics are uncited"
            ),
            **runtime_effect_evidence(
                "python:cm_enter", manager_value, self.site
            ),
        )
        return ExitSet(
            (
                Completed(opaque_completed_guard(completed), result),
                Halted(opaque_halted_guard(completed), effect, None),
            )
        )

    def _exit_exitset(self, manager_value):
        """Exit: completed with an OPEN result under ``g``, halted under ``not g``.

        The completed face carries the exit's open result coordinate rather
        than a decided boolean.  ``and_exit_truthiness`` reads its truthiness
        and, finding it undecidable, keeps both suppression faces.  The halted
        face is what keeps ``__exit__`` fallible: collapsing it would claim a
        cited manager cannot fail while closing.
        """
        from sugar_lift_py_tests.effect import ContextManagerExitRuntimeEffect
        from sugar_lift_py_tests.effect.runtime_effect import runtime_effect_evidence
        from sugar_lift_py_tests.floor.opaque_manager_protocol_coordinate import (
            opaque_completed_guard,
            opaque_exit_completed_coordinate,
            opaque_exit_result_coordinate,
            opaque_halted_guard,
        )
        from sugar_lift_py_tests.outcome.exit_set import Completed, ExitSet, Halted

        manager_term = self._manager_term(manager_value)
        completed = opaque_exit_completed_coordinate(manager_term, self.site)
        result = opaque_exit_result_coordinate(manager_term, self.site)
        effect = ContextManagerExitRuntimeEffect(
            reason=(
                "__exit__ of cited manager "
                f"{self.contract_ref.target_name!r} may halt or suppress: the "
                "callee is off-population, so its exit disposition is uncited"
            ),
            **runtime_effect_evidence("python:cm_exit", manager_value, self.site),
        )
        return ExitSet(
            (
                Completed(opaque_completed_guard(completed), result),
                Halted(opaque_halted_guard(completed), effect, None),
            )
        )

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.outcome.exit_set import ExitSet, Halted
        from sugar_lift_py_tests.outcome.resource_bindings import (
            EnterResultBinding,
            prepend_facts_to_exitset,
        )
        from sugar_lift_py_tests.sugar.exit_set_routing import (
            exitset_to_outcome,
            promote_raise_halts,
            sugar_outcome_to_exitset,
        )
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            _ReducedBlock,
            reduce_block_to_exitset,
        )

        manager_es = sugar_outcome_to_exitset(self.manager.desugar(ctx))
        parts: list = []

        for mgr_exit in manager_es.exits:
            if isinstance(mgr_exit, Halted):
                # The manager expression itself halted; enter is never reached.
                parts.append(ExitSet((mgr_exit,)))
                continue

            enter_es = self._enter_exitset(mgr_exit.value)
            exit_es = self._exit_exitset(mgr_exit.value)

            for enter_exit in enter_es.exits:
                face_guard = _and_guards(mgr_exit.guard, enter_exit.guard)
                if isinstance(enter_exit, Halted):
                    # Enter halted: the body never ran and exit never runs.
                    # Python does not call __exit__ when __enter__ raised.
                    parts.append(
                        ExitSet(
                            (
                                Halted(
                                    face_guard,
                                    enter_exit.effect,
                                    enter_exit.state,
                                    enter_exit.faces,
                                    enter_exit.pending_contracts,
                                ),
                            )
                        )
                    )
                    continue

                enter_facts = ()
                if self.enter_slot_id is not None:
                    enter_facts = EnterResultBinding(
                        self.enter_slot_id, enter_exit.value
                    ).to_facts(site=self.site)

                body_es = promote_raise_halts(
                    reduce_block_to_exitset(self.body, ctx)
                ).guarded(face_guard)

                for body_exit in body_es.exits:
                    # ONE router for both questions. A completed body leaves
                    # completed unless exit halts; a halted body leaves as BOTH
                    # faces under the exit result's undecidable truthiness.
                    after = ExitSet((body_exit,)).and_exit_truthiness(
                        exit_es, site=self.site
                    )
                    parts.append(prepend_facts_to_exitset(after, enter_facts))

        if not parts:
            routed = ExitSet.completed(
                _ReducedBlock(entries=(), can_fall_through=True, fall_through=())
            )
        else:
            routed = parts[0]
            for part in parts[1:]:
                routed = routed.union(part)

        return exitset_to_outcome(routed)


def _and_guards(left, right):
    from sugar_lift_py_tests.ir import and_
    from sugar_lift_py_tests.outcome.exit_set import true_guard

    if left == true_guard():
        return right
    if right == true_guard():
        return left
    if left == right:
        return left
    return and_([left, right])
