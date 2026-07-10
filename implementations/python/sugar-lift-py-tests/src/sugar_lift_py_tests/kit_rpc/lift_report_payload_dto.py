from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .assertion_surface_audit_dto import AssertionSurfaceAuditDto
from .body_universe_dto import BodyUniverseDto
from .component_plan_memento_dto import ComponentPlanMementoDto
from .effect_dto import EffectDto
from .factory_audit_summary_dto import FactoryAuditSummaryDto
from .factory_walk_row_dto import FactoryWalkRowDto
from .implication_dto import ImplicationDto
from .open_lane_dto import (
    CallEdgeDto,
    DiagnosticDto,
    FactoryAuditDto,
    SourceAuditDto,
    VendorConjoinDto,
)
from .rpc_value import to_rpc_value
from .source_memento_dto import SourceMementoDto


@dataclass(frozen=True)
class LiftReportPayloadDto:
    # Closed lanes: a DTO already exists for every row, so no raw-dict side
    # door is left for callers to bypass construction law (#3661).
    ir: list[BodyUniverseDto] = field(default_factory=list[BodyUniverseDto])
    source_mementos: list[SourceMementoDto] = field(
        default_factory=list[SourceMementoDto]
    )
    source_ledger: dict[str, int] | None = None
    assertion_surface_audits: list[AssertionSurfaceAuditDto] = field(
        default_factory=list[AssertionSurfaceAuditDto]
    )
    factory_walk: list[FactoryWalkRowDto] = field(
        default_factory=list[FactoryWalkRowDto]
    )
    plan_mementos: list[ComponentPlanMementoDto] = field(
        default_factory=list[ComponentPlanMementoDto]
    )
    implications: list[ImplicationDto] = field(default_factory=list[ImplicationDto])
    effects: list[EffectDto] = field(default_factory=list[EffectDto])
    # Genuinely-open lanes: no closed recognizer hierarchy backs these yet,
    # so they get an explicit TypedDict membrane instead of an accidental
    # dict[str, Any] (see kit_rpc/open_lane_dto.py for the per-lane reason).
    source_audits: list[SourceAuditDto] = field(default_factory=list[SourceAuditDto])
    factory_audits: list[FactoryAuditDto] = field(default_factory=list[FactoryAuditDto])
    call_edges: list[CallEdgeDto] = field(default_factory=list[CallEdgeDto])
    vendor_conjoins: list[VendorConjoinDto] = field(
        default_factory=list[VendorConjoinDto]
    )
    diagnostics: list[DiagnosticDto] = field(default_factory=list[DiagnosticDto])
    # #4013 dual-axis lift coverage (assertions default / minority bodies).
    # Optional: filled by lift_rpc after the independent AST census.
    lift_coverage: dict[str, Any] | None = None

    def to_rpc(self) -> dict[str, Any]:
        factory_summary = FactoryAuditSummaryDto(rows=self.factory_walk)
        source_ledger = self.source_ledger or _default_source_ledger(
            len(self.source_mementos)
        )
        out: dict[str, Any] = {
            "kind": "ir-document",
            "ir": [to_rpc_value(contract) for contract in self.ir],
            "sourceLedger": to_rpc_value(source_ledger),
            "sourceAudits": [to_rpc_value(audit) for audit in self.source_audits],
            "sourceMementos": [
                to_rpc_value(memento) for memento in self.source_mementos
            ],
            "assertionSurfaceAudits": [
                to_rpc_value(audit) for audit in self.assertion_surface_audits
            ],
            "factoryAudits": [to_rpc_value(audit) for audit in self.factory_audits],
            "factoryAuditSummary": factory_summary.to_rpc(),
            "planMementos": [to_rpc_value(memento) for memento in self.plan_mementos],
            "implications": [to_rpc_value(edge) for edge in self.implications],
            "effects": [to_rpc_value(effect) for effect in self.effects],
            "callEdges": [to_rpc_value(edge) for edge in self.call_edges],
            "vendorConjoins": [to_rpc_value(row) for row in self.vendor_conjoins],
            "diagnostics": [to_rpc_value(row) for row in self.diagnostics],
            "warnings": [],
        }
        if self.lift_coverage is not None:
            # First-class --report line items (Part of #4013).
            out["liftCoverage"] = to_rpc_value(self.lift_coverage)
        return out


def _default_source_ledger(source_memento_count: int) -> dict[str, int]:
    return {
        "source_loci": source_memento_count,
        "source_warranted": source_memento_count,
        "source_inactive": 0,
        "source_support": 0,
        "source_boundary": 0,
        "source_unresolved": 0,
        "unclassified_source": 0,
    }
