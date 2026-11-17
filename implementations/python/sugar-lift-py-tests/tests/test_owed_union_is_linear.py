"""The union of what arms owe asks each item once, not once per kept item (#8416).

Slowness is the defect. In a straight-line body every arm owes the debts of
every operation before it (``ExitSet.two_faced`` puts one item on both arms;
``and_then`` carries the prefix's items onto every continuation). Reading
``owed_items`` off A such arms, each owing up to C items, asked
``item not in merged`` of a list A x C times: A x C^2 ``__eq__`` calls.
``_owed_union`` now asks a hash index where that product is large.

These tests count the work and pin that the answer is the scan's, item for
item, including where an index cannot answer (unhashable items, a class that
keeps identity hashing beside its own ``__eq__``).
"""

from __future__ import annotations

import random

from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.ir import atomic
from sugar_lift_py_tests.outcome import exit_set
from sugar_lift_py_tests.outcome.exit_set import Completed, ExitSet


class _Debt:
    """An owed item that counts every ``==`` asked of it."""

    eq_calls = 0

    def __init__(self, key: object) -> None:
        self.key = key

    def __eq__(self, other: object) -> bool:
        _Debt.eq_calls += 1
        return isinstance(other, _Debt) and self.key == other.key

    def __hash__(self) -> int:
        return hash(self.key)

    def __repr__(self) -> str:
        return f"_Debt({self.key!r})"


class _IdentityHashed(_Debt):
    """Equal by key, hashed by identity: a hash an index cannot trust."""

    __hash__ = object.__hash__


def _scan_union(*parts: tuple) -> tuple:
    """The list scan ``_owed_union`` always was: the reference answer."""
    nonempty = [part for part in parts if part]
    if not nonempty:
        return ()
    merged = list(nonempty[0])
    for part in nonempty[1:]:
        for item in part:
            if item not in merged:
                merged.append(item)
    return tuple(merged)


def _straight_line_arms(debts: list) -> ExitSet:
    """One arm per operation of a straight-line body: arm i owes debts 0..i."""
    return ExitSet(
        tuple(
            Completed(atomic(f"test:arm{i}", []), TermValue(i), owed=tuple(debts[: i + 1]))
            for i in range(len(debts))
        )
    )


def test_owed_items_over_a_straight_line_body_is_linear_in_equality_calls():
    debts = [_Debt(i) for i in range(200)]
    arms = _straight_line_arms(debts)
    _Debt.eq_calls = 0
    owed = arms.owed_items()
    asked = _Debt.eq_calls
    assert owed == tuple(debts)
    assert all(a is b for a, b in zip(owed, debts))
    items = sum(len(arm.owed) for arm in arms.exits)  # 20,100
    # The scan asked 199 * 200 * 201 / 6 = 1,333,300 equalities here.
    assert asked <= items, asked


def test_the_scan_is_cubic_on_the_same_shape():
    # 120 operations: the scan asks 119 * 120 * 121 / 6 = 287,980 equalities.
    debts = [_Debt(i) for i in range(120)]
    parts = [tuple(debts[: i + 1]) for i in range(len(debts))]
    _Debt.eq_calls = 0
    assert _scan_union(*parts) == tuple(debts)
    assert _Debt.eq_calls > 250_000
    _Debt.eq_calls = 0
    assert exit_set._owed_union(*parts) == tuple(debts)
    assert _Debt.eq_calls <= sum(len(part) for part in parts)


def test_the_index_answers_exactly_as_the_scan_on_mixed_items():
    rng = random.Random(8416)
    pool = [
        *(_Debt(i) for i in range(12)),
        *(_Debt(i) for i in range(6)),  # equal to earlier items, never the same object
        1, 1.0, True, 0, False, "a", "b", ("t", 1), ("t", 1.0), None,
    ]
    for _ in range(300):
        parts = [
            tuple(rng.choice(pool) for _ in range(rng.randrange(0, 12)))
            for _ in range(rng.randrange(1, 8))
        ]
        got = exit_set._owed_union(*parts)
        want = _scan_union(*parts)
        assert got == want, parts
        assert all(a is b for a, b in zip(got, want)), parts


def test_the_first_contributor_keeps_its_own_repeats():
    a, b = _Debt("a"), _Debt("b")
    first = (a, a, b) * 10
    rest = [tuple(_Debt(k) for k in "abc") for _ in range(10)]
    got = exit_set._owed_union(first, *rest)
    assert got == _scan_union(first, *rest)
    assert got[:30] == first and len(got) == 31


def test_unhashable_items_are_left_to_the_scan():
    lists = [[i] for i in range(20)]
    parts = [tuple(lists[: i + 1]) for i in range(20)]
    assert exit_set._union_by_index(parts[0], parts[1:]) is None
    assert exit_set._owed_union(*parts) == _scan_union(*parts)


def test_identity_hashing_beside_its_own_equality_is_left_to_the_scan():
    left = tuple(_IdentityHashed(i) for i in range(20))
    right = tuple(_IdentityHashed(i) for i in range(20))  # equal, not the same
    assert exit_set._union_by_index(left, [right]) is None
    got = exit_set._owed_union(left, right)
    assert got == _scan_union(left, right)
    assert all(a is b for a, b in zip(got, left)) and len(got) == 20


def test_small_unions_keep_the_scan():
    a, b = _Debt("a"), _Debt("b")
    assert len((a,)) * len((a, b)) <= exit_set._OWED_SCAN_LIMIT
    assert exit_set._owed_union((a,), (a, b), ()) == (a, b)
    assert exit_set._owed_union((), ()) == ()
    assert exit_set._owed_union((b, a)) == (b, a)
