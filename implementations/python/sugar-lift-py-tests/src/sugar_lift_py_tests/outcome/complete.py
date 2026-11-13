from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.floor import FloorValue


@dataclass(frozen=True)
class Complete:
    value: FloorValue

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
        # A completed value keeps going.  A raise is never a completion: it is
        # an ``Incomplete`` (or a ``Halted`` face), whose ``and_then`` never
        # runs the step.
        return step(self.value)
