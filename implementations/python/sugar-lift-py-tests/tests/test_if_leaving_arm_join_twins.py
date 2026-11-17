"""Twins: after an ``if`` one arm of which always leaves (by ``raise``,
``return``, ``break`` or ``continue``), every name reads what the arm that
goes on left, never a key only the leaving arm binds.

```
def read(self, nrows):
    ...
    if read_len <= 0:
        self.close()
        raise StopIteration
    raw = self.filepath_or_buffer.read(read_len)
```

Python reaches the statement after the ``if`` only from an arm that falls
through.  Before, ``If.substitute`` joined every name either arm bound over
the ``if``'s slot, the leaving arm included, so ``self`` after the ``if`` was
``<self after close()> if <test> else <self>``.  The path after the ``if``
reads that join by the test's condition, which a symbolic test does not
decide, so it read the leaving arm's face too: the key ``self.close()``
binds, which nothing on that path bound.  The read was refused by name
(``EvaluationRefSugar``: "read of `.close()` with its store's evaluation ...
unbound"), and the whole function with it.  The first nine-step lane run
listed seven pandas functions refused so, all in the SAS readers
(``io/sas/sas7bdat.py``: ``__next__``, ``_read_bytes``,
``_process_page_metadata``, ``read``, ``_read_next_page``,
``_chunk_to_dataframe``; ``io/sas/sas_xport.py``: ``read``).

The join now takes only the arms that complete by falling through, by the
one rule a ``try`` joins its routes by and a ``match`` its cases by
(``Try._block_has_completed_fallthrough``).  What the leaving arm bound still
leaves by its own exit: the halt's edge state, the ``return``'s record.

Shapes:

- ``mutation-then-raise``: a list the arm appends to before it raises (the
  ``self.close(); raise`` shape, a read of a store's pair key).
- ``store-then-raise``: a name the arm rebinds before it raises.
- ``store-then-return``: a name the arm rebinds before it returns it.
- ``method-close-then-raise``: the SAS reader's own shape, ``self.close()``
  then ``raise`` in a method, ``self`` read after the ``if``.

A lying claim is never ``sat``; a truthful one is never ``unsat``.  Each half
goes through ``run_source_through_real_solver``: real ``sugar mint`` then real
``sugar prove``.  Neither half's lift refuses by ``EvaluationRefSugar``.
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

# ``name: (helper, truthful claim, lying claim)``.
_SHAPES = {
    "mutation-then-raise": (
        "def f(flag):\n"
        "    items = []\n"
        "    if flag:\n"
        "        items.append(1)\n"
        "        raise ValueError\n"
        "    return len(items)\n",
        "f(False) == 0",
        "f(False) == 1",
    ),
    "store-then-raise": (
        "def f(flag):\n"
        "    result = 0\n"
        "    if flag:\n"
        "        result = 1\n"
        "        raise ValueError\n"
        "    return result\n",
        "f(False) == 0",
        "f(False) == 1",
    ),
    "store-then-return": (
        "def f(flag):\n"
        "    result = 0\n"
        "    if flag:\n"
        "        result = 1\n"
        "        return result\n"
        "    return result + 10\n",
        "f(False) == 10 and f(True) == 1",
        "f(False) == 11",
    ),
    "method-close-then-raise": (
        "class Reader:\n"
        "    def __init__(self):\n"
        "        self.closed = False\n"
        "\n"
        "    def close(self):\n"
        "        self.closed = True\n"
        "\n"
        "    def read(self, n):\n"
        "        if n <= 0:\n"
        "            self.close()\n"
        "            raise StopIteration\n"
        "        return n + 1\n",
        "Reader().read(1) == 2",
        "Reader().read(1) == 3",
    ),
}


def _source(helper: str, claim: str) -> tuple[str, int]:
    """The source, and the line of ``def test_f():`` (its claims start
    there, after every helper)."""
    prefix = helper + "\n\n"
    return (
        prefix + "def test_f():\n" + f"    assert {claim}\n",
        prefix.count("\n") + 1,
    )


@pytest.mark.parametrize("half", ["truthful", "lying"])
@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_a_read_after_an_if_never_reads_the_arm_that_left(
    tmp_path: Path, shape: str, half: str
) -> None:
    helper, truthful, lying = _SHAPES[shape]
    source, test_line = _source(helper, truthful if half == "truthful" else lying)
    result = run_source_through_real_solver(tmp_path / shape / half, source)
    # The function lifts: no read after the ``if`` is refused by name.
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
