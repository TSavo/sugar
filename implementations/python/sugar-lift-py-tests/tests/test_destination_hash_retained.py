"""Retained destination hashes answer what ``hash`` answers (#7664).

``normalize`` buckets arms by destination hash.  A frozen dataclass's hash is
retained per live object; anything else is hashed fresh, so the bucket key
(and therefore which arms merge) is exactly the one ``hash`` would give.
"""

from __future__ import annotations

import gc
from dataclasses import dataclass

from sugar_lift_py_tests.outcome import exit_set
from sugar_lift_py_tests.outcome.exit_set import _retained_hash


@dataclass(frozen=True)
class _Leaf:
    name: str
    parts: tuple


@dataclass
class _Loose:
    name: str

    def __hash__(self) -> int:  # content hash over MUTABLE state
        return hash(self.name)


def test_frozen_values_hash_as_hash_does_and_are_retained():
    values = [_Leaf("a", ()), _Leaf("a", (1, 2)), _Leaf("b", (_Leaf("c", ()),))]
    for value in values:
        assert _retained_hash(value) == hash(value)
        assert id(value) in exit_set._DESTINATION_HASH
        assert _retained_hash(value) == hash(value)


def test_non_frozen_hash_is_never_retained():
    loose = _Loose("a")
    assert _retained_hash(loose) == hash(loose)
    loose.name = "b"
    assert _retained_hash(loose) == hash("b")
    assert id(loose) not in exit_set._DESTINATION_HASH
    assert _retained_hash((1, "x")) == hash((1, "x"))


def test_dead_object_never_answers_for_a_recycled_id():
    value = _Leaf("dead", ())
    vid = id(value)
    _retained_hash(value)
    del value
    gc.collect()
    assert vid not in exit_set._DESTINATION_HASH


def test_unhashable_stays_unhashable():
    @dataclass(frozen=True)
    class _Holder:
        items: list

    holder = _Holder([1])
    for _ in range(2):
        try:
            _retained_hash(holder)
        except TypeError:
            pass
        else:
            raise AssertionError("a list field must stay unhashable")
