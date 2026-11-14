from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue


@dataclass(frozen=True)
class GroundSequenceRepetitionValue(FloorValue):
    """``sequence * count`` for one concrete sequence and one concrete count,
    held without eager element expansion.

    The value is exact: its identity is the receiver sequence (its own category
    and elements) and the concrete count, so its length and truth are decided
    and its term is the one closed ``python:sequence_repeat`` coordinate the
    opaque-count arm also emits. It is not a ``SymbolicValue``: nothing about
    this value is undecided, its Python type included.
    """

    sequence: FloorValue
    elements: tuple
    count: FloorValue
    repetitions: int

    def denotes_value(self) -> bool:
        """A sequence repetition denotes a Python runtime value."""
        return True

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.floor.sequence_repetition import repetition_term

        return repetition_term(self.sequence, self.count, owner)

    def length(self, site):
        del site
        from sugar_lift_py_tests.floor.term_value import TermValue
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.completed(
            TermValue(len(self.elements) * max(self.repetitions, 0))
        )

    def truth(self, site):
        from sugar_lift_py_tests.outcome import ExitSet
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        return ExitSet.completed(
            TrueBoolLiteralSugar(site=site)
            if self.elements and self.repetitions > 0
            else FalseBoolLiteralSugar(site=site)
        )
