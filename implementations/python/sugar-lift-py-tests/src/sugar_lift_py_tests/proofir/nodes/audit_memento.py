from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

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


@dataclass(frozen=True)
class AuditLocus:
    file: str
    line: int
    col: int
    status: str
    ast_kind: str
    role: str
    contract: str
    source_memento: object

    def to_rpc(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "line": self.line,
            "col": self.col,
            "status": self.status,
            "ast_kind": self.ast_kind,
            "role": self.role,
            "contract": self.contract,
            "sourceMemento": self.source_memento,
        }


@dataclass(frozen=True, init=False)
class AuditMemento(ProofIRNode):
    node_class: ClassVar[str] = "AuditMemento"

    role: str = field(init=False)
    contract: str = field(init=False)
    file: str = field(init=False)
    source_function_name: str = field(init=False)
    loci: tuple[AuditLocus, ...] = field(init=False)
    _provenance: Provenance = field(init=False, repr=False)

    def __init__(
        self,
        *,
        role: str,
        contract: str,
        file: str,
        source_function_name: str,
        loci: tuple[AuditLocus, ...],
        provenance: Provenance,
    ) -> None:
        _require_provenance(provenance, owner=self.node_class)
        if not loci:
            raise TypeError("AuditMemento requires at least one AuditLocus")
        for locus in loci:
            if not isinstance(locus, AuditLocus):
                raise TypeError("AuditMemento loci must be AuditLocus")
        object.__setattr__(self, "role", role)
        object.__setattr__(self, "contract", contract)
        object.__setattr__(self, "file", file)
        object.__setattr__(self, "source_function_name", source_function_name)
        object.__setattr__(self, "loci", tuple(loci))
        object.__setattr__(self, "_provenance", provenance)

    def denotation(self) -> None:
        return None

    def provenance(self) -> Provenance:
        return self._provenance

    def to_declaration(self) -> dict[str, Any]:
        source_warranted = sum(1 for locus in self.loci if locus.status == "warranted")
        totals = {
            "source_loci": len(self.loci),
            "source_warranted": source_warranted,
            "source_inactive": 0,
            "source_support": 0,
            "source_refused": 0,
            "source_unresolved": 0,
            "unclassified_source": 0,
        }
        return {
            "role": self.role,
            "contract": self.contract,
            "file": self.file,
            "sourceFunctionName": self.source_function_name,
            "totals": totals,
            "loci": [locus.to_rpc() for locus in self.loci],
        }

    @classmethod
    def verdict_witnesses(cls) -> VerdictWitnessPair:
        return VerdictWitnessPair(
            truthful=VerdictWitnessCase(
                name="audit-memento-warranted-locus",
                expected="sat",
                formulas=(),
                declarations={"out": _INT_SORT},
                source=_truthful_source(),
                node_class=cls.node_class,
                expected_sugar="python.literal-call-sugar",
                construct=lambda: cls(
                    role="python.literal-call-sugar",
                    contract="module::source::assertion",
                    file="witness.py",
                    source_function_name="test_a",
                    loci=(
                        AuditLocus(
                            file="witness.py",
                            line=1,
                            col=0,
                            status="warranted",
                            ast_kind="Assert",
                            role="python.literal-call-sugar",
                            contract="module::source::assertion",
                            source_memento={"kind": "source-memento"},
                        ),
                    ),
                    provenance=_witness_provenance(
                        cls.node_class, warrants=("Stated",)
                    ),
                ),
            ),
            lying=VerdictWitnessCase(
                name="audit-memento-raw-locus-refuses",
                expected="construction-refusal",
                construct=lambda: cls(
                    role="python.literal-call-sugar",
                    contract="module::source::assertion",
                    file="witness.py",
                    source_function_name="test_a",
                    loci=({"line": 1},),
                    provenance=_witness_provenance(
                        cls.node_class, warrants=("Stated",)
                    ),
                ),
            ),
        )


__all__ = ["AuditLocus", "AuditMemento"]
