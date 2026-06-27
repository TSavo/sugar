from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .rpc_value import to_rpc_value
from .source_memento_dto import SourceMementoDto


@dataclass(frozen=True)
class CallsiteFactDto:
    contract_name: str
    callsite: str
    fact: dict[str, Any]
    source_memento: SourceMementoDto | dict[str, Any]

    def to_rpc(self) -> dict[str, Any]:
        return {
            "kind": "callsite-fact",
            "contractName": self.contract_name,
            "callsite": self.callsite,
            "fact": to_rpc_value(self.fact),
            "sourceMemento": to_rpc_value(self.source_memento),
        }
