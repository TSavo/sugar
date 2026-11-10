"""What CPython raises when a bare generator object heads a ``with``.

Calling an undecorated generator function returns a generator object and runs
none of its body. A generator object has no ``__enter__``/``__exit__``, so
``with g():`` evaluates the call and then the ``with`` statement itself raises
``TypeError`` -- before any enter runs and before the body runs. It is a
well-defined Python program with a ground exceptional outcome, not a manager.

THE TYPE AND THE TEXT ARE OBSERVED, NOT TRANSCRIBED (the same law as
``generator_entry_refusal``): this module runs the interpreter's own ``with``
over a real generator object once and records what it raised, against the
``PythonRuntimeIdentity`` it was read from.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from sugar_lift_py_tests.floor.closed_operation_witness import PythonRuntimeIdentity


@dataclass(frozen=True)
class GeneratorObjectWithRefusalV1:
    """The observed ``with`` refusal for a generator object as the manager."""

    runtime: PythonRuntimeIdentity
    exception_name: str
    message: str


def _a_generator_function():
    yield  # pragma: no cover - the body never runs: the with refuses first


@lru_cache(maxsize=1)
def observed_generator_object_with_refusal() -> GeneratorObjectWithRefusalV1:
    """Run ``with <generator object>:`` once and record what the interpreter raised."""
    entered = False
    try:
        with _a_generator_function():  # type: ignore[attr-defined]
            entered = True  # pragma: no cover
    except Exception as raised:  # the interpreter raises TypeError here
        if entered:  # pragma: no cover
            raise AssertionError("the with body ran over a generator object")
        return GeneratorObjectWithRefusalV1(
            runtime=PythonRuntimeIdentity.current(),
            exception_name=type(raised).__name__,
            message=str(raised),
        )
    raise AssertionError(
        "the interpreter entered a generator object as a context manager; the "
        "refusal this module observes no longer exists and the lift must be "
        "re-derived"
    )
