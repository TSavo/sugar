from __future__ import annotations

from dataclasses import dataclass, field

from .plan_atom_dto import PlanAtomDto


@dataclass(frozen=True)
class CompilerSelectionDto:
    name: str
    surface: str
    version: str | None = None
    command: list[str] = field(default_factory=list)
    method: str | None = None

    def to_plan_atom(self) -> PlanAtomDto:
        return PlanAtomDto(
            atom_kind="proofir-compiler",
            role="proofir-compiler",
            surface=self.surface,
            plugin_name=self.name,
            version=self.version,
            command=list(self.command),
            method=self.method,
        )

    def to_rpc(self) -> dict[str, object]:
        return self.to_plan_atom().to_rpc()
