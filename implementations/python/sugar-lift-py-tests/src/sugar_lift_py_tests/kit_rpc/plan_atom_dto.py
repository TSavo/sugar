from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .rpc_value import to_rpc_value


@dataclass(frozen=True)
class PlanAtomDto:
    role: str
    surface: str
    plugin_name: str
    version: str | None = None
    atom_kind: str = "lifter-binary"
    binary_path: str | None = None
    binary_cid: str | None = None
    command: list[str] = field(default_factory=list)
    method: str | None = None
    phase: str | None = None
    workspace_override: str | None = None
    emit: str | None = None
    layer: str | None = None
    participation: str = "executed"
    extra: dict[str, Any] = field(default_factory=dict)

    def to_rpc(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "kind": "plan-atom",
            "schemaVersion": "1",
            "atomKind": self.atom_kind,
            "role": self.role,
            "surface": self.surface,
            "pluginName": self.plugin_name,
            "participation": self.participation,
        }
        if self.version is not None:
            out["version"] = self.version
        if self.binary_path is not None or self.binary_cid is not None:
            out["binary"] = {
                "path": self.binary_path,
                "cid": self.binary_cid,
            }
        if self.command:
            out["command"] = list(self.command)
        if self.method is not None:
            out["method"] = self.method
        if self.phase is not None:
            out["phase"] = self.phase
        if self.workspace_override is not None:
            out["workspaceOverride"] = self.workspace_override
        if self.emit is not None:
            out["emit"] = self.emit
        if self.layer is not None:
            out["layer"] = self.layer
        out.update({key: to_rpc_value(value) for key, value in self.extra.items()})
        return out
