"""Twins: a set or dict comprehension in hand inserts each member as it runs,
so an unhashable member halts before any later member runs (#7757, step 6).

```
def f():
    try:
        {[1 // d] for d in [1, 0]}
        return 0
    except TypeError:
        return 1
    except ZeroDivisionError:
        return 2
```

CPython adds ``[1]`` to the set as the first member runs and raises
``TypeError`` there; the second member, ``[1 // 0]``, never runs.  So
``f()`` is 1.  The comprehension in hand (``ComprehensionSugar._run_in_hand``)
ran every member first and applied the display rule (``_built_set``,
``_built_dict``) to the finished members, so the second member's
``ZeroDivisionError`` was the stated halt and the lie ``f() == 2`` could read
``sat`` (#8966's named residue).  Each member is now inserted by the one
insertion rule (``collection_sugar._uninsertable``) as it runs: after the
element for a set, after the value for a dict (CPython evaluates a pair's key
and value, then inserts it), so ``dict-value-first`` keeps the value's own
halt.

A lying claim is never ``sat``; a truthful one is never ``unsat``.  Each half
goes through ``run_source_through_real_solver``: real ``sugar mint`` then
real ``sugar prove``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import run_source_through_real_solver

_TEMPLATE = """\
def f():
    try:
        COMPREHENSION
        return 0
    except TypeError:
        return 1
    except ZeroDivisionError:
        return 2


def test_f():
    assert f() == CLAIM
"""

# ``name: (comprehension, truth, lie)``.
_SHAPES = {
    "set": ("{[1 // d] for d in [1, 0]}", "1", "2"),
    "dict": ("{[d]: 1 // d for d in [1, 0]}", "1", "2"),
    "dict-value-first": ("{[d]: 1 // d for d in [0]}", "2", "1"),
}


def _source(shape: str, claim: str) -> str:
    comprehension = _SHAPES[shape][0]
    return _TEMPLATE.replace("COMPREHENSION", comprehension).replace("CLAIM", claim)


@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_the_truthful_half_is_never_refuted(shape: str, tmp_path: Path) -> None:
    result = run_source_through_real_solver(
        tmp_path / shape / "t", _source(shape, _SHAPES[shape][1])
    )
    assert result.verdict != "unsat", result.prove_doc


@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_the_lying_half_is_never_sat(shape: str, tmp_path: Path) -> None:
    result = run_source_through_real_solver(
        tmp_path / shape / "l", _source(shape, _SHAPES[shape][2])
    )
    assert result.verdict != "sat", result.prove_doc
