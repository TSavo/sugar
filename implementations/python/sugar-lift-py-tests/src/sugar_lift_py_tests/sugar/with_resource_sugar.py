"""Resource ``with``: manager once, enter, body ExitSet, exit per face.

Tree ownership:
- ``manager`` sugar evaluates the context expression **once**
- ``ManagerRef(M)`` is the stable receiver for enter/exit method coordinates
- ``enter`` is ``M.__enter__()`` sugar
- exit is **built per body face** with correct ``(type, val, tb)`` args
- ``enter_slot_id`` is authenticated from the completed enter value
- disposition is typed (never a name-callback)
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class WithResourceSugar(Sugar):
    """Resource with under tree-owned manager/enter coords + typed disposition."""

    manager: Sugar
    """Context-expression sugar — desugared exactly once."""

    manager_slot_id: str
    """Stable ManagerRef slot; enter/exit receivers share this coordinate."""

    enter: Sugar
    """``ManagerRef(M).__enter__()`` method-coordinate sugar."""

    body: tuple
    disposition: object
    enter_slot_id: str | None = None
    site: object = dataclass_field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        return _call_pair(
            name="with_resource_structure",
            owner_sugar="WithResourceSugar",
            truthful=(
                "def A(z):\n"
                "    with contextlib.suppress(KeyError):\n"
                "        raise KeyError\n"
                "    return z\n\n"
                "def test_a():\n"
                "    assert A(5) == 5\n"
            ),
            lying=(
                "def A(z):\n"
                "    with contextlib.suppress(KeyError):\n"
                "        raise KeyError\n"
                "    return z\n\n"
                "def test_a():\n"
                "    assert A(5) == 6\n"
            ),
        )

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.outcome.exit_set import Completed, ExitSet, Halted
        from sugar_lift_py_tests.outcome.resource_bindings import (
            EnterResultBinding,
            ManagerBinding,
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

        del ctx

        # 1. Evaluate context expression once.
        manager_es = sugar_outcome_to_exitset(self.manager.desugar())
        parts: list = []

        for mgr_exit in manager_es.exits:
            if isinstance(mgr_exit, Halted):
                parts.append(ExitSet((mgr_exit,)))
                continue

            mgr_facts = ()
            if hasattr(mgr_exit.value, "to_term"):
                mgr_facts = ManagerBinding(
                    self.manager_slot_id, mgr_exit.value
                ).to_facts(site=self.site)

            # 2. Enter once (receiver is ManagerRef coordinate sugar).
            enter_es = sugar_outcome_to_exitset(self.enter.desugar())
            for enter_exit in enter_es.exits:
                face_guard = _and_guards(mgr_exit.guard, enter_exit.guard)
                if isinstance(enter_exit, Halted):
                    parts.append(
                        ExitSet((Halted(face_guard, enter_exit.effect),))
                    )
                    continue

                enter_facts = ()
                if self.enter_slot_id is not None and hasattr(
                    enter_exit.value, "to_term"
                ):
                    enter_facts = EnterResultBinding(
                        self.enter_slot_id, enter_exit.value
                    ).to_facts(site=self.site)

                # 3. Body under enter-complete face.
                body_es = promote_raise_halts(
                    reduce_block_to_exitset(self.body)
                ).guarded(face_guard)

                # 4. Exit per body face with face-correct args.
                for body_exit in body_es.exits:
                    exit_sugar = self._exit_sugar_for_face(body_exit)
                    exit_es = sugar_outcome_to_exitset(exit_sugar.desugar())
                    face = ExitSet((body_exit,))
                    after = face.and_exit(exit_es, disposition=self.disposition)
                    after = prepend_facts_to_exitset(
                        after, (*mgr_facts, *enter_facts)
                    )
                    parts.append(after)

        if not parts:
            routed = ExitSet.completed(
                _ReducedBlock(entries=(), can_fall_through=True, fall_through=())
            )
        else:
            routed = parts[0]
            for part in parts[1:]:
                routed = routed.union(part)

        return exitset_to_outcome(routed)

    def _exit_sugar_for_face(self, body_exit) -> Sugar:
        """Build ``M.__exit__(type, val, tb)`` for this body face only.

        - Completed (incl. return): ``(None, None, None)``
        - Halted raise: ``(open type, raise witness, open traceback)``
        - Other halt: open triple residual (never invent completed None)
        """
        from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
        from sugar_lift_py_tests.outcome.exit_set import Completed, Halted
        from sugar_lift_py_tests.sugar.method_call_sugar import MethodCallSugar
        from sugar_lift_py_tests.sugar.none_literal_sugar import NoneLiteralSugar
        from sugar_lift_py_tests.sugar.resource_coord_sugar import (
            ManagerRefSugar,
            OpenExitArgSugar,
            RaiseWitnessSugar,
        )

        receiver = ManagerRefSugar(slot_id=self.manager_slot_id, site=self.site)
        none = NoneLiteralSugar(site=self.site)

        if isinstance(body_exit, Completed):
            args = (none, none, none)
        elif isinstance(body_exit, Halted) and isinstance(
            body_exit.effect, RaiseEffect
        ):
            effect = body_exit.effect
            occurrence = (
                getattr(effect, "occurrence_id", None)
                or getattr(effect, "occurrence", None)
                or getattr(effect, "blame", None)
                or "unknown-raise"
            )
            args = (
                OpenExitArgSugar(kind="exc_type", site=self.site),
                RaiseWitnessSugar(
                    occurrence=str(occurrence),
                    exception_name=effect.exception_name,
                    site=self.site,
                ),
                OpenExitArgSugar(kind="traceback", site=self.site),
            )
        else:
            # Non-raise halt / unknown control: keep all three open.
            args = (
                OpenExitArgSugar(kind="exc_type", site=self.site),
                OpenExitArgSugar(kind="exc_val", site=self.site),
                OpenExitArgSugar(kind="traceback", site=self.site),
            )

        return MethodCallSugar(
            receiver=receiver,
            name="__exit__",
            args=args,
            site=self.site,
        )


def _and_guards(left, right):
    from sugar_lift_py_tests.outcome.exit_set import true_guard
    from sugar_lift_py_tests.ir import and_

    if left == true_guard():
        return right
    if right == true_guard():
        return left
    if left == right:
        return left
    return and_([left, right])
