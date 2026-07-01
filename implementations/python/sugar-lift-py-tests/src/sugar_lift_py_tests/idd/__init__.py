from __future__ import annotations

from .collect_dunder_frontier import collect_dunder_frontier
from .collect_panic_audit import collect_panic_audit
from .command_result import CommandResult
from .dunder_frontier_report import DunderFrontierReport
from .dunder_frontier_vector import DunderFrontierVector
from .dunder_slot import DunderSlot
from .lift_target import LiftTarget
from .panic_audit_report import PanicAuditReport
from .panic_record import PanicRecord
from .panic_vector import PanicVector
from .render_panic_audit import render_text


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
    "collect_dunder_frontier",
    "collect_panic_audit",
    "main",
    "render_text",
]
