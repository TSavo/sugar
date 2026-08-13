"""A per-file wall-clock ceiling on measurement, and the outcome it produces.

Why this exists
---------------
``pandas/core/groupby/generic.py`` (roster index 125 on the pinned 3.0.3
corpus) does not terminate under the census. Its three groupby neighbours
measure in 48-129ms each; this one ran 6h03m in CI shard s5 before the shard
was cancelled, and a cancelled shard uploads no partial. One file therefore
destroyed the whole run's evidence, and the heavy LPT bin moved between runs
without ever disappearing, because the LPT prior can only price a file that
completes.

The fix is NOT a bigger ceiling on the shard. The cost is unbounded, so no
shard ceiling is correct. The fix is that a single file cannot consume a shard
silently: when a file exceeds a stated wall-clock bound, the census records a
loud, countable frontier row naming construct, coordinate and shape, and moves
on to the next file.

What this outcome is, and is not
--------------------------------
``measurement-exhausted`` is its own terminal kind. It is:

- NOT a construction panic. Nothing refused to construct; we stopped asking.
  Reporting exhaustion as a panic would invent a refusal the product never
  made.
- NOT an instrument failure. The instrument did not break; it did exactly what
  it was told and was stopped by its own bound. Reporting exhaustion as an
  instrument failure would make a product fact look like a harness fact — and
  instrument-failure rows are excluded from attestation, so the file would
  vanish from the frontier again.
- NOT an absence. The seat is still counted. The denominator is the 1421
  enrolled files and it does not move.

Absence, refusal and exhaustion never share a representation (#7394, #7399).
``measurement-exhausted`` is a member of the terminal partition that
``compose_control_effect_board`` reconciles, so
``constructed + construction-panic + measurement-exhausted == enrolled``.

The bound
---------
``DEFAULT_CEILING_SECONDS = 300``.

Authenticated, not chosen for roundness. On the pinned pandas 3.0.3 corpus,
measured through this same entrance on the battleaxe sandbox (``bin/brun
--task frontier-profile``), the whole-corpus per-file cost distribution is
reported beside this constant in ``CEILING_EVIDENCE`` below. 300s is set at
roughly two orders of magnitude above the slowest file that completes, so a
file that trips it is not a slow file: it is a file whose cost is not a cost.
A bound tight enough to catch a merely-slow file would be a bound that reports
exhaustion for work that would have produced a real terminal, and that is the
one error this instrument must not make -- an exhaustion row that a longer
bound would have turned into a construction outcome is a false frontier row.

Raising this number does not make a run greener; it only makes a red run take
longer to go red. Lowering it below the measured maximum manufactures
exhaustion rows. Both are visible here, in the place a reader meets the bound,
which is the point.

Override with ``SUGAR_MEASUREMENT_CEILING_SECONDS`` for experiments. The value
in force is reported by every run that arms it, so no reader has to guess
which bound produced a row.
"""

from __future__ import annotations

import os
import signal
import threading
from contextlib import contextmanager
from typing import Any, Iterator

DEFAULT_CEILING_SECONDS = 300.0

CEILING_ENV_VAR = "SUGAR_MEASUREMENT_CEILING_SECONDS"

TERMINAL_KIND_EXHAUSTED = "measurement-exhausted"
CATEGORY_EXHAUSTED = "measurement-exhausted"

# Measured on this branch, not quoted from a ticket. `bin/brun --task
# frontier-profile -- --start 0 --stride 13` on the authenticated pandas 3.0.3
# corpus: 110 seats, every one of them producing a terminal.
CEILING_EVIDENCE = {
    "corpus": "authenticated pandas 3.0.3 (1421 enrolled files)",
    "entrance": "recensus_enumerate_consumer.measure_file_via_enumerate",
    "host": "battleaxe sandbox via bin/brun --task frontier-profile",
    "sample": "sorted(roster)[0::13] -- 110 seats",
    "terminals": {"constructed": 82, "construction-panic": 28},
    "perFileMillis": {
        "min": 3.8,
        "median": 384.6,
        "p95": 4733.1,
        # tests/tools/test_to_datetime.py -- the slowest file in the sample
        # that still produces a terminal.
        "max": 9499.0,
    },
    "sampleWallSeconds": 124.6,
    # 300s is ~32x that slowest completing file. A file that trips this bound
    # is not a slow file.
    "headroomOverSlowestCompletingFile": "~32x",
}


