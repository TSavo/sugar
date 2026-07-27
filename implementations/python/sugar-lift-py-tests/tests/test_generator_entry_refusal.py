"""A managed generator that never yields raises, and the type is OBSERVED.

`@contextlib.contextmanager` over a generator that reaches no suspension is a
well-defined Python program: `next()` raises `StopIteration` and the manager
protocol converts it to `RuntimeError("generator didn't yield")`. Two outcomes,
both ordinary runtime behaviour with a ground exception type.

The lift said otherwise. `GeneratorWithSugar` met that outcome and refused with

    "generator terminated before first yield"

which describes a real Python outcome as an unsupported construct. It is not a
refusal -- it is a legitimate exit that was never given its constructor, and it
read as owed work on the board for exactly that reason.

THE TYPE IS NOT TRANSCRIBED. `generator_entry_refusal` RUNS the vendor's own
conversion and reads what comes out. Writing `RuntimeError` and that string by
hand would be a second copy of a spec that already exists and executes; the
vendor is the spec, so a runtime change must move the lift rather than silently
diverge from it.

THIS LANDS THE OBSERVATION ONLY. The consumer that will ask it -- the
`with` entry path that today refuses this outcome -- is not wired here.
The vendor spelling lives in this module and not in that consumer, which
`generator_construction_law` independently enforces.
"""

from __future__ import annotations

import contextlib
import inspect

from sugar_lift_py_tests.generator_entry_refusal import (
    observed_entry_refusal,
)

# -- the observation is the vendor's, not ours -------------------------------


def test_the_refusal_is_read_from_the_running_interpreter() -> None:
    refusal = observed_entry_refusal()

    assert refusal.exception_name == "RuntimeError"
    assert refusal.message == "generator didn't yield"


def test_the_observation_matches_the_vendor_source_it_claims_to_lift() -> None:
    """The truthful twin: what we observed is what the vendor actually does.

    Read from `contextlib` HERE, in the test, precisely because the lift must
    not read it -- if the observation and the vendor source ever disagree, this
    is the arm that says so.
    """
    source = inspect.getsource(contextlib._GeneratorContextManager.__enter__)
    refusal = observed_entry_refusal()

    assert refusal.exception_name in source
    assert refusal.message in source
    # And the conversion this lift depends on is the one in that source.
    assert "StopIteration" in source


def test_the_observation_records_the_runtime_it_was_read_from() -> None:
    """A fact read off the running interpreter is only as good as that
    interpreter -- same authority `ClosedSemanticOperationWitness` carries."""
    import sys

    runtime = observed_entry_refusal().runtime

    assert runtime.implementation == sys.implementation.name
    assert runtime.major == sys.version_info.major
    assert runtime.minor == sys.version_info.minor


def test_the_observation_is_minted_once() -> None:
    """It is a property of the interpreter, not of a call site."""
    assert observed_entry_refusal() is observed_entry_refusal()


# -- lying twin: any other spelling must flip --------------------------------


def test_a_different_exception_spelling_would_flip_the_twin() -> None:
    """THE lying twin.

    If the lift ever produced anything other than what the vendor raises --
    a hardcoded string that drifted, a wrong exception type, a message someone
    "tidied" -- the truthful arm above compares against `contextlib`'s live
    source and fails. This states that the comparison has teeth by showing the
    shape it rejects.
    """
    source = inspect.getsource(contextlib._GeneratorContextManager.__enter__)

    for wrong in ("StopAsyncIteration", "ValueError", "generator did not yield"):
        assert wrong not in source or wrong == "StopIteration"
