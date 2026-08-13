"""The per-file measurement ceiling: it fires, it names, and it conserves.

One file (``pandas/core/groupby/generic.py``) never terminates under the
census, so the shard it lands in is cancelled and the run's whole evidence is
destroyed. The repair is not a bigger shard ceiling; it is that a seat which
exceeds a stated per-file bound produces a countable frontier row naming
construct, coordinate and shape, and the walk moves on.

These tests are the falsifiability gate for that claim. They exercise BOTH
arms: a subject that must make the bound fire, and a subject that must not be
touched by it. A bound that cannot be made to fire is decorative; a bound that
fires on ordinary work is a manufactured frontier.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from sugar_lift_py_tests import engine_log  # noqa: E402
from sugar_lift_py_tests.measurement_ceiling import (  # noqa: E402
    DEFAULT_CEILING_SECONDS,
    CEILING_ENV_VAR,
    MeasurementCeilingExceeded,
    ceiling_seconds,
    exhaustion_coordinates,
    is_unswallowable,
    measurement_ceiling,
)


# --------------------------------------------------------------------------
# ARM ONE: the bound fires, and the row names the coordinate.
# --------------------------------------------------------------------------


def test_ceiling_fires_and_captures_the_live_construct_stack() -> None:
    """A seat that will not terminate raises BY NAME, carrying its coordinate.

    The stack is captured in the signal handler, before any unwinding, which
    is the only moment at which the construct the walk was actually inside is
    still on the stack. A row assembled after unwinding would name the
    entrance, not the construct -- true, useless, and indistinguishable from
    naming nothing.
    """
    with pytest.raises(MeasurementCeilingExceeded) as caught:
        with measurement_ceiling(seat="fixture/generic.py", seconds=0.25):
            with engine_log.reduction_span(
                sugar="ClassDefSugar", role="statement", site="generic.py:189:0"
            ):
                with engine_log.reduction_span(
                    sugar="FunctionDefSugar", role="term", site="generic.py:1323:12"
                ):
                    # Pure-Python spin, exactly like the real blowup: the
                    # engine is working, not blocked, so nothing but a timer
                    # can end it.
                    deadline = time.monotonic() + 30.0
                    while time.monotonic() < deadline:
                        pass

    error = caught.value
    assert error.seat == "fixture/generic.py"
    assert error.bound_seconds == 0.25
    coordinates = exhaustion_coordinates(error.active_stack)
    assert [row["coordinate"] for row in coordinates] == [
        "generic.py:189:0",
        "generic.py:1323:12",
    ]
    assert [row["construct"] for row in coordinates] == [
        "ClassDefSugar",
        "FunctionDefSugar",
    ]
    # Shape, not just position: the role is what makes the row readable.
    assert coordinates[-1]["role"] == "term"


def test_ceiling_escapes_every_inner_terminal_handler() -> None:
    """Exhaustion must reach the seat boundary, not become a per-file terminal.

    The construction path is full of arms that convert a raised event into a
    terminal row for whatever construct was being built. If the ceiling could
    be caught by one of those, the file would report a CONSTRUCTION outcome
    caused by the clock -- a refusal the product never made.
    """
    swallowed: list[str] = []

    def _inner_handler_like_the_consumer() -> None:
        try:
            deadline = time.monotonic() + 30.0
            while time.monotonic() < deadline:
                pass
        except Exception as error:  # noqa: BLE001 -- the shape being tested
            swallowed.append(f"except Exception: {type(error).__name__}")
        except BaseException as error:  # noqa: BLE001
            if is_unswallowable(error):
                raise
            swallowed.append(f"except BaseException: {type(error).__name__}")

    with pytest.raises(MeasurementCeilingExceeded):
        with measurement_ceiling(seat="fixture/seat.py", seconds=0.25):
            _inner_handler_like_the_consumer()

    assert swallowed == [], f"ceiling was swallowed by an inner handler: {swallowed}"


def test_exhaustion_is_not_an_exception_subclass() -> None:
    """The reason the arm above holds, asserted directly rather than inferred."""
    assert issubclass(MeasurementCeilingExceeded, BaseException)
    assert not issubclass(MeasurementCeilingExceeded, Exception)


# --------------------------------------------------------------------------
# ARM TWO: the bound does NOT fire on ordinary work, and costs it nothing.
# --------------------------------------------------------------------------


def test_ordinary_work_completes_untouched_and_the_timer_is_disarmed() -> None:
    """A normal seat is unaffected: same result, and no timer left armed.

    The neighbours of the pathological file measure in tens of milliseconds. A
    ceiling that changed their outcome, or that leaked an armed timer into the
    next seat, would turn a repair into a new source of spurious rows.
    """
    import signal

    observed: list[str] = []
    for seat in ("a.py", "b.py", "c.py"):
        with measurement_ceiling(seat=seat, seconds=5.0):
            with engine_log.reduction_span(
                sugar="NameSugar", role="term", site=f"{seat}:1:0"
            ):
                observed.append(seat)
        # Disarmed between seats, every time -- not merely at the end.
        assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0), (
            f"timer still armed after {seat}"
        )
    assert observed == ["a.py", "b.py", "c.py"]


def test_ordinary_work_pays_no_measurable_toll() -> None:
    """Arming the bound is not a cost centre.

    Not a benchmark and not a threshold on the product: this asserts only that
    the ceiling's own overhead is far below the scale of the cheapest real
    seat (tens of milliseconds), so an unchanged timing claim is credible.
    """
    started = time.perf_counter()
    for index in range(200):
        with measurement_ceiling(seat=f"seat{index}.py", seconds=5.0):
            pass
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    assert elapsed_ms < 200.0, f"200 arm/disarm cycles cost {elapsed_ms:.1f}ms"


# --------------------------------------------------------------------------
# The bound itself: stated, overridable, and never silently disarmed.
# --------------------------------------------------------------------------


def test_the_bound_is_stated_and_positive() -> None:
    assert ceiling_seconds() == DEFAULT_CEILING_SECONDS
    assert DEFAULT_CEILING_SECONDS > 0


def test_a_non_positive_override_is_refused_not_treated_as_disarmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`0` must not mean "no ceiling". A run that looks bounded and is not is
    the exact failure this instrument exists to end."""
    monkeypatch.setenv(CEILING_ENV_VAR, "0")
    with pytest.raises(ValueError) as caught:
        ceiling_seconds()
    assert CEILING_ENV_VAR in str(caught.value)


def test_nesting_two_ceilings_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two bounds cannot share one interval timer; arming inside another would
    disarm one of them silently."""
    with measurement_ceiling(seat="outer.py", seconds=30.0):
        with pytest.raises(RuntimeError) as caught:
            with measurement_ceiling(seat="inner.py", seconds=5.0):
                pass
    assert "already armed" in str(caught.value)
