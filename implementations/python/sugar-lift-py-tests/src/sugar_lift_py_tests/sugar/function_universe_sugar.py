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
    Completed,
    ExitSet,
    Halted,
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
    # The live reducer context the block was reduced under: a lookup aid a
    # continuation reads bindings OUT of, never testimony (it is already out of
    # equality). ``entries`` and ``fall_through`` are the block's content.
    context: object = dataclass_field(
        default=None, compare=False, repr=False, metadata={"testimony": "lookup"}
    )


def _extend_receiver_store_scope(value, ctx):
    """Thread statement-owned rebinds: Floor ``extend_scope`` only.

    The reducer does not probe capability, ladder rebind kinds, or mint root
    contexts.  Default FloorValue.extend_scope is identity; Floors that rebind
    (ScopeRebind, ReceiverFieldStoreValue, …) own their own root-context mint
    when ``ctx`` is absent.  ``value`` is the completed arm's FloorValue, which
    owns ``extend_scope``.
    """
    return value.extend_scope(ctx)


def plain_completed_value(outcome):
    """The value of ONE plain completed arm, else ``None``.

    Plain: one completed arm under truth, carrying no partition faces and owing
    nothing -- the arm a total step answers. Its value may be handed on alone.
    An arm with faces or debts is sequenced instead, so the sequencing carries
    them onto every continuation (``owed`` is never dropped). A deferred
    native-operation carrier is not an ``ExitSet`` and answers ``None``. A
    set of several arms answers ``None`` before anything normalizes it.
    """
    if not isinstance(outcome, ExitSet) or len(outcome.exits) != 1:
        return None
    arm = outcome.exits[0]
    if arm.faces or arm.owed:
        return None
    return outcome.completed_value()


