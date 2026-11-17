"""Twins: after a ``with`` whose ``__exit__`` suppressed a halt of its body,
every name reads the state at the halt, never the completed body's value.

```
class Swallow:
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc, tb):
        return True

def f(flag):
    result = 0
    with Swallow():
        if flag:
            raise ValueError
        result = 1
    return result
```

Python leaves the ``with`` by one of two routes: the body completed (``f(False)``
returns 1), or ``__exit__`` suppressed the ``raise`` and the store ``result =
1`` was never made (``f(True)`` returns 0).  Before, the ``with`` published
what its completed body left (``With._published``) on both routes, so the
read of ``result`` after it was the reference to ``result = 1``'s key, which
the suppression route never bound: the read was refused by name
(``EvaluationRefSugar``: "read of `result` with its evaluation ... unbound"),
and the whole function with it.  The first nine-step lane run on main
``d5dcbab5c`` listed 236 pandas functions refused so; 130 of them are this
shape (``with tm.assert_produces_warning(...): result = ...`` then a read of
``result``; ``with pytest.raises(...): df.drop(...)`` then a read of ``df``).

The ``with`` now leaves through its routes as a ``try`` does
(``With._suppression_route``): a read after it is joined over its suppression
slot (``route_slot`` of ``with_route_site``), the suppression route's state is
the state a halt of the body carries, joined over the body statement that
raised it (``_HaltEdgeJoin``, one ``try-edge`` slot per body statement), and
``WithReducedManagerSugar`` decides the route and grounds the edge on every
outcome it goes on by (``_route_taken``).

Shapes:

- ``store-after-the-halt``: a name bound before the ``with``, stored in the
  body after the halting statement: the suppression route reads the value
  before the ``with``.
- ``unbound-before-the-with``: a name the body binds first: the suppression
  route reads it unbound, ``UnboundLocalError`` (a ``NameError``), as Python
  does -- never the completed body's value.
- ``mutation-in-the-body``: a list the body appends to after the halting
  statement (the ``df.drop(...)`` shape, a read of a store's pair key): the
  suppression route reads the list as it was.
- ``halt-after-the-store``: two halting statements, the store between them:
  the halt's own occurrence decides which body statement raised it, so the
  route that halted after the store reads the stored value.

A lying claim is never ``sat``; a truthful one is never ``unsat``.  Each
half goes through ``run_source_through_real_solver``: real ``sugar mint``
then real ``sugar prove``.  Neither half's lift refuses a function by
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

_SWALLOW = (
    "class Swallow:\n"
    "    def __enter__(self):\n"
    "        return self\n"
    "\n"
    "    def __exit__(self, exc_type, exc, tb):\n"
    "        return True\n"
    "\n"
    "\n"
)

# ``name: (helper f, truthful claim, lying claim)``.
_SHAPES = {
    "store-after-the-halt": (
        "def f(flag):\n"
        "    result = 0\n"
        "    with Swallow():\n"
        "        if flag:\n"
        "            raise ValueError\n"
        "        result = 1\n"
        "    return result\n",
        "f(True) == 0 and f(False) == 1",
        "f(True) == 1",
    ),
    "unbound-before-the-with": (
        "def f(flag):\n"
        "    with Swallow():\n"
        "        if flag:\n"
        "            raise ValueError\n"
        "        result = 1\n"
        "    try:\n"
        "        return result\n"
        "    except NameError:\n"
        "        return 0\n",
        "f(True) == 0 and f(False) == 1",
        "f(True) == 1",
    ),
    "mutation-in-the-body": (
        "def f(flag):\n"
        "    items = []\n"
        "    with Swallow():\n"
        "        if flag:\n"
        "            raise ValueError\n"
        "        items.append(1)\n"
        "    return len(items)\n",
        "f(True) == 0 and f(False) == 1",
        "f(True) == 1",
    ),
    "halt-after-the-store": (
        "def f(flag):\n"
        "    result = 0\n"
        "    with Swallow():\n"
        "        if flag:\n"
        "            raise ValueError\n"
        "        result = 1\n"
        "        raise KeyError\n"
        "    return result\n",
        "f(True) == 0 and f(False) == 1",
        "f(False) == 0",
    ),
}


def _source(helper: str, claim: str) -> tuple[str, int]:
    """The source, and the line of ``def test_f():`` (its claims start
    there, after every helper)."""
    prefix = _SWALLOW + helper + "\n\n"
    return (
        prefix + "def test_f():\n" + f"    assert {claim}\n",
        prefix.count("\n") + 1,
    )


@pytest.mark.parametrize("half", ["truthful", "lying"])
@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_a_read_after_a_suppressing_with_reads_the_state_at_the_halt(
    tmp_path: Path, shape: str, half: str
) -> None:
    helper, truthful, lying = _SHAPES[shape]
    source, test_line = _source(helper, truthful if half == "truthful" else lying)
    result = run_source_through_real_solver(tmp_path / shape / half, source)
    # The function lifts: no read after the ``with`` is refused by name.
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
