"""Unpack store-outcome composition laws -- owned by the Assign-family branch.

Ownership boundary (T's ruling):

    store ExitSet branch   owns generic store success/halt composition
                           owns sequential assignment spelling

    this branch (#6239)    owns tuple/multi-target construction
                           owns unpack sequencing through that composition

The generic algebra -- ``python:store_completed(occurrence, operation)``,
``FollowStep.halt_guard``, ``Halted(g, effect, prefix_state)`` paired with
``Completed(not g, state_with_testimony)`` -- is the store branch's work and is
proven there by the SEQUENTIAL twins. What is proven HERE is that the
tuple/multi-target ``Assign`` construction this branch owns actually flows
through that composition: a store leaf inside an unpack is not a different kind
of store, so ``x, o.y = p, q`` and ``o.x, o.y = p, q`` must produce exactly the
same arm structure as the sequential spelling.

ONE CONTROL MODEL: the helpers below are IMPORTED from the sequential twins'
module, not copied. If the two spellings were reading the artifact through two
instruments, "the same laws" would be an assertion about the instruments rather
than about the construction. ``UnpackStoreAssignSugar.desugar`` likewise owns no
sequencing of its own -- it hands its store leaves to ``reduce_body``, i.e. to
``reduce_block_to_exitset``, the same reducer the sequential spelling reaches
directly. The success/halt partition is minted in exactly one place
(``FollowStep.halt_guard`` handling in ``function_universe_sugar``).

GATE CONDITIONS recorded before these went green -- DISCHARGED, kept here so the
discharge is auditable rather than assumed:

  1. Both ``_discrimination`` twins used to die inside ``_exits`` and never
     reach their ``pytest.raises`` block, so they were duplicates of the two law
     twins rather than independent evidence. They now enter those bodies; each
     was re-checked to fail for its own reason (a ``pytest.raises(AssertionError)``
     wrapper is the classic shape that goes green while asking nothing).
  2. ``test_unpack_two_stores_..._discrimination`` only required
     ``_store_entries(first.state) != 1``, which 0 AND 2 both satisfy. It now
     pins the EXACT arm cardinality from both sides.
  3. The law twins had never run past their first assertion. Every line was
     re-measured against the constructed artifact, and each twin was perturbed
     (prefix splice removed; unpack projected onto its sole completed arm; store
     order reversed) to confirm it fails for the right reason.
"""

from __future__ import annotations

import pytest

# ONE definition, one owner. These were duplicated verbatim while the store
# ExitSet foundation was still on a branch; it is on main now, so the copy is
# deleted rather than left to diverge silently.
from test_store_outcome_composition import _arms, _exits, _polarity, _store_entries

# Free undecided ``o`` keeps dual-face AttributeStoreRuntimeEffect composition.
# Formal receivers mint setattr_named (see test_setattr_named_formal_caller).
UNPACK_MIXED = """def target(p, q):
    x, o.y = p, q
    return x
"""

UNPACK_BOTH = """def target(p, q):
    o.x, o.y = p, q
    return p
"""


# --------------------------------------------------------------------------
# Unpack spelling:  x, o.y = p, q   and   o.x, o.y = p, q
#
# THE SAME LAWS as the sequential spelling. These are the same store family; a
# store target inside a tuple-unpack assignment is not a different kind of
# store.
#
# They are stated as the real laws rather than pinned to the current behaviour
# on purpose: a test that must be DELETED when the bug is fixed is a test of the
# bug, and a test that must be EDITED when the fix lands was asserting the
# defect.
# --------------------------------------------------------------------------


def test_unpack_mixed_name_and_store_preserves_both_outcomes(tmp_path) -> None:
    """``x, o.y = p, q``

    success arm: ``x == p``, the store on ``o.y`` completed, continuation runs.
    halt arm:    ``x == p`` STILL -- the name target was already bound -- the
                 store halted, and there is NO continuation.
    """
    halted, completed = _arms(_exits(tmp_path, UNPACK_MIXED, "target"))

    assert len(completed) == 1
    assert _polarity(completed[0].guard, "y") is True
    assert "p" in str(completed[0].value.post())

    (arm,) = halted
    assert _polarity(arm.guard, "y") is False

    # "x == p still" on the halt arm.
    #
    # A Name target is spent by substitute -- it is inlined into every later
    # reference and materializes no entry on either arm -- so it cannot be
    # asserted as a retained entry on the halted state; there is nothing there
    # to lose and nothing there to read. The claim with an artifact behind it
    # is the one about anything ESTABLISHED before the store, and the honest
    # spelling of it is a preceding store: it must survive.
    prior = "def target(p, q):\n    o.z = p\n    x, o.y = p, q\n    return x\n"
    prior_halted, prior_completed = _arms(_exits(tmp_path, prior, "target"))
    survivor = next(h for h in prior_halted if _polarity(h.guard, "y") is False)
    assert _polarity(survivor.guard, "z") is True
    assert len(_store_entries(survivor.state)) == 1, (
        "the store completed before the halting one must survive the halt -- "
        "Python rolls back nothing"
    )
    assert "attr=z" in _store_entries(survivor.state)[0].effect.reason
    assert len(prior_completed) == 1


