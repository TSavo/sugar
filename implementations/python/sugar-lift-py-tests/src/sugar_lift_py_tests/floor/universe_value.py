from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.ir import Formula

from .floor_value import FloorValue


@dataclass(frozen=True)
class UniverseValue(FloorValue):
    """A function body lowered to its universe: name, formals, record. The
    slots are PROJECTIONS of the record -- each entry answers for itself
    (inv_contribution / post_contribution), the universe just concatenates.
    invs are the stated facts; post is `out == <exit term>`."""

    name: str
    formals: tuple[str, ...]
    record: object  # the body's BlockValue

    def invs(self) -> tuple[Formula, ...]:
        return tuple(
            formula
            for entry in self.record.statements
            for formula in entry.inv_contribution()
        )

    def post(self) -> Formula:
        exits = tuple(
            formula
            for entry in self.record.statements
            for formula in entry.post_contribution()
        )
        if not exits:
            from sugar_lift_py_tests.factory.factory_gap import factory_panic_gap
            from sugar_lift_py_tests.factory.factory_gap_info import GapKind, GapLocus

            factory_panic_gap(
                owner="UniverseValue",
                blame=self.name,
                observed="no exits",
                requested="a post slot",
                fix="write more Universe: a body with no return posts nothing yet",
                gap_kind=GapKind.FLOOR,
                gap_locus=GapLocus.CONSTRUCTION,
            )
        if len(exits) == 1:
            return exits[0]
        from sugar_lift_py_tests.ir import and_

        return and_(list(exits))
