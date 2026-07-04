from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .floor_value import FloorValue
from .object_value import ObjectValue
from .symbolic_value import SymbolicValue
from .term_value import TermValue
from .tuple_literal_value import TupleLiteralValue


@dataclass(frozen=True)
class ArrayLiteral(FloorValue):
    # Each item is a scalar, object, symbolic parameter, nested array, or tuple literal.
    items: tuple[
        "TermValue | ObjectValue | SymbolicValue | ArrayLiteral | TupleLiteralValue",
        ...,
    ]

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor

        return ctor("array", [item.to_term(owner=owner) for item in self.items])

    def map_with(self, operation: Any, ctx: Any) -> Any:
        return operation.map_array(self, ctx)

    def add_with(self, operation: Any, ctx: Any) -> Any:
        return operation.add_array(self, ctx)

    def binary_operator_with(self, operation: Any, ctx: Any) -> Any:
        return operation.binary_array(self, ctx)

    def contains_with(self, operation: Any, ctx: Any) -> Any:
        return operation.contains_array(self, ctx)

    def subscript_with(self, operation: Any, ctx: Any) -> Any:
        return operation.subscript_array(self, ctx)

    def call_method_with(self, operation: Any, ctx: Any) -> Any:
        del ctx
        if operation.name == "__len__" and not operation.arguments:
            from sugar_lift_py_tests.outcome import Complete

            return Complete(TermValue(len(self.items)))
        _call_method_gap(
            owner=operation.owner,
            blame=operation.blame,
            observed=f"ArrayLiteral.{operation.name}",
            requested="array builtin method floor",
            fix=f"add ArrayLiteral method floor for `{operation.name}`",
        )

    def project_sequence_with(self, operation: Any, ctx: Any) -> Any:
        return operation.project_array(self, ctx)

    def project_callsite_with(self, operation: Any, ctx: Any) -> Any:
        return operation.project_literal(self, ctx)


def _call_method_gap(
    *,
    owner: str,
    blame: str,
    observed: str,
    requested: str,
    fix: str,
):
    from sugar_lift_py_tests.factory import (
        FactoryAuditRow,
        FactoryGap,
        FactoryGapInfo,
        GapKind,
        GapLocus,
    )

    info = FactoryGapInfo(
        owner=owner,
        blame=blame,
        observed=observed,
        requested=requested,
        fix=fix,
        gap_kind=GapKind.FLOOR,
        gap_locus=GapLocus.CONSTRUCTION,
    )
    raise FactoryGap(
        info,
        FactoryAuditRow(
            role=requested,
            status="floor-gap",
            observed=observed,
            blame=blame,
            selected=None,
            candidates=[],
            message=info.message,
        ),
    )
