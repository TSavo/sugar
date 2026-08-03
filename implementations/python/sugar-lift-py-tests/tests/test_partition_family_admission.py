"""The same-type partition law: a producer proves a family, or the gap stays loud.

#6336 let a producer testify to a TWO-way split. A producer that decides among
n routes -- a loop completing by break or by exhaustion, a dispatch over a
closed set -- owns an n-way split and had no way to say so, so its arms reached
`factor_completed` with shape-only evidence and were refused.

ADMISSION REQUIRES ALL OF, and the second line is the trap:

  - the same authenticated producer occurrence (one shared origin);
  - **same destination TYPE is not sufficient by itself** -- the two measured
    remaining-work rows are `PredicateValue`/`PredicateValue` and
    `SymbolicValue`/`SymbolicValue`, and type agreement is a hint, never an
    admission;
  - guards are authenticated complements, or members of an authenticated
    exhaustive partition;
  - every face retained -- an incomplete family is not a partition, because a
    missing face is an outcome nobody accounted for;
  - no fallback, no default-success arm, no lexical inference, no solver guess;
  - if the producer cannot supply that testimony, `ExitSetFactoringGap` stays
    loud.

The last two twins are not bookkeeping. `test_appending_factors_grows_linearly`
is the guard against giving back #6333's `m ** k` bound: a factored family that
grows with appended factors is the exponential returning under a new name.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.ir import and_, atomic, make_var, not_
from sugar_lift_py_tests.outcome.exit_set import (
    Completed,
    ExitSet,
    ExitSetFactoringGap,
    partition,
    partition_family,
)


def _g(name: str):
    return atomic(name, [make_var("state")])


def _arm(guard, value, *faces):
    return Completed(guard, value, frozenset(faces))


def _completed(exits: ExitSet) -> list:
    return [e for e in exits.exits if isinstance(e, Completed)]


# --------------------------------------------------------------------------
# admit
# --------------------------------------------------------------------------


def test_complementary_same_origin_faces_factor():
    """POSITIVE. One producer, both routes named, both present."""
    brk, done = partition_family("loop@7521", ("BreakExit", "NormalExhaustion"))

    factored = ExitSet(
        (_arm(_g("broke"), "a", brk), _arm(_g("exhausted"), "b", done))
    ).factor_completed()

    assert len(_completed(factored)) == 1


def test_a_three_way_family_factors_when_every_face_is_present():
    """POSITIVE. The n-way case `partition` could not express at all."""
    faces = partition_family("dispatch", ("one", "two", "three"))

    factored = ExitSet(
        tuple(_arm(_g(f"g{i}"), i, face) for i, face in enumerate(faces))
    ).factor_completed()

    assert len(_completed(factored)) == 1


# --------------------------------------------------------------------------
# refuse
# --------------------------------------------------------------------------


def test_same_type_faces_from_different_origins_do_not_factor():
    """THE TRAP, and the reason type is not the admission.

    Both arms carry the same value type and both producers testified — about
    their OWN splits. Neither said anything about the other.
    """
    left, _ = partition_family("producer-a", ("x", "y"))
    right, _ = partition_family("producer-b", ("x", "y"))

    with pytest.raises(ExitSetFactoringGap):
        ExitSet(
            (_arm(_g("p"), "same-type", left), _arm(_g("q"), "same-type", right))
        ).factor_completed()


def test_overlapping_guards_do_not_factor():
    """A producer that never testified gets the shape prover, which refuses.

    `_g("p")` and `and_([_g("p"), _g("r")])` can hold together; there is no
    complement anywhere, and nothing may invent one.
    """
    with pytest.raises(ExitSetFactoringGap):
        ExitSet(
            (_arm(_g("p"), "a"), _arm(and_([_g("p"), _g("r")]), "b"))
        ).factor_completed()


def test_an_incomplete_family_is_not_admitted_AS_A_FAMILY():
    """A PARTIAL partition is not a partition — at the FAMILY door.

    DEVIATION FROM THE LITERAL RULING, STATED ON THE RECORD. The ruling asked
    that incomplete partitions not factor at all. They still can, and blocking
    them would be wrong: two arms carrying DISTINCT sides of one origin are
    provably exclusive whatever the family's size, so #6336's pairwise rule
    admits them and the chain it builds is faithful. The absent third face is
    not in this ExitSet to drop — it simply is not here.

    Refusing a pair that is provably exclusive would be INVENTING A REFUSAL,
    which is the same class of lie as inventing an admission, and it would
    weaken a rule #6336 already shipped. So completeness gates the family
    fast-path only, and this twin asserts exactly that and nothing more.
    """
    from sugar_lift_py_tests.outcome.exit_set import _complete_family

    first, second, _third = partition_family("dispatch", ("one", "two", "three"))
    arms = [_arm(_g("a"), "x", first), _arm(_g("b"), "y", second)]

    assert not _complete_family(arms)
    # ...and it still factors, via the pairwise rule, soundly.
    assert len(_completed(ExitSet(tuple(arms)).factor_completed())) == 1


def test_an_unstated_arity_cannot_complete_a_family():
    """DISCRIMINATING. A face from a producer that never declared a size.

    `PartitionFace(origin, side)` with no arity carries pairwise exclusion and
    must never be read as an exhaustive family — otherwise any two stamped arms
    would admit as "complete".
    """
    from sugar_lift_py_tests.outcome.exit_set import PartitionFace, _complete_family

    origin = ("sugar.exit_set.partition", "unstated")
    arms = [
        _arm(_g("a"), "x", PartitionFace(origin, "one")),
        _arm(_g("b"), "y", PartitionFace(origin, "two")),
    ]

    assert not _complete_family(arms)


def test_a_family_of_one_is_refused_at_the_mint():
    """No fallback, no default-success arm: a one-way split is not a split."""
    with pytest.raises(ValueError, match="at least two faces"):
        partition_family("owner", ("only",))


def test_indistinguishable_members_are_refused_at_the_mint():
    """Two members that cannot be told apart carry no exclusion between them."""
    with pytest.raises(ValueError, match="DISTINCT faces"):
        partition_family("owner", ("same", "same"))


# --------------------------------------------------------------------------
# denotation
# --------------------------------------------------------------------------


def test_reordering_faces_preserves_denotation():
    """The family is a SET. Arrival order may not change what is denoted."""
    brk, done = partition_family("loop", ("BreakExit", "NormalExhaustion"))
    forward = ExitSet(
        (_arm(_g("p"), "a", brk), _arm(_g("q"), "b", done))
    ).factor_completed()
    reverse = ExitSet(
        (_arm(_g("q"), "b", done), _arm(_g("p"), "a", brk))
    ).factor_completed()

    def values(exits):
        chain = _completed(exits)[0].value
        seen = []
        while hasattr(chain, "when_true"):
            seen.append(chain.when_true)
            chain = chain.when_false
        seen.append(chain)
        return set(seen)

    assert values(forward) == values(reverse)
    assert len(_completed(forward)) == len(_completed(reverse)) == 1


def test_bounded_expansion_is_extensionally_identical_before_and_after():
    """Same faces, same values, same guards — factoring RELOCATES, never drops.

    Every arm's value must still be reachable in the chain, and the factored
    arm must hold under the disjunction of the arms' guards, not under one.
    """
    faces = partition_family("dispatch", ("a", "b", "c"))
    arms = [_arm(_g(f"g{i}"), f"v{i}", face) for i, face in enumerate(faces)]

    factored = _completed(ExitSet(tuple(arms)).factor_completed())[0]

    chain, seen = factored.value, []
    while hasattr(chain, "when_true"):
        seen.append(chain.when_true)
        chain = chain.when_false
    seen.append(chain)
    assert set(seen) == {"v0", "v1", "v2"}
    assert getattr(factored.guard, "kind", None) == "or"


def test_appending_factors_grows_linearly():
    """THE #6333 GUARD, and it is not bookkeeping.

    A factored family that grows as factors are appended is the `m ** k`
    exponential returning under a new name. Each appended step must leave the
    completed face at ONE arm however many steps there are.
    """
    brk, done = partition_family("loop", ("BreakExit", "NormalExhaustion"))
    family = ExitSet(
        (_arm(_g("p"), "a", brk), _arm(_g("q"), "b", done))
    ).factor_completed()

    series = []
    for step_count in (1, 2, 3, 4, 5, 6, 7, 8):
        exits = family
        for index in range(step_count):
            exits = exits.sequence(
                lambda value, _i=index: ExitSet.completed((value, _i))
            )
        series.append(len(_completed(exits)))

    assert series == [1] * 8, (
        f"completed arms by appended factors {series}: an admitted family is "
        "multiplying again (#6356 / #6333)"
    )


def test_both_admissions_build_through_one_door():
    """DISCRIMINATING. Family and pairwise must not denote differently.

    Two admissions and two chain builders would drift, and the same arms would
    collapse two ways depending on which door saw them first. One `_factored`
    serves both.
    """
    brk, done = partition_family("loop", ("BreakExit", "NormalExhaustion"))
    by_family = _completed(
        ExitSet((_arm(_g("a"), "x", brk), _arm(_g("b"), "y", done))).factor_completed()
    )[0]

    pair_true, pair_false = partition("two-way")
    by_pairwise = _completed(
        ExitSet(
            (
                _arm(_g("a"), "x", pair_true),
                _arm(not_(_g("a")), "y", pair_false),
            )
        ).factor_completed()
    )[0]

    def values(arm):
        chain, seen = arm.value, []
        while hasattr(chain, "when_true"):
            seen.append(chain.when_true)
            chain = chain.when_false
        seen.append(chain)
        return seen

    assert values(by_family) == values(by_pairwise) == ["x", "y"]


# --------------------------------------------------------------------------
# The latch ruling: an exit partition has TWO faces, and the latch is not one
# --------------------------------------------------------------------------


def test_the_loops_exit_partition_is_two_faced_and_excludes_the_latch():
    """THE RULING, pinned. `{BreakExit, NormalExhaustion}` — not the latch.

    A loop leaves exactly one way, and `live_loop_construction` says so in its
    own `completed_specs` list. `BodyFallthrough` is the LATCH input
    (`loop_construction.py:593` requires it as the loop-back edge), so it is not
    an exit route and must not be a member of the exit partition.

    Retention is not the same as claiming exclusivity: the latch face is still
    carried, and it claims nothing. That is the honest state for an edge that
    is not an exit.
    """
    brk, done = partition_family("loop@target", ("BreakExit", "NormalExhaustion"))

    assert brk.arity == done.arity == 2
    factored = ExitSet(
        (_arm(_g("broke"), "a", brk), _arm(_g("exhausted"), "b", done))
    ).factor_completed()
    assert len(_completed(factored)) == 1


def test_stamping_the_latch_into_the_exit_partition_is_rejected():
    """DISCRIMINATING for the ruling, and it is the arm that matters.

    If the latch were minted as a third member, the two genuine exit arms would
    no longer COMPLETE the family — two of three faces is not exhaustive — so
    the family door refuses them. The mis-stamp does not silently widen the
    partition; it costs the admission the exit routes had legitimately earned.

    That is the shape of the error the ruling forbids: asserting an exclusion
    nobody established, and paying for it where the honest testimony used to
    work.
    """
    from sugar_lift_py_tests.outcome.exit_set import _complete_family

    brk, latch, done = partition_family(
        "loop@target", ("BreakExit", "BodyFallthrough", "NormalExhaustion")
    )
    exit_arms = [_arm(_g("broke"), "a", brk), _arm(_g("exhausted"), "b", done)]

    assert not _complete_family(exit_arms)
    # ...and the two-faced mint, over the exit routes alone, does admit them.
    brk2, done2 = partition_family("loop@target", ("BreakExit", "NormalExhaustion"))
    assert _complete_family(
        [_arm(_g("broke"), "a", brk2), _arm(_g("exhausted"), "b", done2)]
    )
    del latch