def _plain_halt(outcome: ExitSet):
    """The effect of ONE plain halted arm that carries no state, else ``None``.

    Plain: one halted arm under truth, no partition faces, owing nothing, and
    no temporal state of its own -- a halt at the head of the statement, whose
    pre-halt state is the enclosing block's prefix.
    """
    if len(outcome.exits) != 1:
        return None
    arm = outcome.exits[0]
    if (
        isinstance(arm, Halted)
        and arm.guard == true_guard()
        and arm.state is None
        and not arm.faces
        and not arm.owed
    ):
        return arm.effect
    return None


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
    nothing to splice onto and is left alone -- ``ExitSet.halted(effect)``
    builds ``Halted(guard, effect, None)`` because its producer has no record
    to offer, and ``and_finally`` / ``and_exit`` fan cleanup and exit halts
    across incoming arms the same way.
    """
    return _prefixed(state, exit_.state)


def _is_return_entry(entry) -> bool:
    """A record entry that is a ``return`` (guarded by its arm or not)."""
    from sugar_lift_py_tests.floor.guarded_return import GuardedReturn
    from sugar_lift_py_tests.floor.return_value import ReturnValue

    return isinstance(entry, (GuardedReturn, ReturnValue))


def _prior_return_face(state, ctx) -> tuple:
    """The completed exit an earlier guarded ``return`` already took.

    After ``if c: return v`` the block goes on only under the fall-through
    guard.  A later statement that halts, or that reduces to its own exits,
    is guarded by it.  Where that guard fails, the function already returned,
    and that completed exit, with its tail unreachable, must stay beside the
    later statement's faces.  Dropping it made ``if c: return 7`` followed by
    ``raise`` claim the function always raised.
    """
    if not state.fall_through or not any(
        _is_return_entry(entry) for entry in state.entries
    ):
        return ()
    from sugar_lift_py_tests.ir import and_
    from sugar_lift_py_tests.outcome.exit_set import complement_guard

    continuation = (
        state.fall_through[0]
        if len(state.fall_through) == 1
        else and_(list(state.fall_through))
    )
    return (
        Completed(
            complement_guard(continuation),
            _ReducedBlock(state.entries, False, (), state.transforms, ctx),
        ),
    )


def reduce_block_to_exitset(
    statements: tuple, ctx: object = None
) -> ExitSet[_ReducedBlock]:
    """Reduce a suite to guarded exits before the linear compatibility view."""
    if ctx is None:
        from sugar_lift_py_tests.context import ReduceContext

        ctx = ReduceContext.root(owner="reduce_block_to_exitset")
    exits = ExitSet.completed(
        _ReducedBlock(entries=(), can_fall_through=True, fall_through=(), context=ctx)
    )

    for index, head in enumerate(statements):

        def reduce_next(
            state: _ReducedBlock, *, statement=head
        ) -> ExitSet[_ReducedBlock]:
            # A native-operation carrier may retain this callback until after
            # the outer reducer loop advances. Bind the current statement now;
            # a late-bound ``head`` skips the deferred tail to the final node.
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
            outcome = statement.desugar(statement_ctx)

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
                    # The value owns its contribution, its follow and its scope.
                    contribution = value.contribution()
                    follow = value.follow_rest()
                    continues = follow.continues
                    nested_fall_through = (
                        ()
                        if follow.continuation_guard is None
                        else (follow.continuation_guard,)
                    )
                    nested_transforms = (
                        () if follow.transform is None else (follow.transform,)
                    )
                    next_context = _extend_receiver_store_scope(value, active_ctx)
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
                # Enroll this block's reducer state only once. A callee that
                # already enrolled at the lookup (stringify_exception at
                # exc.message) keeps that inner state; this caller omits a
                # second conflicting enrollment and only appends project.
                if outcome.pre_effect_state is not None:
                    return outcome.and_then(project)
                return outcome.and_then(
                    project,
                    pre_effect_state=ReducerPreEffectStateV1._from_reducer(state),
                )

            plain = plain_completed_value(outcome)
            if plain is not None and not isinstance(plain, _ReducedBlock):
                # One plain completion: the statement's value carries the block
                # straight on. The value owns its contribution, its follow and
                # its scope (``project``); the fall-through guard stays in the
                # record, where every earlier statement left it. A store is not
                # split here: its producer answers its two faces
                # (``store_faces``), and they arrive through the seam below.
                return project(plain)

            effect = _plain_halt(outcome)
            if effect is not None:
                # One plain halt at the statement: nothing ran inside it before
                # the halt, so its pre-halt state is this block's prefix.
                halted = ExitSet.halted(effect, state=state)
                returned = _prior_return_face(state, active_ctx)
                if returned:
                    # Reached only where no earlier ``return`` fired.
                    from sugar_lift_py_tests.ir import and_

                    continuation = (
                        state.fall_through[0]
                        if len(state.fall_through) == 1
                        else and_(list(state.fall_through))
                    )
                    return ExitSet(
                        (*halted.guarded(continuation).exits, *returned)
                    ).normalize()
                return halted

            returned = _prior_return_face(state, active_ctx)
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
            # would read as rolled back (Python never rolls back a store).
            head_halt = getattr(statement, "halts_at_statement_head", False)
            outcome = ExitSet(
                tuple(
                    (
                        Halted(
                            exit_.guard,
                            exit_.effect,
                            # A simple statement binds nothing before its
                            # own halt (an expression halt, a store's
                            # halted face): a stateless arm halted at its
                            # head, where the prefix is the whole record --
                            # the same state the plain halt above gives.
                            state
                            if head_halt and exit_.state is None
                            else _halt_state(state, exit_),
                            # This rebuild used to state three fields, so it
                            # dropped the arm's partition testimony on the way
                            # through -- the same shape of loss
                            # `ExitSet.guarded` had.
                            exit_.faces,
                            exit_.owed,
                        )
                        if isinstance(exit_, Halted)
                        else exit_
                    )
                    for exit_ in outcome.exits
                )
            )
            composed = outcome.sequence(project)
            if returned:
                return _beside_prior_returns(composed, returned)
            return composed

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
            # Handing the value alone to the next statement would drop what
            # the arm owes; an owing arm sequences like any other.
            and not exits.exits[0].owed
        ):
            # The straight-line singleton is the only ExitSet face that can
            # become a deferred native-operation carrier without needing a
            # guarded carrier algebra. Preserve it directly. Branching paths
            # continue through ExitSet.sequence and remain loud if they try to
            # smuggle an undischarged carrier through a guard.
            exits = reduce_next(exits.exits[0].value)
        else:
            # A completed prefix may expose a deferred native operation.
            # ``sequence`` keeps that carrier outside ExitSet until caller
            # actuals discharge it; no ExitSet ever holds a carrier as an arm.
            exits = exits.sequence(reduce_next)

    # The block boundary is where an obligation stops being in flight, so it is
    # the one door that consumes the carriers. Doing it here rather than per
    # statement keeps a single owner and lets `sequence` compose obligations
    # across statements first.
    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )

    if isinstance(exits, NativeOperationExitCarrierV1):
        return exits
    # No completed record holds a halt (#7826): every halt is already a halted
    # arm, so there is nothing to promote out of a record here.
    return exits


def _beside_prior_returns(composed, returned: tuple):
    """``composed`` with the faces of every earlier ``return`` beside it.

    ``composed`` is what ``ExitSet.sequence`` answered for a statement. A
    continuation still waiting on its caller's actuals keeps waiting: the
    returned faces join its exits once it discharges (``after_discharge``);
    no arm is read off an undischarged carrier.
    """
    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )
    from sugar_lift_py_tests.outcome.exit_set import _require_exit_set

    def beside(continued):
        exits = _require_exit_set(
            continued, owner="reduce_block_to_exitset.prior-returns"
        )
        return ExitSet((*exits.exits, *returned)).normalize()

    if isinstance(composed, NativeOperationExitCarrierV1):
        return composed.after_discharge(beside)
    return beside(composed)


def reduce_body(statements: tuple, ctx: object = None):
    """Reduce a function body to ONE ``ExitSet`` of the body's exits.

    Every completed arm becomes `BlockValue(record)` -- the record carries
    every entry the arm reached. Every halted arm is kept as it is, with its
    guard, its pre-halt state and what it owes: the caller wraps via
    `.and_then`, so a halt never becomes a false universe.
    """
    exits = reduce_block_to_exitset(statements, ctx)
    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )

    def block_value(state):
        return ExitSet.completed(
            BlockValue(
                state.entries,
                fall_through=state.fall_through,
                can_fall_through=state.can_fall_through,
            )
        )

    if isinstance(exits, NativeOperationExitCarrierV1):
        return exits.and_then(block_value)
    return exits.sequence(block_value)


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

    def desugar(self, ctx: object = None) -> ExitSet:
        # The body was already SUBSTITUTED (FunctionDef.sugar): ordinary
        # formals stay free Vars; as-bindings are EffectRef/ObservationRef
        # coordinates.  A class-owned initializer additionally carries one
        # ConstructedReceiverRef coordinate, and its enumeration entrance seats
        # that exact receiver in ``ctx``.  Threading the producer-owned context
        # here lets the existing block reducer resolve it; callers without such
        # authority continue to pass ``None`` and retain the ordinary behavior.
        return reduce_body(self.statements, ctx).and_then(
            lambda record: ExitSet.completed(
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
