from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.floor import FloorValue


@dataclass(frozen=True)
class Complete:
    value: FloorValue

    def binary_conditional(self, then, else_body, ctx=None):
        # The completed value is the dispatcher: True emits the then-face, False the
        # else-face. A value that cannot do the bool thing has no binary_conditional,
        # and the base FloorValue's panic is the honest "no".
        return self.value.binary_conditional(then, else_body, ctx)

    def follow(self, rest, reduce):
        # The value owns whether and how the rest reduces: an ordinary value
        # lets the run go on, an exit keeps the rest raw (unreachable), a
        # guarded-faces value guards the continuation by its negated test.
        return self.value.follow_rest(rest, reduce)

    def contribution(self):
        # The value owns its contribution to the block record -- no interrogation.
        return self.value.contribution()

    def extend_scope(self, ctx):
        # The value owns whether the rest of the block sees a new binding.
        return self.value.extend_scope(ctx)

    def and_then(self, step):
        # A completed value keeps going: hand the value to the next step.
        return step(self.value)
