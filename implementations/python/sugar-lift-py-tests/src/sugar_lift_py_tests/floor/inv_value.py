from __future__ import annotations

from dataclasses import field as dataclass_field, dataclass

from sugar_lift_py_tests.ir import Formula

from .floor_value import FloorValue


@dataclass(frozen=True)
class InvValue(FloorValue):
    """A stated fact: the inv an assert emits into the block record. First
    encounter it is a fact with an obligation to discharge; a later consumer
    meets the same sentence through its memento as a warrant -- a constraint.
    That duality is protocol position, not a field here: the sentence travels
    content-addressed, and the side of the RPC round decides prove-vs-assume.
    It contributes itself to the record (the record IS the emission surface).

    ``bindings`` are exact refinements warranted by the stated fact (for example
    ``assert how in ("first", "last")`` rebinds ``how`` to the finite domain).
    They extend temporal scope for the continuing tail; they are not inventions
    of the assert sugar — they ride from the reduced predicate's then_bindings.
    """

    formula: Formula
    site: object = dataclass_field(default=None, compare=False)
    # CallSiteValues consumed into the formula when the inv was stated --
    # carried so callEdges project from the collapse without a side channel.
    operand_callsites: tuple = dataclass_field(default=(), compare=False)
    derived_formulas: tuple = dataclass_field(default=(), compare=False)
    rewrite_chains: tuple[tuple[str, str, int], ...] = dataclass_field(
        default=(), compare=False
    )
    bindings: tuple[tuple[str, FloorValue], ...] = dataclass_field(
        default=(), compare=False
    )

    def inv_contribution(self):
        # The stated fact IS the inv slot's row.
        return (self.formula,)

    def extend_scope(self, ctx):
        # Asserted then_bindings are definite on the continuing path: the false
        # face of the predicate would have halted (AssertionError), so the tail
        # only runs under the true face.
        if ctx is None:
            return None

        from dataclasses import replace

        temporal = ctx.temporal
        for name, value in self.bindings:
            temporal = temporal.bind_value(name, value)
        return replace(ctx, temporal=temporal)

    def guarded(self, formula):
        # A fact stated under a guard IS an implication; operand callsites ride.
        # Bindings stay attached: they refine under the same guard polarity the
        # inv already carries as implication.
        from sugar_lift_py_tests.ir import implies

        return InvValue(
            implies(formula, self.formula),
            self.site,
            self.operand_callsites,
            self.derived_formulas,
            self.rewrite_chains,
            self.bindings,
        )

    def edge_contribution(self, source_contract):
        # Project edges from the CallSiteValues that rode into this inv.
        return tuple(
            edge
            for callsite in self.operand_callsites
            for edge in callsite.edge_contribution(source_contract)
        )

    def mint_contribution(self, name, formals):
        # The stated fact mints its own row: slot="inv", Stated provenance (the
        # vendor spoke it; the locus is this site), the sealed source warrant
        # read straight off the carried fragment. Carried, projected -- nothing
        # assembled from outside.
        from sugar_lift_py_tests.floor.universe_mint_projection import (
            claim_formula,
            construction_site,
        )
        from sugar_lift_py_tests.proofir.nodes import (
            ConstructionSite,
            Derived,
            Provenance,
            Stated,
        )
        from sugar_lift_py_tests.proofir.nodes.universe_mint import UniverseMint

        locus = construction_site(self.site)
        rewrite_warrants = tuple(
            Derived(
                floor_chain=(chain,),
                locus=ConstructionSite(path=path, line=line, column=0),
            )
            for chain, path, line in self.rewrite_chains
        )
        stated_provenance = Provenance(
            node_class="UniverseMint",
            construction_site=locus,
            warrant=(Stated(locus=locus), *rewrite_warrants),
        )
        stated = (
            UniverseMint(
                name=name,
                slot="inv",
                formula=claim_formula(
                    self.formula,
                    formals=formals,
                    provenance=stated_provenance,
                    role="inv",
                ),
                provenance=stated_provenance,
                source_warrants=(self.site.memento(),),
                formals=formals,
            ),
        )
        # The one derived formula is the Int/Real promotion bridge an
        # equality carries beside its stated ``py.eq``
        # (``equality_atom.resolve_equality_atom``): ``py.eq(i, r) =>
        # to_real(i) = r``, minted as its own row.  Nothing here computes a
        # call's result for a sibling of it (#7789).
        bridge_provenance = Provenance(
            node_class="UniverseMint",
            construction_site=locus,
            warrant=Derived(floor_chain=("PythonEqualityPromotionBridge",)),
        )
        derived = tuple(
            UniverseMint(
                name=name,
                slot="inv",
                formula=claim_formula(
                    formula,
                    formals=formals,
                    provenance=bridge_provenance,
                    role="inv",
                ),
                provenance=bridge_provenance,
                source_warrants=(self.site.memento(),),
                formals=formals,
            )
            for formula in self.derived_formulas
        )
        return (*stated, *derived)
