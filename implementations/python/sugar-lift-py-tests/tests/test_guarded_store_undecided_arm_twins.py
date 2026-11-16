"""Twins: an item store or delete through a guarded choice whose one arm is
a value whose type the lift does not decide.

```
def store(flag, box):
    d = box if flag else {}
    d[5] = 1
    return 0


def test_store():
    assert store(<flag>, [0]) == 0
```

``d`` is a guarded choice (``GuardedValue``) between the formal ``box`` and
a dict.  The store distributes over its arms.  Before, the ``box`` arm's
store was ``SymbolicValue.setitem``, which completed with no halt face: the
helper's contract stated that the store always completes, so the claim
``store(True, [0]) == 0`` could read ``sat`` although Python raises
``IndexError`` (``[0][5] = 1``).  Now every arm stores through the one item
mutation (``store_effect_sugar.item_mutation``): the ``box`` arm is its
dispatched ``__setitem__`` edge on the class the caller binds (a builtin
``list`` takes its law at prove) or, where nothing binds it, owed; never a
completion with the halt dropped.  ``del d[5]`` is the same through
``__delitem__``.

The lying half claims the store through ``box`` completes; it is never
``sat``.  The truthful half takes the dict arm (``flag`` false), which
completes; it is never ``unsat``.

Each half goes through ``run_source_through_real_solver``: real ``sugar
mint`` then real ``sugar prove``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import (
    claim_verdict,
    prove_verdict,
    run_source_through_real_solver,
)

# ``name: (source, line of the test function)``; ``{flag}`` is the half's.
_SHAPES = {
    "setitem": (
        "def store(flag, box):\n"
        "    d = box if flag else {{}}\n"
        "    d[5] = 1\n"
        "    return 0\n"
        "\n"
        "\n"
        "def test_store():\n"
        "    assert store({flag}, [0]) == 0\n",
        7,
    ),
    "delitem": (
        "def drop(flag, box):\n"
        "    d = box if flag else {{5: 1}}\n"
        "    del d[5]\n"
        "    return 0\n"
        "\n"
        "\n"
        "def test_drop():\n"
        "    assert drop({flag}, [0]) == 0\n",
        7,
    ),
}


@pytest.mark.parametrize("half", ["truthful", "lying"])
@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_a_store_through_a_guarded_undecided_arm_never_always_completes(
    tmp_path: Path, shape: str, half: str
) -> None:
    source, line = _SHAPES[shape]
    flag = "False" if half == "truthful" else "True"
    result = run_source_through_real_solver(
        tmp_path / shape / half, source.format(flag=flag)
    )
    verdict = claim_verdict(result.prove_doc, claims_from_line=line)
    whole = prove_verdict(result.prove_doc)
    if half == "lying":
        assert verdict != "sat", result.prove_doc
        assert whole != "sat", result.prove_doc
    else:
        assert verdict != "unsat", result.prove_doc
        assert whole != "unsat", result.prove_doc
