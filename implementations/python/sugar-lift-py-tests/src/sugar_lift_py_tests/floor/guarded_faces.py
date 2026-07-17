from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.ir import Formula

from .floor_value import FloorValue


@dataclass(frozen=True)
class GuardedFaces(FloorValue):
    """A symbolic condition's `if`/`else`: it cannot pick a face, so it guards.
    The entries are the face records already riding under their polarity. Exits
    decide what the continuation rides: both faces exit -- the tail is
    unreachable (raw); only then exits -- the tail rides under not(guard); only
    else exits -- the tail rides under guard; neither -- the tail is
    unconditional. The faces splice into the enclosing record like a block."""

    guard: Formula
    entries: tuple
    then_exits: bool
    else_exits: bool
    joined_bindings: tuple = ()
    guarded_bindings: tuple = ()
    can_fall_through: bool = True
    continuation_guard: Formula | None = None

    def contribution(self):
        from sugar_lift_py_tests.floor.scope_rebind import ScopeRebind

        return (
            *self.entries,
            *(ScopeRebind(name, value) for name, value in self.joined_bindings),
        )

    def inv_contribution(self):
        return tuple(
            formula for entry in self.entries for formula in entry.inv_contribution()
        )

    def post_contribution(self):
        return tuple(
            formula for entry in self.entries for formula in entry.post_contribution()
        )

    def edge_contribution(self, source_contract):
        # Faces splice into the record; each entry projects its own edges.
        return tuple(
            edge
            for entry in self.entries
            for edge in entry.edge_contribution(source_contract)
        )

    def extend_scope(self, ctx):
        from dataclasses import replace

        temporal = ctx.temporal
        for name, value in self.joined_bindings:
            temporal = temporal.bind_value(name, value)
        for guard, name, value in self.guarded_bindings:
            temporal = temporal.bind_guarded(guard, name, value)
        return replace(ctx, temporal=temporal)

    def follow_rest(self):
        # Exits decide what the continuation rides -- no type interrogation:
        # both exit -> unreachable (raw, like code after an unguarded return);
        # only then -> tail under not(guard); only else -> tail under guard;
        # neither -> reduce plain.
        if not self.can_fall_through:
            from sugar_lift_py_tests.outcome.follow_step import FollowStep

            return FollowStep.halt(keeps_rest=True)
        from sugar_lift_py_tests.outcome.follow_step import FollowStep

        if self.continuation_guard is not None:
            guard = self.continuation_guard
            return FollowStep.continue_with(
                lambda entries: tuple(entry.guarded(guard) for entry in entries),
                continuation_guard=guard,
            )
        return FollowStep.continue_with()
