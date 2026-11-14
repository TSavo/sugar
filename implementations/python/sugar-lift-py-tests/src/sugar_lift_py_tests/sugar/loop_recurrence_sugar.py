from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.floor import SymbolicValue
from sugar_lift_py_tests.ir import atomic, ctor, not_, str_const
from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar


def _is_authenticated_stop_iteration(effect) -> bool:
    """Iterator exhaustion only by authenticated ``StopIteration`` type coordinate.

    The kit's ``next`` producer mints ``exception_type_coordinate``. Display
    spelling of ``exception_name`` is never consulted: a foreign coordinate
    wearing the same name is not exhaustion, and a RaiseEffect that omitted
    its coordinate is unwritten work (throw), not a name-based guess.
    """
    from sugar_lift_py_tests.floor.ground_exit import _builtin_exception_identity
    from sugar_source_tree.panic import SugarNotWritten

    owner = "LoopRecurrenceSugar._advance_iterator"
    stop_identity, _ = _builtin_exception_identity("StopIteration")
    coordinate = getattr(effect, "exception_type_coordinate", None)
    if coordinate is None:
        raise SugarNotWritten(
            blame=getattr(effect, "occurrence_id", None) or owner,
            owner=owner,
            observed="RaiseEffect without exception_type_coordinate",
            requested="authenticated StopIteration type coordinate from next producer",
            fix=(
                "mint the halt through ground_exceptional_exit / the iterator "
                "floor; never decide exhaustion by exception_name spelling"
            ),
        )
    return coordinate == stop_identity


@dataclass(frozen=True)
class LoopBindingRefSugar(ConstructedTermSugar):
    """A read after a live loop of ``name``, which the loop carries under
    its binding coordinate: one face (``completion_kind``) of the loop's
    post-binding projection (``project_loop_post_binding``).

    The read resolves through the loop's own key of the name only
    (``post_key``, ``live_loop_construction.loop_post_binding_key``), never
    through the binding coordinate: two loops writing one name carry it
    under one coordinate, and a read after the later one must never find the
    earlier one's value there.  The loop binds the key on every exit it
    leaves by, concrete or symbolic, guarded or not
    (``LoopRecurrenceSugar._publication``), so a read reduced after the loop
    in the block that ran it finds it bound, and an ``if`` carries it out of
    the arm the loop sits in as it carries any evaluation
    (``if_sugar._arm_evaluations``).  The key is an evaluation key, read
    where the reduction runs (``evaluation_read_here``): inside the item of a
    live loop around the write, that item's.  Unbound -- no context, or a
    context the loop's publication never reached -- the read is refused by
    name (``_unbound``): no value is made up in its place."""

    target_cid: str
    binding_coordinate_cid: str
    completion_kind: str
    name: str
    post_key: str
    site: object = field(compare=False)

    @classmethod
    def witnesses(cls):
        return ()

    def to_term(self, *, owner: str):
        del owner
        return ctor(
            "python:loop.post_binding",
            [
                str_const(self.target_cid),
                str_const(self.binding_coordinate_cid),
                str_const(self.completion_kind),
            ],
            symbol_kind="coordinate",
        )

    def desugar(self, ctx=None):
        from sugar_lift_py_tests.sugar.evaluation_ref_sugar import (
            evaluation_read_here,
        )

        temporal = getattr(ctx, "temporal", None)
        bound = None
        if temporal is not None:
            key = evaluation_read_here(temporal, self.post_key)
            bound = temporal.value_if_bound(key)
        if bound is None:
            self._unbound()
        return ExitSet.completed(bound)

    def _unbound(self):
        """A read whose key the loop's publication never reached here.
        Refused by name, naming the key and the binding coordinate: the name
        is never read in its place, the coordinate is never read in its
        place either (another loop writing the name binds the same one), and
        the loop is never assumed to have left some value nobody bound."""
        from sugar_lift_py_tests.gap.panic import construction_panic_gap

        construction_panic_gap(
            owner="LoopBindingRefSugar",
            blame=self.site,
            observed=(
                f"read of `{self.name}` after loop {self.target_cid} "
                f"({self.completion_kind} face) with the loop's key "
                f"{self.post_key} of binding coordinate "
                f"{self.binding_coordinate_cid} unbound"
            ),
            requested=(
                "the loop's publication of the name under its own key "
                "(LoopRecurrenceSugar._publication) on the exit the read "
                "follows"
            ),
            fix=(
                "reduce the read after the loop in the block that ran it, "
                "or carry the loop's publication to where the read is "
                "reduced; never answer an unbound post-binding term"
            ),
        )


