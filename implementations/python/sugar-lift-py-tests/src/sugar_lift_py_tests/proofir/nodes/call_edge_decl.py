from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

from sugar_lift_py_tests.ir import Locus
from sugar_lift_py_tests.proofir.scope import ClaimFormula

from . import (
    Provenance,
    ProofIRNode,
    VerdictWitnessCase,
    VerdictWitnessPair,
    _INT_SORT,
    _require_provenance,
    _truthful_source,
    _witness_provenance,
)


@dataclass(frozen=True, init=False)
class BridgeAtom:
    source_contract: str = field(init=False)
    target_symbol: str = field(init=False)
    target_contract: str | None = field(init=False, default=None)
    target_contract_cid: str | None = field(init=False, default=None)
    target_proof_cid: str | None = field(init=False, default=None)
    call_site_locus: Locus | None = field(init=False, default=None)
    callsite: str | None = field(init=False, default=None)
    evidence_term: ClaimFormula | None = field(init=False, default=None)

    def __init__(
        self,
        *,
        source_contract: str,
        target_symbol: str,
        target_contract: str | None = None,
        target_contract_cid: str | None = None,
        target_proof_cid: str | None = None,
        call_site_locus: Locus | None = None,
        callsite: str | None = None,
        evidence_term: ClaimFormula | None = None,
    ) -> None:
        if not source_contract:
            raise TypeError("BridgeAtom requires source_contract")
        if not target_symbol:
            raise TypeError("BridgeAtom requires target_symbol")
        if call_site_locus is None and callsite is None:
            raise TypeError("BridgeAtom requires call_site_locus or callsite")
        if call_site_locus is not None and not isinstance(call_site_locus, Locus):
            raise TypeError("BridgeAtom call_site_locus must be Locus")
        if evidence_term is not None and not isinstance(evidence_term, ClaimFormula):
            raise TypeError("BridgeAtom evidence_term must be ClaimFormula")
        object.__setattr__(self, "source_contract", source_contract)
        object.__setattr__(self, "target_symbol", target_symbol)
        object.__setattr__(self, "target_contract", target_contract)
        object.__setattr__(self, "target_contract_cid", target_contract_cid)
        object.__setattr__(self, "target_proof_cid", target_proof_cid)
        object.__setattr__(self, "call_site_locus", call_site_locus)
        object.__setattr__(self, "callsite", callsite)
        object.__setattr__(self, "evidence_term", evidence_term)


@dataclass(frozen=True, init=False)
class CallEdgeDecl(ProofIRNode):
    node_class: ClassVar[str] = "CallEdgeDecl"

    bridge: BridgeAtom = field(init=False)
    _provenance: Provenance = field(init=False, repr=False)

    def __init__(self, *, bridge: BridgeAtom, provenance: Provenance) -> None:
        _require_provenance(provenance, owner=self.node_class)
        if not isinstance(bridge, BridgeAtom):
            raise TypeError("CallEdgeDecl bridge must be BridgeAtom")
        object.__setattr__(self, "bridge", bridge)
        object.__setattr__(self, "_provenance", provenance)

    def denotation(self):
        return (
            self.bridge.evidence_term.ir_formula if self.bridge.evidence_term else None
        )

    def provenance(self) -> Provenance:
        return self._provenance

    def to_declaration(self) -> dict[str, Any]:
        edge: dict[str, Any] = {"kind": "call-edge"}
        if self.bridge.call_site_locus is not None:
            edge["schemaVersion"] = "1"
        edge["sourceContract"] = self.bridge.source_contract
        edge["targetSymbol"] = self.bridge.target_symbol
        edge["targetContract"] = self.bridge.target_contract
        if self.bridge.call_site_locus is not None:
            edge["targetContractCid"] = self.bridge.target_contract_cid
            edge["callSiteLocus"] = {
                "file": self.bridge.call_site_locus.file,
                "line": self.bridge.call_site_locus.line,
                "column": self.bridge.call_site_locus.column,
            }
        if self.bridge.callsite is not None:
            edge["callsite"] = self.bridge.callsite
        if self.bridge.target_proof_cid is not None:
            edge["targetProofCid"] = self.bridge.target_proof_cid
        return edge

    @classmethod
    def verdict_witnesses(cls) -> VerdictWitnessPair:
        return VerdictWitnessPair(
            truthful=VerdictWitnessCase(
                name="call-edge-decl-sound-linkage",
                expected="sat",
                formulas=(),
                declarations={"out": _INT_SORT},
                source=_truthful_source(),
                node_class=cls.node_class,
                expected_sugar="python.literal-call-sugar",
                construct=lambda: cls(
                    bridge=BridgeAtom(
                        source_contract="module::source::assertion",
                        target_symbol="call:A",
                        call_site_locus=Locus("witness.py", 1, 0),
                    ),
                    provenance=_witness_provenance(
                        cls.node_class, warrants=("Derived",)
                    ),
                ),
            ),
            lying=VerdictWitnessCase(
                name="call-edge-decl-raw-json-refuses",
                expected="construction-refusal",
                construct=lambda: cls(
                    bridge={"kind": "call-edge"},
                    provenance=_witness_provenance(
                        cls.node_class, warrants=("Derived",)
                    ),
                ),
            ),
        )


__all__ = ["BridgeAtom", "CallEdgeDecl"]
