"""A default read that owes is the call's prefix, never a refused call (#7757).

``SourceVisibleCallFrameV1.bind_actuals`` binds a formal the call omits to
what the ``def`` statement bound under the default's key.  For a module
``def`` called after import that read is the module run's arms that bound the
key (``call_site_sugar.bound_read``): their guard and every debt they owe.  A
module that makes one unanswered call before the ``def`` (``x =
os.getcwd()``) owes it on every arm, so the read owed, and the binder refused
the whole call by name ("default did not construct completely",
``LambdaCallable.callable_application_with``: 40 pandas functions on the
first nine-step lane, d5dcbab5c).

The read is now the call's prefix (``BoundSourceCallActualsV1.then_call``,
through ``ExitSet.and_then``): the bound actual is its one completed arm's
value and its guard and debts ride every arm of the call.  Nothing is dropped
into the actual.

Twins go through ``run_source_through_real_solver``: real ``sugar mint`` then
real ``sugar prove``.  The truthful claim is decided ``sat`` (it was ``open``
while the call was refused); the lying one is never ``sat``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import (
    claim_verdict,
    run_source_through_real_solver,
)

_SOURCE = (
    "import os\n"
    "\n"
    "HERE = os.getcwd()\n"
    "\n"
    "\n"
    "def pick(a, b=1):\n"
    "    return a\n"
    "\n"
    "\n"
    "def test_f():\n"
    "    assert {claim}\n"
)

_CLAIMS = {"truthful": "pick(2) == 2", "lying": "pick(2) == 3"}


def _claims_line(source: str) -> int:
    for number, line in enumerate(source.splitlines(), start=1):
        if line.startswith("def test_"):
            return number
    raise AssertionError("the source states no test function")


@pytest.mark.parametrize("half", ["truthful", "lying"])
def test_a_default_read_that_owes_never_refuses_the_call(
    tmp_path: Path, half: str
) -> None:
    text = _SOURCE.format(claim=_CLAIMS[half])
    native: dict = {}
    exec(text, native)
    if half == "truthful":
        native["test_f"]()
    else:
        with pytest.raises(AssertionError):
            native["test_f"]()
    result = run_source_through_real_solver(tmp_path / half, text)
    verdict = claim_verdict(result.prove_doc, claims_from_line=_claims_line(text))
    if half == "truthful":
        assert verdict == "sat", result.prove_doc
    else:
        assert verdict != "sat", result.prove_doc


def test_then_call_composes_each_read_before_the_call() -> None:
    """The read's guard is conjoined and its debts owed on the call's arms."""
    from sugar_lift_py_tests.ir import atomic, make_var
    from sugar_lift_py_tests.outcome import Completed, ExitSet
    from sugar_lift_py_tests.source_call_frame import BoundSourceCallActualsV1

    guard = atomic("run_arm", [make_var("state")])
    read = ExitSet((Completed(guard, "default", frozenset(), ("debt",)),))
    bound = BoundSourceCallActualsV1((), (), (), (read,))
    call = ExitSet.completed("result")

    (arm,) = bound.then_call(call).exits
    assert arm.value == "result"
    assert "debt" in arm.owed
    assert "run_arm" in repr(arm.guard)
    assert BoundSourceCallActualsV1((), ()).then_call(call) is call
