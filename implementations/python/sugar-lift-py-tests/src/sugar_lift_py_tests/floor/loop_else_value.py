from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.ir import Formula

from .floor_value import FloorValue


@dataclass(frozen=True)
class LoopElseValue(FloorValue):
    """A curried loop plus its no-break projection onto the ``else`` face."""

    loop_scope: FloorValue
    else_faces: FloorValue
    no_break_formula: Formula

    def contribution(self):
        return self.else_faces.contribution()

    def extend_scope(self, ctx):
        return self.else_faces.extend_scope(self.loop_scope.extend_scope(ctx))

    def follow_rest(self, rest, reduce):
        return self.else_faces.follow_rest(rest, reduce)

    def inv_contribution(self):
        return self.else_faces.inv_contribution()

    def post_contribution(self):
        return self.else_faces.post_contribution()

    def edge_contribution(self, source_contract):
        return self.else_faces.edge_contribution(source_contract)
