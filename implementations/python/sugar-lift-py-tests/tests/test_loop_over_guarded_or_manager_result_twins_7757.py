"""Twins: a ``for`` over a guarded iterable, or over what an undecided
``with`` manager's ``__enter__`` returned, runs as its recurrence; the
function is never refused by name.

```
def _count_reduce_items(arr, axis):
    if axis is None:
        axis = tuple(range(arr.ndim))
    elif not isinstance(axis, tuple):
        axis = (axis,)
    items = 1
    for ax in axis:
        items *= arr.shape[ax]
    return items
```

The loop's ``iter`` is the one ``iter`` operation submitted to the
iterable (``iterator_operation.iterated``).  Two receivers had no answer,
and the whole function was refused by name at the loop (owner
``LoopRecurrenceSugar``): a ``GuardedValue`` (the name the loop iterates was
rebound under a branch: 27 numpy and 27 pandas functions on the 13e3413ad
lane) and an ``UndecidedManagerSlotResultValue`` (``with open(p) as f: for
line in f``: 19 numpy and 4 pandas).

Now a guarded iterable's arms each iterate through the one ``iter`` door,
their faces siblings under the guard's two polarities, each holding its own
arm's iterator (``GuardedValue.iter_with``): an arm in hand steps no
``next``, any other arm is the undecided iteration, its halt kept.  A
manager's result iterates as a call's result does: the undecided iteration,
two faces, owed (``UndecidedManagerSlotResultValue.iter_with``).

Shapes:

- ``guarded-list-or-formal``: ``names = [order] if flag else order``.
- ``guarded-nested-call-tuple-formal``: the ``_count_reduce_items`` shape,
  a call's result on one arm, a one-tuple on another, the formal on the
  third.
- ``manager-result``: ``with stream as f: for line in f`` over a formal
  manager, called with an ``io.StringIO``.

What the loop computes is the recurrence's, which nothing decides; each
claim reads the value the function returns after the loop, which every
completed arm decides.  A lying claim is never ``sat``; a truthful one is
never ``unsat``.  Each half goes through ``run_source_through_real_solver``:
real ``sugar mint`` then real ``sugar prove``.  Neither half's lift refuses
by ``GuardedValue`` or ``UndecidedManagerSlotResultValue``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import (
    claim_verdict,
    prove_verdict,
    run_source_through_real_solver,
)

# ``name: (source before the test, truthful claim, lying claim)``.
_SHAPES = {
    "guarded-list-or-formal": (
        "def first(order, flag):\n"
        "    names = [order] if flag else order\n"
        "    seen = 0\n"
        "    for name in names:\n"
        "        seen = 1\n"
        "    return 7\n",
        "first('a', True) == 7",
        "first('a', True) == 8",
    ),
    "guarded-nested-call-tuple-formal": (
        "def count(axis, ndim):\n"
        "    if axis is None:\n"
        "        axis = tuple(range(ndim))\n"
        "    elif not isinstance(axis, tuple):\n"
        "        axis = (axis,)\n"
        "    items = 1\n"
        "    for ax in axis:\n"
        "        items = items * 2\n"
        "    return 5\n",
        "count((1,), 2) == 5",
        "count((1,), 2) == 6",
    ),
    "manager-result": (
        "import io\n"
        "\n"
        "\n"
        "def lines(stream):\n"
        "    n = 0\n"
        "    with stream as f:\n"
        "        for line in f:\n"
        "            n = 1\n"
        "    return 7\n",
        "lines(io.StringIO('x')) == 7",
        "lines(io.StringIO('x')) == 8",
    ),
}

_REFUSED_RECEIVERS = ("GuardedValue", "UndecidedManagerSlotResultValue")


def _source(prefix: str, claim: str) -> tuple[str, int]:
    """The source, and the line of ``def test_f():`` (its claims start
    there, after everything the shape runs before it)."""
    prefix = prefix + "\n\n"
    return (
        prefix + "def test_f():\n" + f"    assert {claim}\n",
        prefix.count("\n") + 1,
    )


@pytest.mark.parametrize("half", ["truthful", "lying"])
@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_a_loop_over_a_guarded_or_manager_iterable_is_its_recurrence(
    tmp_path: Path, shape: str, half: str
) -> None:
    prefix, truthful, lying = _SHAPES[shape]
    source, test_line = _source(prefix, truthful if half == "truthful" else lying)
    result = run_source_through_real_solver(tmp_path / shape / half, source)
    # The loop's ``iter`` is answered by its receiver: no refusal names it.
    lifted = json.dumps(result.lift_doc)
    for receiver in _REFUSED_RECEIVERS:
        assert receiver not in lifted, result.lift_doc
    verdict = claim_verdict(
        result.prove_doc, claims_from_line=test_line, lift_doc=result.lift_doc
    )
    whole = prove_verdict(result.prove_doc)
    if half == "lying":
        assert verdict != "sat", result.prove_doc
        assert whole != "sat", result.prove_doc
    else:
        assert verdict != "unsat", result.prove_doc
        assert whole != "unsat", result.prove_doc
