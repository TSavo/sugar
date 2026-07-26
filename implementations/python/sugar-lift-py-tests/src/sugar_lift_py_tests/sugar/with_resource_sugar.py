"""Resource ``with``: manager once, enter, body ExitSet, parametric exit.

Tree ownership (construction door only):
- ``manager`` — context expr, desugared once
- ``enter`` — ``ManagerRef(M).__enter__()``
- ``exit`` — **one** prebuilt ``M.__exit__(ExitTypeRef(X), ExitValueRef(X),
  ExitTracebackRef(X))`` sugar
- face testimony via ``ExitFaceBinding`` under each body-exit guard

``desugar`` must not import or construct sugars (MethodCallSugar, etc.).
It only desugars existing sugars, emits binding facts, and runs ExitSet algebra.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class WithResourceSugar(Sugar):
    """Resource with: tree-owned manager/enter/exit + typed disposition."""

    manager: Sugar
    manager_slot_id: str
    enter: Sugar
    exit: Sugar
    """Single parametric ``M.__exit__(ExitTypeRef(X), …)`` — never rebuilt."""

    exit_face_id: str
    """Stable face coordinate X for ExitFaceBinding testimony."""

    body: tuple
    disposition: object
    contract_ref: object | None = None
    context_manager_edge: object | None = None
    enter_slot_id: str | None = None
    site: object = dataclass_field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        prefix = (
            "class Resource:\n"
            "    def __init__(self):\n"
            "        self.closed = False\n"
            "    def __enter__(self):\n"
            "        return self\n"
            "    def __exit__(self, effect_type, effect, traceback):\n"
            "        self.closed = True\n"
            "        return False\n\n"
            "def A(halts):\n"
            "    resource = Resource()\n"
            "    try:\n"
            "        with resource:\n"
            "            if halts:\n"
            "                raise ValueError\n"
            "    except ValueError:\n"
            "        pass\n"
            "    return resource.closed\n\n"
        )
        return _call_pair(
            name="with_resource_closes_completed_and_halted",
            owner_sugar="WithResourceSugar",
            truthful=prefix
            + "def test_a():\n"
            "    assert A(False)\n"
            "    assert A(True)\n",
            lying=prefix
            + "def test_a():\n"
            "    assert A(False)\n"
            "    assert not A(True)\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        # Construction boundary: only ExitSet algebra + binding facts.
        # No sugar-class imports or construction on this path.
        from sugar_lift_py_tests.outcome.exit_set import ExitSet, Halted
        from sugar_lift_py_tests.outcome.resource_bindings import (
            EnterResultBinding,
            ExitFaceBinding,
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

            enter_es = sugar_outcome_to_exitset(self.enter.desugar())
            for enter_exit in enter_es.exits:
                face_guard = _and_guards(mgr_exit.guard, enter_exit.guard)
                if isinstance(enter_exit, Halted):
                    parts.append(ExitSet((Halted(face_guard, enter_exit.effect),)))
                    continue

                enter_facts = ()
                if self.enter_slot_id is not None and hasattr(
                    enter_exit.value, "to_term"
                ):
                    enter_facts = EnterResultBinding(
                        self.enter_slot_id, enter_exit.value
                    ).to_facts(site=self.site)

                body_es = promote_raise_halts(
                    reduce_block_to_exitset(self.body)
                ).guarded(face_guard)

                # Parametric exit: materialize once, fan over every body face.
                exit_es = sugar_outcome_to_exitset(self.exit.desugar())

                for body_exit in body_es.exits:
                    face_facts = ExitFaceBinding.from_body_exit(
                        self.exit_face_id, body_exit
                    ).to_facts(site=self.site, guard=body_exit.guard)
                    face = ExitSet((body_exit,))
                    if _is_never_suppressing_resource(self.disposition):
                        after = face.and_finally(lambda: exit_es)
                    else:
                        after = face.and_exit(
                            exit_es, disposition=self.disposition
                        )
                    after = prepend_facts_to_exitset(
                        after, (*mgr_facts, *enter_facts, *face_facts)
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


def _is_never_suppressing_resource(disposition) -> bool:
    from sugar_lift_py_tests.context_manager_contract import (
        NeverSuppresses,
        NeverSuppressesDispositionV1,
    )

    return isinstance(
        disposition, (NeverSuppresses, NeverSuppressesDispositionV1)
    )
