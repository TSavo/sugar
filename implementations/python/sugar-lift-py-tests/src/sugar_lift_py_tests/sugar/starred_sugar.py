"""`*expr` in call/list/tuple/set display — starred value sugar."""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import (
    ConstructedTermSugar,
    require_constructed_term_sugar,
)
from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing


@dataclass(frozen=True)
class StarredSugar(ConstructedTermSugar):
    """A starred expression node owned for construction totality.

    Parents (Call / List / Tuple / Set) already project ``python:starred``
    coordinates from this value. Standalone construction returns a coordinate
    wrap so the node is never an unowned gap; unpack targets stay Assign's job.
    """

    value: ConstructedTermSugar
    site: object = dataclass_field(compare=False)

    def __post_init__(self) -> None:
        require_constructed_term_sugar(self.value, owner="StarredSugar.value")

    @classmethod
    def witnesses(cls):
        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="starred coordinate",
            reason="starred elements are projected by their display/call parent",
        )

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor

        return ctor(
            "python:starred-construction",
            (
                self.occurrence_term(owner=owner),
                self.value.to_term(owner=owner),
            ),
            symbol_kind="coordinate",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
        from sugar_lift_py_tests.ir import ctor

        return self.value.desugar(ctx).and_then(
            lambda inner: Complete(
                SymbolicValue(
                    ctor(
                        "python:starred",
                        [inner.to_term(owner="StarredSugar")],
                    )
                )
            )
        )
