from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, List, Literal, Optional, get_args

if TYPE_CHECKING:
    # kit_rpc's own import chain runs back through factory (effect_dto ->
    # effect -> factory_gap_effect -> factory.factory_gap ->
    # factory_audit_row), so this stays type-checking-only to avoid a
    # runtime circular import; `from __future__ import annotations` above
    # makes the FactoryAuditDto annotation below lazy.
    from sugar_lift_py_tests.kit_rpc import FactoryAuditDto

FactoryAuditStatus = Literal[
    "selected",
    "sugar-gap",
    "sugar-ambiguous",
    "floor-gap",
    "constructor-gap",
    "operation-gap",
    "proofir-gap",
]

_ALLOWED_STATUSES = frozenset(get_args(FactoryAuditStatus))


@dataclass(frozen=True)
class FactoryAuditRow:
    role: str
    status: FactoryAuditStatus
    observed: str
    blame: str
    selected: Optional[str]
    candidates: List[str]
    message: str

    def __post_init__(self) -> None:
        if self.status not in _ALLOWED_STATUSES:
            allowed = ", ".join(sorted(_ALLOWED_STATUSES))
            raise TypeError(
                "FactoryAuditRow.status must be a lift-audit status: "
                f"owner=FactoryAuditRow illegal={self.status!r} "
                f"replacement=Complete(...) or Incomplete(typed Effect); "
                f"allowed={allowed}"
            )

    def to_json(self) -> FactoryAuditDto:
        return {
            "kind": "factory-audit-row",
            "role": self.role,
            "status": self.status,
            "observed": self.observed,
            "blame": self.blame,
            "selected": self.selected,
            "candidates": list(self.candidates),
            "message": self.message,
        }
