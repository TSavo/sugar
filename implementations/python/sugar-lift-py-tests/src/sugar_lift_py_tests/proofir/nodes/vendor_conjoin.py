from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

from . import (
    Provenance,
    ProofIRNode,
    VerdictWitnessCase,
    VerdictWitnessPair,
    _INT_SORT,
    _proofir_gap,
    _require_provenance,
    _truthful_source,
    _witness_provenance,
)
from .equality_fact import EqualityFact
from .refusal_record import RefusalRecord
from .universe_mint import UniverseMint


@dataclass(frozen=True)
class FactAtom:
    fact: EqualityFact

    def __post_init__(self) -> None:
        if not isinstance(self.fact, EqualityFact):
            raise TypeError("FactAtom requires EqualityFact")


@dataclass(frozen=True)
class UniverseAtom:
    universe: UniverseMint

    def __post_init__(self) -> None:
        if not isinstance(self.universe, UniverseMint):
            raise TypeError("UniverseAtom requires UniverseMint")


@dataclass(frozen=True, init=False)
class VendorConjoin(ProofIRNode):
    node_class: ClassVar[str] = "VendorConjoin"

    fact: FactAtom | None = field(init=False)
    universe: UniverseAtom | None = field(init=False)
    refusal: RefusalRecord | None = field(init=False)
    _provenance: Provenance = field(init=False, repr=False)

    def __init__(
        self,
        *,
        fact: FactAtom | None = None,
        universe: UniverseAtom | None = None,
        refusal: RefusalRecord | None = None,
        provenance: Provenance,
    ) -> None:
        _require_provenance(provenance, owner=self.node_class)
        if refusal is not None:
            if not isinstance(refusal, RefusalRecord):
                raise TypeError("VendorConjoin refusal must be RefusalRecord")
            if fact is not None or universe is not None:
                _proofir_gap(
                    owner=self.node_class,
                    observed="fact/universe plus refusal",
                    requested="either typed fact+universe or explicit refusal",
                    fix="do not let a vendor fact float in the silent third state",
                )
        else:
            if not isinstance(fact, FactAtom):
                raise TypeError("VendorConjoin fact must be FactAtom")
            if not isinstance(universe, UniverseAtom):
                raise TypeError("VendorConjoin universe must be UniverseAtom")
        object.__setattr__(self, "fact", fact)
        object.__setattr__(self, "universe", universe)
        object.__setattr__(self, "refusal", refusal)
        object.__setattr__(self, "_provenance", provenance)

    def denotation(self):
        return self.fact.fact.denotation() if self.fact is not None else None

    def provenance(self) -> Provenance:
        return self._provenance

    def to_declaration(self) -> dict[str, Any]:
        if self.refusal is not None:
            return {
                "kind": "vendor-conjoin",
                "refusal": self.refusal.to_declaration(),
                "provenance": self.provenance().to_rpc(),
            }
        assert self.fact is not None and self.universe is not None
        return {
            "kind": "vendor-conjoin",
            "fact": self.fact.fact.euf_key,
            "universe": self.universe.universe.name,
            "provenance": self.provenance().to_rpc(),
        }

    @classmethod
    def verdict_witnesses(cls) -> VerdictWitnessPair:
        return VerdictWitnessPair(
            truthful=VerdictWitnessCase(
                name="vendor-conjoin-typed-fact-and-universe",
                expected="sat",
                formulas=(),
                declarations={"out": _INT_SORT},
                source=_truthful_source(),
                node_class=cls.node_class,
                expected_sugar="python.literal-call-sugar",
                construct=lambda: _witness_vendor_conjoin(cls),
            ),
            lying=VerdictWitnessCase(
                name="vendor-conjoin-raw-formula-refuses",
                expected="construction-refusal",
                construct=lambda: cls(
                    fact={"kind": "atomic"},
                    universe=None,
                    provenance=_witness_provenance(cls.node_class, warrants=("Stated",)),
                ),
            ),
        )


def _witness_vendor_conjoin(cls: type[VendorConjoin]) -> VendorConjoin:
    from sugar_lift_py_tests.proofir.terms import CallTerm, ConstTerm
    from sugar_lift_py_tests.proofir.sorts import IntSort
    from .universe_mint import _witness_claim_formula

    fact = EqualityFact(
        call_term=CallTerm("A", (), sort=IntSort()),
        rhs_term=ConstTerm(0, sort=IntSort()),
        provenance=_witness_provenance("EqualityFact", warrants=("Stated",)),
    )
    universe = UniverseMint(
        name="module::A::callable",
        slot="post",
        formula=_witness_claim_formula("UniverseMint", value=0),
        provenance=_witness_provenance("UniverseMint", warrants=("Derived",)),
    )
    return cls(
        fact=FactAtom(fact),
        universe=UniverseAtom(universe),
        provenance=_witness_provenance(cls.node_class, warrants=("Stated",)),
    )


__all__ = ["FactAtom", "UniverseAtom", "VendorConjoin"]
