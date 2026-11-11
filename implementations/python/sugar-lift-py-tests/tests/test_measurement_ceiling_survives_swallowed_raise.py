"""A ceiling whose raise is swallowed still ends the seat.

The SIGALRM handler runs wherever the main thread is. If that is a weakref
callback or ``__del__``, CPython reports "Exception ignored" and drops the
raise. A one-shot timer would then be spent and the seat would run unbounded
(a pandas lift ran past its 300s ceiling until an outer timeout killed it).
The ceiling must fire again until the raise lands, and leave no timer armed.
"""

from __future__ import annotations

import signal
import time

import pytest

from sugar_lift_py_tests.measurement_ceiling import (
    MeasurementCeilingExceeded,
    measurement_ceiling,
)


class _SwallowsTheFirstFire:
    """Spends time in ``__del__`` until the first alarm lands there."""

    swallowed = 0

    def __del__(self) -> None:
        if type(self).swallowed:
            return
        deadline = time.monotonic() + 2.0
        try:
            while time.monotonic() < deadline:
                time.sleep(0.01)
        except MeasurementCeilingExceeded:
            type(self).swallowed += 1
            raise  # dropped by CPython: raised inside __del__


def test_swallowed_ceiling_fires_again_and_lands() -> None:
    _SwallowsTheFirstFire.swallowed = 0
    started = time.monotonic()
    with pytest.raises(MeasurementCeilingExceeded):
        with measurement_ceiling(seat="swallow.py", seconds=0.2):
            _SwallowsTheFirstFire()  # dies at once; its __del__ eats the fire
            while time.monotonic() - started < 5.0:
                time.sleep(0.01)
    assert _SwallowsTheFirstFire.swallowed == 1
    assert time.monotonic() - started < 3.0
    assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)
