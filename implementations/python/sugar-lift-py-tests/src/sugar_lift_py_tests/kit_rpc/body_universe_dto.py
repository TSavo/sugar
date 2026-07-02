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
    source_warrants: list[SourceMementoDto | dict[str, Any]] = field(
        default_factory=list
    )
    proofir_provenance: dict[str, Any] | None = None
    warranted_by: CallsiteFactDto | dict[str, Any] | None = None
    # The universal variables of `post` (the function's formal params). The
    # verifier's `collect_ambient_posts` only treats a post as an ambient
    # universal -- specializable into a consumer's callsite obligation -- when the
    # contract carries `formals`.
    formals: list[str] = field(default_factory=list)
    # `function-contract` (with `post` + `formals`) makes the mint auto-mint a
    # `sourceSymbol -> this contract` bridge (`bind_function_bridge`), resolving the
    # target CID at seal -- which is what lets `collect_ambient_posts` pick the post
    # up as an ambient universal. `bridge_source_symbol` is the callee's bare name as
    # it appears in harvested call ctors.
    kind: str = "contract"
    bridge_source_symbol: str | None = None

    def to_rpc(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "kind": self.kind,
            "name": self.name,
            "outBinding": self.out_binding,
        }
        if self.formals or self.kind == "function-contract":
            out["formals"] = list(self.formals)
        if self.bridge_source_symbol is not None:
            out["bridgeSourceSymbol"] = self.bridge_source_symbol
        if self.pre is not None:
            out["pre"] = to_rpc_value(self.pre)
        if self.post is not None:
            out["post"] = to_rpc_value(self.post)
        if self.inv is not None:
            out["inv"] = to_rpc_value(self.inv)
        if self.source_warrants:
            out["sourceWarrants"] = [
                to_rpc_value(warrant) for warrant in self.source_warrants
            ]
        if self.proofir_provenance is not None:
            out["proofirProvenance"] = to_rpc_value(self.proofir_provenance)
        if self.warranted_by is not None:
            out["warrantedBy"] = to_rpc_value(self.warranted_by)
        return out
