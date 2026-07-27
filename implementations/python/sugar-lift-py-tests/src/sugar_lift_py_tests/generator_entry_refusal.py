"""What CPython raises when a managed generator does not suspend.

``@contextlib.contextmanager`` over a generator that never reaches a ``yield``
is a well-defined Python program with a named outcome, not an unsupported
construct::

    contextlib._GeneratorContextManager.__enter__:
        try:
            return next(self.gen)
        except StopIteration:
            raise RuntimeError("generator didn't yield") from None

``next()`` raises ``StopIteration`` and ``contextlib`` converts it. So
``if c: yield 1`` under a manager has two outcomes: on one face it enters with
a value, and on the other it raises ``RuntimeError``. Both are ordinary runtime
behaviour with a ground exception type.

THE TYPE AND THE TEXT ARE OBSERVED, NOT TRANSCRIBED. This module runs the
vendor's own conversion and reads what comes out. Writing ``RuntimeError`` and
that string by hand would be a second, drifting copy of a spec that already
exists and executes -- and the vendor is the spec. If CPython changes either,
this changes with it and the twins say so.

The observation is recorded against ``PythonRuntimeIdentity``, the same
authority ``ClosedSemanticOperationWitness`` uses: a fact read off the running
interpreter is only as good as the interpreter it was read from.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from functools import lru_cache

from sugar_lift_py_tests.floor.closed_operation_witness import PythonRuntimeIdentity


@dataclass(frozen=True)
class GeneratorEntryRefusalV1:
    """The observed ``__enter__`` refusal for a generator that never yields."""

    runtime: PythonRuntimeIdentity
    exception_name: str
    message: str


@contextlib.contextmanager
def _a_generator_that_never_yields():
    """A manager whose generator body reaches no suspension.

    ``if False: yield`` is what makes this a generator at all while
    guaranteeing the suspension is unreachable -- which is exactly the shape
    of the non-suspending face of ``if c: yield 1``.
    """
    if False:  # pragma: no cover - the point is that it never runs
        yield


@lru_cache(maxsize=1)
def observed_entry_refusal() -> GeneratorEntryRefusalV1:
    """Run the vendor conversion and record what it raised.

    Memoized because the observation is a property of the interpreter, not of
    any call site, and because running it once is the whole point: the answer
    must come from CPython exactly once and be reused, never re-derived by
    hand at each site.
    """
    try:
        with _a_generator_that_never_yields():  # pragma: no branch
            pass
    except BaseException as raised:  # noqa: BLE001 - the vendor names the type
        return GeneratorEntryRefusalV1(
            runtime=PythonRuntimeIdentity.current(),
            exception_name=type(raised).__name__,
            message=str(raised),
        )
    raise AssertionError(
        "contextlib entered a generator that never yields; the conversion this "
        "module observes no longer exists and the lift must be re-derived"
    )
