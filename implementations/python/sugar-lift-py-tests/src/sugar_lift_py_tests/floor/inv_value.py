from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.ir import Formula

from .floor_value import FloorValue


@dataclass(frozen=True)
class InvValue(FloorValue):
    """A stated fact: the inv an assert emits into the block record. First
    encounter it is a fact with an obligation to discharge; a later consumer
    meets the same sentence through its memento as a warrant -- a constraint.
    That duality is protocol position, not a field here: the sentence travels
    content-addressed, and the side of the RPC round decides prove-vs-assume.
    It contributes itself to the record (the record IS the emission surface)."""

    formula: Formula

    def inv_contribution(self):
        # The stated fact IS the inv slot's row.
        return (self.formula,)

    def guarded(self, formula):
        # A fact stated under a guard IS an implication.
        from sugar_lift_py_tests.ir import implies

        return InvValue(implies(formula, self.formula))
