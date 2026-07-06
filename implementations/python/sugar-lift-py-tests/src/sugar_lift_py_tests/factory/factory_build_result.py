from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.sugar_body import ReducibleSugar
from .factory_audit_row import FactoryAuditRow


@dataclass(frozen=True)
class FactoryBuildResult:
    sugar: ReducibleSugar
    audit_row: FactoryAuditRow
