from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue
from sugar_lift_py_tests.effect.warning_effect import WarningEffect


@dataclass(frozen=True)
class WarningObservationValue(FloorValue):
    """Continuing record entry carrying one observed warning.

    Unlike ``Incomplete(RaiseEffect)``, a warning does not halt the block.
    The ordinary ``FloorValue.follow_rest`` therefore remains correct while
    the shared effect router can consume this value as expectation evidence.
    """

    effect: WarningEffect
    # Branch guards this occurrence was reached under, outermost last. An
    # occurrence under a guard is a CONDITIONAL one: the source says the
    # warning happens when the guard holds, not that it happens. Carrying the
    # guards is what lets the consuming boundary refuse rather than silently
    # promote a conditional occurrence to an unconditional claim.
    guards: tuple = ()

    def guarded(self, formula):
        """Ride under a branch guard, RECORDING it.

        Not ``return self``: that is the arm ``CallSiteValue`` can take,
        because a call coordinate is a value the branch guard already owns.
        This entry is testimony that an effect OCCURRED, so dropping the guard
        would convert "warns when the guard holds" into "warns".
        """
        return WarningObservationValue(self.effect, (formula, *self.guards))
