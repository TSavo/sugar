from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .rpc_value import to_rpc_value
from .source_memento_dto import SourceMementoDto


@dataclass(frozen=True)
class AssertionFactDto:
    contract: str
    kind: str
    claim_count: int
    source_path: str
    source_mementos: list[SourceMementoDto | dict[str, Any]] = field(
        default_factory=list
    )

    def to_rpc(self) -> dict[str, Any]:
        mementos = [to_rpc_value(memento) for memento in self.source_mementos]
        out: dict[str, Any] = {
            "contract": self.contract,
            "kind": self.kind,
            "claimCount": self.claim_count,
            "sourcePath": self.source_path,
            "sourceMementos": mementos,
        }
        if mementos:
            out["sourceMemento"] = mementos[0]
        return out
