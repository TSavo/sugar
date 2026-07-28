"""A function definition, lowered to its universe.

This is the SPINE the whole tree lift stands on. `FunctionDef.sugar()` (on the
AST node) constructs one of these WITH the already-built sugars of its body
statements; `desugar` reduces that body in order into a `BlockValue` record and
wraps it in a `UniverseValue`. The universe's `invs()` are the stated facts the
body emits; its `post()` is the exit constraint `out == <term>` -- the callee
contract a caller's INV discharges against.

Meaning-only, node-constructed: no `owns`, no `new`, no catalog, no SugarBody.
The block reduction here is the factory's `_collect_iterative` (block_sugar.py)
with the one factory coupling removed -- it reduces each statement by calling
`.desugar(ctx)` directly instead of through a SugarBody wrapper. The floor
values it produces (BlockValue, UniverseValue, and every entry's
inv_contribution/post_contribution) are pure meaning and are reused verbatim.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.floor import BlockValue
from sugar_lift_py_tests.floor.universe_value import UniverseValue
from sugar_lift_py_tests.outcome import (
    Complete,
    Completed,
    ExitSet,
    Halted,
    Incomplete,
    Outcome,
    true_guard,
)
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class _ReducedBlock:
    entries: tuple[object, ...]
    can_fall_through: bool
    fall_through: tuple
    transforms: tuple = ()
    context: object = dataclass_field(default=None, compare=False, repr=False)


def _extend_receiver_store_scope(value, ctx):
    """Thread statement-owned rebinds: Floor ``extend_scope`` only.

    The reducer does not probe capability, ladder rebind kinds, or mint root
    contexts.  Default FloorValue.extend_scope is identity; Floors that rebind
    (ScopeRebind, ReceiverFieldStoreValue, …) own their own root-context mint
    when ``ctx`` is absent.  ``value`` is an Outcome (Complete/Incomplete) or a
    FloorValue — both expose Floor-owned ``extend_scope``.
    """
    return value.extend_scope(ctx)


def _enrol_exit_obligations(exits: ExitSet) -> ExitSet:
    """Move every arm's pending obligations INTO that arm's block record.

    THE NAMED CONSUMPTION. ``Completed.pending_contracts`` and
    ``Halted.pending_contracts`` are in-flight carriers: they conserve an
    obligation through the exit algebra, but nothing downstream of the algebra
    reads them, so an arm that still owed something when the block finished had
    its obligation vanish at this boundary -- conserved for the whole flight and
    dropped on landing. Enrolment is what makes it discharged rather than
    forgotten: ``entry.contribution()`` is the same one-row-per-demand split a
    completed carrier goes through, and the rows join the block's entries, where
    ``link_unit_projection`` enrols them for the linker.

    The field is CLEARED as the rows are appended. That is what makes this a
    consumption and not a duplication: the obligation exists in exactly one
    place afterwards.

    THIS IS ALSO THE ONE MINT. An arm carries its obligations as they were
    incurred; the arm's ``guard`` is the face they are owed on, so `guard -> D`
    is minted here, once, against the guard the arm finally holds. An arm under
    the true guard owes the bare obligation and is not re-minted at all.

    An arm with no block to enrol into (a halted arm whose state is ``None``)
    stays LOUD, and the gap belongs to the PRODUCER that built it, not here.
    Every composition that fans a halt across incoming arms -- ``and_finally``
    over a cleanup halt, ``and_exit`` over an exit-expression halt,
    ``outcome_to_exitset`` over an ``Incomplete`` -- can emit a halted arm whose
    ``state`` is ``None``, and an obligation incurred on the path that reached
    it then has no record to be owed on.

    Two things that look like answers are not. Splicing the enclosing block's
    prefix onto such an arm is sound about what happened but changes what
    ``state is None`` MEANS: ``exit_disposition._boundary_halted_edge`` reads it
    as "the reducer omitted the real pre-halt state" and refuses on it, so
    supplying a record here would silence that refusal for exactly the arms that
    owe. Synthesising a record whose entries are only the demand rows is worse
    -- it asserts a temporal record where the producer said there was none.
    Measured: it is one row on pandas `core/reshape/pivot.py:284` (two demands
    from `pivot.py:327:19`, the `data[to_filter]` subscript on a formal), and
    one loud row naming the producer is the honest answer until the producer
    carries the record.
    """
    if not any(exit_.pending_contracts for exit_ in exits.exits):
        # The overwhelmingly common case, and it must cost nothing: this runs at
        # the end of EVERY block reduction, nested ones included, and rebuilding
        # the set would pay for a second `normalize` over every arm of every
        # block that never owed anything.
        return exits

    from sugar_lift_py_tests.caller_parameter_contract import weaken_pending
    from sugar_lift_py_tests.gap.info import GapKind
    from sugar_lift_py_tests.gap.panic import construction_panic_gap
    from sugar_lift_py_tests.outcome.exit_set import _is_true

    enrolled: list[object] = []
    for exit_ in exits.exits:
        if not exit_.pending_contracts:
            enrolled.append(exit_)
            continue
        owed = (
            exit_.pending_contracts
            if _is_true(exit_.guard)
            else weaken_pending(exit_.pending_contracts, exit_.guard)
        )
        rows = tuple(row for entry in owed for row in entry.contribution())
        block = exit_.value if isinstance(exit_, Completed) else exit_.state
        if not isinstance(block, _ReducedBlock):
            construction_panic_gap(
                owner="reduce_block_to_exitset.enrol_exit_obligations",
                blame=exit_.pending_contracts[0].source_node,
                observed=(
                    "a block exit owing "
                    + ", ".join(
                        demand.demand_cid
                        for entry in exit_.pending_contracts
                        for demand in entry.demands
                    )
                    + f" carries {type(block).__name__} where its reduced block "
                    "record should be, so there is nothing to enrol the "
                    "obligation into"
                ),
                requested="a reduced block record on every exit that owes",
                fix=(
                    "carry the reduced block on this arm, or hand the obligation "
                    "to the producer that does; never drop it and never enrol it "
                    "on a block that did not run"
                ),
                gap_kind=GapKind.FLOOR,
            )
        widened = _ReducedBlock(
            (*block.entries, *rows),
            block.can_fall_through,
            block.fall_through,
            block.transforms,
            block.context,
        )
        if isinstance(exit_, Completed):
            enrolled.append(Completed(exit_.guard, widened, exit_.faces, ()))
        else:
            enrolled.append(Halted(exit_.guard, exit_.effect, widened, exit_.faces, ()))
    return ExitSet(tuple(enrolled)).normalize()


def _prefixed(state: _ReducedBlock, inner: object) -> object:
    """The temporal state of a halt INSIDE a nested statement, read from outside.

    ``inner`` is what the nested reduction reached before halting; ``state`` is
    everything this block had already established when the statement began.
    Python never rolls back what already happened, so the halt arm carries both,
    in order. A nested state with no ``entries`` (a non-block payload) is left
    alone -- there is nothing to splice onto.

    Identity law (R1): when the prefix contributes nothing (no entries, no
    transforms), the nested record already IS the complete temporal state.
    Return it by object identity — do not re-seat an ``==``-equal
    ``_ReducedBlock``. Re-seating broke unmatched WithEffectBoundarySugar
    residuals (``face.state is halted.state``) while try/except ``and_exit`` and
    NeverSuppresses correctly retained ``is``.
    """
    entries = getattr(inner, "entries", None)
    if entries is None:
        return inner
    if not state.entries and not state.transforms and isinstance(inner, _ReducedBlock):
        # Empty prefix: retain the nested pre-halt record as the same cell.
        return inner
    for transform in reversed(state.transforms):
        entries = transform(entries)
    return _ReducedBlock(
        (*state.entries, *entries),
        getattr(inner, "can_fall_through", False),
        (),
        state.transforms,
        getattr(inner, "context", state.context),
    )


def _halt_state(state: _ReducedBlock, exit_) -> object:
    """The temporal record a halted arm of a nested statement carries.

    Normally ``_prefixed``: the nested reduction's own record with this block's
    prefix spliced in front. A nested payload that is not a block record has
    nothing to splice onto and is left alone -- ``outcome_to_exitset`` converts
    an ``Incomplete`` to ``Halted(guard, effect, None)`` because that conversion
    has no record to offer, and ``and_finally`` / ``and_exit`` fan cleanup and
    exit halts across incoming arms the same way.

    A stateless halt that OWES is the one case where ``None`` is not an answer.
    The obligation was incurred on the path that reached the halt, and
    ``_enrol_exit_obligations`` needs a record to enrol it into. The prefix IS
    that record: an arm with no nested record halted at the top of this
    statement, so everything this block had established when the statement began
    is the complete temporal record for that path. Nothing is invented -- the
    prefix genuinely happened.

    WHY THIS DOES NOT WEAKEN THE BOUNDARY REFUSAL.
    ``exit_disposition._boundary_halted_edge`` reads ``state is None`` as "the
    reducer omitted the real pre-halt state" and refuses on it, so supplying a
    record where that check will see one would silence it. It will not see this
    one: that check runs inside ``ExitSet.and_exit``, during the statement's own
    ``head.desugar(ctx)``, which is UPSTREAM of this seam. By the time a
    statement hands its ExitSet back here, its boundary edges are already
    decided.

    Narrow on purpose. An arm that owes nothing keeps exactly the state it had,
    so no existing temporal testimony moves; this supplies a record only where
    one is now required and was previously absent. Measured on the 22-file
    pandas 3.0.3 slice: with this, `pivot.py:536` and `format.py:1620` enrol and
    drain; without it, all three sites merely change owner from
    `ContractConditionalConstructionV1.and_then` to this module's refusal, which
    is reattribution, not a drain.
    """
    spliced = _prefixed(state, exit_.state)
    if exit_.pending_contracts and not isinstance(spliced, _ReducedBlock):
        return state
    return spliced


def reduce_block_to_exitset(
    statements: tuple, ctx: object = None
) -> ExitSet[_ReducedBlock]:
    """Reduce a suite to guarded exits before the linear compatibility view."""
    exits = ExitSet.completed(
        _ReducedBlock(entries=(), can_fall_through=True, fall_through=(), context=ctx)
    )

    for index, head in enumerate(statements):

        def reduce_next(state: _ReducedBlock) -> ExitSet[_ReducedBlock]:
            if not state.can_fall_through:
                # A terminal Completed face (return, including return from
                # finally) owns the exit.  It is completed rather than halted,
                # but its source tail is unreachable and must not be reduced
                # into a contradictory second post-state.
                return ExitSet.completed(state)
            active_ctx = state.context if state.context is not None else ctx
            statement_ctx = active_ctx
            # ObservedEffectBinding rows are producer testimony for a consumed
            # slot (Try/With routing). Thread them into the next statement's
            # reduction context so EffectRef / ObservationRef project the same
            # RaiseEffect the boundary routed — not a pure unauthenticated
            # coordinate. Handler bodies also receive this via
            # TrySugar.with_observed_effect before their first statement.
            from sugar_lift_py_tests.effect_router import ObservedEffectBinding

            observed = tuple(
                entry
                for entry in state.entries
                if isinstance(entry, ObservedEffectBinding)
            )
            if observed:
                from sugar_lift_py_tests.context import ReduceContext

                statement_ctx = (
                    ReduceContext.root(owner="reduce_block_to_exitset")
                    if statement_ctx is None
                    else ReduceContext.derived(
                        statement_ctx, owner="reduce_block_to_exitset"
                    )
                )
                for binding in observed:
                    statement_ctx = statement_ctx.with_observed_effect(
                        binding.slot_id, binding.effect
                    )
            outcome = head.desugar(statement_ctx)
            from sugar_lift_py_tests.floor.guarded_faces import GuardedFaces

            def project(value):
                if isinstance(value, _ReducedBlock):
                    contribution = value.entries
                    continues = value.can_fall_through
                    nested_fall_through = value.fall_through
                    nested_transforms = value.transforms
                    next_context = (
                        value.context if value.context is not None else active_ctx
                    )
                else:
                    linear = Complete(value)
                    contribution = linear.contribution()
                    follow = linear.follow()
                    continues = follow.continues
                    nested_fall_through = (
                        ()
                        if follow.continuation_guard is None
                        else (follow.continuation_guard,)
                    )
                    nested_transforms = (
                        () if follow.transform is None else (follow.transform,)
                    )
                    next_context = _extend_receiver_store_scope(linear, active_ctx)
                for transform in reversed(state.transforms):
                    contribution = transform(contribution)
                entries = (*state.entries, *contribution)
                if not continues:
                    return ExitSet.completed(
                        _ReducedBlock(entries, False, (), context=next_context)
                    )
                return ExitSet.completed(
                    _ReducedBlock(
                        entries,
                        True,
                        (*state.fall_through, *nested_fall_through),
                        (*state.transforms, *nested_transforms),
                        next_context,
                    )
                )

            from sugar_lift_py_tests.caller_parameter_contract import (
                NativeOperationExitCarrierV1,
                ReducerPreEffectStateV1,
            )

            if isinstance(outcome, NativeOperationExitCarrierV1):
                # A formal native operation is neither a completion nor a halt
                # until an authenticated caller supplies its actual operands.
                # Retain the ordinary statement projection as a continuation;
                # discharge will feed its Completed face through this exact
                # block seam, while its Halted face bypasses the tail.
                return outcome.and_then(
                    project,
                    pre_effect_state=ReducerPreEffectStateV1._from_reducer(state),
                )

            if (
                isinstance(outcome, Complete)
                and isinstance(outcome.value, GuardedFaces)
                and any(
                    isinstance(entry, Incomplete)
                    for entry in outcome.value.contribution()
                )
            ):
                faces = outcome.value
                entries = []
                exits = []
                for entry in faces.contribution():
                    if isinstance(entry, Incomplete):
                        # A store inside a guarded face is NOT re-split here.
                        # The branch body was already reduced by
                        # reduce_block_to_exitset, so the store's success/halt
                        # partition has already happened; IfSugar then absorbs
                        # each halted arm as guarded red testimony (if_sugar.py,
                        # `Incomplete(exit_.effect).guarded(exit_.guard)`), the
                        # same seam every halt inside an `if` goes through.
                        # Splitting again here would emit the same occurrence
                        # twice.
                        if entry.follow().continues:
                            entries.append(entry)
                            continue
                        from sugar_lift_py_tests.ir import and_

                        guard = (
                            entry.branch_conditions[0]
                            if len(entry.branch_conditions) == 1
                            else and_(list(entry.branch_conditions))
                        )
                        exits.append(Halted(guard, entry.effect, state))
                    else:
                        entries.append(entry)
                completed_state = _ReducedBlock(
                    (*state.entries, *entries),
                    faces.can_fall_through,
                    (),
                    state.transforms,
                    active_ctx,
                )
                if faces.can_fall_through:
                    exits.append(
                        Completed(
                            (
                                faces.continuation_guard
                                if faces.continuation_guard is not None
                                else true_guard()
                            ),
                            completed_state,
                        )
                    )
                return ExitSet(tuple(exits)).normalize()
            if isinstance(outcome, ExitSet):
                if state.fall_through:
                    from sugar_lift_py_tests.ir import and_

                    continuation = (
                        state.fall_through[0]
                        if len(state.fall_through) == 1
                        else and_(list(state.fall_through))
                    )
                    outcome = outcome.guarded(continuation)

                # A statement that reduces to its OWN ExitSet (a nested block:
                # try/with, or an unpack assignment whose store leaves are
                # sequenced by this same reducer) hands back halted arms whose
                # state is the state reached INSIDE that statement. It cannot
                # know the prefix -- `head.desugar(ctx)` is given no state -- so
                # the prefix is spliced on here, at the one seam that owns
                # sequencing. Without this, a halt inside a nested statement
                # would report an empty temporal state and every earlier store
                # would read as rolled back, which is exactly the law the store
                # partition above exists to state.
                outcome = ExitSet(
                    tuple(
                        (
                            Halted(
                                exit_.guard,
                                exit_.effect,
                                _halt_state(state, exit_),
                                # This rebuild used to state three fields, so it
                                # dropped BOTH the arm's partition testimony and
                                # its pending obligations on the way through --
                                # the same shape of loss `ExitSet.guarded` had.
                                exit_.faces,
                                exit_.pending_contracts,
                            )
                            if isinstance(exit_, Halted)
                            else exit_
                        )
                        for exit_ in outcome.exits
                    )
                )
                return outcome.and_then(project)
            contribution = outcome.contribution()
            for transform in reversed(state.transforms):
                contribution = transform(contribution)
            entries = (*state.entries, *contribution)
            next_context = _extend_receiver_store_scope(outcome, active_ctx)

            follow = outcome.follow()
            if follow.continues and follow.halt_guard is not None:
                # A store: runtime-selected success/halt over ONE authenticated
                # occurrence coordinate.
                #
                # Halted arm carries `state` -- the PREFIX. Every earlier
                # binding and every earlier store survives on it (Python never
                # rolls back an assignment that already happened), and this
                # store's own completion testimony is absent from it, because
                # this store did not complete.
                #
                # Completed arm carries `entries` -- the prefix PLUS this
                # store's red testimony. Only this arm is fed to the tail by
                # `ExitSet.sequence`, so no later target can execute after an
                # earlier store halt.
                from sugar_lift_py_tests.outcome.exit_set import complement_guard

                return ExitSet(
                    (
                        Halted(follow.halt_guard, outcome.effect, state),
                        Completed(
                            complement_guard(follow.halt_guard),
                            _ReducedBlock(
                                entries,
                                True,
                                state.fall_through,
                                state.transforms,
                                next_context,
                            ),
                        ),
                    )
                ).normalize()
            if not follow.continues:
                if isinstance(outcome, Incomplete):
                    if outcome.branch_conditions:
                        from sugar_lift_py_tests.ir import and_

                        condition = (
                            outcome.branch_conditions[0]
                            if len(outcome.branch_conditions) == 1
                            else and_(list(outcome.branch_conditions))
                        )
                        return ExitSet.conditional_halt(
                            condition, outcome.effect, state
                        )
                    return ExitSet.halted(outcome.effect, state=state)
                return ExitSet.completed(
                    _ReducedBlock(
                        entries,
                        can_fall_through=False,
                        fall_through=(),
                        context=next_context,
                    )
                )

            transforms = state.transforms
            if follow.transform is not None:
                transforms = (*transforms, follow.transform)
            fall_through = state.fall_through
            if follow.continuation_guard is not None:
                fall_through = (*fall_through, follow.continuation_guard)
            return ExitSet.completed(
                _ReducedBlock(entries, True, fall_through, transforms, next_context)
            )

        from sugar_lift_py_tests.caller_parameter_contract import (
            NativeOperationExitCarrierV1,
        )

        if isinstance(exits, NativeOperationExitCarrierV1):
            exits = exits.and_then(reduce_next)
        elif (
            len(exits.exits) == 1
            and isinstance(exits.exits[0], Completed)
            and exits.exits[0].guard == true_guard()
            and not exits.exits[0].faces
            and not exits.exits[0].pending_contracts
        ):
            # The straight-line singleton is the only ExitSet face that can
            # become a deferred native-operation carrier without needing a
            # guarded carrier algebra. Preserve it directly. Branching paths
            # continue through ExitSet.sequence and remain loud if they try to
            # smuggle an undischarged carrier through a guard.
            exits = reduce_next(exits.exits[0].value)
        else:
            # A completed prefix may expose a deferred native operation. Keep
            # that carrier outside ExitSet until caller actuals discharge it;
            # ExitSet.sequence must only ever receive concrete ExitSets.
            exits = NativeOperationExitCarrierV1.compose_prefix(exits, reduce_next)

    # The block boundary is where an obligation stops being in flight, so it is
    # the one door that consumes the carriers. Doing it here rather than per
    # statement keeps a single owner and lets `sequence` compose obligations
    # across statements first.
    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )

    if isinstance(exits, NativeOperationExitCarrierV1):
        return exits
    from sugar_lift_py_tests.sugar.exit_set_routing import promote_raise_halts

    return _enrol_exit_obligations(promote_raise_halts(exits))


def reduce_statements(statements: tuple, ctx: object = None):
    """Return the legacy tuple only after ExitSet proves one unconditional exit."""
    collapsed = reduce_block_to_exitset(statements, ctx).collapse()
    if isinstance(collapsed, Incomplete):
        return ((collapsed,), False, ())
    if not isinstance(collapsed, Complete):
        return collapsed
    state = collapsed.value
    return state.entries, state.can_fall_through, state.fall_through


def reduce_body(statements: tuple, ctx: object = None):
    """Reduce a function body to ONE Outcome, preserving Complete/Incomplete.

    A body that reduces to a value is `Complete(BlockValue(record))` -- the
    record carries every entry, including any halting effect absorbed as red
    testimony (Incomplete.contribution is the effect itself). A body that
    reduces to a bare, non-absorbed effect stays `Incomplete` and propagates:
    the caller wraps via `.and_then`, so an effect never becomes a false
    universe. Today no written statement sugar throws an effect, so this is
    always Complete -- the distinction is carried structurally for the sugars
    (calls, unsupported statements) that will.
    """
    exits = reduce_block_to_exitset(statements, ctx)
    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )

    if isinstance(exits, NativeOperationExitCarrierV1):
        return exits.and_then(
            lambda state: Complete(
                BlockValue(
                    state.entries,
                    fall_through=state.fall_through,
                    can_fall_through=state.can_fall_through,
                )
            )
        )
    if (
        len(exits.exits) == 1
        and isinstance(exits.exits[0], Halted)
        and exits.exits[0].guard == true_guard()
        and exits.exits[0].state is not None
    ):
        # Incomplete has no temporal-state slot. Keep the authenticated halt
        # face intact rather than laundering its pre-effect state through a
        # representation that cannot carry it.
        return exits
    collapsed = exits.collapse()
    if isinstance(collapsed, Incomplete):
        return collapsed
    if not isinstance(collapsed, Complete):
        return exits.and_then(
            lambda state: Complete(
                BlockValue(
                    state.entries,
                    fall_through=state.fall_through,
                    can_fall_through=state.can_fall_through,
                )
            )
        )
    state = collapsed.value
    entries = state.entries
    # A body that is nothing but a single propagating effect IS that effect --
    # there is no value, no fact, no exit to make a contract from. Propagate it
    # so the def surfaces as an effect (a halt), never a None-returning contract.
    if len(entries) == 1 and isinstance(entries[0], Incomplete):
        return entries[0]
    return Complete(
        BlockValue(
            entries,
            fall_through=state.fall_through,
            can_fall_through=state.can_fall_through,
        )
    )


@dataclass(frozen=True)
class FunctionUniverseSugar(Sugar):
    """`def <name>(<formals>): <body>` -> the body's universe.

    Constructed by `FunctionDef.sugar()` with the body statements ALREADY
    reduced to their own sugars (child-before-parent). `desugar` reduces the
    block and wraps it; the universe projects invs/post off the record.
    """

    name: str
    formals: tuple[str, ...]
    statements: tuple  # the body statements' sugars, in source order
    site: object = dataclass_field(compare=False, default=None)
    bridge_source_symbol: str | None = None
    substitution_trace: object | None = dataclass_field(compare=False, default=None)
    formal_coordinates: tuple = ()

    @classmethod
    def witnesses(cls):
        # A function whose body returns its argument; the caller asserts the
        # returned value. The truthful twin's universe post (out == z) discharges
        # the assert; the lying twin's asserted value contradicts it.
        prefix = "def A(z):\n    return z\n\n"
        return _call_pair(
            name="function_universe",
            owner_sugar="FunctionUniverseSugar",
            truthful=prefix + "def test_a():\n    assert A(2) == 2\n",
            lying=prefix + "def test_a():\n    assert A(2) == 3\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        # No temporal name map and no ambient effect auth. The body was already
        # SUBSTITUTED (FunctionDef.sugar): formals stay free Vars; as-bindings
        # are EffectRef/ObservationRef coordinates. Routing deposits
        # EffectBinding facts into the same record as other testimony.
        del ctx
        return reduce_body(self.statements).and_then(
            lambda record: Complete(
                UniverseValue(
                    name=self.name,
                    formals=self.formals,
                    record=record,
                    bridge_source_symbol=self.bridge_source_symbol,
                    formal_coordinates=self.formal_coordinates,
                )
            )
        )

    def context_manager_edges(self) -> tuple:
        """Project already-constructed CM edges without re-entering the tree."""
        from dataclasses import fields, is_dataclass

        edges = []
        stack = list(reversed(self.statements))
        seen = set()
        while stack:
            sugar = stack.pop()
            marker = id(sugar)
            if marker in seen:
                continue
            seen.add(marker)
            edge = getattr(sugar, "context_manager_edge", None)
            if edge is not None:
                edges.append(edge)
            if not is_dataclass(sugar):
                continue
            for field in reversed(fields(sugar)):
                if field.name in {
                    "site",
                    "contract_ref",
                    "context_manager_edge",
                }:
                    continue
                value = getattr(sugar, field.name)
                if isinstance(value, Sugar):
                    stack.append(value)
                elif isinstance(value, tuple):
                    stack.extend(
                        reversed(
                            tuple(item for item in value if isinstance(item, Sugar))
                        )
                    )
        return tuple(edges)
