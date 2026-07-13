from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .factory_walk_row_dto import FactoryWalkRowDto
from .rpc_value import to_rpc_value
from sugar_lift_py_tests.idd.lift_coverage_census import SourceFactoryConservation


@dataclass(frozen=True)
class FactoryAuditSummaryDto:
    rows: list[FactoryWalkRowDto] = field(default_factory=list)
    source_factory_conservation: SourceFactoryConservation | None = None

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
        out = {
            "sites": len(walk),
            "emittedRows": len(walk),
            "omittedRows": 0,
            "totalRows": len(walk),
            "complete": True,
            "statusCounts": counts,
            "unresolvedSites": unresolved,
            "factoryWalk": walk,
        }
        if self.source_factory_conservation is not None:
            out["sourceFactoryConservation"] = (
                self.source_factory_conservation.to_json()
            )
            if not self.source_factory_conservation.complete:
                out["complete"] = False
        return out