@dataclass(frozen=True)
class LoopRecurrenceSugar(ConstructedTermSugar):
    target_cid: str
    loop_construction_cid: str
    binding_coordinate_cids: tuple[str, ...]
    # The loop's own key of each name it carries under a binding coordinate
    # (``binding_coordinate_cids`` order,
    # ``live_loop_construction.loop_post_binding_key``): what it publishes
    # the name under as it leaves (``_publication``).
    post_binding_keys: tuple[str, ...]
    outward_faces: tuple[object, ...]
    construction: object = field(compare=False)
    site: object = field(compare=False)
    # What the iterable's walrus writes leave the loop as, on every exit
    # (``desugar``, ``_iterable_writes``): bound by the reduction that
    # evaluated the iterable, never by the construction.
    iterable_writes: tuple = field(default=(), compare=False)

    @classmethod
    def witnesses(cls):
        return ()

    def to_term(self, *, owner: str):
        """Project the authenticated loop construction as one canonical term."""
        from sugar_lift_py_tests.loop_construction import (
            LoopWireError,
            decode_loop_construction_v1,
        )

        construction = decode_loop_construction_v1(self.construction.wire_graph())
        if construction.loop_construction_cid != self.loop_construction_cid:
            raise LoopWireError("loop recurrence construction CID mismatch")
        if construction.target.target_cid != self.target_cid:
            raise LoopWireError("loop recurrence target CID mismatch")

        root = construction.wire_graph()["root"]
        outward_face_cids = tuple(root["outwardHaltedFaceCids"])
        if len(outward_face_cids) != len(self.outward_faces):
            raise LoopWireError("loop recurrence outward-face testimony mismatch")
        coordinates = (*self.binding_coordinate_cids, *outward_face_cids)
        if any(
            not isinstance(cid, str) or not cid.startswith("blake3-512:")
            for cid in coordinates
        ):
            raise LoopWireError("loop recurrence testimony must be content-addressed")

        return ctor(
            "python:loop-recurrence-construction",
            (
                str_const(self.target_cid),
                str_const(self.loop_construction_cid),
                self.occurrence_term(owner=owner),
                ctor(
                    "python:loop-binding-coordinates",
                    tuple(str_const(cid) for cid in self.binding_coordinate_cids),
                    symbol_kind="coordinate",
                ),
                ctor(
                    "python:loop-outward-face-testimony",
                    tuple(str_const(cid) for cid in outward_face_cids),
                    symbol_kind="coordinate",
                ),
            ),
            symbol_kind="coordinate",
        )

    def desugar(self, ctx=None):
        from sugar_lift_py_tests.loop_construction import LoopWireError

        runtime = self.construction.loop_runtime
        if getattr(runtime, "test_sugar", None) is not None:
            # A live ``while`` (``LiveWhileRuntimeV1``): its items run where
            # its test decides, exactly as a live ``for``'s run.
            return self._desugar_while(runtime, ctx)
        iterable_sugar = self.construction.iterable_sugar
        iterable_cid = self.construction.iterable_value_construction_cid
        if iterable_cid is None:
            return self._desugar_with_iterable(None, ctx)
        if iterable_sugar is None:
            raise LoopWireError("for recurrence omitted its live iterable sugar")
        if iterable_sugar.site.seal().cid != iterable_cid:
            raise LoopWireError("loop recurrence iterable occurrence mismatch")
        from sugar_lift_py_tests.floor.named_expression_value import (
            peel_walrus_binds,
            written_by,
        )

        from dataclasses import replace

        # The iterable is evaluated once, before the first item: a walrus in
        # it has written before the pre-loop values are read and every item
        # runs (``written_by``).  A carried name it writes starts the loop
        # from the walrus's key (``construct_live_loop_recurrence``).  The
        # loop iterates the value the iterable presents, and leaves, on every
        # exit, with the writes of the names it does not carry
        # (``_iterable_writes``).
        def with_iterable(iterable):
            binds, presented = peel_walrus_binds(iterable)
            loop = replace(self, iterable_writes=self._iterable_writes(binds))
            return loop._desugar_with_iterable(presented, written_by(iterable, ctx))

        return iterable_sugar.desugar(ctx).and_then(with_iterable)

    def _iterable_writes(self, binds):
        """The iterable's walrus writes (``binds``, ``peel_walrus_binds``
        order) of the names the loop does not carry, each as the rebind of
        the key it wrote (``NamedExpressionValue.written``).  A read of such
        a name after the loop is a reference to that key
        (``Statement._substitute_body_tracked``); the iterable ran once,
        before the loop, so the key holds on every exit, the one where no
        item ran included.  A name carried under its binding coordinate
        leaves as the loop's value (``_publish_runtime_bindings``); one
        published through its post-loop key reads the walrus's key on the
        exit no item wrote it (``nodes._live_loop_publication``)."""
        from sugar_lift_py_tests.floor.scope_rebind import ScopeRebind

        runtime = self.construction.loop_runtime
        carried = (
            frozenset()
            if runtime is None
            else frozenset(self._coordinate_names(runtime))
        )
        writes = []
        for bind in binds:
            written = bind.written()
            if written is None or bind.name in carried:
                continue
            writes.append(ScopeRebind(*written))
        return tuple(writes)

    def _start(self, runtime, ctx):
        """``(ctx, carried, early)``: the context the first item of a live
        loop (a ``for``'s or a ``while``'s) begins in, with the header of each
        carried name bound to its pre-loop value, and those values
        (``carried``); or ``early``, the outcome a pre-loop value reduced to
        that is not one unconditional value owing nothing, returned whole in
        place of the loop."""
        from sugar_lift_py_tests.caller_parameter_contract import (
            NativeOperationExitCarrierV1,
        )
        from sugar_lift_py_tests.sugar.evaluation_ref_sugar import evaluation_here
        from sugar_lift_py_tests.temporal import bind_temporal

        from dataclasses import replace

        runtime_ctx = ctx
        if runtime_ctx is not None and runtime.carried_names:
            runtime_ctx = replace(
                runtime_ctx,
                live_loop_names=frozenset(
                    (
                        *getattr(runtime_ctx, "live_loop_names", ()),
                        *runtime.carried_names,
                    )
                ),
            )
        initial_values = []
        for (header, _writes, _else_writes), sugar in zip(
            self._carried_evaluations(runtime),
            runtime.initial_value_sugars,
            strict=True,
        ):
            if sugar is None:
                # A name first bound in the loop: its header starts unbound.
                # Nothing is bound under it until an item writes the name,
                # and each item decides its write slot (``_enter_header``).
                initial_values.append(None)
                continue
            initial = sugar.desugar(runtime_ctx)
            if isinstance(initial, NativeOperationExitCarrierV1):
                return runtime_ctx, None, initial
            initial_value = initial.completed_value()
            # Only one unconditional value owing nothing is bound and carried
            # on; any other shape (a halt, several faces, an arm that owes)
            # is returned whole, with every arm it has.
            if initial_value is None or initial.owed_items():
                return runtime_ctx, None, initial
            # The pre-loop value is bound under the header's key where the
            # loop stands (``evaluation_here``), outside every item of it: the
            # header's evaluation before the first item.  The name is never
            # written; each item binds its own header to what it begins with
            # (``_enter_header``).
            if header is not None:
                runtime_ctx = bind_temporal(
                    runtime_ctx,
                    evaluation_here(header),
                    initial_value,
                    owner="LoopRecurrenceSugar.pre-loop",
                    blame=str(self.site),
                )
            initial_values.append(initial_value)
        # The first item begins with the pre-loop values.
        return runtime_ctx, tuple(initial_values), None

    def _desugar_with_iterable(self, iterable, ctx):
        runtime = self.construction.loop_runtime
        from sugar_lift_py_tests.floor import SymbolicValue

        if (
            iterable is not None
            and runtime is not None
            and not isinstance(iterable, SymbolicValue)
        ):
            from sugar_lift_py_tests.operations.iterator_operation import (
                IteratorOperation,
            )

            runtime_ctx, carried, early = self._start(runtime, ctx)
            if early is not None:
                return early
            return (
                IteratorOperation(owner="LoopRecurrenceSugar", blame=self.site)
                .submit(iterable, runtime_ctx)
                .and_then(
                    lambda iterator: self._advance_iterator(
                        iterator, runtime, runtime_ctx, entries=(), carried=carried
                    )
                )
            )

        from sugar_lift_py_tests.floor import InvValue
        from sugar_lift_py_tests.floor.block_value import BlockValue

        # The recurrence's value of each name the loop writes: one head per
        # name, keyed by what a read after the loop reads it through -- its
        # binding coordinate (``binding_coordinate_cids``), or its post-loop
        # key (``LiveForRuntimeV1.published_evaluations``) -- each the fixed
        # point of the loop's step over the iterable.
        heads = tuple(
            self._recurrence_head(coordinate_cid)
            for coordinate_cid in self.binding_coordinate_cids
        )
        post_keys = tuple(
            post_key
            for post_key, _writes, _else_writes in getattr(
                runtime, "published_evaluations", ()
            )
        )
        post_heads = tuple(self._recurrence_head(post_key) for post_key in post_keys)
        recurrences = []
        for h in (*heads, *post_heads):
            step = ctor(
                "python:loop.step",
                [
                    h,
                    str_const(self.loop_construction_cid),
                    *(
                        ()
                        if iterable is None
                        else (iterable.to_term(owner="LoopRecurrenceSugar"),)
                    ),
                ],
                symbol_kind="coordinate",
            )
            recurrences.append(InvValue(atomic("=", [h, step]), self.site))
        # The loop leaves publishing what a concrete loop publishes
        # (``_publication``): each coordinate name's value under its binding
        # coordinate, and each other written name's under its post-loop key,
        # with its write slot decided -- here as the guard that some item
        # wrote it, which the symbolic iterable does not decide true or false.
        recurrence = BlockValue(
            (
                *self.iterable_writes,
                *recurrences,
                *self._publication(
                    tuple(SymbolicValue(h) for h in heads),
                    tuple(
                        (
                            post_key,
                            SymbolicValue(h),
                            atomic(
                                "python.loop.wrote",
                                [str_const(self.target_cid), str_const(post_key)],
                            ),
                        )
                        for post_key, h in zip(post_keys, post_heads, strict=True)
                    ),
                ),
            ),
            can_fall_through=True,
        )
        # The item's target unpack runs first, whether or not the body has an
        # outward face: the recurrence (and the item's body) are what follows
        # its completed arm (``ExitSet.sequence``), and its halt (too few, too
        # many, not iterable) is an arm of the recurrence as it is.  A body
        # with no ``return``/``raise`` still unpacks every item.
        projected, enter, item = self._enter_symbolic_item(
            runtime, ctx, iterable, heads
        )
        if not self.outward_faces:
            return projected.and_then(
                lambda _projections: ExitSet.completed(recurrence)
            )

        # The body has a ``return``/``raise``: the symbolic item runs the
        # body once, through the one block composition a concrete item and a
        # function body use (``reduce_block_to_exitset``), in the item's
        # context.  Its reads of a carried name and of the target are
        # references to their keys (``For.substitute``), bound here for that
        # item exactly as for a concrete one (``_enter_symbolic_item``); its
        # reads of what an earlier statement of the body wrote (an inner
        # loop's publication) are bound by that statement, which ran ahead of
        # it.  The loop's exits are the arms of that one run
        # (``_leave_symbolic_item``).
        body_sugars, item_guard = self._symbolic_item()

        def run_item(projections):
            from sugar_lift_py_tests.sugar.function_universe_sugar import (
                reduce_block_to_exitset,
            )

            item_ctx = enter(projections)
            with item():
                body = reduce_block_to_exitset(body_sugars, item_ctx)
            return self._leave_symbolic_item(body, recurrence, item_guard)

        if len(projected.exits) == 1:
            # One way in (a name target, a ``while``): the item is exactly
            # what follows it, a body waiting on its caller's actuals handed on.
            return projected.and_then(run_item)
        return projected.sequence(run_item)

    def _symbolic_item(self):
        """``(body_sugars, guard)``: the body the recurrence's one symbolic
        item runs, and the guard under which an item runs at all (the loop's
        ``BodyFallthrough`` guard: some item is reached, or the ``while``
        test holds), from the construction
        (``live_loop_construction.LiveSymbolicItemV1``).  A construction that
        handed none is refused by name: no body is made up in its place."""
        symbolic_item = getattr(self.construction, "symbolic_item", None)
        if symbolic_item is None:
            from sugar_source_tree.panic import SugarNotWritten

            raise SugarNotWritten(
                owner="LoopRecurrenceSugar.symbolic-item",
                blame=self.site,
                observed="an outward face with no symbolic item to run",
                requested="the loop body and its item guard from the construction",
                fix=(
                    "construct the loop through construct_live_loop_recurrence, "
                    "which hands its body to the symbolic item"
                ),
            )
        return symbolic_item.body_sugars, symbolic_item.guard

    def _leave_symbolic_item(self, body, recurrence, guard):
        """The loop's exits from the one run of the symbolic item's
        ``body`` (``reduce_block_to_exitset``'s arms), under ``guard``
        (an item runs), beside the recurrence under its negation (no item
        runs: the loop leaves as it began).

        Each arm leaves as a concrete item's does (``_after_iteration_state``,
        ``_after_loop_control``): an arm that does not fall through (a
        ``return``) leaves the loop with its entries; an arm that falls
        through, and this loop's own ``break``/``continue``, leave the item
        as the recurrence (the loop goes on); any other halt (a ``raise``, an
        inner loop's or a call's) is an arm as it is.  An arm that falls
        through after an earlier guarded ``return`` took its exit where that
        return's guard held: it is split as the block composition splits a
        later halt (``_prior_return_face``), the returned arm with its
        entries, the recurrence under the fall-through guard.  Each exit is
        an arm of the one run, so each is reported once."""
        from sugar_lift_py_tests.caller_parameter_contract import (
            NativeOperationExitCarrierV1,
        )
        from sugar_lift_py_tests.effect.loop_control_effect import LoopControlEffect
        from sugar_lift_py_tests.floor.block_value import BlockValue
        from sugar_lift_py_tests.ir import and_
        from sugar_lift_py_tests.outcome.exit_set import _require_exit_set
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            _prior_return_face,
        )

        def returned(block):
            return ExitSet.completed(BlockValue(block.entries, can_fall_through=False))

        def leave(state):
            if not state.can_fall_through:
                return returned(state)
            goes_on = ExitSet.completed(recurrence)
            earlier = _prior_return_face(state, state.context)
            if earlier is None:
                return goes_on
            continuation = (
                state.fall_through[0]
                if len(state.fall_through) == 1
                else and_(list(state.fall_through))
            )
            return goes_on.guarded(continuation).union(earlier.sequence(returned))

        def own_control(halt):
            effect = halt.effect
            if (
                isinstance(effect, LoopControlEffect)
                and effect.target_cid == self.target_cid
            ):
                return ExitSet.completed(recurrence)
            return None

        def compose(body):
            left = body.sequence(leave, consume=own_control)
            return ExitSet.completed(recurrence, not_(guard)).union(left.guarded(guard))

        if isinstance(body, NativeOperationExitCarrierV1):
            # The body still waits on its caller's actuals: once it
            # discharges, the loop leaves from it exactly as from a body that
            # reduced to its arms here.
            return body.after_discharge(
                lambda projected: compose(
                    _require_exit_set(
                        projected, owner="LoopRecurrenceSugar.symbolic-item"
                    )
                )
            )
        return compose(
            _require_exit_set(body, owner="LoopRecurrenceSugar.symbolic-item")
        )

    def _advance_iterator(self, iterator, runtime, ctx, *, entries, carried, index=0):
        """Run item ``index`` of the live loop.

        ``carried`` is the value of each carried name (``runtime.carried_names``
        order) the item begins with: the pre-loop values for the first item,
        the previous item's latch (``_latched``) after it.  An item handed
        nothing for the names it carries is refused by name
        (``_require_carried``): the names are never read in its place.
        """
        from sugar_lift_py_tests.effect.loop_control_effect import LoopControlEffect
        from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
        from sugar_lift_py_tests.floor.block_value import BlockValue
        from sugar_lift_py_tests.floor.iterator_value import NextResult
        from dataclasses import replace

        from sugar_lift_py_tests.operations.next_operation import NextOperation
        from sugar_lift_py_tests.outcome.exit_set import _require_exit_set
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            reduce_block_to_exitset,
        )

        # The item's ``next`` is read arm by arm (exhaustion, the NextResult):
        # a deferred native-operation carrier here is refused by name.
        outcome = _require_exit_set(
            NextOperation(owner="LoopRecurrenceSugar", blame=self.site).submit(
                iterator, ctx
            ),
            owner="LoopRecurrenceSugar.next",
        )
        if outcome.exits and outcome.halts() == outcome.exits:
            effect = outcome.exits[0].effect
            if (
                len(outcome.exits) == 1
                and isinstance(effect, RaiseEffect)
                and _is_authenticated_stop_iteration(effect)
            ):
                # Exhaustion is this loop's own control: the loop consumes the
                # StopIteration and leaves beneath it, under its guard and
                # faces, owing what the exhausting ``next`` owed.  An ``else``
                # suite still waiting on its caller's actuals is composed
                # beneath it too (``sequence`` hands the carrier on).
                return outcome.sequence(
                    ExitSet.completed,
                    consume=lambda _stop: self._finish_iterator(
                        runtime, ctx, entries=entries, carried=carried, items=index
                    ),
                )
            return outcome
        next_result = outcome.completed_value()
        # A NextResult owing something has no linear place for the debt: it
        # is refused with every other shape, never carried on without it.
        if not isinstance(next_result, NextResult) or outcome.owed_items():
            raise TypeError(
                "NextOperation must produce NextResult or a named exception"
            )

        from sugar_lift_py_tests.outcome import Halted

        projected = self._project_iteration_target(
            runtime.target_pattern, next_result.value, ctx
        )
        # On a halted arm assignment has not begun: the positional-unpack
        # Floor owns the halt and the exact context entering this iteration
        # is its state.  The item runs beneath each completed arm: one plain
        # roster, or the completed face of a symbolic member's runtime unpack
        # beside its halt.
        projected = ExitSet(
            tuple(
                replace(face, state=ctx) if isinstance(face, Halted) else face
                for face in projected.exits
            )
        ).normalize()
        from sugar_lift_py_tests.occurrence import entered, loop_iteration_segment

        def resume(ctx, *, entries, carried, index):
            # The next item takes the iterator's next element.
            return self._advance_iterator(
                next_result.advanced,
                runtime,
                ctx,
                entries=entries,
                carried=carried,
                index=index,
            )

        def run_item(projections):
            # Each iteration is its own evaluation of the body's sites: a call
            # in iteration 2 is never claimed to complete exactly when
            # iteration 1's did (the unrolled loop's law, sugar/loop iteration
            # segments).  Its statement evaluations are its own keys too
            # (``evaluation_here``), its reads of a carried name read this
            # item's header, and its reads of the target read this item's
            # projection, bound under the target's key after the header (a
            # carried target's header is that key).
            with entered(loop_iteration_segment(self.target_cid, index)):
                iteration_ctx = self._enter_header(runtime, ctx, carried)
                iteration_ctx, target_bindings = self._enter_target(
                    runtime, iteration_ctx, projections
                )
                body = reduce_block_to_exitset(runtime.body_sugars, iteration_ctx)
            return self._after_item(
                body, runtime, target_bindings, resume, entries=entries, index=index
            )

        projections = projected.completed_value()
        if projections is not None:
            # One plain roster: the item is exactly what follows it, a later
            # item waiting on its caller's actuals handed on.
            return run_item(projections)
        return projected.sequence(run_item)

    def _after_item(self, body, runtime, target_bindings, resume, *, entries, index):
        """The loop's outcome after item ``index``'s ``body`` reduced, for a
        live ``for`` and a live ``while`` alike.  ``resume(ctx, entries=,
        carried=, index=)`` runs the next item: the iterator's next element,
        or the test evaluated again."""
        from sugar_lift_py_tests.caller_parameter_contract import (
            NativeOperationExitCarrierV1,
        )
        from sugar_lift_py_tests.outcome.exit_set import _require_exit_set

        def after_body(body):
            # Each face of this iteration is its own path, and what follows it
            # runs beneath it (``ExitSet.sequence``): a completed face carries
            # its own state into the next iteration, this loop's own
            # break/continue is consumed and continues, any other halt leaves
            # the loop as it is. The first iteration's faces are never the
            # loop's outcome.
            # A later item still waiting on its caller's actuals answers its
            # deferred carrier: ``sequence`` composes it beneath its face, and
            # the loop hands the composed carrier on to its caller.
            if len(body.exits) != 1:
                return body.sequence(
                    lambda state: self._after_iteration_state(
                        state, runtime, resume, entries=entries, index=index
                    ),
                    consume=lambda halt: self._after_loop_control(
                        halt,
                        runtime,
                        target_bindings,
                        resume,
                        entries=entries,
                        index=index,
                    ),
                )
            face = body.exits[0]
            following = self._after_iteration_face(
                face,
                runtime,
                target_bindings,
                resume,
                entries=entries,
                index=index,
            )
            if following is None:
                return body
            # The one face, whichever kind, continues into ``following``.
            return body.sequence(
                lambda _state: following, consume=lambda _halt: following
            )

        if isinstance(body, NativeOperationExitCarrierV1):
            # This item's body still waits on its caller's actuals: once it
            # discharges, the loop continues from this item exactly as it does
            # from a body that reduced to its faces here.
            return body.after_discharge(
                lambda projected: after_body(
                    _require_exit_set(projected, owner="LoopRecurrenceSugar.body")
                )
            )
        return after_body(_require_exit_set(body, owner="LoopRecurrenceSugar.body"))

    def _after_iteration_face(
        self, face, runtime, target_bindings, resume, *, entries, index
    ):
        """The loop's outcome after one face of an iteration, or None when the
        face leaves the loop as it is (a halt that is not this loop's control)."""
        from sugar_lift_py_tests.outcome import Halted

        if isinstance(face, Halted):
            return self._after_loop_control(
                face,
                runtime,
                target_bindings,
                resume,
                entries=entries,
                index=index,
            )
        return self._after_iteration_state(
            face.value, runtime, resume, entries=entries, index=index
        )

    def _after_loop_control(
        self, halt, runtime, target_bindings, resume, *, entries, index
    ):
        """The loop's outcome after a halted iteration face, or None when the
        halt is not this loop's own break/continue and leaves as it is."""
        from sugar_lift_py_tests.effect.loop_control_effect import LoopControlEffect

        effect = halt.effect
        if (
            isinstance(effect, LoopControlEffect)
            and effect.target_cid == self.target_cid
        ):
            state = self._require_loop_control_state(
                halt.state,
                target_bindings=target_bindings,
            )
            if effect.action == "continue":
                return resume(
                    state,
                    entries=entries,
                    carried=self._latched(runtime, state, index),
                    index=index + 1,
                )
            if effect.action == "break":
                return self._publish_runtime_bindings(
                    runtime,
                    state,
                    entries=entries,
                    carried=self._latched(runtime, state, index),
                    items=index + 1,
                )
        return None

    def _after_iteration_state(self, state, runtime, resume, *, entries, index):
        """The loop's outcome after a completed iteration face whose record is
        ``state``."""
        from sugar_lift_py_tests.floor.block_value import BlockValue

        combined = (*entries, *state.entries)
        if not state.can_fall_through:
            return ExitSet.completed(BlockValue(combined, can_fall_through=False))
        return resume(
            state.context,
            entries=combined,
            carried=self._latched(runtime, state.context, index),
            index=index + 1,
        )

    def _desugar_while(self, runtime, ctx):
        """A live ``while``: its first item begins with the pre-loop values
        (``_start``).  A test that does not decide where the first item
        begins leaves the loop its recurrence, as a ``while`` whose items do
        not run (``_desugar_with_iterable``)."""
        runtime_ctx, carried, early = self._start(runtime, ctx)
        if early is not None:
            return early
        return self._test_item(
            runtime, runtime_ctx, entries=(), carried=carried, index=0, before=ctx
        )

    def _test_item(self, runtime, ctx, *, entries, carried, index, before=None):
        """Run item ``index`` of a live ``while``: bind its header to what the
        previous item handed on (``carried``), evaluate the test there, and
        run the body under every face whose truth is true.  A face whose
        truth is false leaves the loop (``_after_test``).

        The test decides each face or the loop does not run as items: at the
        first item an undecided test leaves the loop its recurrence (``before``
        is the context the loop began in); after an item ran, an undecided
        test is refused by name, never guessed true or false.  So is a loop
        whose test has not decided false within ``runtime.fuel`` items."""
        from sugar_lift_py_tests.occurrence import entered, loop_iteration_segment
        from sugar_lift_py_tests.outcome import Completed
        from sugar_lift_py_tests.outcome.exit_set import (
            _is_false,
            _is_true,
            _require_exit_set,
        )
        from sugar_source_tree.panic import SugarNotWritten

        if index >= runtime.fuel:
            raise SugarNotWritten(
                owner="LoopRecurrenceSugar.while",
                blame=self.site,
                observed=(
                    f"a live while ran {index} items without its test deciding "
                    "false"
                ),
                requested="the item at which the test decides false, or a break",
                fix=(
                    "decide the loop's exit from what its items hand on; never "
                    "cut the loop short"
                ),
            )
        with entered(loop_iteration_segment(self.target_cid, index)):
            item_ctx = self._enter_header(runtime, ctx, carried)
            test = _require_exit_set(
                runtime.test_sugar.desugar(item_ctx),
                owner="LoopRecurrenceSugar.while-test",
            )
            tested = test.sequence(
                lambda value: ExitSet.completed(
                    _WhileTest(
                        self._test_formula(value), value.extend_scope(item_ctx)
                    )
                )
            )
            undecided = any(
                isinstance(face, Completed)
                and not (
                    face.value.formula is not None
                    and (_is_true(face.value.formula) or _is_false(face.value.formula))
                )
                for face in tested.exits
            )
            if not undecided:
                # Each true face runs the body in this item, after the test.
                tested = tested.sequence(
                    lambda item: ExitSet.completed(self._with_body(item, runtime))
                )
        if undecided and index == 0:
            return self._desugar_with_iterable(None, before)
        if undecided:
            raise SugarNotWritten(
                owner="LoopRecurrenceSugar.while",
                blame=self.site,
                observed=(
                    f"undecided while test at item {index}: its truth is not "
                    "decided by what the previous item handed on"
                ),
                requested="a decided truth of the test at every item",
                fix=(
                    "carry the testimony that decides the test into the item; "
                    "never guess the loop continues or stops"
                ),
            )
        return tested.sequence(
            lambda item: self._after_test(item, runtime, entries=entries, index=index)
        )

    @staticmethod
    def _with_body(item, runtime):
        """A true face of the test with the body reduced in its context (in
        the item the caller has entered); a false face as it is."""
        from dataclasses import replace

        from sugar_lift_py_tests.outcome.exit_set import _is_true
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            reduce_block_to_exitset,
        )

        if not _is_true(item.formula):
            return item
        return replace(
            item, body=reduce_block_to_exitset(runtime.body_sugars, item.ctx)
        )

    def _test_formula(self, value):
        """The truth of a ``while`` test's value as a guard (``predicate_formula``),
        or None when its truth is not one value."""
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            plain_completed_value,
        )
        from sugar_lift_py_tests.sugar.if_sugar import predicate_formula

        if plain_completed_value(value.truth(self.site)) is None:
            return None
        return predicate_formula(value, self.site)

    def _after_test(self, item, runtime, *, entries, index):
        """The loop's outcome after item ``index``'s test decided: false
        leaves the loop with what the test left each carried name (the
        previous item's latch, or a walrus in the test), through the ``else``
        suite (``_finish_iterator``); true continues from the body as a live
        ``for``'s item does (``_after_item``)."""
        from sugar_lift_py_tests.outcome.exit_set import _is_false

        if _is_false(item.formula):
            # Item ``index`` evaluated the test: a walrus in it wrote there,
            # so the items the loop leaves after are ``index + 1``.
            return self._finish_iterator(
                runtime,
                item.ctx,
                entries=entries,
                carried=self._latched(runtime, item.ctx, index),
                items=index + 1,
            )

        def resume(ctx, *, entries, carried, index):
            # The next item evaluates the test again.
            return self._test_item(
                runtime, ctx, entries=entries, carried=carried, index=index
            )

        return self._after_item(
            item.body, runtime, (), resume, entries=entries, index=index
        )

    @staticmethod
    def _coordinate_names(runtime):
        """The carried names the loop publishes under their binding
        coordinates (``binding_coordinate_cids`` order,
        ``LiveForRuntimeV1.coordinate_names``); a runtime that names none
        apart publishes every carried name so.  Every other carried name is
        published through its post-loop key (``_post_loop_writes``)."""
        return tuple(getattr(runtime, "coordinate_names", runtime.carried_names))

    @staticmethod
    def _carried_evaluations(runtime):
        """``(header, writes, else_writes)`` per carried name; a runtime that
        names none has no header and no writes for any name."""
        triples = tuple(getattr(runtime, "carried_evaluations", ()))
        if len(triples) != len(runtime.carried_names):
            return tuple((None, (), ()) for _ in runtime.carried_names)
        return triples

    def _require_carried(self, runtime, carried):
        """``carried``: the value of each carried name an item begins with or
        the loop leaves with (the pre-loop values, an item's latch, what the
        ``else`` suite left).  Handed nothing, a loop that carries no name
        carries the empty tuple; one that carries names is refused by name.
        The names are never read in its place: nothing writes them."""
        if carried is not None:
            return carried
        if not runtime.carried_names:
            return ()
        from sugar_source_tree.panic import SugarNotWritten

        names = ", ".join(f"`{name}`" for name in runtime.carried_names)
        raise SugarNotWritten(
            owner="LoopRecurrenceSugar",
            blame=self.site,
            observed=(
                f"a live loop item entered or left with no value handed on for "
                f"the names it carries ({names})"
            ),
            requested=(
                "the pre-loop values, the previous item's latch, or what the "
                "else suite left, handed to the item"
            ),
            fix=(
                "enter every item through the recurrence, which hands it what "
                "it carries; never read the carried names in its place"
            ),
        )

    def _enter_header(self, runtime, ctx, carried, *, decide=True):
        """Bind the header evaluation of each carried name: the value an item
        begins with (``carried``), under the header's key qualified by where
        it is bound (``evaluation_here``): inside an item (the caller has
        entered it), that item's header; after the last item, the header the
        ``else`` suite reads, outside every item.  The body's and the else's
        reads of a carried name are references to it (``For.substitute``).

        A name first bound in the loop (no pre-loop value:
        ``initial_value_sugars``) is read as ``<header> if <an item wrote
        it> else <unbound>`` (``nodes._loop_header_bindings``): its header's
        write slot (``loop_write_slot``) is decided here, true exactly when
        an earlier item handed it a value, so a read before any write is a
        ``NameError``.  The recurrence's symbolic item does not know whether
        an earlier item wrote it (``decide`` false): the slot stays
        undecided there."""
        from sugar_lift_py_tests.floor.branch_result_coordinate import (
            BranchResultDecision,
        )
        from sugar_lift_py_tests.sugar.evaluation_ref_sugar import evaluation_here
        from sugar_lift_py_tests.temporal import bind_temporal
        from sugar_source_tree.binding_state import loop_write_slot

        carried = self._require_carried(runtime, carried)
        if ctx is None:
            return ctx
        starts = tuple(getattr(runtime, "initial_value_sugars", ()))
        for index, ((header, _writes, _else_writes), value) in enumerate(
            zip(self._carried_evaluations(runtime), carried, strict=True)
        ):
            if header is None:
                continue
            if decide and len(starts) == len(carried) and starts[index] is None:
                ctx = BranchResultDecision(
                    loop_write_slot(header), value is not None, self.site
                ).extend_scope(ctx)
            if value is None:
                continue
            ctx = bind_temporal(
                ctx,
                evaluation_here(header),
                value,
                owner="LoopRecurrenceSugar.header",
                blame=str(self.site),
            )
        return ctx

    def _target_keys(self, runtime):
        """Each target leaf's name, to the key the recurrence binds its
        projection under (``LiveForRuntimeV1.target_evaluations``)."""
        names = tuple(runtime.target_pattern.names)
        keys = tuple(getattr(runtime, "target_evaluations", ()))
        if len(keys) != len(names):
            raise TypeError("live for runtime omitted its target evaluation keys")
        return dict(zip(names, keys, strict=True))

    def _enter_target(self, runtime, ctx, projections):
        """Bind this item's projection of each target leaf under the leaf's
        key, qualified by the item (``evaluation_here``), and under the
        leaf's binding coordinate.  The name is never written: the body and
        the ``else`` read the target through its key (``For.substitute``).

        Returns the context and, per leaf, ``(key, coordinate, value)``: the
        identity a loop-control halt's state must hold
        (``_require_loop_control_state``)."""
        from sugar_lift_py_tests.sugar.evaluation_ref_sugar import evaluation_here
        from sugar_lift_py_tests.temporal import bind_temporal

        keys = self._target_keys(runtime)
        bindings = []
        for name, coordinate_cid, value in projections:
            key = evaluation_here(keys[name])
            ctx = bind_temporal(
                ctx,
                key,
                value,
                owner="LoopRecurrenceSugar.target",
                blame=str(self.site),
            )
            ctx = bind_temporal(
                ctx,
                coordinate_cid,
                value,
                owner="LoopRecurrenceSugar.target-coordinate",
                blame=str(self.site),
            )
            bindings.append((key, coordinate_cid, value))
        return ctx, tuple(bindings)

    def _enter_symbolic_item(self, runtime, ctx, iterable, heads):
        """The recurrence's one symbolic item: ``(projected, enter, item)``.
        ``projected`` is the item's target unpack, an ``ExitSet`` whose
        completed arms hold the leaves' projections; ``enter(projections)``
        is the context the item's body reduces in on such an arm; ``item``
        is the item to enter while it does.

        A concrete item binds, inside its own segment, each carried name's
        header to the value the item begins with (``_enter_header``), then
        unpacks its value into the target (``_project_iteration_target``)
        and binds each leaf's key to its projection (``_enter_target``).
        The symbolic item does the same, inside its own segment
        (``loop_symbolic_item_segment``): each header to the recurrence's
        value of the name (``heads``, ``python:loop.recurrence``), then the
        item of the symbolic iterable (``python:loop.item``) through the same
        unpack.  A read in the body decides through its key; the name is
        never read.

        A name target's unpack is the item whole.  A destructuring target's
        is the item's runtime unpack, two-faced: each leaf's key (a
        carried leaf's header is its key) is bound to its projection on the
        unpack's completed arm, and its halt is an arm as it is, from the
        context entering the item, as a concrete item's unpack halt is
        (``_advance_iterator``).  A ``while`` without a runtime has no item:
        the context is unchanged and nothing is entered; a live ``while``'s
        symbolic item binds its headers only (it has no target, so nothing
        to unpack)."""
        from contextlib import nullcontext
        from dataclasses import replace
        from functools import partial

        from sugar_lift_py_tests.occurrence import entered, loop_symbolic_item_segment
        from sugar_lift_py_tests.outcome import Halted

        if runtime is None or (ctx is not None and not hasattr(ctx, "temporal")):
            return ExitSet.completed(()), lambda _projections: ctx, nullcontext
        if ctx is None:
            from sugar_lift_py_tests.context import ReduceContext

            ctx = ReduceContext.root(owner="LoopRecurrenceSugar.symbolic-item")
        item = partial(entered, loop_symbolic_item_segment(self.target_cid))
        # The recurrence has a value for each name it carries under a binding
        # coordinate (``heads``, in coordinate order); a name it carries
        # through its header alone has none here, so its header is left
        # unbound and a read of it is refused by name.  Whether an earlier
        # item wrote a name first bound in the loop is not known here: its
        # write slot is left undecided (``decide``).
        by_name = dict(zip(self._coordinate_names(runtime), heads, strict=True))
        starts = tuple(
            None if by_name.get(name) is None else SymbolicValue(by_name[name])
            for name in runtime.carried_names
        )
        pattern = getattr(runtime, "target_pattern", None)
        if pattern is None:
            with item():
                header_ctx = self._enter_header(runtime, ctx, starts, decide=False)
            return ExitSet.completed(()), lambda _projections: header_ctx, item
        element = ctor(
            "python:loop.item",
            [
                str_const(self.target_cid),
                *(
                    ()
                    if iterable is None
                    else (iterable.to_term(owner="LoopRecurrenceSugar"),)
                ),
            ],
            symbol_kind="coordinate",
        )
        with item():
            header_ctx = self._enter_header(runtime, ctx, starts, decide=False)
            projected = self._project_iteration_target(
                pattern, SymbolicValue(element), header_ctx
            )
        projected = ExitSet(
            tuple(
                replace(exit_, state=ctx) if isinstance(exit_, Halted) else exit_
                for exit_ in projected.exits
            )
        ).normalize()

        def enter(projections):
            # Each completed arm binds its own leaves, inside the item.
            with item():
                return self._enter_target(runtime, header_ctx, projections)[0]

        return projected, enter, item

    def _leave_target(self, runtime, ctx, items):
        """Bind, outside every item, each target leaf's key to the last
        item's projection of it (item ``items - 1``): the value the ``else``
        suite reads the target as.  A carried target's header is the same
        key, and ``_enter_header`` binds it after this to what the last item
        handed on.  With no item, nothing is bound: the target was never
        assigned.  A ``while`` has no target: nothing is bound."""
        from sugar_lift_py_tests.occurrence import entered, loop_iteration_segment
        from sugar_lift_py_tests.sugar.evaluation_ref_sugar import evaluation_here
        from sugar_lift_py_tests.temporal import bind_temporal

        temporal = getattr(ctx, "temporal", None)
        if (
            temporal is None
            or items < 1
            or getattr(runtime, "target_pattern", None) is None
        ):
            return ctx
        keys = tuple(self._target_keys(runtime).values())
        with entered(loop_iteration_segment(self.target_cid, items - 1)):
            last = tuple(
                temporal.value_if_bound(evaluation_here(key)) for key in keys
            )
        for key, value in zip(keys, last, strict=True):
            if value is None:
                continue
            ctx = bind_temporal(
                ctx,
                evaluation_here(key),
                value,
                owner="LoopRecurrenceSugar.target-after-items",
                blame=str(self.site),
            )
        return ctx

    def _latched(self, runtime, ctx, index):
        """The value of each carried name item ``index`` hands on: the latest
        of every write of it in the body (``x += e``, a walrus ``(x := e)``,
        an assignment, a nested loop's publication) and this item's header
        (``_latest_written``).  Read inside item ``index``, so each key is
        that item's.  The loop publishes the last item's latch under its own
        key of the name (``post_binding_keys``), which is what a read after
        the loop reads
        (a walrus's included: ``_substitute_body_tracked``)."""
        from sugar_lift_py_tests.occurrence import entered, loop_iteration_segment

        temporal = getattr(ctx, "temporal", None)
        if temporal is None:
            # Nothing to latch from: the next item and the publication are
            # handed nothing, and refuse by name (``_require_carried``).
            return None
        with entered(loop_iteration_segment(self.target_cid, index)):
            return self._latest_written(runtime, temporal, else_suite=False)

    def _after_else(self, runtime, ctx):
        """The value of each carried name the loop leaves with after its
        ``else`` suite: the latest of every write of it in the suite and the
        header the suite read it through (bound by ``_finish_iterator`` to
        what the last item handed on).  Read where the suite ran, outside
        every item."""
        temporal = getattr(ctx, "temporal", None)
        if temporal is None:
            raise TypeError("loop recurrence omitted its temporal context")
        return self._latest_written(runtime, temporal, else_suite=True)

    def _latest_written(self, runtime, temporal, *, else_suite):
        """Per carried name, the binding bound last of the keys every write of
        it binds (the body's, or the ``else`` suite's:
        ``LiveForRuntimeV1.carried_evaluations``) and the header's, qualified
        by the reduction running now (``evaluation_here``).  A write never
        binds the name, and the name is never read: the latest write is the
        one that ran last on the path taken, wherever it sits (an arm of an
        ``if``, before a ``continue``).  A loop target's header is its
        per-item key, bound to the item's projection after the header
        (``_enter_target``)."""
        from sugar_lift_py_tests.sugar.evaluation_ref_sugar import evaluation_here

        values = []
        for header, writes, else_writes in self._carried_evaluations(runtime):
            keys = tuple(
                evaluation_here(key) for key in (else_writes if else_suite else writes)
            )
            starts = () if header is None else (evaluation_here(header),)
            binding = temporal.latest(*keys, *starts)
            values.append(None if binding is None else binding.value)
        return tuple(values)

    def _project_iteration_target(self, pattern, value, ctx):
        """Project every target leaf through the Floor-owned unpack door.

        Completes with ``(name, coordinate, value)`` per leaf, in source
        order; each unpack's halt is an arm beside it, nothing bound.  An
        item with authenticated members answers one plain roster or halts;
        one without (the symbolic item, a concrete item's symbolic member)
        answers both faces of its runtime unpack (``runtime_unpack_faces``):
        the leaves are read from each completed arm (``ExitSet.sequence``),
        beneath its guard and carrying what it owes, and an inner unpack's
        halt is an arm beneath the outer one's."""
        from sugar_lift_py_tests.operations.positional_unpack_operation import (
            PositionalUnpackOperation,
            UnpackMemberRoster,
        )
        from sugar_lift_py_tests.outcome.exit_set import _require_exit_set
        from sugar_source_tree.nodes import List, Name, Tuple_

        coordinates = {
            coordinate.projection_path: coordinate
            for coordinate in pattern.target_coordinates
        }

        def project(target, current, path=()):
            if isinstance(target, Name):
                coordinate = coordinates[("target", *path)]
                return ExitSet.completed(((target.id, coordinate.cid, current),))
            if not isinstance(target, (Tuple_, List)):
                raise TypeError("live for target contains an unsupported target leaf")
            operation = PositionalUnpackOperation(
                fixed_prefix=len(target.elts),
                fixed_suffix=0,
                has_star=False,
                owner="LoopRecurrenceSugar.target",
                blame=target.fragment,
            )
            unpacked = _require_exit_set(
                operation.submit(current, ctx), owner="LoopRecurrenceSugar.target"
            )
            # A roster owing something has no linear place for the debt: it is
            # refused with every other shape, never carried on without it.
            if unpacked.owed_items():
                raise TypeError(
                    "positional target unpack omitted its authenticated roster"
                )

            def leaves(roster):
                if not isinstance(roster, UnpackMemberRoster):
                    raise TypeError(
                        "positional target unpack omitted its authenticated roster"
                    )
                if (
                    roster.occurrence is not target.fragment
                    or roster.demand_cid != operation.demand_cid()
                    or len(roster.members) != len(target.elts)
                ):
                    raise TypeError(
                        "positional target unpack returned cross-wired testimony"
                    )

                def collect(index, bindings):
                    if index == len(target.elts):
                        return ExitSet.completed(bindings)
                    # A child's halt is an arm as it is; its leaves join the
                    # siblings' on each completed arm.
                    return project(
                        target.elts[index], roster.members[index], (*path, index)
                    ).sequence(
                        lambda child: collect(index + 1, (*bindings, *child))
                    )

                return collect(0, ())

            return unpacked.sequence(leaves)

        return project(pattern.target, value)

    @staticmethod
    def _require_loop_control_state(state, *, target_bindings):
        """Authenticate the producer's exact current reduction context.

        A loop-control halt carries the context it received at its source
        occurrence.  The current target Floor was bound into that context by
        this recurrence, under the target's per-item key and its binding
        coordinate (``_enter_target``), so object identity authenticates the
        context without rebuilding a reduced block or accepting an
        ambient/foreign scope.
        """
        from sugar_lift_py_tests.context.reduce_context import ReduceContext

        if not isinstance(state, ReduceContext):
            raise TypeError("loop control omitted its exact ReduceContext state")
        for target_key, coordinate_cid, target_value in target_bindings:
            if (
                state.temporal.value_if_bound(target_key) is not target_value
                or state.temporal.value_if_bound(coordinate_cid) is not target_value
            ):
                raise TypeError(
                    "loop control state lacks exact iteration target identity"
                )
        return state

    def _finish_iterator(self, runtime, ctx, *, entries, carried, items=0):
        """The loop's outcome after its ``items`` items were exhausted."""
        from sugar_lift_py_tests.caller_parameter_contract import (
            NativeOperationExitCarrierV1,
        )
        from sugar_lift_py_tests.outcome.exit_set import _require_exit_set
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            reduce_block_to_exitset,
        )

        if not runtime.else_sugars:
            # The loop leaves with what the last item handed on (or the
            # pre-loop values when there was no item).
            return self._publish_runtime_bindings(
                runtime, ctx, entries=entries, carried=carried, items=items
            )
        # The else runs once, after every item.  It reads each carried name
        # through the header, bound here, outside every item, to what the last
        # item handed on (``carried``), and the target through its key, bound
        # here to the last item's projection (``_leave_target``; a carried
        # target's is its header); the loop leaves with the latest of the
        # else's writes of each name and that header (``_after_else``).
        otherwise = reduce_block_to_exitset(
            runtime.else_sugars,
            self._enter_header(
                runtime, self._leave_target(runtime, ctx, items), carried
            ),
        )

        def publish(otherwise):
            # The published bindings run beneath every completed face of the
            # else suite (``ExitSet.sequence``): each takes that face's guard
            # and faces and owes what it owes; a halt leaves as it is.
            return otherwise.sequence(
                lambda state: self._publish_runtime_bindings(
                    runtime,
                    state.context,
                    entries=(*entries, *state.entries),
                    carried=self._after_else(runtime, state.context),
                    fall_through=state.fall_through,
                    can_fall_through=state.can_fall_through,
                    items=items,
                    else_ran=True,
                )
            )

        if isinstance(otherwise, NativeOperationExitCarrierV1):
            # The else suite still waits on its caller's actuals: once it
            # discharges, the loop publishes beneath each of its faces exactly
            # as it does beneath a suite that reduced to its faces here.
            return otherwise.after_discharge(
                lambda projected: publish(
                    _require_exit_set(projected, owner="LoopRecurrenceSugar.else")
                )
            )
        return publish(_require_exit_set(otherwise, owner="LoopRecurrenceSugar.else"))

    def _publish_runtime_bindings(
        self,
        runtime,
        ctx,
        *,
        entries,
        carried,
        fall_through=(),
        can_fall_through=True,
        items=0,
        else_ran=False,
    ):
        """Publish the value of each name carried under a binding coordinate
        (``_coordinate_names``) as the loop leaves: ``carried``,
        what the leaving item (``_latched``) or the ``else`` suite
        (``_after_else``) left it with; handed nothing, refused by name
        (``_require_carried``).  The value is published under the loop's own
        key of the name only (``post_binding_keys``): every read after the
        loop is a ``LoopBindingRef`` to it (``project_loop_post_binding``),
        and neither the name nor its binding coordinate is written or read.
        The iterable's walrus writes of the names the loop does not carry
        (``iterable_writes``) are published
        first, under their keys: the iterable ran before every item.  Each
        name the items write that the loop does not carry under a binding
        coordinate (a name first bound in the loop, a module binding) is
        published last, under its post-loop key, with its write slot decided
        on this exit (``_post_loop_writes``): ``items`` items ran, and the
        ``else`` suite ran when ``else_ran``."""
        from sugar_lift_py_tests.floor.block_value import BlockValue

        temporal = getattr(ctx, "temporal", None)
        if temporal is None:
            raise TypeError("loop recurrence omitted its temporal context")
        carried = dict(
            zip(
                runtime.carried_names,
                self._require_carried(runtime, carried),
                strict=True,
            )
        )
        values = []
        for name in self._coordinate_names(runtime):
            value = carried[name]
            if value is None:
                raise TypeError("loop recurrence omitted a carried binding")
            values.append(value)
        posted = self._post_loop_writes(
            runtime, temporal, items=items, else_suite=else_ran
        )
        return ExitSet.completed(
            BlockValue(
                (
                    *self.iterable_writes,
                    *entries,
                    *self._publication(tuple(values), posted),
                ),
                fall_through=fall_through,
                can_fall_through=can_fall_through,
            )
        )

    def _recurrence_head(self, key):
        """The recurrence's value of the name a read after the loop reads
        through ``key`` (a binding coordinate or a post-loop key): the loop's
        symbolic fixed point of it (``python:loop.recurrence``)."""
        return ctor(
            "python:loop.recurrence",
            [str_const(self.target_cid), str_const(key)],
            symbol_kind="coordinate",
        )

    def _publication(self, coordinate_values, posted):
        """What the loop leaves bound for a read after it, on every exit it
        publishes on, concrete or symbolic: each coordinate name's value
        (``coordinate_values``, ``binding_coordinate_cids`` order) under the
        loop's own key of it (``post_binding_keys``), bound outside every
        item of this loop (``evaluation_here``) -- every read after the loop
        is a ``LoopBindingRef`` to it (``project_loop_post_binding``), and
        no other loop binds it, so a read after this loop never finds another
        loop's value of the name -- then, per name published
        through its post-loop key, ``(post_key, value, wrote)``
        (``_post_loop_writes``): the post-loop key bound outside every item
        (``evaluation_here``) to ``value`` where ``value`` is not None, and
        the name's write slot (``loop_write_slot``) decided by ``wrote``.  A
        ``bool`` decides the slot on this exit (``BranchResultDecision``): a
        concrete loop knows whether an item wrote it.  A formula authenticates
        the slot as that guard (``BranchResultAuthentication``): the symbolic
        recurrence does not know, so a read after the loop
        (``nodes._live_loop_publication``) takes the post-loop key under the
        guard and the binding before the loop (unbound when there was none)
        under its negation.  The name is never written nor read."""
        from sugar_lift_py_tests.floor.branch_result_coordinate import (
            BranchResultAuthentication,
            BranchResultDecision,
        )
        from sugar_lift_py_tests.floor.scope_rebind import ScopeRebind
        from sugar_lift_py_tests.sugar.evaluation_ref_sugar import evaluation_here
        from sugar_source_tree.binding_state import loop_write_slot

        published = [
            ScopeRebind(evaluation_here(post_key), value)
            for post_key, value in zip(
                self.post_binding_keys, coordinate_values, strict=True
            )
        ]
        for post_key, value, wrote in posted:
            if value is not None:
                published.append(ScopeRebind(evaluation_here(post_key), value))
            slot = loop_write_slot(post_key)
            published.append(
                BranchResultDecision(slot, wrote, self.site)
                if isinstance(wrote, bool)
                else BranchResultAuthentication(slot, wrote, self.site)
            )
        return tuple(published)

    def _post_loop_writes(self, runtime, temporal, *, items, else_suite):
        """``(post_key, value, wrote)`` (``_publication``) for each name the
        items write that the loop does not carry
        (``LiveForRuntimeV1.published_evaluations``): ``value`` is the latest
        write of the name on the path the loop leaves by -- the ``else``
        suite's when it ran and wrote it, else that of the last of the
        ``items`` items that wrote it (each item's writes are keyed by that
        item) -- and ``wrote`` whether there was one.  A read after the loop
        reads the name through the post-loop key, as a function-level live
        loop's ``else`` reads its target's and header's keys bound after the
        last item (``_leave_target``, ``_enter_header``).  A name no item and
        no ``else`` wrote binds nothing, and its write slot is decided false
        on this exit: the read takes the binding before the loop."""
        from sugar_lift_py_tests.occurrence import entered, loop_iteration_segment
        from sugar_lift_py_tests.sugar.evaluation_ref_sugar import evaluation_here

        posted = []
        for post_key, writes, else_writes in getattr(
            runtime, "published_evaluations", ()
        ):
            binding = None
            if else_suite and else_writes:
                binding = temporal.latest(
                    *(evaluation_here(key) for key in else_writes)
                )
            index = items - 1
            while binding is None and index >= 0 and writes:
                with entered(loop_iteration_segment(self.target_cid, index)):
                    keys = tuple(evaluation_here(key) for key in writes)
                binding = temporal.latest(*keys)
                index -= 1
            posted.append(
                (
                    post_key,
                    None if binding is None else binding.value,
                    binding is not None,
                )
            )
        return tuple(posted)


@dataclass(frozen=True, eq=False)
class _WhileTest:
    """One face of a live ``while``'s test in one item: the truth of the
    test's value as a guard (None when it is not one value), the context the
    body runs in (after the test: a walrus in it is bound), and, for a true
    face, the body reduced there."""

    formula: object
    ctx: object
    body: object = None
