from __future__ import annotations

from .factory_audit_row import FactoryAuditRow
from .factory_gap_info import FactoryGapInfo


class FactoryGap(RuntimeError):
    def __init__(self, info: FactoryGapInfo, audit_row: FactoryAuditRow) -> None:
        self.info = info.to_json()
        self.audit_row = audit_row
        super().__init__(info.message)
