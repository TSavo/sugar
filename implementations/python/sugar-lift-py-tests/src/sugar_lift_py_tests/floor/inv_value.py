from __future__ import annotations

from dataclasses import field as dataclass_field, dataclass, field as dataclass_field

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
    site: object = dataclass_field(default=None, compare=False)

    def inv_contribution(self):
        # The stated fact IS the inv slot's row.
        return (self.formula,)

    def guarded(self, formula):
        # A fact stated under a guard IS an implication.
        from sugar_lift_py_tests.ir import implies

        return InvValue(implies(formula, self.formula), self.site)

    def mint_contribution(self, name, formals):
        # The stated fact mints its own row: slot="inv", Stated provenance (the
        # vendor spoke it; the locus is this site), the sealed source warrant
        # read straight off the carried fragment. Carried, projected -- nothing
        # assembled from outside.
        from sugar_lift_py_tests.floor.universe_mint_projection import (
            claim_formula,
            construction_site,
        )
        from sugar_lift_py_tests.proofir.nodes import Provenance, Stated
        from sugar_lift_py_tests.proofir.nodes.universe_mint import UniverseMint

        locus = construction_site(self.site)
        provenance = Provenance(
            node_class="UniverseMint",
            construction_site=locus,
            warrant=Stated(locus=locus),
        )
        return (
            UniverseMint(
                name=name,
                slot="inv",
                formula=claim_formula(
                    self.formula, formals=formals, provenance=provenance, role="inv"
                ),
                provenance=provenance,
                source_warrants=(self.site.memento(),),
                formals=formals,
            ),
        )
