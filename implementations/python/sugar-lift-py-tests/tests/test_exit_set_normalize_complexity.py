"""The complexity tooth: normalization work must not be quadratic in arms.

`pandas/core/generic.py` timed out because `ExitSet.normalize` merged by
scanning every prior arm. At 1,317 arms that is 866,586 destination
comparisons for ONE call, and the corpus reproducer reached an upper bound of
13,147,074 comparisons — to merge away 1.9% of arms.

This tooth counts DESTINATION COMPARISONS, not wall time. Wall time on a
shared box measures the box; comparison count measures the algorithm, and it
is the quantity that regressed.

It fails if the merge returns to quadratic growth, and it does not care how
fast the machine is.

Read with `test_exit_set_normalize_identity.py`: that file proves the merge
still computes the same answer, this one proves it stops paying a quadratic
price for it. Neither is sufficient alone — a merge can be fast and wrong, or
correct and unusable.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.ir import atomic, make_var
from sugar_lift_py_tests.outcome.exit_set import Completed, ExitSet

ARM_COUNTS = (100, 200, 400, 800)


class CountingDestination:
    """A destination that reports how often it was compared.

    Hash is constant per tag, so bucketing is exercised honestly: equal
    destinations land together, distinct ones are distinguished by the exact
    comparison, never by the hash.
    """

    comparisons = 0

    def __init__(self, tag: int) -> None:
        self.tag = tag

    def __hash__(self) -> int:
        return hash(self.tag)

    def __eq__(self, other: object) -> bool:
        type(self).comparisons += 1
        return isinstance(other, CountingDestination) and self.tag == other.tag


def _guard(index: int):
    return atomic("g", [make_var(f"v{index}")])


def _workload(arm_count: int) -> tuple:
    """Half the arms are repeats, so the merge does real work.

    An all-distinct workload would prove nothing here: every arrival lands in
    an empty bucket and the new merge performs ZERO comparisons, which passes
    any bound trivially. Drawing from `arm_count // 2` destinations forces
    every second arrival to find and compare against its prior — the path that
    must stay cheap.
    """
    distinct = max(arm_count // 2, 1)
    return tuple(
        Completed(_guard(index), CountingDestination(index % distinct))
        for index in range(arm_count)
    )


def _comparisons_for(arm_count: int) -> int:
    """Destination comparisons the shipped merge makes on that workload."""
    exits = _workload(arm_count)
    CountingDestination.comparisons = 0
    normalized = ExitSet(exits).normalize()
    assert len(normalized.exits) == max(arm_count // 2, 1), "no arm may vanish"
    return CountingDestination.comparisons


def _scan_comparisons_for(arm_count: int) -> int:
    """What the replaced all-pairs scan costs on the SAME workload.

    Measured rather than assumed, so the curve compares like with like.
    """
    from sugar_lift_py_tests.outcome.exit_set import Halted, _is_false, _or_guards

    exits = _workload(arm_count)
    CountingDestination.comparisons = 0
    merged: list = []
    for exit_ in exits:
        if _is_false(exit_.guard):
            continue
        for index, prior in enumerate(merged):
            if (
                isinstance(exit_, Completed)
                and isinstance(prior, Completed)
                and exit_.value == prior.value
            ):
                merged[index] = Completed(
                    _or_guards(prior.guard, exit_.guard), prior.value
                )
                break
            if (
                isinstance(exit_, Halted)
                and isinstance(prior, Halted)
                and exit_.effect == prior.effect
                and exit_.state == prior.state
            ):
                break
        else:
            merged.append(exit_)
    return CountingDestination.comparisons


@pytest.mark.parametrize("arm_count", ARM_COUNTS)
def test_comparisons_stay_near_linear_in_arm_count(arm_count: int) -> None:
    """Comparisons scale with arms, not with arms squared.

    The bound is deliberately generous — 8x the arm count — because the point
    is to catch a return to quadratic growth, not to pin an exact constant. At
    800 arms the old scan performs 319,600 comparisons; this bound is 6,400.
    """
    comparisons = _comparisons_for(arm_count)
    scan = _scan_comparisons_for(arm_count)

    assert comparisons <= arm_count * 8, (
        f"{arm_count} arms cost {comparisons} destination comparisons; the "
        f"all-pairs scan this repair replaced costs {scan} on the same "
        "workload. normalize has returned to quadratic growth in arm count"
    )


def test_growth_curve_is_not_quadratic_across_the_range() -> None:
    """Doubling the arms must not quadruple the comparisons.

    A single point cannot distinguish a linear algorithm from a quadratic one
    with a small constant. The curve can. Each doubling of arm count is
    allowed to at most triple the comparison count; a quadratic would
    reliably quadruple it.
    """
    measured = {count: _comparisons_for(count) for count in ARM_COUNTS}

    for smaller, larger in zip(ARM_COUNTS, ARM_COUNTS[1:]):
        low, high = measured[smaller], measured[larger]
        assert high <= max(low, 1) * 3, (
            f"comparisons grew {low} -> {high} when arms doubled "
            f"{smaller} -> {larger}; doubling the arms roughly quadrupled the "
            f"work, which is the quadratic signature. Full curve: {measured}"
        )
