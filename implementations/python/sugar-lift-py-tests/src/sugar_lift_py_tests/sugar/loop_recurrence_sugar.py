from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.floor import SymbolicValue
from sugar_lift_py_tests.ir import atomic, ctor, not_, or_, str_const
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
    target_cid: str
    binding_coordinate_cid: str
    completion_kind: str
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
        temporal = getattr(ctx, "temporal", None) if ctx is not None else None
        if temporal is not None:
            bound = temporal.value_if_bound(self.binding_coordinate_cid)
            if bound is not None:
                return ExitSet.completed(bound)
        return ExitSet.completed(
            SymbolicValue(self.to_term(owner="LoopBindingRefSugar"))
        )


@dataclass(frozen=True)
class LoopRecurrenceSugar(ConstructedTermSugar):
    target_cid: str
    loop_construction_cid: str
    binding_coordinate_cids: tuple[str, ...]
    outward_faces: tuple[object, ...]
    construction: object = field(compare=False)
    site: object = field(compare=False)

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

        iterable_sugar = self.construction.iterable_sugar
        iterable_cid = self.construction.iterable_value_construction_cid
        if iterable_cid is None:
            return self._desugar_with_iterable(None, ctx)
        if iterable_sugar is None:
            raise LoopWireError("for recurrence omitted its live iterable sugar")
        if iterable_sugar.site.seal().cid != iterable_cid:
            raise LoopWireError("loop recurrence iterable occurrence mismatch")
        return iterable_sugar.desugar(ctx).and_then(
            lambda iterable: self._desugar_with_iterable(iterable, ctx)
        )

    def _desugar_with_iterable(self, iterable, ctx):
        runtime = self.construction.loop_runtime
        from sugar_lift_py_tests.floor import SymbolicValue

        if (
            iterable is not None
            and runtime is not None
            and not isinstance(iterable, SymbolicValue)
        ):
            from sugar_lift_py_tests.caller_parameter_contract import (
                NativeOperationExitCarrierV1,
            )
            from sugar_lift_py_tests.operations.iterator_operation import (
                IteratorOperation,
            )
            from sugar_lift_py_tests.sugar.evaluation_ref_sugar import (
                evaluation_here,
            )
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
                initial = sugar.desugar(runtime_ctx)
                if isinstance(initial, NativeOperationExitCarrierV1):
                    return initial
                initial_value = initial.completed_value()
                # Only one unconditional value owing nothing is bound and
                # carried on; any other shape (a halt, several faces, an arm
                # that owes) is returned whole, with every arm it has.
                if initial_value is None or initial.owed_items():
                    return initial
                # The pre-loop value is bound under the header's key where
                # the loop stands (``evaluation_here``), outside every item of
                # it: the header's evaluation before the first item.  The
                # name is never written; each item binds its own header to
                # what it begins with (``_enter_header``).
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
            carried = tuple(initial_values)
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

        recurrences = []
        for coordinate_cid in self.binding_coordinate_cids:
            h = ctor(
                "python:loop.recurrence",
                [str_const(self.target_cid), str_const(coordinate_cid)],
                symbol_kind="coordinate",
            )
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
        recurrence = BlockValue(tuple(recurrences), can_fall_through=True)
        if not self.outward_faces:
            return ExitSet.completed(recurrence)

        from sugar_lift_py_tests.outcome import Completed

        halted_guards = [face.guard for face in self.outward_faces]
        completed_guard = not_(
            halted_guards[0] if len(halted_guards) == 1 else or_(halted_guards)
        )
        from sugar_lift_py_tests.caller_parameter_contract import (
            NativeOperationExitCarrierV1,
        )

        exits = [Completed(completed_guard, recurrence)]
        deferred = []
        for face in self.outward_faces:
            outcome = face.statement_sugar.desugar(ctx)
            if isinstance(outcome, NativeOperationExitCarrierV1):
                # The face's statement waits for the caller's actuals (a
                # method call on a formal): it contributes its partition
                # under its own guard once they discharge it.
                marker = _DeferredOutwardFace(len(deferred))
                deferred.append(
                    outcome.after_discharge(
                        lambda projected, *, face=face: ExitSet(
                            _outward_face_partition(projected, face)
                        )
                    )
                )
                exits.append(Completed(face.guard, marker))
                continue
            # Every face the statement reduced to, under the outward face's
            # guard: a return is the face's one block entry, a halt keeps the
            # face's state, and each arm keeps what it owes. One return value
            # or one effect is the one-arm case of the same partition; a return
            # whose expression PARTITIONS (`return d.setdefault(k, v)`), a
            # guarded return, or a return that owes a parameter contract
            # (`return p[0]`) is not a missing wire -- each is a partition the
            # face contributes under its own guard, which is what
            # `BindingStateWireGap: loop outward face did not construct return
            # or raise testimony` was refusing to state.
            exits.extend(_outward_face_partition(outcome, face, guarded=True))
        if deferred:

            def select(value):
                if isinstance(value, _DeferredOutwardFace):
                    return deferred[value.index]
                return ExitSet.completed(value)

            return NativeOperationExitCarrierV1.compose_prefix(
                ExitSet(tuple(exits)), select
            )
        return ExitSet(tuple(exits)).normalize()

    def _advance_iterator(self, iterator, runtime, ctx, *, entries, carried, index=0):
        """Run item ``index`` of the live loop.

        ``carried`` is the value of each carried name (``runtime.carried_names``
        order) the item begins with: the pre-loop values for the first item,
        the previous item's latch (``_latched``) after it.  An item handed
        nothing for the names it carries is refused by name
        (``_require_carried``): the names are never read in its place.
        """
        from sugar_lift_py_tests.caller_parameter_contract import (
            NativeOperationExitCarrierV1,
        )
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

        projected = self._project_iteration_target(
            runtime.target_pattern, next_result.value, ctx
        )
        if projected.exits and projected.halts() == projected.exits:
            # Assignment has not begun: the positional-unpack Floor owns the
            # halt and the exact context entering this iteration is its state.
            return ExitSet(
                tuple(replace(face, state=ctx) for face in projected.halts())
            ).normalize()
        projections = projected.completed_value()
        if projections is None or projected.owed_items():
            return projected
        from sugar_lift_py_tests.occurrence import entered, loop_iteration_segment

        # Each iteration is its own evaluation of the body's sites: a call in
        # iteration 2 is never claimed to complete exactly when iteration 1's
        # did (the unrolled loop's law, sugar/loop iteration segments).  Its
        # statement evaluations are its own keys too (``evaluation_here``),
        # its reads of a carried name read this item's header, and its reads
        # of the target read this item's projection, bound under the target's
        # key after the header (a carried target's header is that key).
        with entered(loop_iteration_segment(self.target_cid, index)):
            iteration_ctx = self._enter_header(runtime, ctx, carried)
            iteration_ctx, target_bindings = self._enter_target(
                runtime, iteration_ctx, projections
            )
            body = reduce_block_to_exitset(runtime.body_sugars, iteration_ctx)

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
                        state, next_result, runtime, entries=entries, index=index
                    ),
                    consume=lambda halt: self._after_loop_control(
                        halt,
                        next_result,
                        runtime,
                        target_bindings,
                        entries=entries,
                        index=index,
                    ),
                )
            face = body.exits[0]
            following = self._after_iteration_face(
                face,
                next_result,
                runtime,
                target_bindings,
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
        self, face, next_result, runtime, target_bindings, *, entries, index
    ):
        """The loop's outcome after one face of an iteration, or None when the
        face leaves the loop as it is (a halt that is not this loop's control)."""
        from sugar_lift_py_tests.outcome import Halted

        if isinstance(face, Halted):
            return self._after_loop_control(
                face,
                next_result,
                runtime,
                target_bindings,
                entries=entries,
                index=index,
            )
        return self._after_iteration_state(
            face.value, next_result, runtime, entries=entries, index=index
        )

    def _after_loop_control(
        self, halt, next_result, runtime, target_bindings, *, entries, index
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
                return self._advance_iterator(
                    next_result.advanced,
                    runtime,
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
                )
        return None

    def _after_iteration_state(self, state, next_result, runtime, *, entries, index):
        """The loop's outcome after a completed iteration face whose record is
        ``state``."""
        from sugar_lift_py_tests.floor.block_value import BlockValue

        combined = (*entries, *state.entries)
        if not state.can_fall_through:
            return ExitSet.completed(BlockValue(combined, can_fall_through=False))
        return self._advance_iterator(
            next_result.advanced,
            runtime,
            state.context,
            entries=combined,
            carried=self._latched(runtime, state.context, index),
            index=index + 1,
        )

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

    def _enter_header(self, runtime, ctx, carried):
        """Bind the header evaluation of each carried name: the value an item
        begins with (``carried``), under the header's key qualified by where
        it is bound (``evaluation_here``): inside an item (the caller has
        entered it), that item's header; after the last item, the header the
        ``else`` suite reads, outside every item.  The body's and the else's
        reads of a carried name are references to it (``For.substitute``)."""
        from sugar_lift_py_tests.sugar.evaluation_ref_sugar import evaluation_here
        from sugar_lift_py_tests.temporal import bind_temporal

        carried = self._require_carried(runtime, carried)
        if ctx is None:
            return ctx
        for (header, _writes, _else_writes), value in zip(
            self._carried_evaluations(runtime), carried, strict=True
        ):
            if header is None or value is None:
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

    def _leave_target(self, runtime, ctx, items):
        """Bind, outside every item, each target leaf's key to the last
        item's projection of it (item ``items - 1``): the value the ``else``
        suite reads the target as.  A carried target's header is the same
        key, and ``_enter_header`` binds it after this to what the last item
        handed on.  With no item, nothing is bound: the target was never
        assigned."""
        from sugar_lift_py_tests.occurrence import entered, loop_iteration_segment
        from sugar_lift_py_tests.sugar.evaluation_ref_sugar import evaluation_here
        from sugar_lift_py_tests.temporal import bind_temporal

        temporal = getattr(ctx, "temporal", None)
        if temporal is None or items < 1:
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
        that item's.  The loop publishes the last item's latch under the
        name's binding coordinate, which is what a read after the loop reads
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
        """Project every target leaf through the Floor-owned unpack door."""
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
            if unpacked.exits and unpacked.halts() == unpacked.exits:
                return unpacked
            roster = unpacked.completed_value()
            # A roster owing something has no linear place for the debt: it is
            # refused with every other shape, never carried on without it.
            if not isinstance(roster, UnpackMemberRoster) or unpacked.owed_items():
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
            bindings = []
            for index, (child, member) in enumerate(
                zip(target.elts, roster.members, strict=True)
            ):
                child_result = project(child, member, (*path, index))
                child_bindings = child_result.completed_value()
                if child_bindings is None:
                    return child_result
                bindings.extend(child_bindings)
            return ExitSet.completed(tuple(bindings))

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
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            reduce_block_to_exitset,
        )
        from sugar_lift_py_tests.outcome import Completed, ExitSet

        if not runtime.else_sugars:
            # The loop leaves with what the last item handed on (or the
            # pre-loop values when there was no item).
            return self._publish_runtime_bindings(
                runtime, ctx, entries=entries, carried=carried
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
        if not isinstance(otherwise, ExitSet) or len(otherwise.exits) != 1:
            return otherwise
        if not isinstance(otherwise.exits[0], Completed):
            return otherwise
        # The published bindings run beneath the else suite's one completed
        # face: they take its guard and faces and owe what it owes.
        return otherwise.sequence(
            lambda state: self._publish_runtime_bindings(
                runtime,
                state.context,
                entries=(*entries, *state.entries),
                carried=self._after_else(runtime, state.context),
                fall_through=state.fall_through,
                can_fall_through=state.can_fall_through,
            )
        )

    def _publish_runtime_bindings(
        self,
        runtime,
        ctx,
        *,
        entries,
        carried,
        fall_through=(),
        can_fall_through=True,
    ):
        """Publish each carried name's value as the loop leaves: ``carried``,
        what the leaving item (``_latched``) or the ``else`` suite
        (``_after_else``) left it with; handed nothing, refused by name
        (``_require_carried``).  The value is published under the name's
        binding coordinate only: every read after the loop is a
        ``LoopBindingRef`` to it (``project_loop_post_binding``), and the
        name is never written nor read."""
        from sugar_lift_py_tests.floor.block_value import BlockValue
        from sugar_lift_py_tests.floor.scope_rebind import ScopeRebind

        temporal = getattr(ctx, "temporal", None)
        if temporal is None:
            raise TypeError("loop recurrence omitted its temporal context")
        carried = self._require_carried(runtime, carried)
        projected = []
        for value, coordinate_cid in zip(
            carried, self.binding_coordinate_cids, strict=True
        ):
            if value is None:
                raise TypeError("loop recurrence omitted a carried binding")
            projected.append(ScopeRebind(coordinate_cid, value))
        return ExitSet.completed(
            BlockValue(
                (*entries, *projected),
                fall_through=fall_through,
                can_fall_through=can_fall_through,
            )
        )


@dataclass(frozen=True)
class _DeferredOutwardFace:
    """Stands for an outward face whose statement a caller's actuals select."""

    index: int


def _outward_face_partition(outcome, face, *, guarded=False):
    """The exits one outward face contributes: each return is the face's one
    block entry, each halt keeps the face's state."""
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.outcome import Completed, Halted
    from sugar_lift_py_tests.outcome.exit_set import _require_exit_set

    # A deferred face is enrolled by its caller through ``after_discharge``;
    # one that reaches here undischarged is refused by name.
    exits = _require_exit_set(outcome, owner="LoopRecurrenceSugar.outward_face")
    if guarded:
        exits = exits.guarded(face.guard)
    partition = []
    for exit_ in exits.exits:
        if isinstance(exit_, Halted):
            partition.append(
                Halted(exit_.guard, exit_.effect, face.state, owed=exit_.owed)
            )
            continue
        partition.append(
            Completed(
                exit_.guard,
                BlockValue((exit_.value,), can_fall_through=False),
                owed=exit_.owed,
            )
        )
    return tuple(partition)
