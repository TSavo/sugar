"""``except*`` subgroup routing over authenticated ``GroupedRaiseEffect`` trees.

Laws (owned here; ExitSet/carrier untouched):

- Partition each body ``GroupedRaiseEffect`` by authenticated handler type.
- Matching subgroup reaches its handler once (type-tuple = one body run).
- Unmatched residual continues to subsequent handlers in source order.
- Handler halt effects regroup with residual; empty residual completes.
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
        from sugar_lift_py_tests.effect.grouped_raise_effect import GroupedRaiseEffect
        from sugar_lift_py_tests.effect_router import (
            regroup_except_star,
            route_except_star,
        )
        from sugar_lift_py_tests.in_flight_effect import bind_in_flight_effect
        from sugar_lift_py_tests.outcome.exit_set import Completed, ExitSet, Halted
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
            handler_effects = []
            # Temporal fragments from handlers that complete or halt — merged
            # into the outgoing face so assignments before a handler raise /
            # pass survive into residual propagation (occurrence identities
            # already live on the RaiseEffect leaves themselves).
            temporal_fragments = []
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
                    expected = matcher.desugar(ctx)
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
                handler_ctx = bind_in_flight_effect(
                    ctx, slot_id, matched, blame=self.site
                )
                if slot_id is not None:
                    observer = getattr(handler_ctx, "with_observed_effect", None)
                    if observer is not None:
                        handler_ctx = observer(slot_id, matched)
                handler_exits = promote_raise_halts(
                    reduce_block_to_exitset(handler_body, handler_ctx)
                )
                if len(handler_exits.exits) != 1:
                    raise SugarNotWritten(
                        blame=self.site,
                        owner="TryStarSugar.desugar",
                        observed="symbolically branching except* handler",
                        requested="one closed handler exit for exact regrouping",
                        fix="keep unresolved handler regrouping typed loud",
                    )
                for handler_exit in handler_exits.exits:
                    if isinstance(handler_exit, Halted):
                        handler_effects.append(handler_exit.effect)
                        temporal_fragments.append(handler_exit.state)
                    elif isinstance(handler_exit, Completed):
                        temporal_fragments.append(handler_exit.value)
            outgoing = list(handler_effects)
            if residual.children:
                outgoing.append(residual)
            regrouped = regroup_except_star(original, outgoing)
            state = _merge_temporal_state(exit_.state, temporal_fragments)
            if regrouped is not None:
                parts.append(ExitSet((Halted(exit_.guard, regrouped, state),)))
            elif temporal_fragments:
                parts.append(ExitSet((Completed(exit_.guard, state),)))
            else:
                parts.append(ExitSet.completed(state))

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


def _merge_temporal_state(base, fragments):
    """Fold handler temporal fragments into the body halt state.

    Entries/transforms from completed or halted handlers append onto the body
    halt's ``_ReducedBlock`` so residual propagation retains work the handlers
    performed. Non-block bases pass through unchanged when nothing merges.
    """
    from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock

    if not fragments:
        return base
    if not isinstance(base, _ReducedBlock):
        # Prefer the last fragment when the body halt carried no block state.
        for fragment in reversed(fragments):
            if isinstance(fragment, _ReducedBlock):
                return fragment
        return base
    entries = list(base.entries)
    transforms = list(getattr(base, "transforms", ()) or ())
    for fragment in fragments:
        if isinstance(fragment, _ReducedBlock):
            entries.extend(fragment.entries)
            transforms.extend(getattr(fragment, "transforms", ()) or ())
    return replace(
        base,
        entries=tuple(entries),
        transforms=tuple(transforms),
    )
