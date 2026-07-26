"""ExitSet.normalize: bucketed LOOKUP, all-pairs MEANING.

``normalize`` used to ask every arm about every prior arm. On
``pandas/core/generic.py`` #6296 raised the honest guarded-exit population to a
1,317-arm maximum (mean 4.17 over 128,462 calls), and the all-pairs scan bounded
13.1M destination comparisons for a merge that removes under 2% of arms. The
arm population is not the defect; asking O(n^2) questions to answer it is.

This file is the tooth for the repair. Two axes, kept apart on purpose:

- **fidelity**: the bucketed normalizer must produce the byte-identical exit
  tuple, in the identical order, that the all-pairs normalizer produced.
- **complexity**: destination comparisons must scale near-linearly in the arm
  count, and identity work must scale with distinct objects, not comparisons.

The reference all-pairs implementation below is a verbatim copy of the shape
``normalize`` had before the index. It is the "old" side of the fingerprint
comparison and must not be edited to match a new output.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.ir import and_, atomic, make_var, not_
from sugar_lift_py_tests.outcome.exit_set import (
    Completed,
    ExitSet,
    Halted,
    _is_false,
    _or_guards,
    reset_unhashable_destination_arms,
    unhashable_destination_arms,
)


def _guard(name: str):
    return atomic(name, [make_var("state")])


def _all_pairs_normalize(exit_set: ExitSet) -> ExitSet:
    """The pre-index normalizer, kept verbatim as the fingerprint reference."""
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


class _CountingValue:
    """A destination whose equality questions are countable.

    ``__hash__`` hashes exactly the field ``__eq__`` compares — the same
    relationship ``CallSiteValue`` already has, and the reason the bucket key
    invents no new coordinate.
    """

    comparisons = 0

    def __init__(self, name: str) -> None:
        self.name = name

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, _CountingValue):
            return NotImplemented
        type(self).comparisons += 1
        return self.name == other.name

    def __hash__(self) -> int:
        return hash(self.name)

    def __repr__(self) -> str:
        return f"_CountingValue({self.name!r})"


class _CollidingValue(_CountingValue):
    """Distinct destinations that share one hash bucket."""

    def __hash__(self) -> int:
        return 0


class _UnhashableValue:
    """A destination species that owes a ``__hash__`` and does not have one."""

    __hash__ = None  # type: ignore[assignment]

    def __init__(self, name: str) -> None:
        self.name = name

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _UnhashableValue) and self.name == other.name


def _population(arm_count: int, *, distinct: int, value_cls=_CountingValue) -> ExitSet:
    """``arm_count`` arms cycling over ``distinct`` destinations, all distinct guards."""
    return ExitSet(
        tuple(
            Completed(_guard(f"g{index}"), value_cls(f"d{index % distinct}"))
            for index in range(arm_count)
        )
    )


# --- fidelity -------------------------------------------------------------


@pytest.mark.parametrize("arm_count", [1, 2, 7, 64, 257])
@pytest.mark.parametrize("distinct", [1, 3, 64])
def test_normalized_fingerprint_is_byte_identical_to_all_pairs(arm_count, distinct):
    population = _population(arm_count, distinct=distinct)
    assert population.normalize().exits == _all_pairs_normalize(population).exits


def test_mixed_completed_and_halted_fingerprint_is_byte_identical():
    effects = [RaiseEffect(exception_name=name) for name in ("ValueError", "KeyError")]
    exits = []
    for index in range(120):
        guard = _guard(f"g{index}")
        if index % 3 == 0:
            exits.append(Completed(guard, _CountingValue(f"d{index % 5}")))
        else:
            exits.append(
                Halted(guard, effects[index % 2], _CountingValue(f"s{index % 4}"))
            )
    population = ExitSet(tuple(exits))
    normalized = population.normalize()
    assert normalized.exits == _all_pairs_normalize(population).exits
    # Neither edge disappears: both species survive the index.
    assert any(isinstance(exit_, Completed) for exit_ in normalized.exits)
    assert any(isinstance(exit_, Halted) for exit_ in normalized.exits)


def test_output_order_is_insertion_order_of_first_arrival():
    population = ExitSet(
        (
            Completed(_guard("a"), _CountingValue("z")),
            Completed(_guard("b"), _CountingValue("y")),
            Completed(_guard("c"), _CountingValue("z")),
            Completed(_guard("d"), _CountingValue("y")),
        )
    )
    normalized = population.normalize()
    assert [exit_.value.name for exit_ in normalized.exits] == ["z", "y"]


def test_no_arm_disappears_when_every_destination_is_distinct():
    population = _population(200, distinct=200)
    assert len(population.normalize().exits) == 200


def test_equal_destinations_merge_and_disjoin_guards_exactly_once():
    left, right = _guard("left"), _guard("right")
    population = ExitSet(
        (
            Completed(left, _CountingValue("d")),
            Completed(right, _CountingValue("d")),
            Completed(_guard("third"), _CountingValue("d")),
        )
    )
    normalized = population.normalize()
    assert len(normalized.exits) == 1
    assert normalized.exits[0].guard == _or_guards(
        _or_guards(left, right), _guard("third")
    )


def test_false_guarded_arms_are_dropped_exactly_as_before():
    population = ExitSet(
        (
            Completed(not_(and_([])), _CountingValue("dropped")),
            Completed(_guard("kept"), _CountingValue("kept")),
        )
    )
    normalized = population.normalize()
    assert [exit_.value.name for exit_ in normalized.exits] == ["kept"]
    assert normalized.exits == _all_pairs_normalize(population).exits


def test_same_hash_but_unequal_destination_stays_separate():
    population = ExitSet(
        tuple(
            Completed(_guard(f"g{index}"), _CollidingValue(f"d{index}"))
            for index in range(16)
        )
    )
    normalized = population.normalize()
    # A collision is a collision, not equality: the exact comparison decides.
    assert len(normalized.exits) == 16
    assert normalized.exits == _all_pairs_normalize(population).exits


def test_colliding_hashes_still_merge_when_actually_equal():
    population = _population(32, distinct=4, value_cls=_CollidingValue)
    normalized = population.normalize()
    assert len(normalized.exits) == 4
    assert normalized.exits == _all_pairs_normalize(population).exits


def test_unhashable_destinations_preserve_behavior_and_are_counted():
    population = ExitSet(
        tuple(
            Completed(_guard(f"g{index}"), _UnhashableValue(f"d{index % 3}"))
            for index in range(12)
        )
    )
    reset_unhashable_destination_arms()
    normalized = population.normalize()
    assert normalized.exits == _all_pairs_normalize(population).exits
    assert len(normalized.exits) == 3
    # Measured, not quiet: the fallback names how many arms took it.
    assert unhashable_destination_arms() == 12


def test_unhashable_and_hashable_destinations_still_compare_against_each_other():
    """An unhashable arm is never hidden from a hashable one by the index."""

    class _Bridge:
        """Hashable, and equal to an ``_UnhashableValue`` of the same name."""

        def __init__(self, name: str) -> None:
            self.name = name

        def __eq__(self, other: object) -> bool:
            return getattr(other, "name", object()) == self.name

        def __hash__(self) -> int:
            return hash(self.name)

    population = ExitSet(
        (
            Completed(_guard("a"), _UnhashableValue("d")),
            Completed(_guard("b"), _Bridge("d")),
            Completed(_guard("c"), _UnhashableValue("d")),
        )
    )
    assert population.normalize().exits == _all_pairs_normalize(population).exits


# --- complexity -----------------------------------------------------------


@pytest.mark.parametrize("arm_count", [100, 200, 400, 800])
def test_destination_comparisons_scale_near_linearly(arm_count):
    """The complexity tooth: comparisons per arm must not grow with arm count.

    All-pairs over ``arm_count`` arms with ``arm_count // 2`` distinct
    destinations bounds ~arm_count^2/4 comparisons (100 -> 2,500;
    800 -> 160,000). Bucketed lookup asks ~1 per arm.
    """
    population = _population(arm_count, distinct=arm_count // 2)
    _CountingValue.comparisons = 0
    population.normalize()
    bucketed = _CountingValue.comparisons

    _CountingValue.comparisons = 0
    _all_pairs_normalize(population)
    all_pairs = _CountingValue.comparisons

    assert bucketed <= 2 * arm_count, (
        f"{arm_count} arms asked {bucketed} destination comparisons; "
        "bucketed lookup must stay near-linear in the arm count"
    )
    assert all_pairs > 4 * bucketed, (
        "reference all-pairs scan is not quadratic here — the population no "
        "longer exercises the shape this tooth measures"
    )


def test_comparison_growth_is_sublinear_in_the_quadratic_ratio():
    """Show the curve: doubling arms must not quadruple comparisons."""
    curve = {}
    for arm_count in (100, 200, 400, 800):
        population = _population(arm_count, distinct=arm_count // 2)
        _CountingValue.comparisons = 0
        population.normalize()
        curve[arm_count] = _CountingValue.comparisons
    for smaller, larger in ((100, 200), (200, 400), (400, 800)):
        ratio = curve[larger] / max(curve[smaller], 1)
        assert ratio < 3.0, f"comparison curve {curve} grew {ratio:.2f}x from doubling"


def test_no_destination_species_has_a_finer_hash_than_its_equality():
    """The membrane over an OPEN boundary: destination species keep arriving.

    A bucket index is exact only while ``a == b`` implies
    ``hash(a) == hash(b)``. The dangerous shape is a class that overrides
    ``__eq__`` and keeps object-identity ``__hash__``: two equal destinations
    would land in different buckets, stop merging, and the ExitSet fingerprint
    would change SILENTLY. Unhashable is fine (measured linear fallback);
    finer-than-equality is not.

    Retirement path: this auditor is deletable the day ``Effect`` and
    ``FloorValue`` are closed hierarchies whose construction door refuses a
    subclass with an ``__eq__``/``__hash__`` split.
    """
    import importlib
    import pkgutil
    import typing

    import sugar_lift_py_tests as package
    from sugar_lift_py_tests.effect import Effect
    from sugar_lift_py_tests.floor import FloorValue

    for module in pkgutil.walk_packages(package.__path__, package.__name__ + "."):
        try:
            importlib.import_module(module.name)
        except BaseException:  # optional/heavy leaves are not this tooth's job
            pass

    roots: list[type] = []
    for base in (Effect, FloorValue):
        roots.extend(typing.get_args(base) or [base])

    seen: set[type] = set()
    stack = list(roots)
    offenders: list[str] = []
    while stack:
        cls = stack.pop()
        if not isinstance(cls, type) or cls in seen:
            continue
        seen.add(cls)
        stack.extend(cls.__subclasses__())
        if "__eq__" not in cls.__dict__:
            continue
        if cls.__dict__.get("__hash__", "inherited") is object.__hash__:
            offenders.append(f"{cls.__module__}.{cls.__qualname__}")

    assert seen, "destination species scan found no classes — the scan is broken"
    assert not offenders, (
        "destination species with custom __eq__ and identity __hash__: "
        f"{offenders}. ExitSet.normalize buckets by hash and decides by "
        "equality; a finer hash makes equal arms stop merging without any "
        "test going red. Give each class a __hash__ over exactly the fields "
        "its __eq__ compares (as CallSiteValue does), or set __hash__ = None "
        "so it takes the measured linear fallback."
    )
