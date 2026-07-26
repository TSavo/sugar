"""The membrane the bucketed merge needs: hash must never be finer than equality.

`ExitSet.normalize` buckets destinations by hash and decides by exact equality.
That is sound only while ``a == b`` implies ``hash(a) == hash(b)``. The
dangerous shape is a class that overrides ``__eq__`` and inherits
object-identity ``__hash__``: two equal destinations would land in different
buckets, quietly stop merging, and the ExitSet fingerprint would change with
nothing going red.

The randomized oracle in `test_exit_set_normalize_identity.py` cannot be
trusted to catch that. It only sees the destination species its generator
happens to build; a real offender would sit in a class the generator never
constructs. Destination species arrive from an OPEN boundary — every new
Effect and FloorValue is a new one — so this is a membrane over that
boundary, not a fixture over a closed set.

Auditor imported from #6307, which scanned 142 Effect/FloorValue classes with
zero offenders. Credit to that PR; the merge it protects is #6311's.

Retirement path: deletable the day ``Effect`` and ``FloorValue`` are closed
hierarchies whose construction door refuses a subclass with an
``__eq__``/``__hash__`` split. Until then no local type can close it, and the
auditor earns its keep by naming the offender class and its two lawful fixes.
"""

from __future__ import annotations

from sugar_lift_py_tests.ir import atomic, make_var
from sugar_lift_py_tests.outcome.exit_set import Completed, ExitSet


def _guard(index: int):
    return atomic("g", [make_var(f"v{index}")])


def test_no_destination_species_has_a_finer_hash_than_its_equality() -> None:
    """Every destination species: custom ``__eq__`` implies a matching ``__hash__``.

    Unhashable is fine — that takes the measured linear fallback.
    Finer-than-equality is not: it is a silent merge failure.
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


def test_colliding_hashes_still_merge_when_actually_equal() -> None:
    """A collision must not prevent a merge that equality demands.

    The companion to `test_same_hash_but_unequal_destination_stays_separate`:
    that one proves a collision does not force a merge, this one proves it
    does not prevent one. Both directions, or the bucket is only half checked.
    """

    class AlwaysColliding:
        def __init__(self, tag: str) -> None:
            self.tag = tag

        def __hash__(self) -> int:
            return 7

        def __eq__(self, other: object) -> bool:
            return isinstance(other, AlwaysColliding) and self.tag == other.tag

    produced = ExitSet(
        (
            Completed(_guard(1), AlwaysColliding("same")),
            Completed(_guard(2), AlwaysColliding("same")),
        )
    ).normalize()

    assert len(produced.exits) == 1, (
        "two equal destinations sharing a hash must merge; the bucket narrows "
        "candidates and equality decides"
    )


def test_unhashable_and_hashable_destinations_compare_against_each_other() -> None:
    """A hashable arrival is still compared against unhashable priors.

    Bucketing must not create two populations that never meet. An arrival with
    a usable hash still checks the arms that took the fallback, so no pair of
    equal destinations can be separated by hashability alone.
    """

    class SometimesHashable:
        """Equal across instances; hashable only when ``ok`` is set."""

        def __init__(self, ok: bool) -> None:
            self.ok = ok

        def __eq__(self, other: object) -> bool:
            return isinstance(other, SometimesHashable)

        def __hash__(self) -> int:
            if not self.ok:
                raise TypeError("unhashable by construction")
            return 11

    produced = ExitSet(
        (
            Completed(_guard(1), SometimesHashable(ok=False)),
            Completed(_guard(2), SometimesHashable(ok=True)),
        )
    ).normalize()

    assert len(produced.exits) == 1, (
        "an unhashable prior and a hashable arrival that are EQUAL must still "
        "merge; bucketing may narrow candidates but must never partition them"
    )
