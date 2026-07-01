from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .factory_walk_row_dto import FactoryWalkRowDto
from .rpc_value import to_rpc_value


@dataclass(frozen=True)
class FactoryAuditSummaryDto:
    rows: list[FactoryWalkRowDto | dict[str, Any]] = field(default_factory=list)

    def to_rpc(self) -> dict[str, Any]:
        walk = [to_rpc_value(row) for row in self.rows]
        counts = {"warranted": 0, "refused": 0, "support": 0, "unresolved": 0}
        for row in walk:
            status = row.get("status")
            if status in counts:
                counts[status] += 1
        unresolved = [
            row for row in walk if row.get("status") in ("unresolved", "unclassified")
        ]
        return {
            "sites": len(walk),
            "emittedRows": len(walk),
            "omittedRows": 0,
            "totalRows": len(walk),
            "complete": True,
            "statusCounts": counts,
            "unresolvedSites": unresolved,
            "factoryWalk": walk,
        }
