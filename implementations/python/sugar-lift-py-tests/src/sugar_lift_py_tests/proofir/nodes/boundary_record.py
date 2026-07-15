from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar, cast

from sugar_lift_py_tests.canonicalizer import blake3_512_of, encode_jcs
from sugar_lift_py_tests.effect import (
    CallResultTypeRuntimeEffect,
    Effect,
    effect_kind,
    effect_reason,
    require_effect,
    runtime_effect_witness,
)
from sugar_lift_py_tests.ir import _json_like_to_value, eq, make_var, num
from sugar_lift_py_tests.outcome import Incomplete

from . import (
    Provenance,
    VerdictWitnessCase,
    VerdictWitnessPair,
    _proofir_gap,
    _require_provenance,
    _witness_provenance,
)

if TYPE_CHECKING:
    from sugar_lift_py_tests.factory.floor_contract_agreement import (
        FloorContractAgreementViolation,
    )


@dataclass(frozen=True, init=False)
class BoundaryRecord:
    """A typed-effect record with grounds, not a lift-side refusal."""

    node_class: ClassVar[str] = "BoundaryRecord"

    effect: Effect = field(init=False)
    _provenance: Provenance = field(init=False, repr=False)

    def __init__(self, *, effect: Effect, provenance: Provenance) -> None:
        _require_provenance(provenance, owner=self.node_class)
        resolved_effect = require_effect(effect)
        reason = effect_reason(resolved_effect)
        if not reason:
            _proofir_gap(
                owner=self.node_class,
                observed="empty reason",
                requested="effect reason",
                fix="preserve the boundary reason when constructing BoundaryRecord",
            )
        object.__setattr__(self, "effect", resolved_effect)
        object.__setattr__(self, "_provenance", provenance)

    @property
    def effect_kind(self) -> str:
        return effect_kind(self.effect)

    @property
    def reason(self) -> str:
        return effect_reason(self.effect)

    @classmethod
    def from_incomplete(
        cls,
        incomplete: Incomplete,
        *,
        provenance: Provenance,
    ) -> BoundaryRecord:
        if not isinstance(incomplete, Incomplete):
            raise TypeError("BoundaryRecord.from_incomplete requires Incomplete")
        return cls(effect=incomplete.effect, provenance=provenance)

    def denotation(self) -> None:
        return None

    def provenance(self) -> Provenance:
        return self._provenance

    def to_declaration(self) -> dict[str, Any]:
        return {
            "kind": "boundary-record",
            "effectKind": self.effect_kind,
            "reason": self.reason,
            "provenance": self.provenance().to_rpc(),
        }

    @staticmethod
    def agreement_violation_diagnostic(
        violation: FloorContractAgreementViolation,
    ) -> dict[str, Any]:
        from sugar_lift_py_tests.factory.floor_contract_agreement import (
            FloorContractAgreementViolation,
        )

        if not isinstance(violation, FloorContractAgreementViolation):
            raise TypeError(
                "agreement_violation_diagnostic requires "
                "FloorContractAgreementViolation"
            )
        return {
            "kind": "floor-contract-agreement-violation",
            "callee": violation.callee,
            "contract": violation.contract,
            "callsite": violation.callsite,
            "reason": violation.reason,
        }

    def to_proof_ir(self) -> str:
        return encode_jcs(_json_like_to_value(self.to_declaration()))

    def cid(self) -> str:
        return blake3_512_of(self.to_proof_ir().encode("utf-8"))

    def to_semantic_declaration(self) -> dict[str, Any]:
        return self.to_declaration()

    def semantic_cid(self) -> str:
        return blake3_512_of(
            encode_jcs(_json_like_to_value(self.to_semantic_declaration())).encode(
                "utf-8"
            )
        )

    @classmethod
    def verdict_witnesses(cls) -> VerdictWitnessPair:
        return VerdictWitnessPair(
            truthful=VerdictWitnessCase(
                name="boundary-record-bridge-only",
                expected="sat",
                formulas=(),
                declarations={},
                source=_effectful_refusal_source(),
                node_class=cls.node_class,
                expected_sugar="python.literal-call-sugar",
                refusal_absence=True,
                construct=lambda: cls.from_incomplete(
                    _runtime_effect_incomplete("opaque runtime effect"),
                    provenance=_witness_provenance(
                        cls.node_class, warrants=("Derived",)
                    ),
                ),
            ),
            lying=VerdictWitnessCase(
                name="boundary-record-fact-and-refusal-refuses",
                expected="construction-refusal",
                formulas=(),
                declarations={},
                construct=lambda: _fact_and_refusal_refuses(cls),
            ),
        )


def _effectful_refusal_source() -> str:
    return (
        "def A(x):\n"
        "    print(x)\n"
        "    return x\n"
        "\n"
        "def test_a():\n"
        "    assert A(5) == 5\n"
    )


def _runtime_effect_incomplete(reason: str) -> Incomplete:
    return Incomplete(
        CallResultTypeRuntimeEffect(
            reason,
            witness=runtime_effect_witness(
                "py.call", "print", "<boundary-record-witness-case>"
            ),
        )
    )


def _fact_and_refusal_refuses(cls: type[BoundaryRecord]) -> BoundaryRecord:
    return cast(Any, cls.from_incomplete)(
        _runtime_effect_incomplete("opaque runtime effect"),
        provenance=_witness_provenance(cls.node_class, warrants=("Derived",)),
        formula=eq(make_var("call"), num(0)),
    )


__all__ = ["BoundaryRecord"]
