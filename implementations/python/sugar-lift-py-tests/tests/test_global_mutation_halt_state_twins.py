"""Twins: a halt inside a call on a module global holds the global as it
stood before the call, never the object after it (#7757).

```
class Gate:
    def check(self, flag):
        if flag:
            raise ValueError
        return 1

GATE = Gate()

def f(flag):
    with Swallow():
        GATE.check(flag)
    with Swallow():
        GATE.check(flag)
    return 7
```

``GATE.check(flag)`` is the one mutation door on the object ``GATE`` denotes
(``container_mutation.name_mutation_statement``): after the statement
``GATE`` is the object after the call (``PathAfterCall``), a read of the
call's pair key.  A halt inside the call never bound that key.  A name bound
before the statement was already held at such a halt as the object before
the call, which the call may have changed and then raised
(``Try._mid_statement_state``); a module global is in no scope before the
statement, so its halt held nothing for it (#9121 carried this), and every
join over the halts read the completed body's post-state instead:

- the ``with`` suppression route (``With._suppression_route``): the second
  ``with`` read ``GATE`` through the first call's pair key on the route
  where that call raised -- refused by name (``EvaluationRefSugar``: "read
  of `.check()` with its store's evaluation ... unbound"), the whole
  function with it.  pandas ``tests/test_nanops.py``
  (``nanops._ensure_numeric`` under ``pytest.raises``),
  ``tests/indexes/interval/test_constructors.py``
  (``IntervalIndex.from_tuples``), numpy ``testing/tests/test_utils.py``
  (``warnings.warn``);
- the ``finally`` under a halt (``_HaltEdgeJoin.finally_state``): pandas
  ``tests/extension/json/test_json.py`` (``sys.setrecursionlimit(100)`` in a
  ``try`` whose ``finally`` restores it), numpy ``testing/_private/utils.py``
  (``sys.settrace``);
- an ``except`` arm (``Try._incoming_halt_state``), which read the global as
  the frame's entry read it.

Shapes:

- ``with-suppressed-call``: the call itself raises, and the ``with`` goes
  on; the next ``with`` reads the global at the halt.
- ``with-halt-before-the-call``: an earlier body statement raises, before
  the call that changed the global: the halt holds the global's read before
  that change.
- ``finally-restores``: the ``finally`` calls on the global after the body
  called on it and returned.
- ``handler-calls-again``: the ``except`` arm calls on the global after the
  body's call raised.

A lying claim is never ``sat``; a truthful one is never ``unsat``.  Each half
goes through ``run_source_through_real_solver``: real ``sugar mint`` then
real ``sugar prove``.  Neither half's lift refuses a function by
``EvaluationRefSugar``.
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

_HELPERS = (
    "class Swallow:\n"
    "    def __enter__(self):\n"
    "        return self\n"
    "\n"
    "    def __exit__(self, exc_type, exc, tb):\n"
    "        return True\n"
    "\n"
    "\n"
    "class Gate:\n"
    "    def check(self, flag):\n"
    "        if flag:\n"
    "            raise ValueError\n"
    "        return 1\n"
    "\n"
    "\n"
    "GATE = Gate()\n"
    "\n"
    "\n"
)

# ``name: (helper f, truthful claim, lying claim)``.
_SHAPES = {
    "with-suppressed-call": (
        "def f(flag):\n"
        "    with Swallow():\n"
        "        GATE.check(flag)\n"
        "    with Swallow():\n"
        "        GATE.check(flag)\n"
        "    return 7\n",
        "f(True) == 7 and f(False) == 7",
        "f(True) == 8",
    ),
    "with-halt-before-the-call": (
        "def f(flag):\n"
        "    with Swallow():\n"
        "        if flag:\n"
        "            raise ValueError\n"
        "        GATE.check(False)\n"
        "    with Swallow():\n"
        "        GATE.check(flag)\n"
        "    return 7\n",
        "f(True) == 7 and f(False) == 7",
        "f(True) == 8",
    ),
    "finally-restores": (
        "def f(flag):\n"
        "    try:\n"
        "        GATE.check(flag)\n"
        "        return 7\n"
        "    finally:\n"
        "        GATE.check(False)\n",
        "f(False) == 7",
        "f(False) == 8",
    ),
    "handler-calls-again": (
        "def f(flag):\n"
        "    try:\n"
        "        GATE.check(flag)\n"
        "    except ValueError:\n"
        "        GATE.check(False)\n"
        "    return 7\n",
        "f(True) == 7 and f(False) == 7",
        "f(True) == 8",
    ),
}


def _source(helper: str, claim: str) -> tuple[str, int]:
    """The source, and the line of ``def test_f():`` (its claims start
    there, after every helper)."""
    prefix = _HELPERS + helper + "\n\n"
    return (
        prefix + "def test_f():\n" + f"    assert {claim}\n",
        prefix.count("\n") + 1,
    )


@pytest.mark.parametrize("half", ["truthful", "lying"])
@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_a_halt_inside_a_call_on_a_global_holds_the_global_before_the_call(
    tmp_path: Path, shape: str, half: str
) -> None:
    helper, truthful, lying = _SHAPES[shape]
    source, test_line = _source(helper, truthful if half == "truthful" else lying)
    result = run_source_through_real_solver(tmp_path / shape / half, source)
    # The function lifts: no read of the global after a halt inside the call
    # is refused by name.
    assert "EvaluationRefSugar" not in json.dumps(result.lift_doc), result.lift_doc
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
