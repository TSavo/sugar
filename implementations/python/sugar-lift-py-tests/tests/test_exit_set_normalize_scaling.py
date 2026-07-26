"""`ExitSet.normalize` is bucket-indexed: same answer, near-linear comparisons.

Two obligations, and they are different in kind:

1. EQUIVALENCE. The bucketed normalizer must produce byte-identical output to the
   all-pairs scan it replaced, for every input -- same exits, same order, same
   merged guards. That is checked against a reference implementation of the OLD
   algorithm kept in this file, so the comparison is against the real prior
   behaviour rather than against what someone remembers it did.

2. SCALING. Comparisons must stop growing with the square of the arm count. The
   old scan at ~775 arms is ~600k comparisons; that is what pushed
   `core/generic.py` past the timeout floor.

The scaling assertion counts COMPARISONS, not wall time. This box runs four
fleets at load ~14, so a wall-clock threshold here would measure the box and
would fail or pass for reasons that have nothing to do with the algorithm.
Comparison counts are load-independent and are the thing the change is actually
about.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.ir import Formula, atomic, make_var, not_
from sugar_lift_py_tests.outcome.exit_set import (
    Completed,
    ExitSet,
    Halted,
    _is_false,
    _or_guards,
    normalize_stats,
    true_guard,
)


def _reference_normalize(exit_set: ExitSet) -> ExitSet:
    """The ORIGINAL all-pairs scan, verbatim, as the equivalence oracle."""
    merged: list[object] = []
    for exit_ in exit_set.exits:
        if _is_false(exit_.guard):
            continue
        for index, prior in enumerate(merged):
            same_completed = (
                isinstance(exit_, Completed)
                and isinstance(prior, Completed)
                and exit_.value == prior.value
            )
            same_halted = (
                isinstance(exit_, Halted)
                and isinstance(prior, Halted)
                and exit_.effect == prior.effect
                and exit_.state == prior.state
            )
            if same_completed:
                merged[index] = Completed(
                    _or_guards(prior.guard, exit_.guard), prior.value
                )
                break
            if same_halted:
                merged[index] = Halted(
                    _or_guards(prior.guard, exit_.guard), prior.effect, prior.state
                )
                break
        else:
            merged.append(exit_)
    return ExitSet(tuple(merged))


def _g(name: str) -> Formula:
    return atomic(name, [make_var("state")])


def _raise(name: str) -> RaiseEffect:
    return RaiseEffect(exception_name=name)


def _arms(count: int, *, distinct: int | None = None) -> tuple[object, ...]:
    """`count` exits over `distinct` destinations, interleaved so merges are real."""
    distinct = count if distinct is None else distinct
    return tuple(
        Completed(_g(f"g{i}"), f"dest{i % distinct}") for i in range(count)
    )


class TestEquivalence:
    """Same answer as the scan, on the shapes that make merging non-trivial."""

    @pytest.mark.parametrize(
        "exits",
        [
            pytest.param((), id="empty"),
            pytest.param(_arms(1), id="single"),
            pytest.param(_arms(8), id="all-distinct"),
            pytest.param(_arms(8, distinct=1), id="all-same-destination"),
            pytest.param(_arms(9, distinct=3), id="interleaved-merges"),
            pytest.param(
                (
                    Completed(_g("a"), "x"),
                    Halted(_g("b"), _raise("ValueError"), "x"),
                    Completed(_g("c"), "x"),
                    Halted(_g("d"), _raise("ValueError"), "x"),
                ),
                id="completed-and-halted-same-payload-stay-separate",
            ),
            pytest.param(
                (
                    Halted(_g("a"), _raise("ValueError"), "s1"),
                    Halted(_g("b"), _raise("ValueError"), "s2"),
                    Halted(_g("c"), _raise("KeyError"), "s1"),
                ),
                id="halted-splits-on-effect-and-state",
            ),
            pytest.param(
                (
                    Completed(not_(true_guard()), "dropped"),
                    Completed(_g("a"), "kept"),
                ),
                id="false-guard-dropped",
            ),
            pytest.param(
                (
                    Completed(_g("a"), "x"),
                    Completed(not_(_g("a")), "x"),
                ),
                id="complement-guards-merge-to-true",
            ),
        ],
    )
    def test_matches_the_all_pairs_scan(self, exits):
        source = ExitSet(tuple(exits))
        assert source.normalize() == _reference_normalize(source)

    def test_output_order_is_first_occurrence(self):
        exits = (
            Completed(_g("a"), "second"),
            Completed(_g("b"), "first"),
            Completed(_g("c"), "second"),
        )
        result = ExitSet(exits).normalize()
        assert [e.value for e in result.exits] == ["second", "first"]
        assert result == _reference_normalize(ExitSet(exits))

    def test_no_arm_disappears(self):
        exits = _arms(40, distinct=7)
        result = ExitSet(exits).normalize()
        assert len(result.exits) == 7
        assert result == _reference_normalize(ExitSet(exits))


class TestUnhashableDestinations:
    """Never a silent drop, never a missed merge -- and the fallback is measured."""

    def test_unhashable_destination_still_merges_and_is_counted(self):
        # A list value cannot be a dict key; the old scan never needed one to be.
        exits = (
            Completed(_g("a"), ["unhashable"]),
            Completed(_g("b"), ["unhashable"]),
            Completed(_g("c"), "hashable"),
        )
        source = ExitSet(exits)
        stats = normalize_stats()
        stats.reset()
        result = source.normalize()
        # The two unhashable destinations are EQUAL, so they must merge -- exactly
        # as the scan did. Bucketing must not turn "cannot hash" into "distinct".
        assert len(result.exits) == 2
        assert result == _reference_normalize(source)
        assert stats.unhashable_destinations >= 1

    def test_hashable_exit_merges_into_an_earlier_unhashable_prior(self):
        """The asymmetry that a naive bucket-only lookup gets wrong.

        A bucket lookup for a hashable exit will never find an unhashable prior,
        because the prior is in no bucket. If the fallback list is not also
        consulted, this silently fails to merge and the ExitSet grows an arm.
        """

        class SometimesHashable:
            def __init__(self, hashable: bool) -> None:
                self.hashable = hashable

            def __eq__(self, other) -> bool:
                return isinstance(other, SometimesHashable)

            def __hash__(self):
                if not self.hashable:
                    raise TypeError("unhashable")
                return 7

        source = ExitSet(
            (
                Completed(_g("a"), SometimesHashable(hashable=False)),
                Completed(_g("b"), SometimesHashable(hashable=True)),
            )
        )
        result = source.normalize()
        assert len(result.exits) == 1, "equal destinations must merge across the fallback"
        assert result == _reference_normalize(source)


class TestCollisionsAreNotEquality:
    def test_same_hash_unequal_destination_stays_separate(self):
        class Colliding:
            def __init__(self, tag: str) -> None:
                self.tag = tag

            def __eq__(self, other) -> bool:
                return isinstance(other, Colliding) and other.tag == self.tag

            def __hash__(self) -> int:
                return 1234  # every instance collides

        source = ExitSet(
            (
                Completed(_g("a"), Colliding("x")),
                Completed(_g("b"), Colliding("y")),
                Completed(_g("c"), Colliding("x")),
            )
        )
        result = source.normalize()
        # Colliding hashes share a bucket; exact comparison still decides.
        assert len(result.exits) == 2
        assert result == _reference_normalize(source)


class TestScaling:
    """Comparisons, not wall time: load-independent and about the algorithm."""

    @pytest.mark.parametrize("arms", [100, 200, 400, 800])
    def test_comparisons_are_near_linear_in_arm_count(self, arms):
        stats = normalize_stats()
        stats.reset()
        ExitSet(_arms(arms)).normalize()
        # All-distinct destinations: the scan did n(n-1)/2 comparisons (800 arms ->
        # 319,600). Bucketed, each exit finds an empty bucket and compares nothing.
        assert stats.comparisons <= arms, (
            f"{arms} arms took {stats.comparisons} comparisons; "
            "bucketing should keep this at or below one per arm"
        )

    def test_growth_is_not_quadratic_across_the_curve(self):
        measured: dict[int, int] = {}
        for arms in (100, 200, 400, 800):
            stats = normalize_stats()
            stats.reset()
            ExitSet(_arms(arms, distinct=arms // 4)).normalize()
            measured[arms] = stats.comparisons
        # Doubling the arms must not quadruple the comparisons. The old scan did
        # exactly that; this is the gate that would catch a regression back to it.
        for small, large in ((100, 200), (200, 400), (400, 800)):
            assert measured[large] <= measured[small] * 3, (
                f"comparisons {measured} grew faster than linear-ish from "
                f"{small} to {large} arms"
            )

    def test_worst_case_single_destination_is_still_linear(self):
        """Every arm to ONE destination -- the densest possible bucket."""
        stats = normalize_stats()
        stats.reset()
        result = ExitSet(_arms(800, distinct=1)).normalize()
        assert len(result.exits) == 1
        # Each exit merges into the single prior on its first comparison.
        assert stats.comparisons <= 800
