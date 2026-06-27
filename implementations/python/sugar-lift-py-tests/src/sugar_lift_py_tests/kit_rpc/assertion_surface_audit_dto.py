from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .assertion_fact_dto import AssertionFactDto
from .rpc_value import to_rpc_value
from .source_memento_dto import SourceMementoDto


@dataclass(frozen=True)
class AssertionSurfaceAuditDto:
    assertion_source: str
    file: str
    line: int
    source_status: str
    status: str
    facts: list[AssertionFactDto | dict[str, Any]]
    source_memento: SourceMementoDto | dict[str, Any]
    surface: str = "python"
    support_facts: list[AssertionFactDto | dict[str, Any]] = field(default_factory=list)
    reason: str | None = None

    def to_rpc(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "kind": "assertion-surface-audit",
            "surface": self.surface,
            "assertionSource": self.assertion_source,
            "file": self.file,
            "line": self.line,
            "sourceStatus": self.source_status,
            "status": self.status,
            "facts": [to_rpc_value(fact) for fact in self.facts],
            "supportFacts": [to_rpc_value(fact) for fact in self.support_facts],
            "sourceMemento": to_rpc_value(self.source_memento),
        }
        if self.reason is not None:
            out["reason"] = self.reason
        return out
