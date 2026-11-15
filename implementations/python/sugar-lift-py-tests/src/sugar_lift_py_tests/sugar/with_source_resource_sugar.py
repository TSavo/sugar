"""A ``with`` whose manager is the value its head reduced to."""

from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class WithReducedManagerSugar(Sugar):
    """``with <head>:`` whose manager is the value its head reduced to.

    The head is reduced once, as any expression is (``manager``); each value
    it completes with is the manager, and ``protocol`` reads ``__enter__``
    and ``__exit__`` on that value's own type, or answers the undecided
    manager.  The faces are routed by the one router every constructed
    ``with`` uses (``_route_manager_faces``) under Python's own disposition:
    the truth of what ``__exit__`` returns decides whether an exception the
    body raised is suppressed (8.5).
    """

    manager: Sugar
    protocol: object
    body: tuple[Sugar, ...]
    manager_slot_id: str
    enter_slot_id: str | None
    exit_face_id: str
    site: object = field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        from sugar_lift_py_tests.sugar.witnesses import _call_pair

        prefix = (
            "class Resource:\n"
            "    def __init__(self):\n"
            "        self.closed = False\n"
            "    def __enter__(self):\n"
            "        return self\n"
            "    def __exit__(self, effect_type, effect, traceback):\n"
            "        self.closed = True\n"
            "        return False\n\n"
            "def make():\n"
            "    return Resource()\n\n"
            "def A(halts):\n"
            "    resource = make()\n"
            "    try:\n"
            "        with resource:\n"
            "            if halts:\n"
            "                raise ValueError\n"
            "    except ValueError:\n"
            "        pass\n"
            "    return resource.closed\n\n"
        )
        return _call_pair(
            name="with_reduced_manager_closes_completed_and_halted",
            owner_sugar="WithReducedManagerSugar",
            truthful=prefix + "def test_a():\n"
            "    assert A(False)\n"
            "    assert A(True)\n",
            lying=prefix + "def test_a():\n"
            "    assert A(False)\n"
            "    assert not A(True)\n",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        return _route_manager_faces(self, ctx)


def _route_manager_faces(resource, ctx: object = None) -> ExitSet:
    """Enter every manager face under its guard; union the exits (8.5).

    The enter runs beneath its manager face and the body beneath its enter
    face, each composed onto that face by ``ExitSet.and_then``: it takes the
    face's guard and faces and owes what the face owes. The exit routing
    carries a body face's debts onto every arm it leaves through, under
    Python's own disposition: the truth of what ``__exit__`` returns.
    """
    from sugar_lift_py_tests.outcome.exit_set import Halted, _require_exit_set
    from sugar_lift_py_tests.outcome.resource_bindings import (
        EnterResultBinding,
        ExitFaceBinding,
        ManagerBinding,
        prepend_facts_to_exitset,
    )
    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        face_record,
        halt_record,
        halts_recorded,
        reduce_block_to_exitset,
        resumed,
    )

    def resume(state):
        # A body halt the exit suppresses goes on after the ``with`` from the
        # one record a continuation after a halt starts from (``resumed``).
        return resumed(
            state, ctx, owner="WithReducedManagerSugar.suppressed", blame=resource.site
        )

    # The manager, its enter and its exit are each routed face by face here:
    # a deferred native-operation carrier at any of them is refused by name.
    # A manager call coordinate is not its returned receiver. Perform its
    # source outcome once, preserving exceptional faces before enter. A
    # manager or enter halt is at the head of the ``with``: it carries the
    # record of where it halted (``halts_recorded``).
    # The manager is the ``with``'s header: a walrus bind or callee store its
    # value carried reaches the body by the one header rule
    # (``header_applied``), the stores laid in every arm's record.
    from sugar_lift_py_tests.sugar.function_universe_sugar import header_applied

    headed, manager_out = header_applied(resource, "manager", ctx)
    if headed is not None:
        return headed
    manager_out = _require_exit_set(
        manager_out, owner="WithReducedManagerSugar.manager"
    )
    manager_es = halts_recorded(
        manager_out.and_then(lambda value: _project_manager_receiver(value, ctx)),
        halt_record(ctx),
    )
    parts = []
    for manager_face in manager_es.exits:
        if isinstance(manager_face, Halted):
            parts.append(ExitSet((manager_face,)))
            continue
        manager_facts = ManagerBinding(
            resource.manager_slot_id, manager_face.value
        ).to_facts(site=resource.site)
        enter_es = ExitSet((manager_face,)).and_then(
            lambda manager: halts_recorded(
                _require_exit_set(
                    resource.protocol.enter_resource_outcome_for(manager, ctx),
                    owner="WithReducedManagerSugar.enter",
                ),
                halt_record(ctx),
            )
        )
        for enter_face in enter_es.exits:
            if isinstance(enter_face, Halted):
                parts.append(ExitSet((enter_face,)))
                continue
            entered = enter_face.value
            enter_value = _as_target(_returned_value(entered.enter_value), entered)
            enter_facts = ()
            body_ctx = ctx
            if resource.enter_slot_id is not None and enter_value is not None:
                binding = EnterResultBinding(resource.enter_slot_id, enter_value)
                enter_facts = binding.to_facts(site=resource.site)
                # The body reads ``as x`` as the value ``__enter__`` returned.
                body_ctx = binding.bound_in(ctx)
            # The exit is routed per body face: a body whose carrier
            # ``and_then`` composed is refused by name here.
            body_es = _require_exit_set(
                ExitSet((enter_face,)).and_then(
                    lambda _entered, body_ctx=body_ctx: reduce_block_to_exitset(
                        resource.body, body_ctx
                    )
                ),
                owner="WithReducedManagerSugar.body",
            )
            concrete_exit = getattr(resource.protocol, "exit_outcome_for_body", None)
            # Generator protocols have a linear resume: retain their single
            # existing exit reduction instead of resuming per body face.
            abstract_exit = (
                None
                if concrete_exit is not None
                else _require_exit_set(
                    resource.protocol.exit_outcome_for(entered, ctx),
                    owner="WithReducedManagerSugar.exit",
                )
            )
            for body_face in body_es.exits:
                # ``__exit__`` runs where the body left this face: a body
                # halt's record (``resumed``), or the record the body
                # completed with -- never the context the ``with`` began in.
                # A halt of it that offers no record of its own carries that
                # face's record (``halts_recorded``).
                record = face_record(
                    body_face,
                    owner="WithReducedManagerSugar.exit",
                    blame=resource.site,
                )
                exit_es = halts_recorded(
                    (
                        _require_exit_set(
                            concrete_exit(
                                entered,
                                body_face,
                                resumed(
                                    record,
                                    ctx,
                                    owner="WithReducedManagerSugar.exit",
                                    blame=resource.site,
                                ).context,
                            ),
                            owner="WithReducedManagerSugar.exit",
                        )
                        if concrete_exit is not None
                        else abstract_exit
                    ),
                    record,
                )
                face_facts = ExitFaceBinding.from_body_exit(
                    resource.exit_face_id, body_face
                ).to_facts(site=resource.site, guard=body_face.guard)
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
                        resume=resume,
                    )
                else:
                    routed = ExitSet((body_face,)).and_exit_truthiness(
                        _exit_return_values(exit_es),
                        site=resource.site,
                        resume=resume,
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
            owner="WithReducedManagerSugar.desugar",
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
            blame="WithReducedManagerSugar.manager",
            owner="WithReducedManagerSugar.manager",
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
    if not callable(getattr(value, "project_operation_receiver_outcome", None)):
        # A value with no retained completion to project is its own receiver.
        return ExitSet.completed(value)
    from sugar_lift_py_tests.outcome.exit_set import _require_exit_set

    projected = _require_exit_set(
        value.project_operation_receiver_outcome(
            ctx, owner="WithReducedManagerSugar.manager"
        ),
        owner="WithReducedManagerSugar.manager",
    )
    return projected.and_then(
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


def _as_target(enter_value, entered):
    """What the body reads ``as x`` as: the value ``__enter__`` returned.

    A ``return`` hands its caller the value by binding
    (``ReturnSugar``, ``object_identity.arrived``): an object the frame
    returns is not current in the caller.  ``return self`` returns the
    manager itself, and the ``with`` already holds that object as
    ``__enter__`` left it (``EnteredManagerStateValue.receiver_state``,
    the receiver with the method's stores applied), with the currency it
    has in this frame: nothing runs between ``__enter__``'s return and the
    body's first statement, and no source name but ``as x`` holds the
    manager.  So a returned value that is the receiver -- the same object
    coordinate (``identity``) and the same contents, compared as values
    (``ObjectValue``'s equality reads neither ``allocation`` nor
    ``arrival``) -- is ``receiver_state``.  Anything else ``__enter__``
    returned is the value it returned, as it arrived."""
    from sugar_lift_py_tests.floor.object_value import ObjectValue

    receiver = getattr(entered, "receiver_state", None)
    if (
        isinstance(receiver, ObjectValue)
        and type(enter_value) is type(receiver)
        and enter_value.identity
        and enter_value == receiver
    ):
        return receiver
    return enter_value


def _exit_return_values(exit_es, *, owner="WithReducedManagerSugar.exit-return"):
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
        guard; ``and_then`` conjoins the face's guard, faces and ``owed``
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

    result = exit_es.and_then(returns)
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
