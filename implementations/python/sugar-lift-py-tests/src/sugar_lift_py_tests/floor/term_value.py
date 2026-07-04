from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .floor_value import FloorValue


@dataclass(frozen=True)
class TermValue(FloorValue):
    # The collapsed Number: an int OR a float. Int embeds in Real losslessly, so they are
    # one value type -- 3 and 3.0 are the same number, and 3.0 == 3 is reflexively true.
    # The Int/Real SMT sort is an emission-time inference, not a value-level split.
    value: int | float

    def add_with(self, operation: Any, ctx: Any) -> Any:
        return operation.add_term(self, ctx)

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import num

        return num(int(self.value))

    def project_callsite_with(self, operation: Any, ctx: Any) -> Any:
        return operation.project_literal(self, ctx)

    def call_method_with(self, operation: Any, ctx: Any) -> Any:
        del ctx
        if operation.name == "__format__" and len(operation.arguments) == 1:
            from sugar_lift_py_tests.floor.string_value import StringValue
            from sugar_lift_py_tests.outcome import Complete

            spec = operation.arguments[0]
            if isinstance(spec, StringValue):
                return Complete(StringValue(format(self.value, spec.value)))
        if operation.name == "__int__" and not operation.arguments:
            from sugar_lift_py_tests.outcome import Complete

            return Complete(TermValue(int(self.value)))
        _call_method_gap(
            owner=operation.owner,
            blame=operation.blame,
            observed=f"TermValue.{operation.name}",
            requested="numeric builtin method floor",
            fix=f"add TermValue method floor for `{operation.name}`",
        )

    def str_with(self, operation: Any, ctx: Any) -> Any:
        return operation.str_term(self, ctx)

    def bitwise_with(self, operation: Any, ctx: Any) -> Any:
        return operation.bitwise_term(self, ctx)

    def binary_operator_with(self, operation: Any, ctx: Any) -> Any:
        return operation.binary_term(self, ctx)

    def unary_operator_with(self, operation: Any, ctx: Any) -> Any:
        return operation.unary_term(self, ctx)


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
