"""The conditional binding read names its own split, and the merge keeps it.

THE PRODUCER OWNED EVIDENCE AND DID NOT SPEAK. `read_binding`'s
`GuardedProjection` branch is the reader for every conditionally-bound name: the
value is one thing under an authenticated branch result and another under its
negation. That is a two-way partition this producer DECIDES, and it guarded both
arms with `.guarded(guard)` / `.guarded(not_(guard))` carrying no face at all.
Downstream `factor_completed` therefore had nothing but guard SHAPE, and shape
decays -- the moment a prefix conjoins or a sibling merges, a real partition
stops being provable.

Same shape as the loop before #6375: the producer already named its routes
(`when_true` / `when_false` over `state.slot`) and simply never minted. Wiring
it is a mint and two face arguments; no admission rule changes, and
`factor_completed` refuses exactly when it refused before.

WHY THE MINT IS OWNED BY THE SLOT AND NOT THE READ SITE. Two reads of the same
conditional binding are governed by the SAME branch outcome. Keying the
partition by read site would mint two unrelated tokens for one decision, and
arms that genuinely exclude each other would look like arms from different
splits -- the `STAMPED_DISJOINT` shape, which proves nothing. `partition`
addresses by content, so slot-keyed tokens are reproducible across reads rather
than allocation-based.

EVERY TRUTHFUL ARM HERE HAS A LYING ONE. A carrier that mints faces is exactly
the change that can buy a green by handing out testimony nobody earned, so each
arm that says "this factors now" is paired with one that says "and this still
does not".
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.ir import and_, atomic, not_, or_
from sugar_lift_py_tests.outcome.exit_set import (
    Completed,
    ExitSet,
    ExitSetFactoringGap,
    _are_exclusive,
    _faces_exclusive,
)
from sugar_lift_py_tests.sugar.binding_projection import GuardedProjection
from sugar_lift_py_tests.sugar.guarded_binding_read_sugar import read_binding
from sugar_source_tree.binding_state import BranchResultSlot


class _Value:
    """A leaf binding state that desugars to one completed arm.

    `read_binding` treats a `Sugar` state as "already reduced", so this is the
    smallest thing that can sit on a branch without dragging a source file in.
    """

    def __init__(self, value):
        self.value = value

    def desugar(self, ctx=None):
        from sugar_lift_py_tests.outcome import Complete

        return Complete(self.value)


# `read_binding` dispatches on `Sugar`, so the leaf must register as one.
from sugar_lift_py_tests.sugar.sugar_base import Sugar  # noqa: E402

Sugar.register(_Value)


def _read(slot_id: str, *, site="site-1", then="then-value", other="else-value"):
    """Drive the carrier directly, the way #6375's file drives the loop one.

    `site` is a real parameter, not a placeholder: the arm below that pins the
    mint to the SLOT is only able to see a read-site-keyed mint if two reads
    differ in it. Holding it constant made that control silent -- measured, not
    supposed: keying the partition by `read_site` fired nothing at all until
    this argument existed.
    """
    return read_binding(
        GuardedProjection(
            BranchResultSlot(slot_id), _Value(then), _Value(other)
        ),
        read_name="chosen",
        read_site=site,
        ctx=None,
    )


def _completed(exits):
    return [e for e in exits.exits if isinstance(e, Completed)]


def _faces_of(exit_):
    return exit_.faces


def test_the_read_stamps_both_arms_of_the_binding_it_split():
    """POSITIVE, and the whole point: the arms arrive carrying testimony.

    Before the wiring every arm here had `faces == frozenset()`, so the split
    the reader owns was invisible to anything downstream.
    """
    arms = _completed(_read("slot-a"))

    assert len(arms) == 2
    assert all(_faces_of(arm) for arm in arms), (
        "the conditional binding read minted no partition testimony: the "
        "producer owns this split and must say so"
    )


def test_the_two_arms_are_opposite_sides_of_ONE_split():
    """POSITIVE. One partition, two sides -- not two unrelated tokens.

    Two tokens would classify as STAMPED_DISJOINT downstream, which proves
    nothing at all, and would still read as "the producer testified".
    """
    left, right = (_faces_of(a) for a in _completed(_read("slot-a")))

    assert {f.partition for f in left} == {f.partition for f in right}
    assert _faces_exclusive(left, right), (
        "the two arms of one conditional binding must be provably exclusive "
        "from carried testimony alone"
    )


def test_the_stamped_arms_factor_when_a_MERGE_has_hidden_the_exclusion():
    """THE TOOTH, and the live condition is a merge, not a prefix.

    A conjunctive prefix does NOT hide anything -- `_conjuncts` flattens, so
    `_are_exclusive` still sees `g` against `not g` one literal deep. That was
    measured here rather than assumed, and the first draft of this arm asserted
    the opposite and failed.

    The shape that genuinely hides an exclusion is the DISJUNCTION `normalize`
    writes when it merges two equal destinations: `g` against `or(not g, q)`
    really can hold together as far as shape is concerned. That is the arm the
    corpus rows are shaped like, and the reason a wired producer is worth
    anything -- carried testimony reads through it.
    """
    arms = _completed(_read("slot-a"))
    merged_guard = or_([arms[1].guard, atomic("sibling", [])])

    hidden = ExitSet(
        (
            Completed(arms[0].guard, arms[0].value, _faces_of(arms[0])),
            Completed(merged_guard, arms[1].value, _faces_of(arms[1])),
        )
    )
    # Shape alone cannot separate these...
    assert not _are_exclusive(hidden.exits[0].guard, hidden.exits[1].guard)
    # ...and the producer's own testimony can.
    assert len(_completed(hidden.factor_completed())) == 1


def test_the_same_slot_read_twice_mints_the_SAME_partition():
    """POSITIVE. The mint is owned by the branch decision, not by the read.

    Two reads of one conditional binding are governed by the same outcome. If
    the token were keyed by read site, arms from the two reads would look like
    arms of unrelated splits and prove nothing about each other.
    """
    first = _completed(_read("slot-a", site="read-here"))
    again = _completed(_read("slot-a", site="read-somewhere-else"))

    assert _faces_exclusive(_faces_of(first[0]), _faces_of(again[1])), (
        "two reads of ONE conditional binding minted unrelated partitions: the "
        "mint is keyed by the read site instead of the branch slot"
    )


def test_two_unrelated_conditional_bindings_do_not_exclude_each_other():
    """LYING TWIN. Different slots are different splits.

    This fires if the mint is keyed by anything coarser than the slot -- a
    per-function or per-file token would make every conditional binding in a
    function look mutually exclusive.
    """
    first = _completed(_read("slot-a"))
    second = _completed(_read("slot-b"))

    assert not _faces_exclusive(_faces_of(first[0]), _faces_of(second[1]))
    assert not _faces_exclusive(_faces_of(first[1]), _faces_of(second[0]))


def test_arms_on_the_SAME_side_are_still_refused():
    """LYING TWIN. A partition token is not exclusivity; the SIDE carries it.

    Reusing one arm's face for both arms is the cheapest way to fake a green,
    and it is what `factor_completed` must keep refusing.
    """
    arms = _completed(_read("slot-a"))
    one_side = _faces_of(arms[0])

    with pytest.raises(ExitSetFactoringGap):
        ExitSet(
            tuple(
                Completed(atomic(f"g{i}", []), arm.value, one_side)
                for i, arm in enumerate(arms)
            )
        ).factor_completed()


def test_the_refusal_still_fires_for_a_producer_that_owns_no_split():
    """LYING TWIN. The door did not widen.

    Nothing in this change touches when `factor_completed` refuses. Two arms
    nobody testified about still cannot be factored, whatever their shape.
    """
    left = atomic("p", [])
    right = or_([not_(left), atomic("q", [])])

    with pytest.raises(ExitSetFactoringGap):
        ExitSet(
            (Completed(left, "a"), Completed(right, "b"))
        ).factor_completed()
