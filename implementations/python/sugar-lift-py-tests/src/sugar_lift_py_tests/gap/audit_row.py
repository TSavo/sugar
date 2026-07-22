from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    # kit_rpc's own import chain runs back through factory (effect_dto ->
    # effect -> factory_gap_effect -> factory.factory_gap ->
    # factory_audit_row), so this stays type-checking-only to avoid a
    # runtime circular import; `from __future__ import annotations` above
    # makes the FactoryAuditDto annotation below lazy.
    from sugar_lift_py_tests.kit_rpc import FactoryAuditDto


class FactoryAuditStatus(StrEnum):
    """A lift-audit status. An enum, not a string: an illegal status is
    unrepresentable by construction, so FactoryAuditRow needs no runtime
    membership guard. StrEnum keeps the wire bytes identical -- each member
    renders as its literal status string in RPC/JSON."""

    SELECTED = "selected"
    SUGAR_GAP = "sugar-gap"
    SUGAR_AMBIGUOUS = "sugar-ambiguous"
    FLOOR_GAP = "floor-gap"
    CONSTRUCTOR_GAP = "constructor-gap"
    OPERATION_GAP = "operation-gap"
    PROOFIR_GAP = "proofir-gap"


@dataclass(frozen=True)
class FactoryAuditRow:
    role: str
    status: FactoryAuditStatus
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
