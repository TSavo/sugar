"""Source-derived ProtocolResource routing over constructed protocol testimony."""

from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class WithSourceResourceSugar(Sugar):
    manager: Sugar
    enter: Sugar
    exit: Sugar
    protocol: object
    summary: object
    body: tuple[Sugar, ...]
    manager_slot_id: str
    enter_slot_id: str | None
    exit_face_id: str
    enter_definition: object
    exit_definition: object
    site: object = field(compare=False, default=None)

    def __post_init__(self) -> None:
        from sugar_lift_py_tests.sugar.method_call_sugar import MethodCallSugar

        for call, definition, slot in (
            (self.enter, self.enter_definition, "context-enter"),
            (self.exit, self.exit_definition, "context-exit"),
        ):
            if not isinstance(call, MethodCallSugar):
                raise TypeError(f"source resource {slot} must be a MethodCallSugar")
            if call.native_definition_coordinate != definition:
                raise ValueError(
                    f"{slot} call is not authenticated by its definition coordinate"
                )

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx: object = None) -> ExitSet:
        return _route_manager_faces(self, ctx)


def _route_manager_faces(resource, ctx: object = None) -> ExitSet:
    """Enter every manager face under its guard; union the exits (8.5).

    The enter runs beneath its manager face and the body beneath its enter
    face, each composed onto that face by ``ExitSet.sequence``: it takes the
    face's guard and faces and owes what the face owes. The exit routing
    carries a body face's debts onto every arm it leaves through.
    """
    from sugar_lift_py_tests.outcome.exit_set import Halted, _require_exit_set
    from sugar_lift_py_tests.outcome.resource_bindings import (
        EnterResultBinding,
        ExitFaceBinding,
        ManagerBinding,
        prepend_facts_to_exitset,
    )
    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        reduce_block_to_exitset,
        resumed,
    )

    # The manager, its enter and its exit are each routed face by face here:
    # a deferred native-operation carrier at any of them is refused by name.
    # A manager call coordinate is not its returned receiver. Perform its
    # source outcome once, preserving exceptional faces before enter.
    manager_out = _require_exit_set(
        resource.manager.desugar(ctx), owner="WithSourceResourceSugar.manager"
    )
    manager_es = manager_out.sequence(
        lambda value: _project_manager_receiver(value, ctx)
    )
    parts = []
    for manager_face in manager_es.exits:
        if isinstance(manager_face, Halted):
            parts.append(ExitSet((manager_face,)))
            continue
        manager_facts = ManagerBinding(
            resource.manager_slot_id, manager_face.value
        ).to_facts(site=resource.site)
        enter_es = ExitSet((manager_face,)).sequence(
            lambda manager: _require_exit_set(
                resource.protocol.enter_resource_outcome_for(manager, ctx),
                owner="WithSourceResourceSugar.enter",
            )
        )
        for enter_face in enter_es.exits:
            if isinstance(enter_face, Halted):
                parts.append(ExitSet((enter_face,)))
                continue
            entered = enter_face.value
            enter_value = _returned_value(entered.enter_value)
            enter_facts = ()
            if resource.enter_slot_id is not None and enter_value is not None:
                enter_facts = EnterResultBinding(
                    resource.enter_slot_id, enter_value
                ).to_facts(site=resource.site)
            # The exit is routed per body face: a body whose carrier
            # ``sequence`` composed is refused by name here.
            body_es = _require_exit_set(
                ExitSet((enter_face,)).sequence(
                    lambda _entered: reduce_block_to_exitset(resource.body, ctx)
                ),
                owner="WithSourceResourceSugar.body",
            )
            concrete_exit = getattr(resource.protocol, "exit_outcome_for_body", None)
            # Generator protocols have a linear resume: retain their single
            # existing exit reduction instead of resuming per body face.
            abstract_exit = (
                None
                if concrete_exit is not None
                else _require_exit_set(
                    resource.protocol.exit_outcome_for(entered, ctx),
                    owner="WithSourceResourceSugar.exit",
                )
            )
            for body_face in body_es.exits:
                # ``__exit__`` runs where the body left this face: a body
                # halt's record (``resumed``), or the record the body
                # completed with -- never the context the ``with`` began in.
                exit_es = (
                    _require_exit_set(
                        concrete_exit(
                            entered,
                            body_face,
                            resumed(
                                body_face.state
                                if isinstance(body_face, Halted)
                                else body_face.value,
                                ctx,
                                owner="WithSourceResourceSugar.exit",
                                blame=resource.site,
                            ).context,
                        ),
                        owner="WithSourceResourceSugar.exit",
                    )
                    if concrete_exit is not None
                    else abstract_exit
                )
                face_facts = ExitFaceBinding.from_body_exit(
                    resource.exit_face_id, body_face
                ).to_facts(site=resource.site, guard=body_face.guard)
                disposition = resource.summary.semantics.exit.disposition
                from sugar_lift_py_tests.context_manager_contract import (
                    ReturnTruthinessDispositionV1,
                )

                if isinstance(disposition, ReturnTruthinessDispositionV1):
                    from sugar_lift_py_tests.context_manager_contract import (
                        NeverSuppressesDispositionV1,
                    )
                    from sugar_lift_py_tests.effect import (
                        GroupedRaiseEffect,
                        RaiseEffect,
                    )
                    from sugar_lift_py_tests.effect.raise_effect import (
                        UndeterminedRaiseEffect,
                    )

                    # An exception (a leaf or a group) is suppressed by a
                    # true exit result; loop control and return are not
                    # exceptions, so the exit result is ignored for them.
                    # A RuntimeEffect is not an exception either: it is the
                    # lift's boundary at an operation whose dispatch exists
                    # only at runtime (it may complete or raise anything).
                    # Every exception Python raises from a decided operation
                    # (``1/0``, ``{}[k]``, a NameError) is a RaiseEffect and
                    # takes the truth split; handing a boundary to exit as a
                    # raise would invent one, so it stays the With's residue.
                    if isinstance(body_face, Halted) and not isinstance(
                        body_face.effect,
                        (RaiseEffect, GroupedRaiseEffect, UndeterminedRaiseEffect),
                    ):
                        routed = ExitSet((body_face,)).and_exit(
                            exit_es,
                            disposition=NeverSuppressesDispositionV1(),
                        )
                    else:
                        routed = ExitSet((body_face,)).and_exit_truthiness(
                            _exit_return_values(exit_es), site=resource.site
                        )
                else:
                    routed = ExitSet((body_face,)).and_exit(
                        exit_es,
                        disposition=disposition,
                    )
                parts.append(
                    prepend_facts_to_exitset(
                        routed, (*manager_facts, *enter_facts, *face_facts)
                    )
                )
    if not parts:
        from sugar_source_tree.panic import SugarNotWritten

        raise SugarNotWritten(
            blame=resource.site,
            owner="WithSourceResourceSugar.desugar",
            observed="constructed manager protocol produced no face",
            requested="one completed or halted source-derived manager face",
            fix="keep empty protocol testimony loud",
        )
    result = parts[0]
    for part in parts[1:]:
        result = result.union(part)
    return result.normalize()


