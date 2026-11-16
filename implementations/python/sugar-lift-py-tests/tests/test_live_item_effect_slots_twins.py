"""Twins: two items of a live loop bind two ``except ... as e`` (or ``with
... as x``) objects, never one (#7757, step 6).

```
def test_slots():
    errs = []
    for i in [1, 2]:
        e = None
        try:
            raise ValueError(i)
        except ValueError as e:
            errs.append(e)
    assert <claim>
```

Python raises a new ``ValueError`` in each item, so ``errs[0] is not
errs[1]`` is the truth and ``errs[0] is errs[1]`` the lie.

A live loop's body is constructed once for every item (#8957), so the
handler (and the ``with``) in it carries one construct-time slot
(``ExceptHandler._effect_slot_id``, the with-item's ``#enter_result`` slot).
The coordinate a read of ``e`` or ``x`` projects (``EffectCoordinate``,
``ObservedEffectValue``: ``python:effect_slot(<slot>)``) and the facts
stated on it (``EffectBinding``, ``EnterResultBinding``) named that one slot
in every item, so two items' objects were one term and the lie could fold
true.  #7921 keyed the slot by the statement's evaluation for an unrolled
copy; a live item is known only at reduce.  The slot is now qualified by the
live items around it wherever it becomes a term
(``evaluation_ref_sugar.effect_slot_here``), as ``evaluation_here`` keys a
statement's evaluation and ``branch_slot_here`` an ``if``'s slot.

``e = None`` / ``x = None`` in the body make the name one the loop carries,
so the items can run in hand.

A lying claim is never ``sat``; a truthful one is never ``unsat``.  Each
half goes through ``run_source_through_real_solver``: real ``sugar mint``
then real ``sugar prove``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import (
    claim_verdict,
    prove_verdict,
    run_source_through_real_solver,
)

_HEADER = "def test_slots():\n"
_TEST_SLOTS_LINE = 1

# ``name: (body of test_slots, truthful claim, lying claim)``.
_SHAPES = {
    "except-as": (
        "    errs = []\n"
        "    for i in [1, 2]:\n"
        "        e = None\n"
        "        try:\n"
        "            raise ValueError(i)\n"
        "        except ValueError as e:\n"
        "            errs.append(e)\n"
        "    assert {claim}\n",
        "errs[0] is not errs[1]",
        "errs[0] is errs[1]",
    ),
    "with-as": (
        "    seen = []\n"
        "    for i in [1, 2]:\n"
        "        x = None\n"
        "        with open(__file__) as x:\n"
        "            seen.append(x)\n"
        "    assert {claim}\n",
        "seen[0] is not seen[1]",
        "seen[0] is seen[1]",
    ),
}


@pytest.mark.parametrize("half", ["truthful", "lying"])
@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_two_items_bind_two_objects(tmp_path: Path, shape: str, half: str) -> None:
    body, truthful, lying = _SHAPES[shape]
    claim = truthful if half == "truthful" else lying
    result = run_source_through_real_solver(
        tmp_path / shape / half, _HEADER + body.format(claim=claim)
    )
    verdict = claim_verdict(result.prove_doc, claims_from_line=_TEST_SLOTS_LINE)
    whole = prove_verdict(result.prove_doc)
    if half == "lying":
        assert verdict != "sat", result.prove_doc
        assert whole != "sat", result.prove_doc
    else:
        assert verdict != "unsat", result.prove_doc
        assert whole != "unsat", result.prove_doc