class MeasurementCeilingExceeded(BaseException):
    """One seat exceeded the stated wall-clock bound.

    Deliberately a ``BaseException`` and not an ``Exception``. The construction
    path is full of ``except Exception`` arms that turn a raised event into a
    terminal row for the file being measured; if the ceiling could be caught by
    one of those, the file would report a *construction* outcome caused by the
    clock. Exhaustion must reach the seat boundary intact or it is a lie about
    what the product did.
    """

    def __init__(
        self,
        *,
        seat: str,
        bound_seconds: float,
        active_stack: list[str],
    ) -> None:
        super().__init__(
            f"measurement ceiling exceeded: seat={seat} bound_s={bound_seconds} "
            f"depth={len(active_stack)} tip={active_stack[-1] if active_stack else '<no active span>'}"
        )
        self.seat = seat
        self.bound_seconds = bound_seconds
        self.active_stack = list(active_stack)


def ceiling_seconds() -> float:
    """The bound in force, from the environment or the stated default."""
    raw = os.environ.get(CEILING_ENV_VAR)
    if raw is None or not raw.strip():
        return DEFAULT_CEILING_SECONDS
    value = float(raw)
    if value <= 0:
        raise ValueError(
            f"{CEILING_ENV_VAR} must be positive; got {value!r}. "
            "A non-positive ceiling would disarm the bound silently, which is "
            "the failure this instrument exists to end."
        )
    return value


def is_unswallowable(error: BaseException) -> bool:
    """Events a per-file terminal handler must re-raise, never bank as a row.

    Process control (the shard is dying) and measurement exhaustion (the seat
    boundary owns this outcome, not an inner handler) are both events that an
    inner ``except BaseException`` must not convert into a terminal for the
    construct it happened to be building.
    """
    return isinstance(
        error,
        (KeyboardInterrupt, SystemExit, GeneratorExit, MeasurementCeilingExceeded),
    )


def _active_stack_snapshot() -> list[str]:
    """The live reduction stack, captured before any unwinding."""
    try:
        from sugar_lift_py_tests.engine_log import active_stack_snapshot
    except ImportError:
        return []
    return active_stack_snapshot()


@contextmanager
def measurement_ceiling(*, seat: str, seconds: float | None = None) -> Iterator[float]:
    """Arm a wall-clock bound for one seat; raise by name when it is exceeded.

    Refuses rather than degrading. If ``SIGALRM`` is unavailable or this is not
    the main thread, this raises: a ceiling that quietly does nothing is worse
    than no ceiling, because the run then looks bounded and is not.
    """
    bound = ceiling_seconds() if seconds is None else float(seconds)
    if bound <= 0:
        raise ValueError(f"measurement ceiling must be positive; got {bound!r}")
    if not hasattr(signal, "SIGALRM") or not hasattr(signal, "setitimer"):
        raise RuntimeError(
            "measurement ceiling requires signal.SIGALRM/setitimer; this "
            "platform has neither. Refusing to run unbounded while claiming a "
            f"bound of {bound}s."
        )
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError(
            "measurement ceiling must be armed on the main thread (signal "
            "delivery is main-thread only). Refusing to run unbounded while "
            f"claiming a bound of {bound}s."
        )

    def _fire(signum: int, frame: Any) -> None:
        raise MeasurementCeilingExceeded(
            seat=seat,
            bound_seconds=bound,
            active_stack=_active_stack_snapshot(),
        )

    previous_handler = signal.signal(signal.SIGALRM, _fire)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, bound)
    if previous_timer[0]:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        raise RuntimeError(
            "an interval timer was already armed when the measurement ceiling "
            f"tried to arm ({previous_timer[0]}s remaining). Nesting would "
            "disarm one of the two bounds silently."
        )
    try:
        yield bound
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


def exhaustion_coordinates(active_stack: list[str]) -> list[dict[str, str]]:
    """Name construct, coordinate and shape from a captured reduction stack.

    Each frame fingerprint is ``sugar|role|site``: the sugar class being
    reduced, the role it was reduced in, and the blame coordinate. That triple
    is what makes an exhaustion row a frontier row and not a complaint about
    the clock -- ``generic.py:1323:12`` is a coordinate a reader can open.
    """
    rows: list[dict[str, str]] = []
    for fingerprint in active_stack:
        parts = str(fingerprint).split("|")
        if len(parts) >= 3:
            rows.append(
                {"construct": parts[0], "role": parts[1], "coordinate": parts[2]}
            )
        else:
            rows.append(
                {
                    "construct": str(fingerprint),
                    "role": "<unfingerprinted>",
                    "coordinate": "<unfingerprinted>",
                }
            )
    return rows
