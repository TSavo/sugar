"""The `factoring_gaps` discriminator: remaining work vs correct output (#6356).

One number covered two different things — a producer that owned a partition and
failed to carry the testimony, and a refusal of arms with no exclusion
available. The first is closable work; the second is `factor_completed` doing
its job. A term that mixes correct output with remaining work overstates the
board, so it is split here, off CARRIED TESTIMONY rather than guard shape.

EVERY TEST IS A PAIR, because a classifier is exactly the kind of code that can
look right while calling everything one class. Each positive is followed by a
discriminator that would pass if the classifier had collapsed two kinds
together.

The naming caveat is load-bearing and is asserted, not just documented:
`_are_exclusive` is SOUND-ONLY, so `False` means "not proven", never "proven
false". No classification may claim the arms overlap, and
`test_no_classification_claims_the_arms_overlap` holds that line by name.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.ir import and_, atomic, make_var, not_, or_
from sugar_lift_py_tests.outcome.exit_set import (
    Completed,
    ExitSet,
    ExitSetFactoringGap,
    partition,
)
from sugar_lift_py_tests.outcome.factoring_gap_kind import (
    FactoringGapKind,
    classify_factoring_gap,
)


def _guard(name: str):
    return atomic(name, [make_var("state")])


def _arm(guard, value, faces=frozenset()):
    return Completed(guard, value, faces)


# --------------------------------------------------------------------------
# The four kinds
# --------------------------------------------------------------------------


def test_two_silent_arms_are_unstamped():
    """POSITIVE. No producer testified, so nothing was offered to separate them."""
    left = _arm(_guard("a"), "one")
    right = _arm(_guard("b"), "two")

    assert classify_factoring_gap(left, right).kind is FactoringGapKind.UNSTAMPED


def test_one_silent_arm_is_partly_stamped_not_unstamped():
    """DISCRIMINATING. The silent SIDE is the lead, so it must not read as
    'nobody testified' — one producer did, and the other is the one to look at.
    """
    face, _ = partition("owner")
    left = _arm(_guard("a"), "one", frozenset({face}))
    right = _arm(_guard("b"), "two")

    assert classify_factoring_gap(left, right).kind is FactoringGapKind.PARTLY_STAMPED


def test_shared_partition_same_side_is_stamped_not_separating():
    """POSITIVE. Testimony WAS offered and does not separate these two.

    Wiring more producers cannot help here: the producers that own these arms
    have already spoken.
    """
    face, _ = partition("owner")
    left = _arm(_guard("a"), "one", frozenset({face}))
    right = _arm(_guard("b"), "two", frozenset({face}))

    classification = classify_factoring_gap(left, right)

    assert classification.kind is FactoringGapKind.STAMPED_NOT_SEPARATING
    assert not classification.is_remaining_work


def test_unrelated_partitions_are_stamped_disjoint():
    """DISCRIMINATING. Sharing NO partition is a different fact from sharing one
    and agreeing on the side. Collapsing them would hide that these arms come
    from unrelated splits whose producers never claimed anything about each
    other."""
    left_face, _ = partition("owner-a")
    right_face, _ = partition("owner-b")
    left = _arm(_guard("a"), "one", frozenset({left_face}))
    right = _arm(_guard("b"), "two", frozenset({right_face}))

    assert classify_factoring_gap(left, right).kind is FactoringGapKind.STAMPED_DISJOINT


def test_opposed_faces_never_reach_a_gap_at_all():
    """DISCRIMINATING for the whole file: a separating pair FACTORS.

    If this ever raised, the classifier would be describing refusals that
    should not exist, and every count above would be measuring the wrong set.
    """
    true_face, false_face = partition("owner")
    guard = _guard("a")

    factored = ExitSet(
        (
            _arm(and_([_guard("p"), guard]), "one", frozenset({true_face})),
            _arm(and_([_guard("q"), not_(guard)]), "two", frozenset({false_face})),
        )
    ).factor_completed()

    assert sum(isinstance(e, Completed) for e in factored.exits) == 1


# --------------------------------------------------------------------------
# The merged-arm flag: why "unstamped" is not the same as "closable"
# --------------------------------------------------------------------------


def test_an_unstamped_pair_is_remaining_work():
    """POSITIVE. Nobody testified and no arm was merged: worth wiring."""
    classification = classify_factoring_gap(
        _arm(_guard("a"), "one"), _arm(_guard("b"), "two")
    )

    assert classification.is_remaining_work
    assert not classification.merged_arm


def test_an_unstamped_pair_with_a_merged_arm_is_not_remaining_work():
    """DISCRIMINATING, and it is the whole reason the flag exists.

    #6361 MEASURED an occurrence where wiring the producer changed nothing: the
    face would be minted and then intersected away, because #6336's rule keeps
    only testimony every contributing arm carried when an equal-destination
    merge disjoins guards. Calling that "remaining work" would send the next
    agent down the afternoon that produced the refutation.
    """
    merged = and_([_guard("p"), or_([_guard("a"), _guard("x")])])
    classification = classify_factoring_gap(
        _arm(merged, "one"), _arm(_guard("b"), "two")
    )

    assert classification.kind is FactoringGapKind.UNSTAMPED
    assert classification.merged_arm
    assert not classification.is_remaining_work


def test_the_flag_reads_either_arm():
    """DISCRIMINATING. A merge on the RIGHT arm is the same obstacle.

    Checking only the left would classify half the real occurrences as work.
    """
    merged = and_([_guard("p"), or_([_guard("a"), _guard("x")])])

    assert classify_factoring_gap(
        _arm(_guard("b"), "two"), _arm(merged, "one")
    ).merged_arm


# --------------------------------------------------------------------------
# The honesty line
# --------------------------------------------------------------------------


def test_no_classification_claims_the_arms_overlap():
    """THE NAMING LAW. `_are_exclusive` is sound-only.

    `False` means "not proven", never "proven false". A classification that
    said "overlapping" would be a claim about reachability that nothing here
    measured. Every kind name must describe the EVIDENCE, not the world.
    """
    forbidden = ("overlap", "simultaneous", "reachable", "proven-false")

    for kind in FactoringGapKind:
        assert not any(word in kind.value for word in forbidden), (
            f"{kind.value!r} claims something about the world; _are_exclusive "
            "returning False only means no exclusion was proven (#6356)"
        )


def test_the_refusal_carries_its_arms_so_a_census_never_parses_the_message():
    """The census reads arms, not a repr.

    Re-deriving the pair by parsing the exception's prose is how a measurement
    starts depending on message formatting.
    """
    with pytest.raises(ExitSetFactoringGap) as raised:
        ExitSet((_arm(_guard("a"), "one"), _arm(_guard("b"), "two"))).factor_completed()

    gap = raised.value
    assert gap.left is not None and gap.right is not None
    assert gap.classification().kind is FactoringGapKind.UNSTAMPED


def test_a_gap_without_arms_classifies_as_nothing_rather_than_guessing():
    """DISCRIMINATING. An occurrence with no arms must not default into a kind.

    A classifier that guessed would put uncounted rows into whichever bucket it
    defaulted to, which is exactly how a mixed number is born.
    """
    assert ExitSetFactoringGap("bare message").classification() is None
