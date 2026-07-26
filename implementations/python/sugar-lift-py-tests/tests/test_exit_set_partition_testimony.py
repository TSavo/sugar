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

from dataclasses import dataclass

import pytest

from sugar_lift_py_tests.floor.branch_result_coordinate import branch_result_guard
from sugar_lift_py_tests.ir import and_, atomic, not_, or_
from sugar_lift_py_tests.outcome.exit_set import (
    Completed,
    ExitSet,
    ExitSetFactoringGap,
    partition,
    true_guard,
)
from sugar_lift_py_tests.outcome.exit_set import _are_exclusive
from sugar_lift_py_tests.sugar.binding_projection import GuardedProjection
from sugar_lift_py_tests.sugar.guarded_binding_read_sugar import read_binding
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_source_tree.binding_state import BranchResultSlot


def _pred(name: str):
    return atomic(name, [])


def _path(*faces):
    return frozenset({frozenset(faces)})


@dataclass(frozen=True)
class _PartitionedLeaf(Sugar):
    value: object
    guard: object
    face: object

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        del ctx
        return ExitSet.completed(self.value).guarded(self.guard, self.face)


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


def test_guarded_projection_equal_value_merge_keeps_alternative_path_testimony():
    """Truthful twin: the real producer merge must not erase its alternatives.

    The two binding faces read the same value, so ``read_binding`` normalizes
    them into one destination. Each face already carries a different outer
    partition. A later sibling is opposite to both outer faces, making every
    cross-path pair exclusive even though no formula-level complement remains
    visible.
    """
    q_guard = _pred("q")
    r_guard = _pred("r")
    q_true, q_false = partition(("outer", "q"))
    r_true, r_false = partition(("outer", "r"))
    slot = BranchResultSlot("branch-result:truthful-twin")
    state = GuardedProjection(
        slot=slot,
        when_true=_PartitionedLeaf("same", q_guard, q_true),
        when_false=_PartitionedLeaf("same", r_guard, r_true),
    )

    merged = read_binding(
        state,
        read_name="value",
        read_site="truthful-twin-site",
        ctx=None,
    )

    assert len(merged.exits) == 1
    producer_true, producer_false = partition(
        (
            "GuardedBindingRead",
            slot,
            "truthful-twin-site",
            branch_result_guard(slot, "truthful-twin-site"),
        )
    )
    assert merged.exits[0].faces == frozenset(
        {
            frozenset({producer_true, q_true}),
            frozenset({producer_false, r_true}),
        }
    )

    sibling = (
        ExitSet.completed("sibling")
        .guarded(not_(q_guard), q_false)
        .guarded(not_(r_guard), r_false)
    )
    assert not _are_exclusive(merged.exits[0].guard, sibling.exits[0].guard)

    factored = merged.union(sibling).factor_completed()

    assert len(factored.exits) == 1


def test_formula_complements_without_producer_testimony_still_refuse():
    """Lying twin: spelling ``g``/``not g`` is not branch authority."""
    guard = _pred("looks-complementary")
    exits = ExitSet(
        (
            Completed(guard, "left"),
            Completed(not_(guard), "right"),
        )
    )

    with pytest.raises(ExitSetFactoringGap):
        exits.factor_completed()


def test_owned_partition_makes_the_factoring_gap_unconstructable():
    """Truthful twin: testimony carried, shape unreadable, no gap."""
    left_guard, right_guard = _shape_opaque_pair()
    left_face, right_face = partition(("twin-owner", "one-split"))

    exits = ExitSet(
        (
            Completed(left_guard, "then-value", _path(left_face)),
            Completed(right_guard, "else-value", _path(right_face)),
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
            Completed(left_guard, "then-value", _path(left_face)),
            Completed(right_guard, "else-value", _path(right_face)),
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
            Completed(left_guard, "a", _path(face)),
            Completed(right_guard, "b", _path(face)),
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
    assert faced.exits[0].faces == _path(then_face)

    plain = ExitSet.completed("v").guarded(condition)
    assert plain.exits[0].faces == _path()

    joined = faced.union(
        ExitSet.completed("w").guarded(not_(condition), else_face)
    )
    # The join is factorable because the producer testified, not because the
    # guards happen to be spelled as negations of each other.
    factored = joined.factor_completed()
    assert len([e for e in factored.exits if isinstance(e, Completed)]) == 1


def test_disjoining_merge_keeps_faces_as_alternative_paths():
    """A merged arm preserves alternatives without conjoining their faces."""
    condition = _pred("c")
    left_face, right_face = partition(("merge-owner", condition))

    merged = ExitSet(
        (
            Completed(condition, "same", _path(left_face)),
            Completed(not_(condition), "same", _path(right_face)),
        )
    ).normalize()

    assert len(merged.exits) == 1
    assert merged.exits[0].faces == frozenset(
        {frozenset({left_face}), frozenset({right_face})}
    )


def test_conjoining_a_face_discards_the_contradictory_alternative():
    condition = _pred("c")
    left_face, right_face = partition(("merge-owner", condition))
    merged = ExitSet(
        (
            Completed(condition, "same", _path(left_face)),
            Completed(not_(condition), "same", _path(right_face)),
        )
    ).normalize()

    restricted = merged.guarded(condition, left_face)

    assert restricted.exits[0].faces == _path(left_face)


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

    assert result.exits[0].faces == _path(face, tail_face)


def test_shape_level_exclusion_does_not_replace_producer_testimony():
    """Formula appearance is diagnostic only, never factoring authority."""
    condition = _pred("c")

    with pytest.raises(ExitSetFactoringGap):
        ExitSet(
            (
                Completed(condition, "a"),
                Completed(not_(condition), "b"),
            )
        ).factor_completed()


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
    stamped = Completed(condition, "v", _path(face))

    assert bare == stamped
    assert hash(bare) == hash(stamped)
    assert repr(bare) == repr(stamped)
    assert stamped.faces == _path(face)

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
