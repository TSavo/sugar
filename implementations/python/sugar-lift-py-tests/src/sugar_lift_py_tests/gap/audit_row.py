"""Audit / roll-call projection of construction gap testimony.

``ConstructionGap`` (in ``info``) is pure testimony. This module projects it
into audit wire shapes: status enum and rows. Never import this module from
``info`` — that would re-couple testimony to its projection.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, List, Never, NoReturn, Optional

from .info import GapKind

if TYPE_CHECKING:
    # kit_rpc import chain stays type-checking-only to avoid a runtime circular
    # import; `from __future__ import annotations` makes FactoryAuditDto lazy.
    # Wire kind remains "factory-audit-row" (retain-old-wire discriminator).
    from sugar_lift_py_tests.kit_rpc import FactoryAuditDto


class ConstructionAuditStatus(StrEnum):
    """A lift-audit status. An enum, not a string: an illegal status is
    unrepresentable by construction, so ConstructionAuditRow needs no runtime
    membership guard. StrEnum keeps the wire bytes identical -- each member
    renders as its literal status string in RPC/JSON."""

    SELECTED = "selected"
    SUGAR_GAP = "sugar-gap"
    SUGAR_AMBIGUOUS = "sugar-ambiguous"
    FLOOR_GAP = "floor-gap"
    CONSTRUCTOR_GAP = "constructor-gap"
    OPERATION_GAP = "operation-gap"
    PROOFIR_GAP = "proofir-gap"


def gap_kind_status(kind: GapKind) -> ConstructionAuditStatus:
    """Project ``GapKind`` testimony onto an audit-row status.

    Owned here (audit/roll-call boundary), not on ``ConstructionGap`` /
    ``info`` — so pure gap testimony does not depend on audit projection.
    """
    if kind is GapKind.FLOOR:
        return ConstructionAuditStatus.FLOOR_GAP
    if kind is GapKind.SUGAR:
        return ConstructionAuditStatus.SUGAR_GAP
    if kind is GapKind.CONSTRUCTOR:
        return ConstructionAuditStatus.CONSTRUCTOR_GAP
    if kind is GapKind.SUGAR_ORDERING:
        return ConstructionAuditStatus.SUGAR_AMBIGUOUS
    if kind is GapKind.OPERATION:
        return ConstructionAuditStatus.OPERATION_GAP
    if kind is GapKind.PROOFIR:
        return ConstructionAuditStatus.PROOFIR_GAP
    return _unhandled_gap_kind(kind)


def _unhandled_gap_kind(kind: Never) -> NoReturn:
    raise TypeError(f"unhandled GapKind arm: {type(kind).__name__}")



@dataclass(frozen=True)
class ConstructionAuditRow:
    role: str
    status: ConstructionAuditStatus
    observed: str
    blame: str
    selected: Optional[str]
    candidates: List[str]
    message: str

    def to_json(self) -> FactoryAuditDto:
        return {
            "kind": "factory-audit-row",
            "role": self.role,
            "status": self.status.value,
            "observed": self.observed,
            "blame": self.blame,
            "selected": self.selected,
            "candidates": list(self.candidates),
            "message": self.message,
        }
