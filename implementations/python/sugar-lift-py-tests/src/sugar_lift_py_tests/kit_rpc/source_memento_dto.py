from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .rpc_value import to_rpc_value
from .source_span_dto import SourceSpanDto


@dataclass(frozen=True)
class SourceMementoDto:
    file: str
    span: SourceSpanDto
    source_cid: str
    template_cid: str | None = None
    source_function_name: str | None = None
    role: str | None = None
    claim_name: str | None = None
    contract_name: str | None = None
    param_names: list[str] = field(default_factory=list[str])
    # `extra` is a deliberate open membrane, not an accidental dict: it is the
    # sugar-specific pass-through slot for factory rows that attach ad hoc
    # RPC keys (see FactoryWalkCompleteRowDto's `extra=`). It cannot close to
    # a TypedDict because callers choose arbitrary keys; the runtime
    # body_text/ast_template stripping below is the type this membrane wants
    # to grow into once those keys become named fields instead of extras.
    extra: dict[str, Any] = field(default_factory=dict[str, Any])

    def to_rpc(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "kind": "source-memento",
            "file": self.file,
            "span": to_rpc_value(self.span),
            "source_cid": self.source_cid,
            "sourceCid": self.source_cid,
        }
        if self.template_cid is not None:
            out["template_cid"] = self.template_cid
            out["templateCid"] = self.template_cid
        if self.source_function_name is not None:
            out["source_function_name"] = self.source_function_name
            out["sourceFunctionName"] = self.source_function_name
        if self.role is not None:
            out["role"] = self.role
        if self.claim_name is not None:
            out["claimName"] = self.claim_name
        if self.contract_name is not None:
            out["contractName"] = self.contract_name
        if self.param_names:
            out["param_names"] = list(self.param_names)
            out["paramNames"] = list(self.param_names)
        out.update({key: to_rpc_value(value) for key, value in self.extra.items()})
        for forbidden in (
            "body_text",
            "ast_template",
            "bodyText",
            "astTemplate",
            "source",
        ):
            out.pop(forbidden, None)
        return out
