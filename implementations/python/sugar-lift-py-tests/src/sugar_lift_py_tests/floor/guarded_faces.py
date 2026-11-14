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
    can_fall_through: bool = True
    continuation_guard: Formula | None = None
    unconditional_entries: tuple = ()
    # ``(evaluation key, value)``: the statement evaluations a completed arm
    # made (``AugAssign._evaluation_key``).  A key names one statement inside
    # one arm, so after the ``if`` it is read only by the phi's arm for that
    # face, under that face's guard; it carries the arm's value there.  Arms
    # that bound one key to different values carry each arm's value under
    # that arm's guard (``if_sugar._arm_evaluations``).
    evaluations: tuple = ()

    def contribution(self):
        return (*self.unconditional_entries, *self.entries)

    def extend_scope(self, ctx):
        if not self.evaluations:
            return ctx
        from dataclasses import replace

        temporal = ctx.temporal
        for key, value in self.evaluations:
            temporal = temporal.bind_value(key, value)
        return replace(ctx, temporal=temporal)

    def inv_contribution(self):
        return tuple(
            formula
            for entry in (*self.unconditional_entries, *self.entries)
            for formula in entry.inv_contribution()
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
