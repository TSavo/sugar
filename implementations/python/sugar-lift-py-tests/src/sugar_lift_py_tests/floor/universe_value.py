from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.ir import Formula, eq, make_var

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
            term
            for entry in self.record.statements
            for term in entry.post_contribution()
        )
        if len(exits) != 1:
            from sugar_lift_py_tests.factory.factory_gap import factory_panic_gap
            from sugar_lift_py_tests.factory.factory_gap_info import GapKind, GapLocus

            factory_panic_gap(
                owner="UniverseValue",
                blame=self.name,
                observed=f"{len(exits)} exits",
                requested="one post slot",
                fix="write more Universe: guarded multi-exit post composition",
                gap_kind=GapKind.FLOOR,
                gap_locus=GapLocus.CONSTRUCTION,
            )
        return eq(make_var("out"), exits[0])
