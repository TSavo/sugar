from __future__ import annotations

from .collect_dunder_frontier import collect_dunder_frontier
from .dunder_frontier_report import DunderFrontierReport
from .dunder_frontier_vector import DunderFrontierVector
from .dunder_slot import DunderSlot


def main(argv=None):
    from .cli import main as cli_main

    return cli_main(argv)


__all__ = [
    "DunderFrontierReport",
    "DunderFrontierVector",
    "DunderSlot",
    "collect_dunder_frontier",
    "main",
]
