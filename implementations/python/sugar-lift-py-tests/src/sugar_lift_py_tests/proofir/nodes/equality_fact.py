from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

from sugar_lift_py_tests.ir import Formula, Term, TermTableBuilder, _Ctor
from sugar_lift_py_tests.kit_rpc import BodyUniverseDto
from sugar_lift_py_tests.proofir._errors import proofir_construction_gap
from sugar_lift_py_tests.proofir.formulas import Eq as ProofEq
from sugar_lift_py_tests.proofir.scope import ClosedFormula, claim_formula_from_ir
from sugar_lift_py_tests.proofir.sorts import IntSort
from sugar_lift_py_tests.proofir.terms import (
    CallTerm,
    ConstTerm,
    Term as ProofTerm,
)

from . import (
    Provenance,
    ProofIRNode,
    VerdictWitnessCase,
    VerdictWitnessPair,
    _INT_SORT,
    _canonical_term_sig,
    _formula_to_rpc,
    _lying_source,
    _merge_provenance,
    _proofir_gap,
    _require_provenance,
    _truthful_source,
    _witness_provenance,
)


@dataclass(frozen=True, init=False)
class EqualityFact(ProofIRNode):
    node_class: ClassVar[str] = "EqualityFact"

    euf_key: str = field(init=False)
    call_term: CallTerm[Any] = field(init=False)
    rhs_term: ProofTerm[Any] = field(init=False)
    _provenance: Provenance = field(init=False, repr=False)
    _closed_formula: ClosedFormula = field(init=False, repr=False)

    def __init__(
        self,
        *,
        call_term: CallTerm[Any],
        rhs_term: ProofTerm[Any],
        provenance: Provenance,
    ) -> None:
        _require_provenance(provenance, owner=self.node_class)
        if not isinstance(call_term, CallTerm):
            proofir_construction_gap(
                owner=self.node_class,
                observed=type(call_term).__name__,
                requested="CallTerm",
                fix="construct EqualityFact from proofir.terms.CallTerm, never a naked Formula or raw ir term",
            )
        if not isinstance(rhs_term, ProofTerm):
            proofir_construction_gap(
                owner=self.node_class,
                observed=type(rhs_term).__name__,
                requested="typed ProofIR Term",
                fix="wrap the rhs ir.py term before constructing EqualityFact",
            )
        closed = ClosedFormula(ProofEq(call_term, rhs_term))
        object.__setattr__(self, "euf_key", canonical_euf_callsite_name(call_term))
        object.__setattr__(self, "call_term", call_term)
        object.__setattr__(self, "rhs_term", rhs_term)
        object.__setattr__(self, "_provenance", provenance)
        object.__setattr__(self, "_closed_formula", closed)

    def denotation(self) -> Formula:
        return self._closed_formula.ir_formula

    def provenance(self) -> Provenance:
        return self._provenance

    def to_body_universe(self) -> BodyUniverseDto:
        return BodyUniverseDto(
            name=self.euf_key,
            out_binding="out",
            inv=claim_formula_from_ir(
                self.denotation(),
                var_sorts={
                    **self.call_term.free_var_sorts,
                    **self.rhs_term.free_var_sorts,
                },
                allowed_vars=self._closed_formula.formula.free_vars,
                provenance=self.provenance(),
                role="EqualityFact.inv",
            ),
            proofir_provenance=self.provenance().warrant_memento(),
        )

    def to_declaration(self) -> dict[str, Any]:
        # Wire shape: term positions are content-addressed refs (#4406).
        return self.to_body_universe().to_rpc_with_term_table(TermTableBuilder())

    def to_semantic_declaration(self) -> dict[str, Any]:
        # Local merge identity preimage — expanded trees, not the payload door.
        return BodyUniverseDto(
            name=self.euf_key,
            out_binding="out",
            inv=claim_formula_from_ir(
                self.denotation(),
                var_sorts={
                    **self.call_term.free_var_sorts,
                    **self.rhs_term.free_var_sorts,
                },
                allowed_vars=self._closed_formula.formula.free_vars,
                provenance=self.provenance(),
                role="EqualityFact.inv",
            ),
        ).to_semantic_rpc()

    @classmethod
    def verdict_witnesses(cls) -> VerdictWitnessPair:
        call = CallTerm("A", (), sort=IntSort())
        stated_truth = cls(
            call_term=call,
            rhs_term=ConstTerm(0, sort=IntSort()),
            provenance=_witness_provenance(cls.node_class, warrants=("Stated",)),
        )
        derived_truth = cls(
            call_term=call,
            rhs_term=ConstTerm(0, sort=IntSort()),
            provenance=_witness_provenance(cls.node_class, warrants=("Derived",)),
        )
        truthful = merge_equality_facts(stated_truth, derived_truth)
        stated_lie = cls(
            call_term=call,
            rhs_term=ConstTerm(1, sort=IntSort()),
            provenance=_witness_provenance(cls.node_class, warrants=("Stated",)),
        )
        derived = cls(
            call_term=call,
            rhs_term=ConstTerm(0, sort=IntSort()),
            provenance=_witness_provenance(cls.node_class, warrants=("Derived",)),
        )
        return VerdictWitnessPair(
            truthful=VerdictWitnessCase(
                name="equality-truthful-collapse",
                expected="sat",
                formulas=(truthful.denotation(),),
                declarations={"call:A": _INT_SORT},
                source=_truthful_source(),
                node_class=cls.node_class,
                expected_sugar="python.literal-call-sugar",
            ),
            lying=VerdictWitnessCase(
                name="equality-stated-derived-disagreement",
                expected="unsat",
                formulas=(stated_lie.denotation(), derived.denotation()),
                declarations={"call:A": _INT_SORT},
                source=_lying_source(),
                node_class=cls.node_class,
                expected_sugar="python.literal-call-sugar",
            ),
        )


def merge_equality_facts(left: EqualityFact, right: EqualityFact) -> EqualityFact:
    if left.semantic_cid() != right.semantic_cid():
        _proofir_gap(
            owner="EqualityFact.merge",
            observed=(
                f"left semantic_cid={left.semantic_cid()} "
                f"right semantic_cid={right.semantic_cid()}"
            ),
            requested="equal semantic_cid for EqualityFact merge",
            fix="keep disagreeing stated/derived facts as separate formulas",
        )
    if left.provenance() == right.provenance():
        return left
    merged_provenance = _merge_provenance(left.provenance(), right.provenance())
    return EqualityFact(
        call_term=left.call_term,
        rhs_term=left.rhs_term,
        provenance=merged_provenance,
    )


def canonical_euf_callsite_name(
    call_term: Term | CallTerm[Any],
    *,
    suffix: str = "::assertion",
) -> str:
    ir_call_term = call_term.ir_term if isinstance(call_term, CallTerm) else call_term
    if not isinstance(ir_call_term, _Ctor) or not ir_call_term.name.startswith("call:"):
        _proofir_gap(
            owner="EqualityFact",
            observed=repr(ir_call_term),
            requested="call:<callee> ctor term",
            fix="derive #euf# keys only from euf_call_term outputs",
        )
    callee = ir_call_term.name.removeprefix("call:")
    return f"{callee}#euf#{_canonical_term_sig(ir_call_term)}{suffix}"
