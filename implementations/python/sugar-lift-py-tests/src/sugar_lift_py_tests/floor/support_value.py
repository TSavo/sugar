from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue


@dataclass(frozen=True)
class SupportValue(FloorValue):
    """The inert outcome of desugaring an inert node (a comment).

    It carries no term, no binding, no scope -- it is the materialization of the
    Support category: present, accounted for, and contributing nothing to the
    first-order logic. Desugaring to it always completes."""

    non_fol_support = True
