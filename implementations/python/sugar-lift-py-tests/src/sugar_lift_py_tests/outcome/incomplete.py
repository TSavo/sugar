from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.effect import Effect, effect_reason, require_effect


@dataclass(frozen=True)
class Incomplete:
    effect: Effect

    def __post_init__(self) -> None:
        object.__setattr__(self, "effect", require_effect(self.effect))

    @property
    def reason(self) -> str:
        return effect_reason(self.effect)

    def binary_conditional(
        self, then, else_body, ctx: object = None, site=None
    ) -> "Incomplete":
        # An effect never decides a branch; it rides straight through by returning
        # itself. Same shape for every operation an effect is asked to do.
        del then, else_body, ctx, site
        return self

    def follow(self):
        # Default: an effect halts the run; the rest of the block stays unreduced.
        # Store side-effects are different: the statement completed (typed red),
        # and Python continues. Halting would drop later bindings (e.g. `res = …`
        # after `receiver[index][...] = 0`) and panic NameSugar unbound — a false
        # construction gap. Continuing store effects contribute red and let the
        # block reduce subsequent statements.
        from sugar_lift_py_tests.outcome.follow_step import FollowStep

        if _effect_continues_control_flow(self.effect):
            return FollowStep.continue_with()
        return FollowStep.halt(keeps_rest=True)

    def contribution(self):
        # An effect contributes itself to the block record; the unresolved tail rides
        # beside it via follow.
        return (self,)

    def guarded(self, formula):
        """Keep a typed effect red while recording its branch condition."""
        from dataclasses import replace

        return Incomplete(
            replace(
                self.effect,
                reason=(
                    f"{self.reason}; effect occurs under branch condition "
                    f"{formula!r}"
                ),
            )
        )

    def extend_scope(self, ctx):
        # An effect does not rebind: the rest never runs under a new scope.
        return ctx

    def inv_contribution(self):
        # An effect states no inv.
        return ()

    def post_contribution(self):
        # An effect posts no exit.
        return ()

    def mint_contribution(self, name, formals):
        # An effect mints no row.
        del name, formals
        return ()

    def edge_contribution(self, source_contract):
        # An effect projects no call edge.
        del source_contract
        return ()

    def and_then(self, step):
        # An effect never continues: it propagates by returning itself, the next step
        # never runs.
        del step
        return self


def _effect_continues_control_flow(effect) -> bool:
    """True when the effect is red testimony for a completed non-exiting statement.

    Store mutations do not raise or return: after `xs[i] = v` or `obj.attr = v`
    the next statement still runs. Incomplete must contribute the red effect and
    continue so later TemporalContext bindings still construct.
    """
    from sugar_lift_py_tests.effect import (
        AttributeAugAssignRuntimeEffect,
        AttributeStoreRuntimeEffect,
        SubscriptStoreRuntimeEffect,
    )

    return isinstance(
        effect,
        (
            SubscriptStoreRuntimeEffect,
            AttributeStoreRuntimeEffect,
            AttributeAugAssignRuntimeEffect,
        ),
    )