def _project_manager_receiver(value, ctx, seen=frozenset()):
    """Follow retained factory returns, not fresh source-body evaluations.

    A factory may return another call (including its class constructor). Each
    floor projects its own retained completion; only the fixed-point receiver
    reaches enter. ExitSet sequencing keeps every exceptional/guarded face.
    """
    from sugar_source_tree.panic import SugarNotWritten

    if id(value) in seen:
        raise SugarNotWritten(
            blame="WithSourceResourceSugar.manager",
            owner="WithSourceResourceSugar.manager",
            observed="cycle in retained manager return projections",
            requested="an acyclic constructed manager receiver",
            fix="retain the source call-graph cycle as a construction gap",
        )
    from sugar_lift_py_tests.generator_construction import GeneratorConstructionV1

    if type(value) is GeneratorConstructionV1:
        # ``contextmanager(f)(...)`` is ``_GeneratorContextManager(f, args,
        # kwds)``, whose ``self.gen`` is this allocated generator: the generator
        # protocol enters and exits exactly this machine.
        return ExitSet.completed(value)
    from sugar_lift_py_tests.outcome.exit_set import _require_exit_set

    projected = _require_exit_set(
        value.project_operation_receiver_outcome(
            ctx, owner="WithSourceResourceSugar.manager"
        ),
        owner="WithSourceResourceSugar.manager",
    )
    return projected.sequence(
        lambda receiver: (
            ExitSet.completed(receiver)
            if receiver is value
            else _project_manager_receiver(receiver, ctx, seen | {id(value)})
        )
    )


