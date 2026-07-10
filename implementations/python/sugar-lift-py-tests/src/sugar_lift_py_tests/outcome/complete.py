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
        # A completed statement lets the run go on: reduce the rest of the block.
        return reduce(rest)

    def contribution(self):
        # The value owns its contribution to the block record -- no interrogation.
        return self.value.contribution()

    def and_then(self, step):
        # A completed value keeps going: hand the value to the next step.
        return step(self.value)
