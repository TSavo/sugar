"""``except*`` subgroup routing over authenticated ``GroupedRaiseEffect`` trees.

Laws (owned here; ExitSet/carrier untouched):

- Partition each body ``GroupedRaiseEffect`` by authenticated handler type.
- Matching subgroup reaches its handler once (type-tuple = one body run).
- Unmatched residual continues to subsequent handlers in source order.
- Temporal state is an ExitSet of **per-face** handler states — never a single
  scalar accumulator. Each handler face branches the frontier independently.
- Every ExitSet face carries the enclosing body guard conjoined.
- Handler fall-through is **not** a try* completed edge while residual remains;
  residual continues and ultimately halts unless later consumed.
- Exceptional raise effects regroup **only within equal guards** (never AND
  mutually exclusive alternative faces into one impossible guard).
- Finally restore preserves residual; finally terminate overrides.
- Leaf occurrence identities and nested topology survive partition/regroup.
- Ordinary ``RaiseEffect`` under ``except*`` stays loud (distinct from Try).
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field, replace

from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class _StarFace:
    """One except* routing face: residual + temporal state under one guard."""

    guard: object
    residual: object  # GroupedRaiseEffect
    state: object  # _ReducedBlock
    faces: frozenset
    # Exceptional raises collected on THIS face's guard path only.
    exceptional: tuple
    # What the path into this face owes, as ``ExitSet.sequence`` composed it
    # from every handler arm it ran through; every arm emitted from the face
    # carries it.
    owed: tuple


def _matcher_value(matcher, ctx):
    """One ``except*`` type operand's completed value, or None.

    The operand is read here, never retained for a caller: a deferred
    native-operation carrier is refused by name.
    """
    from sugar_lift_py_tests.outcome.exit_set import _require_exit_set

    return _require_exit_set(
        matcher.desugar(ctx), owner="TryStarSugar.handler-matcher"
    ).completed_value()


@dataclass(frozen=True)
class TryStarSugar(Sugar):
    body: tuple
    handlers: tuple
    orelse: tuple = ()
    finalbody: tuple = ()
    site: object = dataclass_field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        from sugar_lift_py_tests.effect.grouped_raise_effect import GroupedRaiseEffect
        from sugar_lift_py_tests.effect_router import (
            regroup_except_star,
            route_except_star,
        )
        from sugar_lift_py_tests.in_flight_effect import bind_in_flight_effect
        from sugar_lift_py_tests.outcome.exit_set import (
            Completed,
            ExitSet,
            Halted,
            _require_exit_set,
            true_guard,
        )
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            _ReducedBlock,
            reduce_block_to_exitset,
        )
        from sugar_source_tree.panic import SugarNotWritten

        body = reduce_block_to_exitset(self.body, ctx)

        def after_body(value):
            if self.orelse:
                return reduce_block_to_exitset(self.orelse, ctx)
            return ExitSet.completed(value)

        def handled(exit_):
            """The continuation beneath one body halt the try* owns.

            Built from the halt's point on: the frontier starts under truth,
            with no faces and owing nothing, and ``sequence`` conjoins the
            body halt's guard, faces and ``owed`` onto every arm answered here.
            """
            if not isinstance(exit_.effect, GroupedRaiseEffect):
                raise SugarNotWritten(
                    blame=self.site,
                    owner="TryStarSugar.desugar",
                    observed=type(exit_.effect).__name__,
                    requested="GroupedRaiseEffect for except* routing",
                    fix="keep ordinary except and except* distinct",
                )
            original = exit_.effect
            # Frontier: one face per body halt, then each handler branches it.
            frontier: list[_StarFace] = [
                _StarFace(
                    guard=true_guard(),
                    residual=original,
                    state=_seed_temporal(exit_.state, ctx),
                    faces=frozenset(),
                    exceptional=(),
                    owed=(),
                )
            ]
            # Faces that leave the residual walk (non-raise halts).
            retained: list = []

            for matchers, handler_body, slot_id in self.handlers:
                if not isinstance(matchers, tuple):
                    matchers = (matchers,)
                next_frontier: list[_StarFace] = []
                for face in frontier:
                    handler_residual = face.residual
                    matched_parts = []
                    for matcher in matchers:
                        expected = _matcher_value(matcher, face.state.context)
                        if expected is None:
                            raise SugarNotWritten(
                                blame=self.site,
                                owner="TryStarSugar.desugar",
                                observed="symbolic except* type",
                                requested="authenticated subtype partition operand",
                                fix="keep symbolic subtype partition typed loud",
                            )
                        routed = route_except_star(
                            handler_residual,
                            expected,
                            slot_id=slot_id,
                            site=self.site,
                        )
                        if routed is None:
                            continue
                        if routed.matched.children:
                            matched_parts.append(routed.matched)
                        handler_residual = routed.residual
                    if not matched_parts:
                        # This face does not match this handler — residual continues.
                        next_frontier.append(face)
                        continue
                    matched = regroup_except_star(face.residual, matched_parts)
                    base_ctx = (
                        face.state.context if face.state.context is not None else ctx
                    )
                    handler_ctx = bind_in_flight_effect(
                        base_ctx, slot_id, matched, blame=self.site
                    )
                    if slot_id is not None:
                        # Shared typed ReduceContext surface.
                        handler_ctx = handler_ctx.with_observed_effect(slot_id, matched)
                    seed = replace(face.state, context=handler_ctx)
                    handler_exits = _reduce_block_from_state(
                        handler_body, seed, handler_ctx
                    )
                    # The handler runs beneath this face's path: ``sequence``
                    # conjoins the face's guard, faces and ``owed`` onto every
                    # handler arm. One next face per composed arm.
                    path = ExitSet(
                        (Completed(face.guard, face.state, face.faces, face.owed),)
                    )
                    # The frontier is built from the handler's arms now: a
                    # handler still waiting on its caller's actuals, whose
                    # carrier ``sequence`` composed, is refused by name here.
                    composed = _require_exit_set(
                        path.sequence(lambda _state, exits=handler_exits: exits),
                        owner="TryStarSugar.handler",
                    )
                    for arm in composed.exits:
                        if isinstance(arm, Halted):
                            exceptional = face.exceptional
                            if _is_exceptional_raise(arm.effect):
                                exceptional = (*exceptional, arm.effect)
                            else:
                                # Non-raise halt leaves the residual walk as
                                # an exit.
                                retained.append(arm)
                            next_state = (
                                arm.state
                                if isinstance(arm.state, _ReducedBlock)
                                else face.state
                            )
                        else:
                            # Handler fall-through is NOT a try* completed edge
                            # while an unmatched residual remains — Python has
                            # no completed edge there. Only advance temporal
                            # state on the residual/exceptional frontier.
                            exceptional = face.exceptional
                            next_state = (
                                arm.value
                                if isinstance(arm.value, _ReducedBlock)
                                else face.state
                            )
                        next_frontier.append(
                            _StarFace(
                                guard=arm.guard,
                                residual=handler_residual,
                                state=next_state,
                                faces=arm.faces,
                                exceptional=exceptional,
                                owed=arm.owed,
                            )
                        )
                frontier = next_frontier

            # Emit residual / exceptional per face — regroup only within a face
            # (equal guard path). Never AND guards across alternative faces.
            # Completed only when residual is empty and no exceptional remains.
            for face in frontier:
                effects = list(face.exceptional)
                if face.residual.children:
                    effects.append(face.residual)
                if effects:
                    # Never None: a face that owes a raise answers it (#7825).
                    retained.append(
                        Halted(
                            face.guard,
                            regroup_except_star(original, effects),
                            face.state,
                            face.faces,
                            face.owed,
                        )
                    )
                else:
                    retained.append(
                        Completed(face.guard, face.state, face.faces, face.owed)
                    )

            # No arm is invented: when no path leaves the handlers (every arm
            # was unsatisfiable, so ``sequence`` dropped it), the continuation
            # is exactly the empty set ``sequence`` composed. A raise is never
            # a completion (#7825).
            # Not normalized here: ``sequence`` conjoins the body halt's guard
            # first and normalizes the composed set once.
            return ExitSet(tuple(retained))

        result = (
            body.sequence(after_body, consume=handled)
            if body.exits
            else ExitSet.completed(_ReducedBlock((), True, ()))
        )
        if self.finalbody:
            cleanup = reduce_block_to_exitset(self.finalbody, ctx)
            from sugar_lift_py_tests.floor.return_value import ReturnValue
            from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock

            def restores(value):
                return not (
                    isinstance(value, _ReducedBlock)
                    and (
                        not value.can_fall_through
                        or any(isinstance(e, ReturnValue) for e in value.entries)
                    )
                )

            result = result.and_finally(lambda: cleanup, cleanup_restores=restores)
        # The try*'s own faces: a halt stays a halted arm, never an entry of a
        # completed record (#7826).
        return result.normalize()


def _is_exceptional_raise(effect) -> bool:
    from sugar_lift_py_tests.effect.grouped_raise_effect import GroupedRaiseEffect
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect

    return isinstance(effect, (RaiseEffect, GroupedRaiseEffect))


def _seed_temporal(state, ctx):
    from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock

    if isinstance(state, _ReducedBlock):
        if state.context is None and ctx is not None:
            return replace(state, context=ctx)
        return state
    return _ReducedBlock(
        entries=(),
        can_fall_through=True,
        fall_through=(),
        context=ctx,
    )


def _reduce_block_from_state(statements, state, ctx):
    """Reduce ``statements`` continuing from an existing temporal ``state``;
    a state that is no reduced block reduces the handler under ``ctx``, the
    handler's context.

    A statement still waiting on its caller's actuals (a deferred carrier)
    keeps waiting: every later statement runs beneath its completed arms once
    it discharges (the carrier's own ``and_then``), as the block reducer
    hands one on."""
    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )
    from sugar_lift_py_tests.outcome.exit_set import ExitSet
    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        _ReducedBlock,
        reduce_block_to_exitset,
    )

    if not isinstance(state, _ReducedBlock):
        return reduce_block_to_exitset(statements, ctx)

    exits = ExitSet.completed(state)
    for statement in statements:

        def step(prefix, stmt=statement):
            return _reduce_one_from(prefix, stmt)

        if isinstance(exits, NativeOperationExitCarrierV1):
            exits = exits.and_then(step)
        else:
            exits = exits.sequence(step)
    return exits


def _reduce_one_from(state, statement):
    """Reduce one statement after ``state``; prefix entries; keep new context.

    A statement still waiting on its caller's actuals answers its carrier:
    its faces take this prefix once it discharges (``after_discharge``)."""
    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )
    from sugar_lift_py_tests.outcome.exit_set import ExitSet, _require_exit_set
    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        reduce_block_to_exitset,
    )

    if not state.can_fall_through:
        return ExitSet.completed(state)

    following = reduce_block_to_exitset((statement,), state.context)
    if isinstance(following, NativeOperationExitCarrierV1):
        return following.after_discharge(
            lambda projected: _beneath_prefix(
                state,
                _require_exit_set(projected, owner="TryStarSugar.statement"),
            )
        )
    return _beneath_prefix(state, following)


def _beneath_prefix(state, following):
    """``following``'s faces with ``state``'s entries and transforms before
    their own; a halt that carries no state halts at ``state``."""
    from sugar_lift_py_tests.outcome.exit_set import Completed, ExitSet, Halted
    from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock

    out = []
    for face in following.exits:
        if isinstance(face, Completed) and isinstance(face.value, _ReducedBlock):
            out.append(
                Completed(
                    face.guard,
                    replace(
                        face.value,
                        entries=(*state.entries, *face.value.entries),
                        transforms=(*state.transforms, *face.value.transforms),
                    ),
                    face.faces,
                    face.owed,
                )
            )
        elif isinstance(face, Halted):
            halt_state = face.state
            if isinstance(halt_state, _ReducedBlock):
                halt_state = replace(
                    halt_state,
                    entries=(*state.entries, *halt_state.entries),
                    transforms=(*state.transforms, *halt_state.transforms),
                )
            elif halt_state is None:
                halt_state = state
            out.append(
                Halted(
                    face.guard,
                    face.effect,
                    halt_state,
                    face.faces,
                    face.owed,
                )
            )
        else:
            out.append(face)
    return ExitSet(tuple(out)).normalize()
