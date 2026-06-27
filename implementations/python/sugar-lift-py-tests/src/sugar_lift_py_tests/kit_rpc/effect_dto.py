from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .rpc_value import to_rpc_value
from .source_memento_dto import SourceMementoDto


@dataclass(frozen=True)
class EffectDto:
    name: str
    reason: str
    source_memento: SourceMementoDto | dict[str, Any]
    status: str = "refused"

    def to_rpc(self) -> dict[str, Any]:
        return {
            "kind": "effect",
            "name": self.name,
            "status": self.status,
            "reason": self.reason,
            "sourceMemento": to_rpc_value(self.source_memento),
        }
