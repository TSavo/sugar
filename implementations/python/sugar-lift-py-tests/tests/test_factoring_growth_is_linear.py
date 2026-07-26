"""`factor_completed` keeps sequenced growth LINEAR — and the check can fail.

#6333's defect was `m ** k`: k sequenced steps of m completed arms distributing
into m ** k exit-level arms, because `sequence` appends every exit of the tail
under every completed exit of the prefix. `factor_completed` fixed it by moving
the partition onto the VALUE, so k steps contribute k guarded values to one arm.

WHAT THIS GUARDS, AND WHAT IT DOES NOT. It covers `factor_completed`'s admission
and how a factored family is built: a change there can silently restore the
exponential, and a family that grows as factors are appended is `m ** k` under a
new name.

It does NOT cover what a merged arm RETAINS (#6336/#6420), and an earlier draft
of this docstring claimed it did. Measured, not assumed: reverting `_merge_faces`
to `return frozenset()` -- #6420's rule fully removed, and worse than the
intersection that preceded it -- leaves both tests below GREEN, while
`test_exit_set_partition_testimony.py` reds two. That surface is guarded there,
by `test_a_disjoining_merge_keeps_every_side_either_contributor_could_be_on` and
`test_a_merge_whose_arms_agree_KEEPS_the_face_they_share`.

The reason is structural, and it is the trap below taken one turn further: the
equal-destination merge only fires on EQUAL destinations, and the accumulation
that makes the exponential reachable is exactly what makes every destination
distinct. You cannot have both in one fold -- no accumulation, no exponential;
accumulation, no merge. A retention guard therefore needs its own non-accumulating
fold asserting on FACES RETAINED, because arm count cannot see it: with no
accumulation the count is flat regardless of what the rule does.

THE CONSTRAINT THAT MAKES THIS TEST REAL, and it is not obvious: a fold whose
tail IGNORES the prefix value cannot blow up at all, no matter what the algebra
does. Every path reaches the same destination, the equal-destination merge
collapses them, and the arm count sits flat at m forever. Written that way this
test is green by construction and proves nothing about factoring. It was
measured: the same fold reads a flat 2 at every k without accumulation, and
2/4/16/256/4096 with it. The tail here therefore accumulates onto the prefix
value, so distinct paths reach distinct destinations and the exponential is
actually reachable -- which is what gives the assertion below its teeth.
"""

from __future__ import annotations

from sugar_lift_py_tests.ir import atomic, make_var, not_
from sugar_lift_py_tests.outcome import true_guard
from sugar_lift_py_tests.outcome.exit_set import Completed, ExitSet, partition

_KS = (1, 2, 4, 8, 12)


def _arms_after_k_steps(k: int, *, factor: bool) -> int:
    """k sequenced two-way partitions, each factored before the next or not."""
    exits = ExitSet((Completed(true_guard(), "seed"),))
    for step in range(k):
        left_face, right_face = partition(f"producer-{step}")
        guard = atomic(f"g{step}", [make_var("state")])

        def build(value, guard=guard, lf=left_face, rf=right_face, step=step):
            # ACCUMULATES onto the prefix value -- see the module docstring.
            return ExitSet(
                (
                    Completed(guard, (value, f"a{step}"), frozenset({lf})),
                    Completed(not_(guard), (value, f"b{step}"), frozenset({rf})),
                )
            )

        exits = exits.sequence(build)
        if factor:
            exits = exits.factor_completed()
    return len(exits.exits)


def test_appended_factors_do_not_grow_the_arm_count() -> None:
    """STRICT, not a loose bound. When every step is an admitted partition the
    arm count must not grow with k AT ALL: the partition lives on the value."""
    counts = {k: _arms_after_k_steps(k, factor=True) for k in _KS}
    assert len(set(counts.values())) == 1, counts


def test_lying_the_same_fold_without_factoring_really_does_blow_up() -> None:
    """The discriminator. Without this arm the twin above is a control that
    cannot fail, and a control that cannot fail is worse than no control: it
    reports a law is held by a mechanism that may no longer be running."""
    counts = {k: _arms_after_k_steps(k, factor=False) for k in _KS}
    assert counts[1] == 2
    # Exactly 2 ** k -- #6333's exponential, reachable and measured.
    assert all(counts[k] == 2**k for k in _KS), counts
    assert counts[12] == 4096
