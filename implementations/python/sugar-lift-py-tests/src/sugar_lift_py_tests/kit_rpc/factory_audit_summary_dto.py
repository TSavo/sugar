from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .factory_walk_row_dto import FactoryWalkRowDto
from .rpc_value import to_rpc_value


@dataclass(frozen=True)
class FactoryAuditSummaryDto:
    rows: list[FactoryWalkRowDto] = field(default_factory=list)

    def to_rpc(self) -> dict[str, Any]:
        walk = [to_rpc_value(row) for row in self.rows]
        counts = {"warranted": 0, "incomplete": 0, "support": 0, "unresolved": 0}
        for row in walk:
            status = row.get("status")
            if status in ("warranted", "support", "unresolved"):
                counts[status] += 1
            elif row.get("verdict") == "incomplete":
                counts["incomplete"] += 1
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
