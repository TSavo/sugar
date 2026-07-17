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

    def add(self, other, site):
        from sugar_lift_py_tests.effect import (
            SequenceConcatenationRuntimeEffect,
            runtime_effect_witness,
        )
        from sugar_lift_py_tests.floor.list_value import ListValue
        from sugar_lift_py_tests.outcome import Incomplete

        if type(other) in (ComprehensionValue, ListValue):
            return Incomplete(
                SequenceConcatenationRuntimeEffect(
                    "sequence concatenation depends on runtime comprehension "
                    f"members; owner=ComprehensionValue.add site={site}",
                    witness=runtime_effect_witness("py.sequence_concat", other, site),
                )
            )
        return super().add(other, site)
