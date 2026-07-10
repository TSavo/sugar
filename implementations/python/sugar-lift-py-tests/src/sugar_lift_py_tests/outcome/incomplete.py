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

    def binary_conditional(self, then, else_body, ctx: object = None) -> "Incomplete":
        # An effect never decides a branch; it rides straight through by returning
        # itself. Same shape for every operation an effect is asked to do.
        del then, else_body, ctx
        return self

    def follow(self, rest, reduce):
        # An effect halts the run: the rest of the block is unreachable, so it stays
        # exactly as it is -- unreduced sugar. Never reason about code that never runs.
        del reduce
        return rest

    def contribution(self):
        # An effect contributes itself to the block record; the unresolved tail rides
        # beside it via follow.
        return (self,)

    def and_then(self, step):
        # An effect never continues: it propagates by returning itself, the next step
        # never runs.
        del step
        return self
