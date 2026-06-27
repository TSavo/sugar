from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .factory_audit_row import FactoryAuditRow


@dataclass(frozen=True)
class FactoryBuildResult:
    sugar: Any
    audit_row: FactoryAuditRow
