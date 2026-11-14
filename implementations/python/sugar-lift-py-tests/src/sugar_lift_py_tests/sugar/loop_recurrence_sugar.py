from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.floor import SymbolicValue
from sugar_lift_py_tests.ir import atomic, ctor, not_, or_, str_const
from sugar_lift_py_tests.outcome import Complete
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
                return Complete(bound)
        return Complete(SymbolicValue(self.to_term(owner="LoopBindingRefSugar")))


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
            from sugar_lift_py_tests.operations.iterator_operation import (
                IteratorOperation,
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
            for name, sugar in zip(
                runtime.carried_names, runtime.initial_value_sugars, strict=True
            ):
                initial = sugar.desugar(runtime_ctx)
                if not isinstance(initial, Complete):
                    return initial
                runtime_ctx = bind_temporal(
                    runtime_ctx,
                    name,
                    initial.value,
                    owner="LoopRecurrenceSugar",
                    blame=str(self.site),
                )
            return (
                IteratorOperation(owner="LoopRecurrenceSugar", blame=self.site)
                .submit(iterable, runtime_ctx)
                .and_then(
                    lambda iterator: self._advance_iterator(
                        iterator, runtime, runtime_ctx, entries=()
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
            return Complete(recurrence)

        from sugar_lift_py_tests.floor import ReturnValue
        from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted, Incomplete

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
            if isinstance(outcome, Complete) and isinstance(outcome.value, ReturnValue):
                exits.append(
                    Completed(
                        face.guard,
                        BlockValue((outcome.value,), can_fall_through=False),
                    )
                )
            elif isinstance(outcome, Incomplete):
                exits.append(Halted(face.guard, outcome.effect, face.state))
            else:
                # The face reduced to something richer than one return value or
                # one effect: a return whose expression PARTITIONS (`return
                # d.setdefault(k, v)`), a guarded return, or a return that owes a
                # parameter contract (`return p[0]`). None of those is a missing
                # wire -- each is a partition the face contributes under its own
                # guard, which is what `BindingStateWireGap: loop outward face did
                # not construct return or raise testimony` was refusing to state.
                exits.extend(_outward_face_partition(outcome, face, guarded=True))
        if deferred:

            def select(value):
                if isinstance(value, _DeferredOutwardFace):
                    return deferred[value.index]
                return Complete(value)

            return NativeOperationExitCarrierV1.compose_prefix(
                ExitSet(tuple(exits)), select
            )
        return ExitSet(tuple(exits)).normalize()

    def _advance_iterator(self, iterator, runtime, ctx, *, entries, index=0):
        from sugar_lift_py_tests.effect.loop_control_effect import LoopControlEffect
        from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
        from sugar_lift_py_tests.floor.block_value import BlockValue
        from sugar_lift_py_tests.floor.iterator_value import NextResult
        from sugar_lift_py_tests.operations.next_operation import NextOperation
        from sugar_lift_py_tests.outcome import (
            Complete,
            Completed,
            ExitSet,
            Halted,
            Incomplete,
        )
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            reduce_block_to_exitset,
        )
        from sugar_lift_py_tests.temporal import bind_temporal

        outcome = NextOperation(owner="LoopRecurrenceSugar", blame=self.site).submit(
            iterator, ctx
        )
        if isinstance(outcome, Incomplete):
            effect = outcome.effect
            if isinstance(effect, RaiseEffect) and _is_authenticated_stop_iteration(
                effect
            ):
                return self._finish_iterator(runtime, ctx, entries=entries)
            return outcome
        if not isinstance(outcome, Complete) or not isinstance(
            outcome.value, NextResult
        ):
            raise TypeError(
                "NextOperation must produce NextResult or a named exception"
            )

        next_result = outcome.value
        projected = self._project_iteration_target(
            runtime.target_pattern, next_result.value, ctx
        )
        if isinstance(projected, Incomplete):
            # Assignment has not begun: the positional-unpack Floor owns the
            # halt and the exact context entering this iteration is its state.
            return ExitSet.halted(projected.effect, state=ctx)
        if not isinstance(projected, Complete):
            return projected
        target_bindings = projected.value
        iteration_ctx = ctx
        for name, coordinate_cid, value in target_bindings:
            iteration_ctx = bind_temporal(
                iteration_ctx,
                name,
                value,
                owner="LoopRecurrenceSugar",
                blame=str(self.site),
            )
            iteration_ctx = bind_temporal(
                iteration_ctx,
                coordinate_cid,
                value,
                owner="LoopRecurrenceSugar.target-coordinate",
                blame=str(self.site),
            )
        from sugar_lift_py_tests.occurrence import entered, loop_iteration_segment

        # Each iteration is its own evaluation of the body's sites: a call in
        # iteration 2 is never claimed to complete exactly when iteration 1's
        # did (the unrolled loop's law, sugar/loop iteration segments).
        with entered(loop_iteration_segment(self.target_cid, index)):
            body = reduce_block_to_exitset(
                tuple(statement.sugar() for statement in runtime.body_statements),
                iteration_ctx,
            )
        if not isinstance(body, ExitSet):
            return body
        if len(body.exits) != 1:
            # Each face of this iteration is its own path: a halt leaves the
            # loop under its guard, a completed face carries its own state into
            # the next iteration under its guard. The first iteration's faces
            # are never the loop's outcome.
            from sugar_lift_py_tests.outcome.exit_set import outcome_to_exitset

            exits = []
            for face in body.exits:
                following = self._after_iteration_face(
                    face,
                    next_result,
                    runtime,
                    target_bindings,
                    entries=entries,
                    index=index,
                )
                if following is None:
                    exits.append(face)
                    continue
                exits.extend(outcome_to_exitset(following).guarded(face.guard).exits)
            return ExitSet(tuple(exits)).normalize()
        face = body.exits[0]
        following = self._after_iteration_face(
            face, next_result, runtime, target_bindings, entries=entries, index=index
        )
        return body if following is None else following

    def _after_iteration_face(
        self, face, next_result, runtime, target_bindings, *, entries, index
    ):
        """The loop's outcome after one face of an iteration, or None when the
        face leaves the loop as it is (a halt that is not this loop's control)."""
        from sugar_lift_py_tests.effect.loop_control_effect import LoopControlEffect
        from sugar_lift_py_tests.floor.block_value import BlockValue
        from sugar_lift_py_tests.outcome import Complete, Completed, Halted

        if isinstance(face, Halted):
            effect = face.effect
            if (
                isinstance(effect, LoopControlEffect)
                and effect.target_cid == self.target_cid
            ):
                state = self._require_loop_control_state(
                    face.state,
                    target_bindings=target_bindings,
                )
                if effect.action == "continue":
                    return self._advance_iterator(
                        next_result.advanced,
                        runtime,
                        state,
                        entries=entries,
                        index=index + 1,
                    )
                if effect.action == "break":
                    return self._publish_runtime_bindings(
                        runtime, state, entries=entries
                    )
            return None
        if not isinstance(face, Completed):
            return None
        state = face.value
        combined = (*entries, *state.entries)
        if not state.can_fall_through:
            return Complete(BlockValue(combined, can_fall_through=False))
        return self._advance_iterator(
            next_result.advanced,
            runtime,
            state.context,
            entries=combined,
            index=index + 1,
        )

    def _project_iteration_target(self, pattern, value, ctx):
        """Project every target leaf through the Floor-owned unpack door."""
        from sugar_lift_py_tests.operations.positional_unpack_operation import (
            PositionalUnpackOperation,
            UnpackMemberRoster,
        )
        from sugar_lift_py_tests.outcome import Complete, Incomplete
        from sugar_source_tree.nodes import List, Name, Tuple_

        coordinates = {
            coordinate.projection_path: coordinate
            for coordinate in pattern.target_coordinates
        }

        def project(target, current, path=()):
            if isinstance(target, Name):
                coordinate = coordinates[("target", *path)]
                return Complete(((target.id, coordinate.cid, current),))
            if not isinstance(target, (Tuple_, List)):
                raise TypeError("live for target contains an unsupported target leaf")
            operation = PositionalUnpackOperation(
                fixed_prefix=len(target.elts),
                fixed_suffix=0,
                has_star=False,
                owner="LoopRecurrenceSugar.target",
                blame=target.fragment,
            )
            unpacked = operation.submit(current, ctx)
            if isinstance(unpacked, Incomplete):
                return unpacked
            if not isinstance(unpacked, Complete) or not isinstance(
                unpacked.value, UnpackMemberRoster
            ):
                raise TypeError(
                    "positional target unpack omitted its authenticated roster"
                )
            if (
                unpacked.value.occurrence is not target.fragment
                or unpacked.value.demand_cid != operation.demand_cid()
                or len(unpacked.value.members) != len(target.elts)
            ):
                raise TypeError(
                    "positional target unpack returned cross-wired testimony"
                )
            bindings = []
            for index, (child, member) in enumerate(
                zip(target.elts, unpacked.value.members, strict=True)
            ):
                child_result = project(child, member, (*path, index))
                if not isinstance(child_result, Complete):
                    return child_result
                bindings.extend(child_result.value)
            return Complete(tuple(bindings))

        return project(pattern.target, value)

    @staticmethod
    def _require_loop_control_state(state, *, target_bindings):
        """Authenticate the producer's exact current reduction context.

        A loop-control halt carries the context it received at its source
        occurrence.  The current target Floor was bound into that context by
        this recurrence, so object identity authenticates the context without
        rebuilding a reduced block or accepting an ambient/foreign scope.
        """
        from sugar_lift_py_tests.context.reduce_context import ReduceContext

        if not isinstance(state, ReduceContext):
            raise TypeError("loop control omitted its exact ReduceContext state")
        for target_name, coordinate_cid, target_value in target_bindings:
            if (
                state.temporal.value_if_bound(target_name) is not target_value
                or state.temporal.value_if_bound(coordinate_cid) is not target_value
            ):
                raise TypeError(
                    "loop control state lacks exact iteration target identity"
                )
        return state

    def _finish_iterator(self, runtime, ctx, *, entries):
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            reduce_block_to_exitset,
        )
        from sugar_lift_py_tests.outcome import Completed, ExitSet

        if not runtime.else_statements:
            return self._publish_runtime_bindings(runtime, ctx, entries=entries)
        otherwise = reduce_block_to_exitset(
            tuple(statement.sugar() for statement in runtime.else_statements), ctx
        )
        if not isinstance(otherwise, ExitSet) or len(otherwise.exits) != 1:
            return otherwise
        face = otherwise.exits[0]
        if not isinstance(face, Completed):
            return otherwise
        state = face.value
        return self._publish_runtime_bindings(
            runtime,
            state.context,
            entries=(*entries, *state.entries),
            fall_through=state.fall_through,
            can_fall_through=state.can_fall_through,
        )

    def _publish_runtime_bindings(
        self,
        runtime,
        ctx,
        *,
        entries,
        fall_through=(),
        can_fall_through=True,
    ):
        from sugar_lift_py_tests.floor.block_value import BlockValue
        from sugar_lift_py_tests.floor.scope_rebind import ScopeRebind
        from sugar_lift_py_tests.outcome import Complete

        temporal = getattr(ctx, "temporal", None)
        if temporal is None:
            raise TypeError("loop recurrence omitted its temporal context")
        projected = []
        for name, coordinate_cid in zip(
            runtime.carried_names, self.binding_coordinate_cids, strict=True
        ):
            value = temporal.value_if_bound(name)
            if value is None:
                raise TypeError("loop recurrence omitted a carried binding")
            projected.append(ScopeRebind(name, value))
            projected.append(ScopeRebind(coordinate_cid, value))
        return Complete(
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
    from sugar_lift_py_tests.outcome.exit_set import outcome_to_exitset

    exits = outcome_to_exitset(outcome)
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
