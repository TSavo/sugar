from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue


@dataclass(frozen=True)
class BoolOpTruthSelection(FloorValue):
    """One evaluation's operand and its completed native truth result.

    BoolOp needs both: truth selects the next face, while Python returns the
    original operand on the short-circuit face.  Keeping them together lets a
    caller-discharge continuation return the substituted actual rather than
    the definition-time formal symbol.
    """

    operand: object
    truth_value: object
