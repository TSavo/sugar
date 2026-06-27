from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .callsite_fact_dto import CallsiteFactDto
from .rpc_value import to_rpc_value
from .source_memento_dto import SourceMementoDto


@dataclass(frozen=True)
class BodyUniverseDto:
    name: str
    out_binding: str = "out"
    pre: dict[str, Any] | None = None
    post: dict[str, Any] | None = None
    inv: dict[str, Any] | None = None
    source_warrants: list[SourceMementoDto | dict[str, Any]] = field(default_factory=list)
    warranted_by: CallsiteFactDto | dict[str, Any] | None = None

    def to_rpc(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "kind": "contract",
            "name": self.name,
            "outBinding": self.out_binding,
        }
        if self.pre is not None:
            out["pre"] = to_rpc_value(self.pre)
        if self.post is not None:
            out["post"] = to_rpc_value(self.post)
        if self.inv is not None:
            out["inv"] = to_rpc_value(self.inv)
        if self.source_warrants:
            out["sourceWarrants"] = [to_rpc_value(warrant) for warrant in self.source_warrants]
        if self.warranted_by is not None:
            out["warrantedBy"] = to_rpc_value(self.warranted_by)
        return out
