from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

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
                    owner="TryStarSugar.desugar",
                    observed=type(exit_.effect).__name__,
                    requested="GroupedRaiseEffect for except* routing",
                    fix="keep ordinary except and except* distinct",
                )
            original = exit_.effect
            residual = original
            handler_effects = []
            completed_states = []
            for matcher, handler_body, slot_id in self.handlers:
                expected = matcher.desugar(ctx)
                if not isinstance(expected, Complete):
                    raise SugarNotWritten(
                        owner="TryStarSugar.desugar",
                        observed="symbolic except* type",
                        requested="authenticated subtype partition operand",
                        fix="keep symbolic subtype partition typed loud",
                    )
                routed = route_except_star(
                    residual, expected.value, slot_id=slot_id, site=self.site
                )
                if routed is None or not routed.matched.children:
                    continue
                handler_ctx = bind_in_flight_effect(ctx, slot_id, routed.matched)
                handler_exits = promote_raise_halts(
                    reduce_block_to_exitset(handler_body, handler_ctx)
                )
                if len(handler_exits.exits) != 1:
                    raise SugarNotWritten(
                        owner="TryStarSugar.desugar",
                        observed="symbolically branching except* handler",
                        requested="one closed handler exit for exact regrouping",
                        fix="keep unresolved handler regrouping typed loud",
                    )
                for handler_exit in handler_exits.exits:
                    if isinstance(handler_exit, Halted):
                        handler_effects.append(handler_exit.effect)
                    elif isinstance(handler_exit, Completed):
                        completed_states.append(handler_exit.value)
                residual = routed.residual
            outgoing = list(handler_effects)
            if residual.children:
                outgoing.append(residual)
            regrouped = regroup_except_star(original, outgoing)
            state = exit_.state
            if isinstance(state, _ReducedBlock):
                entries = list(state.entries)
                for completed in completed_states:
                    if isinstance(completed, _ReducedBlock):
                        entries.extend(completed.entries)
                from dataclasses import replace

                state = replace(state, entries=tuple(entries))
            if regrouped is not None:
                parts.append(ExitSet((Halted(exit_.guard, regrouped, state),)))
            elif completed_states:
                parts.append(ExitSet((Completed(exit_.guard, state),)))
            else:
                parts.append(ExitSet.completed(state))

        result = parts[0] if parts else ExitSet.completed(None)
        for part in parts[1:]:
            result = result.union(part)
        if self.finalbody:
            cleanup = reduce_block_to_exitset(self.finalbody, ctx)
            from sugar_lift_py_tests.floor.return_value import ReturnValue
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
