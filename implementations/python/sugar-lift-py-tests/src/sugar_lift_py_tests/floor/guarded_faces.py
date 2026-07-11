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
        # Exits decide what the continuation rides -- no type interrogation:
        # both exit -> unreachable (raw, like code after an unguarded return);
        # only then -> tail under not(guard); only else -> tail under guard;
        # neither -> reduce plain.
        if self.then_exits and self.else_exits:
            del reduce
            return rest
        entries = reduce(rest)
        if self.then_exits:
            from sugar_lift_py_tests.ir import not_

            return tuple(entry.guarded(not_(self.guard)) for entry in entries)
        if self.else_exits:
            return tuple(entry.guarded(self.guard) for entry in entries)
        return entries
