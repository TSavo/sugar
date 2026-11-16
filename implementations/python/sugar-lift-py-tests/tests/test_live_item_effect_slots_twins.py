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

Two slot terms are still two coordinates prove does not interpret: ``=``
over them is a choice the solver makes, and a claim reads ``sat`` where some
choice satisfies it, so with the slots keyed the lie still read ``sat``.  The
identity of a slot coordinate with anything but its own term is the
undecided read (``effect_coordinate.slot_identity``): the claim owes the
undecided member, never a free choice.

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


# -- the term each read gets, and what its identity owes ----------------------

_SLOT = "blake3-512:test-except-slot"
_LOOP = "blake3-512:test-live-loop"


def _read_in_item(index: int):
    """``e`` read in live item ``index``: the handler's ``EffectRef`` with no
    deposit, so its pure coordinate."""
    from sugar_lift_py_tests.occurrence import entered, loop_iteration_segment
    from sugar_lift_py_tests.sugar.effect_ref_sugar import EffectRefSugar

    with entered(loop_iteration_segment(_LOOP, index)):
        return EffectRefSugar(slot_id=_SLOT, site=None).desugar(None).completed_value()


def _owes(outcome) -> bool:
    from sugar_lift_py_tests.unanswered_calls import UnansweredCallV1

    return any(isinstance(item, UnansweredCallV1) for item in outcome.owed_items())


def test_each_item_reads_its_own_slot_term() -> None:
    from sugar_lift_py_tests.ir import ctor, str_const
    from sugar_lift_py_tests.occurrence import loop_iteration_segment

    for index in (0, 1):
        item = loop_iteration_segment(_LOOP, index)
        assert _read_in_item(index).to_term(owner="test") == ctor(
            "python:effect_slot", [str_const(f"{_SLOT}@{item}")]
        )


def test_two_items_objects_identity_owes_never_a_free_choice() -> None:
    # ``=`` over two slot terms is a choice the solver makes; a claim is
    # ``sat`` where some choice satisfies it.  The identity owes instead.
    first, second = _read_in_item(0), _read_in_item(1)
    assert _owes(first.is_identical(second, None))
    assert _owes(second.is_identical(first, None))


def test_one_items_binding_read_twice_is_one_object_and_owes_nothing() -> None:
    first = _read_in_item(0)
    assert not _owes(first.is_identical(_read_in_item(0), None))


def test_an_exception_info_and_its_exception_are_two_objects_that_owe() -> None:
    from sugar_lift_py_tests.floor.effect_coordinate import (
        EffectCoordinate,
        ExceptionInfoCoordinate,
    )

    info = ExceptionInfoCoordinate(slot_id=_SLOT)
    exception = EffectCoordinate(slot_id=_SLOT)
    assert _owes(info.is_identical(exception, None))
    assert _owes(exception.is_identical(info, None))
    assert not _owes(info.is_identical(ExceptionInfoCoordinate(slot_id=_SLOT), None))
