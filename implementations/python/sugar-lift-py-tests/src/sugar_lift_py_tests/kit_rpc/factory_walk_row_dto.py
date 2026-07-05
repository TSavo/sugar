from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, get_args

from .rpc_value import to_rpc_value
from .source_memento_dto import SourceMementoDto
from .source_span_dto import SourceSpanDto

FactoryWalkStatus = Literal[
    "warranted",
    "support",
    "unclassified",
    "raise-effect",
    "runtime-effect",
    "coverage-gap",
    "factory-gap",
    "dig-refusal",
    "absent",
    "drifted",
]
_ALLOWED_STATUSES = frozenset(get_args(FactoryWalkStatus))

# Every status that renders red. A red verdict with no grounds is an
# unclassified state reaching output: a claim the report cannot back. That
# must be impossible BY CONSTRUCTION -- a red row IS a (verdict, grounds)
# pair. The guard in __post_init__ is the tripwire; the pyright-visible type
# split is the law (in flight). See #3540.
_RED_STATUSES = frozenset(
    {
        "raise-effect",
        "runtime-effect",
        "coverage-gap",
        "factory-gap",
        "dig-refusal",
        "absent",
        "drifted",
    }
)


@dataclass(frozen=True)
class FactoryWalkRowDto:
    file: str
    line: int
    requested_role: str
    ast_kind: str
    selected: str | None
    status: FactoryWalkStatus
    output: Any
    source_memento: SourceMementoDto | dict[str, Any]
    span: SourceSpanDto | dict[str, Any] | None = None
    reason: str | None = None
    occurrences: int | None = None
    emitted_formula: Mapping[str, Any] | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in _ALLOWED_STATUSES:
            allowed = ", ".join(sorted(_ALLOWED_STATUSES))
            raise TypeError(
                "FactoryWalkRowDto.status must be a lift factory-walk status: "
                f"owner=FactoryWalkRowDto illegal={self.status!r} "
                f"replacement=typed Effect status or warranted/support; "
                f"allowed={allowed}"
            )
        if self.status in _RED_STATUSES and not (self.reason or "").strip():
            raise TypeError(
                "red verdict carries no grounds; the ledger lost the dragon: "
                f"owner=FactoryWalkRowDto status={self.status!r} "
                f"blame={self.file}:{self.line} "
                "replacement=construct red rows with their cause (own gap/effect "
                "reason, or inherited contamination provenance such as "
                "'via unresolved call at file:line'); a red row IS a "
                "(verdict, grounds) pair. See #3540."
            )

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
            "raise-effect": "incomplete",
            "runtime-effect": "incomplete",
            "coverage-gap": "incomplete",
            "factory-gap": "incomplete",
            "dig-refusal": "incomplete",
            "absent": "incomplete",
            "drifted": "incomplete",
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
