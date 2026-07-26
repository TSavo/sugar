"""ExitSet.normalize: bucketed merge is the all-pairs scan, exactly.

The repair replaced a quadratic all-pairs merge with a destination-hash
indexed one. The merge decides which execution arms are the SAME destination,
so a behaviour change here is a semantic change to every lifted function that
branches — it would not show up as a crash, it would show up as a wrong
formula months later. These teeth pin the replacement against the code it
replaced, on the same inputs, arm for arm.

The reference implementation below IS the pre-repair scan, kept verbatim. It
is not a second opinion about what normalize should do; it is what normalize
did. Every randomized case asserts byte-identical output.
"""

from __future__ import annotations

import random

import pytest

from sugar_lift_py_tests.ir import atomic, make_var, not_, or_
from sugar_lift_py_tests.outcome.exit_set import (
    Completed,
    ExitSet,
    Halted,
    false_guard,
    _is_false,
    _or_guards,
    _unhashable_destination_count,
)
from sugar_lift_py_tests.effect import RaiseEffect


def _reference_normalize(exit_set: ExitSet) -> ExitSet:
    """The pre-repair all-pairs scan, verbatim. The oracle, not a rewrite."""
    merged: list = []
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


def _guard(index: int):
    return atomic("g", [make_var(f"v{index}")])


def _effect(name: str) -> RaiseEffect:
    return RaiseEffect(exception_name=name)


def _random_exits(rng: random.Random, count: int, distinct: int) -> tuple:
    """Arms drawn from a small destination pool, so merges actually happen."""
    exits = []
    for _ in range(count):
        guard = _guard(rng.randrange(distinct))
        if rng.random() < 0.5:
            exits.append(Completed(guard, f"dest{rng.randrange(distinct)}"))
        else:
            exits.append(
                Halted(
                    guard,
                    _effect(f"eff{rng.randrange(distinct)}"),
                    f"state{rng.randrange(distinct)}",
                )
            )
    return tuple(exits)


@pytest.mark.parametrize("seed", range(40))
def test_bucketed_merge_is_byte_identical_to_the_scan(seed: int) -> None:
    """Same arms in, same tuple out — order, count, guards, destinations."""
    rng = random.Random(seed)
    exits = _random_exits(rng, rng.randrange(1, 60), rng.randrange(1, 8))
    subject = ExitSet(exits)

    produced = ExitSet.normalize(subject)
    expected = _reference_normalize(subject)

    assert produced.exits == expected.exits
    assert [type(e) for e in produced.exits] == [type(e) for e in expected.exits]
    assert [e.guard for e in produced.exits] == [e.guard for e in expected.exits]


@pytest.mark.parametrize("seed", range(10))
def test_no_arm_disappears_and_order_is_first_occurrence(seed: int) -> None:
    """Every distinct destination survives, in the order it first arrived."""
    rng = random.Random(1000 + seed)
    exits = _random_exits(rng, 40, 5)
    kept = [e for e in exits if not _is_false(e.guard)]

    produced = ExitSet(exits).normalize()

    def destination(exit_):
        if isinstance(exit_, Completed):
            return ("completed", exit_.value)
        return ("halted", exit_.effect, exit_.state)

    first_seen: list = []
    for exit_ in kept:
        key = destination(exit_)
        if key not in first_seen:
            first_seen.append(key)

    assert [destination(e) for e in produced.exits] == first_seen


def test_equal_destinations_merge_and_disjoin_guards_exactly_once() -> None:
    """Two arms, one destination: one output arm carrying the disjunction."""
    left, right = _guard(1), _guard(2)
    produced = ExitSet(
        (Completed(left, "same"), Completed(right, "same"))
    ).normalize()

    assert len(produced.exits) == 1
    assert produced.exits[0].value == "same"
    assert produced.exits[0].guard == or_([left, right])


def test_same_hash_but_unequal_destination_stays_separate() -> None:
    """A collision costs a comparison, never an identity. Hash never decides."""

    class Colliding:
        def __init__(self, tag: str) -> None:
            self.tag = tag

        def __hash__(self) -> int:
            return 4  # every instance collides, deliberately

        def __eq__(self, other: object) -> bool:
            return isinstance(other, Colliding) and self.tag == other.tag

    subject = ExitSet(
        (
            Completed(_guard(1), Colliding("a")),
            Completed(_guard(2), Colliding("b")),
            Completed(_guard(3), Colliding("a")),
        )
    )
    produced = subject.normalize()

    assert produced.exits == _reference_normalize(subject).exits
    assert len(produced.exits) == 2, "colliding-but-unequal arms must not merge"
    assert produced.exits[0].value == Colliding("a")
    assert produced.exits[1].value == Colliding("b")


def test_unhashable_destination_preserves_behaviour_and_is_counted() -> None:
    """The slow path stays correct AND stays visible. Never a silent drop."""
    before = _unhashable_destination_count()

    subject = ExitSet(
        (
            Completed(_guard(1), ["unhashable"]),
            Completed(_guard(2), ["unhashable"]),
            Completed(_guard(3), ["other"]),
        )
    )
    produced = subject.normalize()

    assert produced.exits == _reference_normalize(subject).exits
    assert len(produced.exits) == 2
    assert _unhashable_destination_count() > before, (
        "an unhashable destination took the scan path and must be measured, "
        "not silently absorbed into a 'fixed' normalizer"
    )


def test_false_guarded_arms_are_dropped_as_before() -> None:
    guard = _guard(1)
    subject = ExitSet(
        (
            Completed(false_guard(), "dropped"),
            Completed(guard, "kept"),
        )
    )
    produced = subject.normalize()

    assert produced.exits == _reference_normalize(subject).exits
    assert [e.value for e in produced.exits] == ["kept"]


def test_both_faces_of_a_partition_survive() -> None:
    """A retained predicate's truth AND false faces both reach the output.

    #6298's whole point is that an undecidable predicate is not decided. A
    merge that silently collapsed one face would decide it by omission.
    """
    predicate = atomic("undecidable", [make_var("m")])
    subject = ExitSet(
        (
            Completed(predicate, "truth-face"),
            Completed(not_(predicate), "false-face"),
        )
    )
    produced = subject.normalize()

    assert produced.exits == _reference_normalize(subject).exits
    assert [e.value for e in produced.exits] == ["truth-face", "false-face"]