def test_unpack_mixed_name_and_store_preserves_both_outcomes_discrimination(
    tmp_path,
) -> None:
    """The bite: a single unconditional arm would mean the store cannot fail.

    Stated as the EXACT pre-repair cardinality (0 halted, 1 completed) so that
    the arm count is pinned from both sides -- ``!= 1`` would be satisfied by a
    zero-arm reading as well as by the real two-arm one.
    """
    halted, completed = _arms(_exits(tmp_path, UNPACK_MIXED, "target"))

    with pytest.raises(AssertionError):
        assert len(halted) == 0 and len(completed) == 1, "store is infallible"

    # ...and the guard on the halt arm really is this store's complement, not
    # some unrelated coordinate that happens to be negated.
    with pytest.raises(AssertionError):
        assert _polarity(halted[0].guard, "y") is True, "halt arm asserts completion"

    # ...and the non-rollback reading bites: a halted arm with an empty prefix
    # after an earlier store is the transactional lie.
    prior = "def target(p, q):\n    o.z = p\n    x, o.y = p, q\n    return x\n"
    prior_halted, _ = _arms(_exits(tmp_path, prior, "target"))
    survivor = next(h for h in prior_halted if _polarity(h.guard, "y") is False)
    with pytest.raises(AssertionError):
        assert _store_entries(survivor.state) == [], "assignment rolled back"


def test_unpack_two_stores_preserve_both_outcomes_per_store(tmp_path) -> None:
    """``o.x, o.y = p, q`` -- the same three arms as the sequential spelling:
    first success + second success, first success + second halt, and first halt
    with NO second-store occurrence."""
    halted, completed = _arms(_exits(tmp_path, UNPACK_BOTH, "target"))

    assert len(completed) == 1
    assert len(halted) == 2

    first = next(h for h in halted if _polarity(h.guard, "x") is False)
    assert _polarity(first.guard, "y") is None
    assert _store_entries(first.state) == []

    second = next(h for h in halted if _polarity(h.guard, "y") is False)
    assert _polarity(second.guard, "x") is True
    assert len(_store_entries(second.state)) == 1


def test_unpack_two_stores_preserve_both_outcomes_per_store_discrimination(
    tmp_path,
) -> None:
    """The bite: the first-halt arm must not carry the second store, and the
    three-arm structure is pinned to EXACTLY three.

    ``len(halted) != 1`` would be satisfied by zero halted arms too -- i.e. by
    the very defect these twins exist to forbid -- so the cardinality is stated
    exactly.
    """
    halted, completed = _arms(_exits(tmp_path, UNPACK_BOTH, "target"))
    first = next(h for h in halted if _polarity(h.guard, "x") is False)

    with pytest.raises(AssertionError):
        assert len(_store_entries(first.state)) == 1, "second target ran anyway"

    with pytest.raises(AssertionError):
        assert (len(halted), len(completed)) == (0, 1), "stores are infallible"

    with pytest.raises(AssertionError):
        assert (len(halted), len(completed)) == (1, 1), "one store swallowed the other"

    # ...and the first-halt arm is not conditioned on the second store at all.
    with pytest.raises(AssertionError):
        assert _polarity(first.guard, "y") is not None, "second store was consulted"


def test_unpack_and_sequential_spellings_produce_the_same_arm_structure(
    tmp_path,
) -> None:
    """T's merge criterion, stated as a twin.

    ``o.x = p; o.y = q`` and ``o.x, o.y = p, q`` are two spellings of the same
    two stores. Read through the SAME instrument they must present the same
    partition: three arms, the same guard polarities per store, the same prefix
    contents per halted arm. Anything else means the unpack grew a second
    sequencing door.
    """
    sequential = "def target(p, q):\n    o.x = p\n    o.y = q\n    return p\n"

    def shape(src):
        halted, completed = _arms(_exits(tmp_path, src, "target"))
        return (
            len(completed),
            sorted(
                (
                    _polarity(h.guard, "x"),
                    _polarity(h.guard, "y"),
                    len(_store_entries(h.state)),
                )
                for h in halted
            ),
            sorted(
                (_polarity(c.guard, "x"), _polarity(c.guard, "y")) for c in completed
            ),
        )

    assert shape(UNPACK_BOTH) == shape(sequential)

    # Discrimination: the instrument is not blind -- a spelling with only ONE
    # store presents a different shape through the same reader.
    assert shape(UNPACK_BOTH) != shape("def target(p):\n    o.x = p\n    return p\n")
