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
