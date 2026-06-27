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
from .rpc_value import to_rpc_value
from .source_memento_dto import SourceMementoDto


@dataclass(frozen=True)
class LiftReportPayloadDto:
    ir: list[BodyUniverseDto | dict[str, Any]] = field(default_factory=list)
    source_mementos: list[SourceMementoDto | dict[str, Any]] = field(default_factory=list)
    assertion_surface_audits: list[
        AssertionSurfaceAuditDto | dict[str, Any]
    ] = field(default_factory=list)
    factory_walk: list[FactoryWalkRowDto | dict[str, Any]] = field(default_factory=list)
    factory_audits: list[dict[str, Any]] = field(default_factory=list)
    plan_mementos: list[ComponentPlanMementoDto | dict[str, Any]] = field(default_factory=list)
    implications: list[ImplicationDto | dict[str, Any]] = field(default_factory=list)
    effects: list[EffectDto | dict[str, Any]] = field(default_factory=list)
    call_edges: list[dict[str, Any]] = field(default_factory=list)
    vendor_conjoins: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: list[dict[str, Any]] = field(default_factory=list)

    def to_rpc(self) -> dict[str, Any]:
        factory_summary = FactoryAuditSummaryDto(rows=self.factory_walk)
        return {
            "kind": "ir-document",
            "ir": [to_rpc_value(contract) for contract in self.ir],
            "sourceMementos": [to_rpc_value(memento) for memento in self.source_mementos],
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
