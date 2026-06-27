from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .plan_atom_dto import PlanAtomDto
from .rpc_value import to_rpc_value


@dataclass(frozen=True)
class ComponentPlanMementoDto:
    workspace_root: str
    plan_atoms: list[PlanAtomDto | dict[str, Any]] = field(default_factory=list)
    expected_output_cids: list[str] = field(default_factory=list)
    planning_source: str = "component-discovery"
    tool_outputs: list[dict[str, Any]] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_rpc(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "kind": "component-plan",
            "schemaVersion": "1",
            "workspaceRoot": self.workspace_root,
            "planning": {"source": self.planning_source},
            "planAtoms": [to_rpc_value(atom) for atom in self.plan_atoms],
            "expectedOutputCids": list(self.expected_output_cids),
        }
        if self.tool_outputs:
            out["toolOutputs"] = to_rpc_value(self.tool_outputs)
        out.update({key: to_rpc_value(value) for key, value in self.extra.items()})
        return out
