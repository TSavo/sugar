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

from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class _StarFace:
    """One except* routing face: residual + temporal state under one guard."""

    guard: object
    residual: object  # GroupedRaiseEffect
    state: object  # _ReducedBlock
    faces: frozenset
    pending: tuple
    # Exceptional raises collected on THIS face's guard path only.
    exceptional: tuple


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
        from sugar_lift_py_tests.caller_parameter_contract import merge_pending
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
            _and_guards,
        )
        from sugar_lift_py_tests.sugar.exit_set_routing import (
            exitset_to_outcome,
            promote_raise_halts,
        )
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            _ReducedBlock,
            reduce_block_to_exitset,
        )
        from sugar_source_tree.panic import SugarNotWritten

        body = promote_raise_halts(reduce_block_to_exitset(self.body, ctx))
        parts = []
        for exit_ in body.exits:
            if not isinstance(exit_, Halted):
                if self.orelse:
                    else_exits = reduce_block_to_exitset(self.orelse, ctx)
                    parts.append(ExitSet((exit_,)).sequence(lambda _state: else_exits))
                else:
                    parts.append(ExitSet((exit_,)))
                continue
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
                    guard=exit_.guard,
                    residual=original,
                    state=_seed_temporal(exit_.state, ctx),
                    faces=exit_.faces,
                    pending=exit_.pending_contracts,
                    exceptional=(),
                )
            ]
            # Faces that leave the residual walk (unknown control / terminal).
            retained: list = []

            for matchers, handler_body, slot_id in self.handlers:
                if not isinstance(matchers, tuple):
                    matchers = (matchers,)
                next_frontier: list[_StarFace] = []
                for face in frontier:
                    handler_residual = face.residual
                    matched_parts = []
                    for matcher in matchers:
                        expected = matcher.desugar(face.state.context)
                        if not isinstance(expected, Complete):
                            raise SugarNotWritten(
                                blame=self.site,
                                owner="TryStarSugar.desugar",
                                observed="symbolic except* type",
                                requested="authenticated subtype partition operand",
                                fix="keep symbolic subtype partition typed loud",
                            )
                        routed = route_except_star(
                            handler_residual,
                            expected.value,
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
                    handler_exits = promote_raise_halts(
                        _reduce_block_from_state(handler_body, seed)
                    )
                    # Branch the frontier: one next face per handler exit face.
                    for handler_exit in handler_exits.exits:
                        guard = _and_guards(face.guard, handler_exit.guard)
                        faces = face.faces | handler_exit.faces
                        owed = merge_pending(
                            face.pending, handler_exit.pending_contracts
                        )
                        if isinstance(handler_exit, Halted) and _is_exceptional_raise(
                            handler_exit.effect
                        ):
                            next_state = (
                                handler_exit.state
                                if isinstance(handler_exit.state, _ReducedBlock)
                                else face.state
                            )
                            next_frontier.append(
                                _StarFace(
                                    guard=guard,
                                    residual=handler_residual,
                                    state=next_state,
                                    faces=faces,
                                    pending=owed,
                                    exceptional=(
                                        *face.exceptional,
                                        handler_exit.effect,
                                    ),
                                )
                            )
                            continue
                        if isinstance(handler_exit, Halted):
                            # Non-raise halt leaves the residual walk as an exit.
                            retained.append(
                                Halted(
                                    guard,
                                    handler_exit.effect,
                                    handler_exit.state,
                                    faces,
                                    owed,
                                )
                            )
                            next_state = (
                                handler_exit.state
                                if isinstance(handler_exit.state, _ReducedBlock)
                                else face.state
                            )
                            next_frontier.append(
                                _StarFace(
                                    guard=guard,
                                    residual=handler_residual,
                                    state=next_state,
                                    faces=faces,
                                    pending=owed,
                                    exceptional=face.exceptional,
                                )
                            )
                            continue
                        if isinstance(handler_exit, Completed):
                            # Handler fall-through is NOT a try* completed edge
                            # while an unmatched residual remains — Python has
                            # no completed edge there. Only advance temporal
                            # state on the residual/exceptional frontier.
                            next_state = (
                                handler_exit.value
                                if isinstance(handler_exit.value, _ReducedBlock)
                                else face.state
                            )
                            next_frontier.append(
                                _StarFace(
                                    guard=guard,
                                    residual=handler_residual,
                                    state=next_state,
                                    faces=faces,
                                    pending=owed,
                                    exceptional=face.exceptional,
                                )
                            )
                            continue
                        # Unknown face: still conjoin enclosing guard; retain.
                        retained.append(
                            _rebind_face_guard(handler_exit, guard, faces, owed)
                        )
                        next_frontier.append(
                            _StarFace(
                                guard=guard,
                                residual=handler_residual,
                                state=face.state,
                                faces=faces,
                                pending=owed,
                                exceptional=face.exceptional,
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
                    regrouped = regroup_except_star(original, effects)
                    if regrouped is not None:
                        retained.append(
                            Halted(
                                face.guard,
                                regrouped,
                                face.state,
                                face.faces,
                                face.pending,
                            )
                        )
                else:
                    retained.append(
                        Completed(face.guard, face.state, face.faces, face.pending)
                    )

            if not retained:
                retained.append(
                    Completed(
                        exit_.guard,
                        _seed_temporal(exit_.state, ctx),
                        exit_.faces,
                        exit_.pending_contracts,
                    )
                )
            parts.append(ExitSet(tuple(retained)).normalize())

        result = parts[0] if parts else ExitSet.completed(None)
        for part in parts[1:]:
            result = result.union(part)
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
        return exitset_to_outcome(result)


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


def _rebind_face_guard(face, guard, faces, owed):
    """Retain a face with the enclosing guard conjoined (all faces, no drop)."""
    from sugar_lift_py_tests.outcome.exit_set import Completed, Halted
    from sugar_source_tree.panic import SugarNotWritten

    if isinstance(face, Halted):
        return Halted(guard, face.effect, face.state, faces, owed)
    if isinstance(face, Completed):
        return Completed(guard, face.value, faces, owed)
    raise SugarNotWritten(
        blame=None,
        owner="TryStarSugar.desugar",
        observed=type(face).__name__,
        requested="Completed|Halted ExitSet face with conjoined body guard",
        fix="extend TryStarSugar face retention for the new ExitSet face kind",
    )


def _reduce_block_from_state(statements, state):
    """Reduce ``statements`` continuing from an existing temporal ``state``."""
    from sugar_lift_py_tests.outcome.exit_set import ExitSet
    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        _ReducedBlock,
        reduce_block_to_exitset,
    )

    if not isinstance(state, _ReducedBlock):
        return reduce_block_to_exitset(statements, None)

    exits = ExitSet.completed(state)
    for statement in statements:
        exits = exits.sequence(lambda s, stmt=statement: _reduce_one_from(s, stmt))
    return exits


def _reduce_one_from(state, statement):
    """Reduce one statement after ``state``; prefix entries; keep new context."""
    from sugar_lift_py_tests.outcome.exit_set import Completed, ExitSet, Halted
    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        _ReducedBlock,
        reduce_block_to_exitset,
    )

    if not state.can_fall_through:
        return ExitSet.completed(state)

    following = reduce_block_to_exitset((statement,), state.context)
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
                    face.pending_contracts,
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
                    face.pending_contracts,
                )
            )
        else:
            out.append(face)
    return ExitSet(tuple(out)).normalize()
