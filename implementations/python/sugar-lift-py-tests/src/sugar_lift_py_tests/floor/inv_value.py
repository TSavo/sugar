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
    It contributes itself to the record (the record IS the emission surface)."""

    formula: Formula
    site: object = dataclass_field(default=None, compare=False)
    # CallSiteValues consumed into the formula when the inv was stated --
    # carried so callEdges project from the collapse without a side channel.
    operand_callsites: tuple = dataclass_field(default=(), compare=False)
    derived_formulas: tuple = dataclass_field(default=(), compare=False)
    rewrite_chains: tuple[tuple[str, str, int], ...] = dataclass_field(
        default=(), compare=False
    )

    def inv_contribution(self):
        # The stated fact IS the inv slot's row.
        return (self.formula,)

    def guarded(self, formula):
        # A fact stated under a guard IS an implication; operand callsites ride.
        from sugar_lift_py_tests.ir import implies

        return InvValue(
            implies(formula, self.formula),
            self.site,
            self.operand_callsites,
            self.derived_formulas,
            self.rewrite_chains,
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
        stated_warrant = Stated(locus=locus)
        exact_duplicate = any(
            formula == self.formula for formula in self.derived_formulas
        )
        equality_duplicate = next(
            (
                formula
                for formula in self.derived_formulas
                if _same_equality_operands(formula, self.formula)
            ),
            None,
        )
        duplicate_derived = exact_duplicate or equality_duplicate is not None
        stated_formula = self.formula
        if equality_duplicate is not None:
            # The derived warrant resolves the final per-atom vocabulary to
            # FOL equality.  Collapse the truthful stated/derived pair by
            # semantic operands while retaining both provenance warrants.
            stated_formula = equality_duplicate
        elif exact_duplicate:
            from sugar_lift_py_tests.ir import and_

            stated_formula = and_([self.formula, self.formula])
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
            warrant=(
                (
                    stated_warrant,
                    Derived(floor_chain=_derived_floor_chain(self.formula)),
                    *rewrite_warrants,
                )
                if duplicate_derived
                else (stated_warrant, *rewrite_warrants)
            ),
        )
        stated = (
            UniverseMint(
                name=name,
                slot="inv",
                formula=claim_formula(
                    stated_formula,
                    formals=formals,
                    provenance=stated_provenance,
                    role="inv",
                ),
                provenance=stated_provenance,
                source_warrants=(self.site.memento(),),
                formals=formals,
            ),
        )
        if not self.derived_formulas:
            return stated

        derived = tuple(
            UniverseMint(
                name=name,
                slot="inv",
                formula=claim_formula(
                    formula,
                    formals=formals,
                    provenance=Provenance(
                        node_class="UniverseMint",
                        construction_site=locus,
                        warrant=Derived(floor_chain=_derived_floor_chain(formula)),
                    ),
                    role="inv",
                ),
                provenance=Provenance(
                    node_class="UniverseMint",
                    construction_site=locus,
                    warrant=Derived(floor_chain=_derived_floor_chain(formula)),
                ),
                source_warrants=(self.site.memento(),),
                formals=formals,
            )
            for formula in self.derived_formulas
            if formula != self.formula
            and not _same_equality_operands(formula, self.formula)
        )
        return (*stated, *derived)


def _derived_floor_chain(formula: Formula) -> tuple[str, ...]:
    from sugar_lift_py_tests.ir import _Atomic, _Connective, _Ctor

    if (
        isinstance(formula, _Connective)
        and formula.kind == "implies"
        and len(formula.operands) == 2
        and isinstance(formula.operands[0], _Atomic)
        and formula.operands[0].name == "py.eq"
        and isinstance(formula.operands[1], _Atomic)
        and formula.operands[1].name == "="
        and any(
            isinstance(arg, _Ctor) and arg.name == "to_real"
            for arg in formula.operands[1].args
        )
    ):
        return ("PythonEqualityPromotionBridge",)
    return ("OpaqueOpCallsite.computed",)


def _same_equality_operands(left: Formula, right: Formula) -> bool:
    from sugar_lift_py_tests.ir import _Atomic

    return (
        isinstance(left, _Atomic)
        and isinstance(right, _Atomic)
        and left.name in {"=", "py.eq"}
        and right.name in {"=", "py.eq"}
        and left.args == right.args
        and left.name != right.name
    )
