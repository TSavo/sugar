from __future__ import annotations

from .collect_dunder_frontier import collect_dunder_frontier
from .collect_panic_audit import collect_panic_audit
from .collect_temporal_dispatch_frontier import collect_temporal_dispatch_frontier
from .command_result import CommandResult
from .dunder_frontier_report import DunderFrontierReport
from .dunder_frontier_vector import DunderFrontierVector
from .dunder_slot import DunderSlot
from .lift_target import LiftTarget
from .panic_audit_report import PanicAuditReport
from .panic_record import PanicRecord
from .panic_vector import PanicVector
from .render_panic_audit import render_text
from .temporal_dispatch_offender import TemporalDispatchOffender
from .temporal_dispatch_report import TemporalDispatchReport
from .temporal_dispatch_vector import TemporalDispatchVector


def main(argv=None):
    from .cli import main as cli_main

    return cli_main(argv)


__all__ = [
    "CommandResult",
    "DunderFrontierReport",
    "DunderFrontierVector",
    "DunderSlot",
    "LiftTarget",
    "PanicAuditReport",
    "PanicRecord",
    "PanicVector",
    "TemporalDispatchOffender",
    "TemporalDispatchReport",
    "TemporalDispatchVector",
    "collect_dunder_frontier",
    "collect_panic_audit",
    "collect_temporal_dispatch_frontier",
    "main",
    "render_text",
]
