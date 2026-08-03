from __future__ import annotations

from .floor_value import FloorValue


class GuardStableValue(FloorValue):
    """A pure constructed value whose meaning is unchanged by control guard.

    This category is explicit: only values with no invariant, postcondition,
    control effect, or scope transition may opt in. ``FloorValue`` remains the
    loud default for every unclassified value.
    """

    def guarded(self, formula):
        del formula
        return self
