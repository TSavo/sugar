from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .rpc_value import to_rpc_value
from .source_memento_dto import SourceMementoDto
from .source_span_dto import SourceSpanDto


@dataclass(frozen=True)
class FactoryWalkRowDto:
    file: str
    line: int
    requested_role: str
    ast_kind: str
    selected: str | None
    status: str
    output: Any
    source_memento: SourceMementoDto | dict[str, Any]
    span: SourceSpanDto | dict[str, Any] | None = None
    reason: str | None = None
    occurrences: int | None = None
    emitted_formula: Mapping[str, Any] | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_rpc(self) -> dict[str, Any]:
        forbidden = {"source", "term", "site"} & set(self.extra)
        if forbidden:
            joined = ", ".join(sorted(forbidden))
            raise ValueError(
                "factory walk rows must carry SourceMemento pins only; "
                f"forbidden inline field(s): {joined}"
            )
        status = "unresolved" if self.status == "unclassified" else self.status
        verdict_by_status = {
            "warranted": "complete",
            "support": "complete",
            "refused": "incomplete",
            "unresolved": "gap",
        }
        if status not in verdict_by_status:
            raise ValueError(
                f"unowned factory walk status {status!r}: add it to verdict_by_status "
                "deliberately -- a defaulted verdict is a quiet failure"
            )
        verdict = verdict_by_status[status]
        output = "gap" if status == "unresolved" else self.output
        out: dict[str, Any] = {
            "kind": "factory-walk-row",
            "file": self.file,
            "line": self.line,
            "requested_role": self.requested_role,
            "ast_kind": self.ast_kind,
            "selected": self.selected,
            "status": status,
            "verdict": verdict,
            "output": to_rpc_value(output),
            "sourceMemento": to_rpc_value(self.source_memento),
        }
        if self.span is not None:
            out["span"] = to_rpc_value(self.span)
        if self.reason is not None:
            out["reason"] = self.reason
        if self.occurrences is not None:
            out["occurrences"] = self.occurrences
        if self.emitted_formula is not None:
            out["emittedFormula"] = to_rpc_value(self.emitted_formula)
        out.update({key: to_rpc_value(value) for key, value in self.extra.items()})
        return out
