from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.ir import Formula

from .floor_value import FloorValue


@dataclass(frozen=True)
class GuardedFaces(FloorValue):
    """A symbolic condition's `if`: it cannot pick a face, so it guards. The
    entries are the face records already riding under their polarity. When the
    then-face exits and there is no else, the block's continuation IS the else:
    it rides under the negated guard (`then_exits` carries that). The faces
    splice into the enclosing record like a block."""

    guard: Formula
    entries: tuple
    then_exits: bool

    def contribution(self):
        return self.entries

    def inv_contribution(self):
        return tuple(
            formula
            for entry in self.entries
            for formula in entry.inv_contribution()
        )

    def post_contribution(self):
        return tuple(
            formula
            for entry in self.entries
            for formula in entry.post_contribution()
        )

    def edge_contribution(self, source_contract):
        # Faces splice into the record; each entry projects its own edges.
        return tuple(
            edge
            for entry in self.entries
            for edge in entry.edge_contribution(source_contract)
        )

    def follow_rest(self, rest, reduce):
        # The continuation after a then-only `if` whose face exits IS the else:
        # it rides under the negated guard. A non-exiting face constrains
        # nothing downstream -- the continuation runs either way.
        entries = reduce(rest)
        if not self.then_exits:
            return entries
        from sugar_lift_py_tests.ir import not_

        return tuple(entry.guarded(not_(self.guard)) for entry in entries)
