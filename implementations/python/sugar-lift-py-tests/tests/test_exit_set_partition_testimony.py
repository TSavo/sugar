"""Carried partition testimony: the ExitSetFactoringGap's truthful/lying twins.

``factor_completed`` refuses when completed arms are not provably pairwise
exclusive, because a ``GuardedValue`` chain is first-match-wins and can only
carry a partition. Before #6309's follow-up the only proof available was
``_are_exclusive``, a sound but shallow read of guard SHAPE. Shape decays: the
moment a producer's two faces are conjoined with a prefix guard or merged with
a sibling arm, ``g`` against ``not g`` is no longer one literal deep, and a
producer that genuinely owned a partition hit the refusal anyway.

The fix is testimony, not a better prover. A producer that owns a two-way split
mints it with ``partition(owner)`` and stamps each arm via
``ExitSet.guarded(guard, face)``. Exclusivity is then READ, not re-derived.

Both faces are pinned here:

- **truthful twin** — a producer that owns complementary faces cannot construct
  the gap, even with guards whose shape hides the exclusion;
- **lying twin** — a producer that owns no partition still hits the refusal,
  and faces minted by two DIFFERENT owners never count as complementary.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.ir import and_, atomic, not_, or_
from sugar_lift_py_tests.outcome.exit_set import (
    Completed,
    ExitSet,
    ExitSetFactoringGap,
    partition,
    partition_family,
    true_guard,
)
from sugar_lift_py_tests.outcome.exit_set import _are_exclusive, _faces_exclusive


def _pred(name: str):
    return atomic(name, [])


def _shape_opaque_pair():
    """Two guards that are complementary in fact but not in one-literal shape.

    ``c`` against ``or(not c, q)`` is exactly what a branch face looks like once
    a sibling arm has been merged into the other face by ``normalize``. The
    shape prover cannot see it, and that is the point of the twin: it is the
    live condition under which a real partition used to be refused.
    """
    condition = _pred("c")
    other = or_([not_(condition), _pred("q")])
    assert not _are_exclusive(condition, other)
    assert not _are_exclusive(other, condition)
    return condition, other


def test_owned_partition_makes_the_factoring_gap_unconstructable():
    """Truthful twin: testimony carried, shape unreadable, no gap."""
    left_guard, right_guard = _shape_opaque_pair()
    left_face, right_face = partition(("twin-owner", "one-split"))

    exits = ExitSet(
        (
            Completed(left_guard, "then-value", frozenset({left_face})),
            Completed(right_guard, "else-value", frozenset({right_face})),
        )
    )

    factored = exits.factor_completed()

    # Exactly one completed arm remains, and it carries BOTH values as a chain.
    completed = [e for e in factored.exits if isinstance(e, Completed)]
    assert len(completed) == 1
    chain = completed[0].value
    assert chain.guard == left_guard
    assert chain.when_true == "then-value"
    assert chain.when_false == "else-value"


def test_unowned_arms_still_hit_the_refusal():
    """Lying twin A: no testimony, unreadable shape — the gap must fire."""
    left_guard, right_guard = _shape_opaque_pair()

    exits = ExitSet(
        (
            Completed(left_guard, "then-value"),
            Completed(right_guard, "else-value"),
        )
    )

    with pytest.raises(ExitSetFactoringGap) as raised:
        exits.factor_completed()
    assert "not provably exclusive" in str(raised.value)


def test_faces_from_two_different_owners_are_not_complementary():
    """Lying twin B: two splits are not one split.

    Face identity is per MINT. Two producers that each own a genuine partition
    say nothing about each other's arms, so stamping one arm from each must not
    buy an exclusion neither producer testified to.
    """
    left_guard, right_guard = _shape_opaque_pair()
    left_face, _ = partition(("twin-owner", "first-split"))
    right_face, _ = partition(("twin-owner", "second-split"))

    exits = ExitSet(
        (
            Completed(left_guard, "then-value", frozenset({left_face})),
            Completed(right_guard, "else-value", frozenset({right_face})),
        )
    )

    with pytest.raises(ExitSetFactoringGap):
        exits.factor_completed()


def test_same_partition_same_side_is_not_an_exclusion():
    """Lying twin C: both arms on the SAME face prove nothing.

    A partition token alone must not be mistaken for exclusivity — it is the
    pair (partition, differing side) that carries the proof.
    """
    left_guard, right_guard = _shape_opaque_pair()
    face, _ = partition(("twin-owner", "one-split"))

    exits = ExitSet(
        (
            Completed(left_guard, "a", frozenset({face})),
            Completed(right_guard, "b", frozenset({face})),
        )
    )

    with pytest.raises(ExitSetFactoringGap):
        exits.factor_completed()


def test_guarded_stamps_the_face_it_is_given_and_nothing_else():
    """The door producers use: ``.guarded(guard, face)`` carries testimony.

    Without a face argument the restriction is not a partition claim, so no
    testimony appears. That default is what keeps unrelated arms loud.
    """
    condition = _pred("c")
    then_face, else_face = partition(("IfSugarLike", "site", condition))

    faced = ExitSet.completed("v").guarded(condition, then_face)
    assert faced.exits[0].faces == frozenset({then_face})

    plain = ExitSet.completed("v").guarded(condition)
    assert plain.exits[0].faces == frozenset()

    joined = faced.union(
        ExitSet.completed("w").guarded(not_(condition), else_face)
    )
    # The join is factorable because the producer testified, not because the
    # guards happen to be spelled as negations of each other.
    factored = joined.factor_completed()
    assert len([e for e in factored.exits if isinstance(e, Completed)]) == 1


def test_a_disjoining_merge_keeps_every_side_either_contributor_could_be_on():
    """A merged arm holds under a DISJUNCTION, so its SIDES union.

    LAW CHANGED ON THE RECORD. This arm used to assert
    `merged.exits[0].faces == frozenset()`: a merge of two arms on different
    sides of one split kept nothing. That was a conservative approximation, not
    the truth. The merged arm holds wherever either contributor did, so what is
    actually known is "on one of these two sides, and no other" — a weaker
    statement than either contributor made, and a strictly stronger one than
    silence.

    Dropping it had a measured cost: it is why wiring a producer could not close
    a merged-arm refusal. The producer would mint `range` and `single`, the
    merge would erase both, and the arm would arrive unstamped no matter how
    well the producer testified. Testimony that cannot survive the wire is not
    propagation.

    The reason the old assertion existed is preserved exactly, and is pinned by
    the arm below: a merged arm must never claim to be on ONE named side.
    """
    condition = _pred("c")
    left_face, right_face = partition(("merge-owner", condition))

    merged = ExitSet(
        (
            Completed(condition, "same", frozenset({left_face})),
            Completed(not_(condition), "same", frozenset({right_face})),
        )
    ).normalize()

    assert len(merged.exits) == 1
    assert merged.exits[0].faces == frozenset({left_face, right_face})


def test_a_merged_arm_is_not_exclusive_with_either_side_it_came_from():
    """THE LYING TWIN for the union, and the reason the old rule was written.

    The danger the intersection was guarding against is that an arm reachable on
    EITHER side of a split ends up claiming one named side, forging an exclusion
    the producer never gave. Carrying both sides does not forge it, because
    `_faces_exclusive` asks for DISJOINT side sets: `{c, not c}` overlaps `{c}`
    and overlaps `{not c}`, so the merged arm is provably apart from neither.

    Without this arm, a union looks like a free upgrade. With it, the union is
    only sound because the prover reads sets.
    """
    condition = _pred("c")
    left_face, right_face = partition(("merge-owner", condition))
    both = frozenset({left_face, right_face})

    assert not _faces_exclusive(both, frozenset({left_face}))
    assert not _faces_exclusive(both, frozenset({right_face}))
    assert not _faces_exclusive(both, both)
    # ...and it still separates from a side of the SAME split it cannot be on.
    a, b, c = partition_family(("three", "way"), ("a", "b", "c"))
    assert _faces_exclusive(frozenset({a, b}), frozenset({c}))
    assert not _faces_exclusive(frozenset({a, b}), frozenset({b, c}))


def test_a_merge_drops_a_split_only_one_contributor_named():
    """DISCRIMINATING. Union is per SHARED partition, never across all faces.

    A plain `left | right` would let an arm inherit a face from a split the
    other contributor never mentioned — the merged arm would claim to lie on a
    side of a partition it may be entirely outside. Only splits both arms spoke
    about survive.
    """
    condition = _pred("c")
    mine, _other = partition(("mine", condition))
    theirs, _ = partition(("theirs", condition))

    merged = ExitSet(
        (
            Completed(condition, "same", frozenset({mine})),
            Completed(not_(condition), "same", frozenset({theirs})),
        )
    ).normalize()

    assert merged.exits[0].faces == frozenset()


def test_a_merge_whose_arms_agree_KEEPS_the_face_they_share():
    """The other half of the intersection law, and it was unpinned.

    The rule is `prior.faces & exit_.faces` -- keep exactly what BOTH
    contributors carried. The twin above pins only the case where they carry
    DIFFERENT faces, where the intersection is empty. That case is also what
    "clear the stamps when merging" describes, and the two readings are not the
    same rule: `frozenset()` and `&` agree on disagreeing arms and disagree
    here. A merge of two arms that lie on the SAME side of one split is still
    entirely on that side, and the testimony survives.

    THIS IS THE STEP `merged_arm` RESTS ON. `FactoringGapClassification`
    declares an `UNSTAMPED` gap with `merged_arm=True` to be correct output
    rather than remaining work, on the reasoning that a face minted by wiring
    the producer "would be minted and then intersected away". That is true
    exactly when the merge's contributors would receive DIFFERENT faces. This
    arm exhibits the shape where it is false -- same face, face survives -- so
    the reasoning is a prediction about which shape a given site has, not a
    theorem about merges. Losing this half would make the prediction look
    unconditional, which is why it needs its own red.
    """
    condition = _pred("c")
    one_side, _other_side = partition(("merge-owner", condition))

    merged = ExitSet(
        (
            Completed(condition, "same", frozenset({one_side})),
            Completed(_pred("q"), "same", frozenset({one_side})),
        )
    ).normalize()

    assert len(merged.exits) == 1
    assert merged.exits[0].faces == frozenset({one_side}), (
        "a merge of two arms on the SAME side of one split dropped the face "
        "they both carried: the rule is intersection, not clearing"
    )
    assert getattr(merged.exits[0].guard, "kind", None) == "or"


def test_conjoining_composition_accumulates_both_arms_testimony():
    """``sequence`` conjoins guards, so the result carries both face sets."""
    condition = _pred("c")
    outer = _pred("d")
    face, _ = partition(("prefix-owner", condition))
    tail_face, _ = partition(("tail-owner", outer))

    prefix = ExitSet.completed("v").guarded(condition, face)
    result = prefix.sequence(
        lambda value: ExitSet.completed(value + "!").guarded(outer, tail_face)
    )

    assert result.exits[0].faces == frozenset({face, tail_face})


def test_shape_level_exclusion_still_factors_without_testimony():
    """The sound shape prover is retained, not replaced.

    Arms whose producer never minted a partition but whose guards ARE one
    literal apart still factor exactly as before this change.
    """
    condition = _pred("c")

    factored = ExitSet(
        (
            Completed(condition, "a"),
            Completed(not_(condition), "b"),
        )
    ).factor_completed()

    assert len([e for e in factored.exits if isinstance(e, Completed)]) == 1


def test_single_completed_arm_is_returned_untouched():
    exits = ExitSet((Completed(true_guard(), "only"),))
    assert exits.factor_completed() is exits


def test_testimony_does_not_change_what_an_exit_denotes():
    """Faces are testimony ABOUT an arm, never part of its meaning.

    Two arms with the same guard and destination are the same exit whether or
    not a producer stamped one of them. Letting faces into ``__eq__`` silently
    changed ``normalize``'s merge, ``collapse``'s fixpoint check, and every
    caller that compares an ExitSet against an expected one — carried testimony
    must be free to ride along without moving denotation.
    """
    condition = _pred("c")
    face, _ = partition(("owner", condition))

    bare = Completed(condition, "v")
    stamped = Completed(condition, "v", frozenset({face}))

    assert bare == stamped
    assert hash(bare) == hash(stamped)
    assert repr(bare) == repr(stamped)
    assert stamped.faces == frozenset({face})

    # And the whole set compares equal, which is what collapse/normalize use.
    assert ExitSet((bare,)) == ExitSet((stamped,))


def test_partition_owner_identity_is_reproducible_not_allocation_based():
    """Two mints for the SAME owner agree; different owners do not.

    Face tokens ride on in-memory exits and never reach emitted FOL, but they
    must still be a function of what the producer owns — a token that changed
    with allocation would make the same lift testify differently twice.
    """
    first_a, first_b = partition(("owner", "split"))
    second_a, second_b = partition(("owner", "split"))
    assert first_a == second_a and first_b == second_b
    assert first_a != first_b

    other_a, _ = partition(("owner", "other-split"))
    assert other_a != first_a
