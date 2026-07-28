"""``except*`` subgroup routing over authenticated ``GroupedRaiseEffect`` trees.

Laws (owned here; ExitSet/carrier untouched):

- Partition each body ``GroupedRaiseEffect`` by authenticated handler type.
- Matching subgroup reaches its handler once (type-tuple = one body run).
- Unmatched residual continues to subsequent handlers in source order.
- Handlers execute temporally: each handler begins from the prior handler's
  resulting state (not a fresh original ctx / concatenated fragment merge).
- Every ExitSet face is retained (Completed including terminal return, Halted,
  and any future face); only exceptional raise faces are regrouped.
- Handler-exit guards are conjoined with the body halt guard on every face.
- Finally restore preserves residual; finally terminate overrides.
- Leaf occurrence identities and nested topology survive partition/regroup.
- Ordinary ``RaiseEffect`` under ``except*`` stays loud (distinct from Try).
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field, replace

from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.sugar_base import Sugar


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
        from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
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
            residual = original
            # Temporal seed: body halt state, carrying context for the first
            # matching handler. Each subsequent matching handler begins from
            # the previous handler's resulting state — not original ctx.
            temporal = _seed_temporal(exit_.state, ctx)
            # Exceptional raise effects for regroup only (not Completed/return).
            exceptional_effects: list = []
            exceptional_guards: list = []
            # Every non-exceptional face retained with conjoined guards.
            retained: list = []

            for matchers, handler_body, slot_id in self.handlers:
                # One handler, one body run, however many types it lists. Each
                # type partitions what the previous type left behind, and the
                # matched pieces are regrouped into ONE subgroup carrying the
                # original topology -- so `except* (A, B)` over a group holding
                # both binds a single group of both leaves rather than entering
                # the body twice.
                if not isinstance(matchers, tuple):
                    matchers = (matchers,)
                handler_residual = residual
                matched_parts = []
                for matcher in matchers:
                    expected = matcher.desugar(temporal.context)
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
                    continue
                matched = regroup_except_star(residual, matched_parts)
                residual = handler_residual

                base_ctx = (
                    temporal.context if temporal.context is not None else ctx
                )
                handler_ctx = bind_in_flight_effect(
                    base_ctx, slot_id, matched, blame=self.site
                )
                if slot_id is not None:
                    handler_ctx = _with_observed_effect(
                        handler_ctx, slot_id, matched, blame=self.site
                    )
                seed = replace(temporal, context=handler_ctx)
                handler_exits = promote_raise_halts(
                    _reduce_block_from_state(handler_body, seed)
                )

                for handler_exit in handler_exits.exits:
                    guard = _and_guards(exit_.guard, handler_exit.guard)
                    faces = exit_.faces | handler_exit.faces
                    owed = merge_pending(
                        exit_.pending_contracts, handler_exit.pending_contracts
                    )
                    if isinstance(handler_exit, Halted) and _is_exceptional_raise(
                        handler_exit.effect
                    ):
                        # Regroup exceptional raises only; do not emit raw face.
                        exceptional_effects.append(handler_exit.effect)
                        exceptional_guards.append(guard)
                        if isinstance(handler_exit.state, _ReducedBlock):
                            temporal = handler_exit.state
                        continue
                    if isinstance(handler_exit, Halted):
                        retained.append(
                            Halted(
                                guard,
                                handler_exit.effect,
                                handler_exit.state,
                                faces,
                                owed,
                            )
                        )
                        if isinstance(handler_exit.state, _ReducedBlock):
                            temporal = handler_exit.state
                        continue
                    if isinstance(handler_exit, Completed):
                        retained.append(
                            Completed(guard, handler_exit.value, faces, owed)
                        )
                        if isinstance(handler_exit.value, _ReducedBlock):
                            temporal = handler_exit.value
                        continue
                    # Unknown face kinds must not disappear — retain as-is under
                    # the conjoined guard when the face carries one.
                    retained.append(handler_exit)

            if residual.children:
                exceptional_effects.append(residual)
                exceptional_guards.append(exit_.guard)

            regrouped = (
                regroup_except_star(original, exceptional_effects)
                if exceptional_effects
                else None
            )
            if regrouped is not None:
                regroup_guard = exit_.guard
                for g in exceptional_guards:
                    regroup_guard = _and_guards(regroup_guard, g)
                retained.append(
                    Halted(
                        regroup_guard,
                        regrouped,
                        temporal,
                        exit_.faces,
                        exit_.pending_contracts,
                    )
                )
            elif not retained:
                retained.append(Completed(exit_.guard, temporal, exit_.faces))

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


def _with_observed_effect(ctx, slot_id, effect, *, blame):
    """Require the typed observed-effect operation — no getattr soft-probe."""
    from sugar_source_tree.panic import SugarNotWritten

    if ctx is None:
        raise SugarNotWritten(
            blame=blame,
            owner="TryStarSugar.desugar",
            observed="None",
            requested="ReduceContext.with_observed_effect for except* as-binding",
            fix="route except* handlers through the shared ReduceContext",
        )
    try:
        return ctx.with_observed_effect(slot_id, effect)
    except AttributeError as exc:
        raise SugarNotWritten(
            blame=blame,
            owner="TryStarSugar.desugar",
            observed=type(ctx).__name__,
            requested="ReduceContext.with_observed_effect for except* as-binding",
            fix="route except* handlers through the shared ReduceContext",
        ) from exc


def _reduce_block_from_state(statements, state):
    """Reduce ``statements`` continuing from an existing temporal ``state``.

    Unlike ``reduce_block_to_exitset`` (always empty seed), each statement
    begins from the prior face's state so earlier handler work is visible.
    """
    from sugar_lift_py_tests.outcome.exit_set import Completed, ExitSet, Halted
    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        _ReducedBlock,
        reduce_block_to_exitset,
    )

    if not isinstance(state, _ReducedBlock):
        return reduce_block_to_exitset(statements, None)

    exits = ExitSet.completed(state)
    for statement in statements:
        exits = exits.sequence(
            lambda s, stmt=statement: _reduce_one_from(s, stmt)
        )
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
