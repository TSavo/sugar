from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue


@dataclass(frozen=True)
class ComprehensionValue(FloorValue):
    """A native comprehension coordinate with no invented cardinality.

    Finite literal comprehensions reduce to concrete collection floors. All
    other comprehensions retain their constructor term, but ``length`` stays on
    FloorValue's loud missing arm until cardinality semantics are constructed.
    """

    term: object

    def to_term(self, *, owner: str):
        del owner
        return self.term
