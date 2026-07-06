from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, TypeAlias, get_args

from .rpc_value import to_rpc_value
from .source_memento_dto import SourceMementoDto
from .source_span_dto import SourceSpanDto

FactoryWalkCompleteStatus = Literal["warranted", "support"]
FactoryWalkRedStatus = Literal[
    "unclassified",
    "raise-effect",
    "runtime-effect",
    "coverage-gap",
    "factory-gap",
    "dig-boundary",
    # #3632 legacy: accepted for read compatibility with rows emitted by an
    # older kit build; no writer in this tree emits it anymore.
    "dig-refusal",
    "absent",
    "drifted",
]
FactoryWalkStatus = FactoryWalkCompleteStatus | FactoryWalkRedStatus

_ALLOWED_STATUSES = frozenset(get_args(FactoryWalkCompleteStatus)) | frozenset(
    get_args(FactoryWalkRedStatus)
)
_RED_STATUSES = frozenset(get_args(FactoryWalkRedStatus))

SourceMementoLike: TypeAlias = SourceMementoDto | dict[str, Any]
SourceSpanLike: TypeAlias = SourceSpanDto | dict[str, Any] | None


@dataclass(frozen=True)
class FactoryWalkCompleteRowDto:
    file: str
    line: int
    requested_role: str
    ast_kind: str
    selected: str | None
    status: FactoryWalkCompleteStatus
    output: Any
    source_memento: SourceMementoLike
    span: SourceSpanLike = None
    reason: str | None = None
    occurrences: int | None = None
    emitted_formula: Mapping[str, Any] | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_status(self.status)

    def to_rpc(self) -> dict[str, Any]:
        return _row_to_rpc(self, self.status, self.reason)


@dataclass(frozen=True)
class FactoryWalkRedRowDto:
    file: str
    line: int
    requested_role: str
    ast_kind: str
    selected: str | None
    status: FactoryWalkRedStatus
    output: Any
    source_memento: SourceMementoLike
    reason: str
    span: SourceSpanLike = None
    occurrences: int | None = None
    emitted_formula: Mapping[str, Any] | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_status(self.status)
        _validate_red_reason(
            status=self.status,
            reason=self.reason,
            file=self.file,
            line=self.line,
        )

    def to_rpc(self) -> dict[str, Any]:
        return _row_to_rpc(self, self.status, self.reason)


FactoryWalkRowDto: TypeAlias = FactoryWalkCompleteRowDto | FactoryWalkRedRowDto


def _validate_status(status: str) -> None:
    if status not in _ALLOWED_STATUSES:
        allowed = ", ".join(sorted(_ALLOWED_STATUSES))
        raise TypeError(
            "FactoryWalkRowDto.status must be a lift factory-walk status: "
            f"owner=FactoryWalkRowDto illegal={status!r} "
            f"replacement=typed Effect status or warranted/support; "
            f"allowed={allowed}"
        )


def _validate_red_reason(
    *, status: str, reason: str | None, file: str, line: int
) -> None:
    if status in _RED_STATUSES and not (reason or "").strip():
        raise TypeError(
            "red verdict carries no grounds; the ledger lost the dragon: "
            f"owner=FactoryWalkRowDto status={status!r} "
            f"blame={file}:{line} "
            "replacement=construct red rows with their cause (own gap/effect "
            "reason, or inherited contamination provenance such as "
            "'via unresolved call at file:line'); a red row IS a "
            "(verdict, grounds) pair. See #3540."
        )


def _row_to_rpc(
    row: FactoryWalkCompleteRowDto | FactoryWalkRedRowDto,
    status: FactoryWalkStatus,
    reason: str | None,
) -> dict[str, Any]:
    forbidden = {"source", "term", "site"} & set(row.extra)
    if forbidden:
        joined = ", ".join(sorted(forbidden))
        raise ValueError(
            "factory walk rows must carry SourceMemento pins only; "
            f"forbidden inline field(s): {joined}"
        )
    _validate_status(status)
    _validate_red_reason(
        status=status,
        reason=reason,
        file=row.file,
        line=row.line,
    )
    rpc_status = "unresolved" if status == "unclassified" else status
    verdict_by_status = {
        "warranted": "complete",
        "support": "complete",
        "raise-effect": "incomplete",
        "runtime-effect": "incomplete",
        "coverage-gap": "incomplete",
        "factory-gap": "incomplete",
        "dig-boundary": "incomplete",
        "dig-refusal": "incomplete",  # #3632 legacy read compatibility
        "absent": "incomplete",
        "drifted": "incomplete",
        "unresolved": "gap",
    }
    if rpc_status not in verdict_by_status:
        raise ValueError(
            f"unowned factory walk status {rpc_status!r}: add it to verdict_by_status "
            "deliberately -- a defaulted verdict is a quiet failure"
        )
    verdict = verdict_by_status[rpc_status]
    output = "gap" if rpc_status == "unresolved" else row.output
    out: dict[str, Any] = {
        "kind": "factory-walk-row",
        "file": row.file,
        "line": row.line,
        "requested_role": row.requested_role,
        "ast_kind": row.ast_kind,
        "selected": row.selected,
        "status": rpc_status,
        "verdict": verdict,
        "output": to_rpc_value(output),
        "sourceMemento": to_rpc_value(row.source_memento),
    }
    if row.span is not None:
        out["span"] = to_rpc_value(row.span)
    if reason is not None:
        out["reason"] = reason
    if row.occurrences is not None:
        out["occurrences"] = row.occurrences
    if row.emitted_formula is not None:
        out["emittedFormula"] = to_rpc_value(row.emitted_formula)
    out.update({key: to_rpc_value(value) for key, value in row.extra.items()})
    return out
