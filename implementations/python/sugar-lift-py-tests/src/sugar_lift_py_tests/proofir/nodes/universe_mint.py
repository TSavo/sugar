from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal

from sugar_lift_py_tests.kit_rpc import BodyUniverseDto, CallsiteFactDto, SourceMementoDto
from sugar_lift_py_tests.proofir.scope import ClaimFormula

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


UniverseSlot = Literal["pre", "post", "inv"]
SourceWarrant = SourceMementoDto | dict[str, Any]


@dataclass(frozen=True, init=False)
class UniverseMint(ProofIRNode):
    node_class: ClassVar[str] = "UniverseMint"

    name: str = field(init=False)
    slot: UniverseSlot = field(init=False)
    formula: ClaimFormula = field(init=False)
    _provenance: Provenance = field(init=False, repr=False)
    out_binding: str = field(init=False, default="out")
    source_warrants: tuple[SourceWarrant, ...] = field(init=False, default=())
    warranted_by: CallsiteFactDto | dict[str, Any] | None = field(init=False, default=None)
    formals: tuple[str, ...] = field(init=False, default=())
    kind: str = field(init=False, default="contract")
    bridge_source_symbol: str | None = field(init=False, default=None)

    def __init__(
        self,
        *,
        name: str,
        slot: UniverseSlot,
        formula: ClaimFormula,
        provenance: Provenance,
        out_binding: str = "out",
        source_warrants: tuple[SourceWarrant, ...] = (),
        warranted_by: CallsiteFactDto | dict[str, Any] | None = None,
        formals: tuple[str, ...] = (),
        kind: str = "contract",
        bridge_source_symbol: str | None = None,
    ) -> None:
        _require_provenance(provenance, owner=self.node_class)
        if slot not in {"pre", "post", "inv"}:
            _proofir_gap(
                owner=self.node_class,
                observed=str(slot),
                requested="pre, post, or inv",
                fix="install the formula into one verifier-visible BodyUniverse slot",
            )
        if not isinstance(formula, ClaimFormula):
            raise TypeError("UniverseMint formula must be ClaimFormula")
        if not name:
            _proofir_gap(
                owner=self.node_class,
                observed="empty name",
                requested="BodyUniverse contract name",
                fix="name the contract before minting the universe",
            )
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "slot", slot)
        object.__setattr__(self, "formula", formula)
        object.__setattr__(self, "_provenance", provenance)
        object.__setattr__(self, "out_binding", out_binding)
        object.__setattr__(self, "source_warrants", tuple(source_warrants))
        object.__setattr__(self, "warranted_by", warranted_by)
        object.__setattr__(self, "formals", tuple(formals))
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "bridge_source_symbol", bridge_source_symbol)

    def denotation(self):
        return self.formula.ir_formula

    def provenance(self) -> Provenance:
        return self._provenance

    def to_body_universe(self) -> BodyUniverseDto:
        slots: dict[str, ClaimFormula | None] = {"pre": None, "post": None, "inv": None}
        slots[self.slot] = self.formula
        return BodyUniverseDto(
            name=self.name,
            out_binding=self.out_binding,
            pre=slots["pre"],
            post=slots["post"],
            inv=slots["inv"],
            source_warrants=list(self.source_warrants),
            warranted_by=self.warranted_by,
            formals=list(self.formals),
            kind=self.kind,
            bridge_source_symbol=self.bridge_source_symbol,
        )

    def to_declaration(self) -> dict[str, Any]:
        return self.to_body_universe().to_rpc()

    @classmethod
    def verdict_witnesses(cls) -> VerdictWitnessPair:
        return VerdictWitnessPair(
            truthful=VerdictWitnessCase(
                name="universe-mint-post-models-floor",
                expected="sat",
                formulas=(),
                declarations={"out": _INT_SORT},
                source=_truthful_source(),
                node_class=cls.node_class,
                expected_sugar="python.literal-call-sugar",
                construct=lambda: cls(
                    name="module::truthful::assertion",
                    slot="inv",
                    formula=_witness_claim_formula(cls.node_class, value=0),
                    provenance=_witness_provenance(cls.node_class, warrants=("Derived",)),
                ),
            ),
            lying=VerdictWitnessCase(
                name="universe-mint-raw-formula-refuses",
                expected="construction-refusal",
                construct=lambda: cls(
                    name="module::lying::assertion",
                    slot="inv",
                    formula={"kind": "atomic"},
                    provenance=_witness_provenance(cls.node_class, warrants=("Derived",)),
                ),
            ),
        )


def _witness_claim_formula(node_class: str, *, value: int) -> ClaimFormula:
    from sugar_lift_py_tests.ir import eq, make_var, num
    from sugar_lift_py_tests.proofir.scope import claim_formula_from_ir
    from sugar_lift_py_tests.proofir.sorts import IntSort

    return claim_formula_from_ir(
        eq(make_var("out"), num(value)),
        var_sorts={"out": IntSort()},
        allowed_vars=("out",),
        provenance=_witness_provenance(node_class, warrants=("Derived",)),
        role=f"{node_class}.witness",
    )


BodyUniverse = UniverseMint


__all__ = ["BodyUniverse", "UniverseMint"]
