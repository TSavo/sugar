from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .floor_value import FloorValue


@dataclass(frozen=True)
class TupleLiteralValue(FloorValue):
    items: tuple[FloorValue, ...]

    def __post_init__(self) -> None:
        if not all(isinstance(item, FloorValue) for item in self.items):
            raise TypeError("TupleLiteralValue items must be floor values")

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor

        return ctor("tuple", [item.to_term(owner=owner) for item in self.items])

    def binary_operator_with(self, operation: Any, ctx: Any) -> Any:
        return operation.binary_tuple(self, ctx)

    def contains_with(self, operation: Any, ctx: Any) -> Any:
        return operation.contains_tuple(self, ctx)

    def call_method_with(self, operation: Any, ctx: Any) -> Any:
        del ctx
        if operation.name == "__len__" and not operation.arguments:
            from sugar_lift_py_tests.floor.term_value import TermValue
            from sugar_lift_py_tests.outcome import Complete

            # Bare folded count; BuiltinCallSugar wrap re-attaches call:len.
            return Complete(TermValue(len(self.items)))
        if operation.name == "__hash__" and not operation.arguments:
            from sugar_lift_py_tests.outcome import Complete

            # Non-folding pure builtin: marker only → call:hash, no companion.
            return Complete(self)
        _call_method_gap(
            owner=operation.owner,
            blame=operation.blame,
            observed=f"TupleLiteralValue.{operation.name}",
            requested="tuple builtin method floor",
            fix=f"add TupleLiteralValue method floor for `{operation.name}`",
        )

    def materialize_with(self, operation: Any, ctx: Any) -> Any:
        return operation.materialize_tuple(self, ctx)

    def project_sequence_with(self, operation: Any, ctx: Any) -> Any:
        return operation.project_tuple(self, ctx)

    def project_callsite_with(self, operation: Any, ctx: Any) -> Any:
        return operation.project_literal(self, ctx)

    def subscript_with(self, operation: Any, ctx: Any) -> Any:
        return operation.subscript_tuple(self, ctx)


def _call_method_gap(
    *,
    owner: str,
    blame: str,
    observed: str,
    requested: str,
    fix: str,
):
    from sugar_lift_py_tests.factory import (
        FactoryAuditRow, factory_panic,
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
    factory_panic(
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
