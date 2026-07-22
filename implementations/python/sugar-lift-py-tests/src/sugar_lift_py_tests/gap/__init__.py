"""Kit-domain construction gap authority.

Not a construction factory. Live tree construction gaps are
``SugarNotWritten`` / the roll call. These types remain where floor, effect,
temporal, and proof paths raise a typed construction None arm.

Layering:
  - ``info`` — pure testimony (``ConstructionGap``, ``GapKind``, ``GapLocus``)
  - ``panic`` — loud None arm carrying only ``ConstructionGap``
  - ``audit_row`` — audit/roll-call projection (status, rows, ``gap_kind_status``)

Audit projection must not be imported by testimony.
"""

from .audit_row import (
    ConstructionAuditRow,
    ConstructionAuditStatus,
    gap_kind_status,
)
from .info import ConstructionGap, GapKind, GapLocus
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