def _returned_value(value):
    from sugar_lift_py_tests.floor import BlockValue, ReturnValue

    if isinstance(value, BlockValue) and value.statements:
        last = value.statements[-1]
        if isinstance(last, ReturnValue):
            return last.value
    return value


def _exit_return_values(exit_es, *, owner="WithSourceResourceSugar.exit-return"):
    """Project native returns, retaining guards and refusing untransported state.

    A constructed conditional return is GuardedReturn, not a truthy BlockValue.
    Branch-result slots may be eliminated only by their native authentication.
    Prefix stores/effects are not discarded to obtain a convenient predicate.
    """
    from sugar_lift_py_tests.floor import (
        BlockValue,
        BranchResultAuthentication,
        GuardedReturn,
        NoneValue,
        ReturnValue,
    )
    from sugar_lift_py_tests.floor.branch_result_coordinate import (
        resolve_branch_result_guards,
    )
    from sugar_lift_py_tests.gap.panic import construction_panic_gap
    from sugar_lift_py_tests.ir import and_
    from sugar_lift_py_tests.outcome.exit_set import (
        ExitSet,
        complement_guard,
        true_guard,
    )

    def returns(block):
        """What one completed exit face returns, each return under its own
        guard; ``sequence`` conjoins the face's guard, faces and ``owed``
        onto every one. Halts bypass."""
        if not isinstance(block, BlockValue):
            return ExitSet.completed(block)
        rows = []
        authentication = {
            item.slot.slot_id: item.observed_guard
            for item in block.statements
            if isinstance(item, BranchResultAuthentication)
        }
        remaining = true_guard()
        for item in block.statements:
            if isinstance(item, BranchResultAuthentication):
                continue
            if not isinstance(item, (ReturnValue, GuardedReturn)):
                construction_panic_gap(
                    owner=owner,
                    blame=type(item).__name__,
                    observed="native exit prefix requires state/effect transport",
                    requested="return testimony without discarding prefix operations",
                    fix="transport the native prefix state before projecting its return",
                )
            guards = item.guards if isinstance(item, GuardedReturn) else ()
            local_guard = guards[0] if len(guards) == 1 else and_(list(guards))
            local_guard = resolve_branch_result_guards(local_guard, authentication)
            if local_guard is None:
                construction_panic_gap(
                    owner=owner,
                    blame=type(item).__name__,
                    observed="return guard lacks native branch authentication",
                    requested="native branch-result testimony",
                    fix="carry the branch producer's actual observed guard",
                )
            rows.append(
                ExitSet.completed(item.value, _and(remaining, local_guard))
            )
            remaining = _and(remaining, complement_guard(local_guard))
        if block.can_fall_through:
            fall_guard = resolve_branch_result_guards(
                and_(list(block.fall_through)), authentication
            )
            if fall_guard is None:
                construction_panic_gap(
                    owner=owner,
                    blame="fall-through",
                    observed="fall-through guard lacks native branch authentication",
                    requested="native branch-result testimony",
                    fix="carry the branch producer's actual observed guard",
                )
            rows.append(ExitSet.completed(NoneValue(), _and(remaining, fall_guard)))
        # A terminal residue without a return contributes no completed result.
        # The returns are siblings: one join.
        return ExitSet(()).union(*rows)

    result = exit_es.sequence(returns)
    if not result.exits:
        construction_panic_gap(
            owner=owner,
            blame="native exit",
            observed="exit has no returned, fall-through, or halted face",
            requested="a reachable native exit outcome, not an empty green",
            fix="retain the native exit's actual control outcome",
        )
    return result


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
