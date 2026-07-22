"""Kit-domain construction gap authority.

Not a construction factory. Live tree construction gaps are
``SugarNotWritten`` / the roll call. These types remain where floor, effect,
temporal, and proof paths raise a typed construction None arm.

Role names (not factory-era labels):
  ConstructionGap, ConstructionPanic, ConstructionAuditRow/Status.
Audit rows are construction testimony; they are not carried on the panic.
"""

from .audit_row import ConstructionAuditRow, ConstructionAuditStatus
from .info import ConstructionGap, GapKind, GapLocus, gap_kind_status
from .panic import (
    ConstructionPanic,
    construction_panic,
    construction_panic_gap,
    dig_boundary_panic,
)

__all__ = [
    "ConstructionAuditRow",
    "ConstructionAuditStatus",
    "ConstructionGap",
    "ConstructionPanic",
    "GapKind",
    "GapLocus",
    "construction_panic",
    "construction_panic_gap",
    "dig_boundary_panic",
    "gap_kind_status",
]
