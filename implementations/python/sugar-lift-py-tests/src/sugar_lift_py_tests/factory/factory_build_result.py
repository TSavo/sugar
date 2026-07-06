from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sugar_lift_py_tests.sugar_body import ReducibleSugar
from .factory_audit_row import FactoryAuditRow


@dataclass(frozen=True)
class FactoryBuildResult:
    # ReducibleSugar's reduction result varies per SugarRole (Formula vs
    # Outcome vs role-specific shapes); FactoryBuildResult is the polymorphic
    # boundary DTO handed back from build_node, so Any is the open membrane.
    sugar: ReducibleSugar[Any]
    audit_row: FactoryAuditRow
