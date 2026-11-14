from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.effect import Effect, effect_reason, require_effect


@dataclass(frozen=True)
class Incomplete:
    """A typed effect: the linear spelling of a halt or a runtime-dependent step."""

    effect: Effect
    branch_conditions: tuple = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "effect", require_effect(self.effect))

    @property
    def reason(self) -> str:
        base = effect_reason(self.effect)
        if not self.branch_conditions:
            return base
        conds = " and ".join(repr(f) for f in self.branch_conditions)
        return f"{base}; effect occurs under branch condition {conds}"

    def follow(self):
        # An effect halts the run; the rest of the block stays unreduced. A
        # store is not an Incomplete: its producer answers its two faces
        # (floor/store_outcome_coordinate.py, ``store_faces``).
        from sugar_lift_py_tests.outcome.follow_step import FollowStep

        return FollowStep.halt(keeps_rest=True)

    def contribution(self):
        # An effect contributes itself to the block record; the unresolved tail rides
        # beside it via follow.
        return (self,)

    def guarded(self, formula):
        """Keep a typed effect red while recording its branch condition.

        The condition is wrapper-level metadata, recorded on the Incomplete --
        NOT smashed into the effect's reason. The effect stays pristine (some
        effects, e.g. RaiseEffect, compute ``reason`` as a property with no field
        to replace), and a raise guarded by several nested ifs accumulates its
        conditions in order."""
        return Incomplete(self.effect, (*self.branch_conditions, formula))

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
