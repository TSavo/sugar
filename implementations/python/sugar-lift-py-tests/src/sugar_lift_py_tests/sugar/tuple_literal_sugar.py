from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor.sequence_constructor import SequenceConstructor
from sugar_lift_py_tests.operations.perform_operation import perform_operation
from sugar_lift_py_tests.operations.sequence_construction_operation import (
    SequenceConstructionOperation,
)
from sugar_lift_py_tests.outcome import Incomplete, Outcome, complete_value
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witness_examples import (
    tuple_literal_subscript_return_witness,
)
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class TupleLiteralSugar(Sugar, role=SugarRole.TERM):
    elements: tuple[SugarBody, ...]
    blame: str = "<unknown>"

    def __post_init__(self) -> None:
        if not all(isinstance(element, SugarBody) for element in self.elements):
            raise TypeError("TupleLiteralSugar elements must be factory-built bodies")

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "Tuple"

    @classmethod
    def build(cls, site, ctx) -> "TupleLiteralSugar":
        return cls(
            elements=tuple(
                ctx.build_body(element, SugarRole.TERM) for element in site.terms()
            ),
            blame=site.blame,
        )

    @classmethod
    def witnesses(cls):
        return tuple_literal_subscript_return_witness()

    def desugar(self, ctx) -> Outcome:
        values = []
        for element in self.elements:
            outcome = element.reduce(ctx)
            if isinstance(outcome, Incomplete):
                return outcome
            values.append(complete_value(outcome, owner="TupleLiteralSugar element"))
        elements = tuple(values)
        return perform_operation(
            owner="TupleLiteralSugar",
            blame=self.blame,
            receiver=SequenceConstructor("tuple"),
            operation=SequenceConstructionOperation(
                elements=elements,
                owner="TupleLiteralSugar",
                blame=self.blame,
            ),
            ctx=ctx,
        )
