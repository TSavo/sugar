from __future__ import annotations

from sugar_lift_py_tests.floor import FloorValue

from .complete import Complete
from .incomplete import Incomplete
from .outcome import Outcome


def complete_value(outcome: Outcome, *, owner: str) -> FloorValue:
    if isinstance(outcome, Incomplete):
        raise RuntimeError(
            f"{owner} cannot read completed value from incomplete effect: {outcome.reason}"
        )
    return outcome.value
