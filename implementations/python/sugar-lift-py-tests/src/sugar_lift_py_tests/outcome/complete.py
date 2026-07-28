from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.floor import FloorValue


@dataclass(frozen=True)
class Complete:
    value: FloorValue

    def binary_conditional(self, then, else_body, ctx=None, site=None):
        # The completed value is the dispatcher: True emits the then-face, False the
        # else-face. Truth answers first for values that fold; the standing decides.
        return self.value.binary_conditional(then, else_body, ctx, site)

    def follow(self):
        # The value owns whether and how the rest reduces: an ordinary value
        # lets the run go on, an exit keeps the rest raw (unreachable), a
        # guarded-faces value guards the continuation by its negated test.
        return self.value.follow_rest()

    def contribution(self):
        # The value owns its contribution to the block record -- no interrogation.
        return self.value.contribution()

    def extend_scope(self, ctx):
        # The value owns whether the rest of the block sees a new binding.
        return self.value.extend_scope(ctx)

    def and_then(self, step):
        # A completed ordinary value keeps going. A constructed raise is also
        # complete testimony, but Python does not evaluate any enclosing
        # expression step after it; preserve the control-flow value unchanged.
        from sugar_lift_py_tests.floor import BlockValue, CallSiteValue, RaiseValue

        if isinstance(self.value, RaiseValue):
            return self
        value = self.value
        if isinstance(value, CallSiteValue) and value.body is not None:
            projected = value._dig_floor_or_none(
                None, owner="Complete.and_then authenticated source return"
            )
            if projected is not None and not isinstance(projected, BlockValue):
                value = projected
        return step(value)
