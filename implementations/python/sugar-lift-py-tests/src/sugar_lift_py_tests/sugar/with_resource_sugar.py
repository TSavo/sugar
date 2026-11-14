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

from sugar_lift_py_tests.outcome import ExitSet
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
    enter_definition: object | None = None
    exit_definition: object | None = None
    site: object = dataclass_field(compare=False, default=None)

    def __post_init__(self) -> None:
        if self.enter_definition is None or self.exit_definition is None:
            raise ValueError(
                "WithResourceSugar requires authenticated enter and exit definition coordinates"
            )
        from sugar_lift_py_tests.sugar.method_call_sugar import MethodCallSugar

        for call, definition, slot in (
            (self.enter, self.enter_definition, "context-enter"),
            (self.exit, self.exit_definition, "context-exit"),
        ):
            if isinstance(call, MethodCallSugar) and (
                call.native_definition_coordinate != definition
            ):
                raise ValueError(
                    f"{slot} call is not authenticated by its definition coordinate"
                )

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
            truthful=prefix + "def test_a():\n"
            "    assert A(False)\n"
            "    assert A(True)\n",
            lying=prefix + "def test_a():\n"
            "    assert A(False)\n"
            "    assert not A(True)\n",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        # Construction boundary: only ExitSet algebra + binding facts.
        # No sugar-class imports or construction on this path.
        from sugar_lift_py_tests.floor import EnteredManagerStateValue
        from sugar_lift_py_tests.outcome.exit_set import Halted, _require_exit_set
        from sugar_lift_py_tests.outcome.resource_bindings import (
            EnterResultBinding,
            ExitFaceBinding,
            ManagerBinding,
            prepend_facts_to_exitset,
        )
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            _ReducedBlock,
            reduce_block_to_exitset,
        )

        # The manager, the enter, the body and the exit all run under the
        # ``with`` statement's own context: there is no second way to reduce
        # them without it (#7757). Each is routed face by face here: a
        # deferred native-operation carrier at any of them is refused by name.
        manager_es = _require_exit_set(
            self.manager.desugar(ctx), owner="WithResourceSugar.manager"
        )
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

            # The enter runs beneath its manager face and the body beneath its
            # enter face (``ExitSet.sequence``): each takes the face's guard
            # and faces and owes what it owes; the exit routing carries a body
            # face's debts onto every arm it leaves through.
            enter_es = ExitSet((mgr_exit,)).sequence(
                lambda _manager: _require_exit_set(
                    self.enter.desugar(ctx), owner="WithResourceSugar.enter"
                )
            )
            for enter_exit in enter_es.exits:
                if isinstance(enter_exit, Halted):
                    parts.append(ExitSet((enter_exit,)))
                    continue

                entered = EnteredManagerStateValue(
                    enter_value=enter_exit.value,
                    receiver_state=mgr_exit.value,
                )

                enter_facts = ()
                if self.enter_slot_id is not None and hasattr(
                    enter_exit.value, "to_term"
                ):
                    enter_facts = EnterResultBinding(
                        self.enter_slot_id, entered.enter_value
                    ).to_facts(site=self.site)

                # The exit is routed per body face: a body whose carrier
                # ``sequence`` composed is refused by name here.
                body_es = _require_exit_set(
                    ExitSet((enter_exit,)).sequence(
                        lambda _entered: reduce_block_to_exitset(self.body, ctx)
                    ),
                    owner="WithResourceSugar.body",
                )

                # Parametric exit: materialize once, fan over every body face.
                exit_es = _require_exit_set(
                    self.exit.desugar(ctx), owner="WithResourceSugar.exit"
                )

                for body_exit in body_es.exits:
                    face_facts = ExitFaceBinding.from_body_exit(
                        self.exit_face_id, body_exit
                    ).to_facts(site=self.site, guard=body_exit.guard)
                    face = ExitSet((body_exit,))
                    from sugar_lift_py_tests.context_manager_contract import (
                        NeverSuppressesDispositionV1,
                        ReturnTruthinessDispositionV1,
                    )
                    from sugar_lift_py_tests.effect import (
                        GroupedRaiseEffect,
                        RaiseEffect,
                    )
                    from sugar_lift_py_tests.effect.raise_effect import (
                        UndeterminedRaiseEffect,
                    )

                    # Every exception -- a leaf, a group, or the one a
                    # may-raise operation threw without testimony -- is handed
                    # to the parametric exit, so its truth decides suppression.
                    # Treating an undetermined raise as never suppressed would
                    # claim the exit cannot swallow it.
                    if (
                        isinstance(self.disposition, ReturnTruthinessDispositionV1)
                        and isinstance(body_exit, Halted)
                        and isinstance(
                            body_exit.effect,
                            (RaiseEffect, GroupedRaiseEffect, UndeterminedRaiseEffect),
                        )
                    ):
                        after = face.and_exit_truthiness(exit_es, site=self.site)
                    else:
                        disposition = (
                            NeverSuppressesDispositionV1()
                            if isinstance(
                                self.disposition, ReturnTruthinessDispositionV1
                            )
                            else self.disposition
                        )
                        after = face.and_exit(exit_es, disposition=disposition)
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

        # The with's own faces: a halt stays a halted arm (#7826).
        return routed.normalize()
