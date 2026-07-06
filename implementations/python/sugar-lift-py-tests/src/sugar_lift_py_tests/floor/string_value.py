from __future__ import annotations

from dataclasses import dataclass
import math
from typing import TYPE_CHECKING, NoReturn

from .floor_value import FloorValue

if TYPE_CHECKING:
    from sugar_lift_py_tests.context import FactoryBuildContext
    from sugar_lift_py_tests.operations.method_call_operation import (
        MethodCallOperation,
    )
    from sugar_lift_py_tests.outcome import Outcome


@dataclass(frozen=True)
class StringValue(FloorValue):
    value: str

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import str_const

        return str_const(self.value)

    def project_callsite_with(self, operation, ctx):
        return operation.project_literal(self, ctx)

    def call_method_with(
        self, operation: MethodCallOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        del ctx
        if operation.name == "__int__" and not operation.arguments:
            from sugar_lift_py_tests.floor.term_value import TermValue
            from sugar_lift_py_tests.outcome import Complete

            return Complete(TermValue(int(self.value)))
        if operation.name == "__float__" and not operation.arguments:
            from sugar_lift_py_tests.effect import RuntimeEffect
            from sugar_lift_py_tests.floor.term_value import TermValue
            from sugar_lift_py_tests.outcome import Complete, Incomplete

            try:
                parsed = float(self.value)
            except ValueError:
                return Incomplete(
                    RuntimeEffect(
                        "string float conversion runtime boundary: "
                        "crime=StringValue.__float__ cannot parse a static string; "
                        "owner=StringValue; "
                        f"shape=value `{self.value}`; "
                        "replacement=keep this as typed red because Python raises "
                        "ValueError at runtime; "
                        f"blame={operation.blame}"
                    )
                )
            if not math.isfinite(parsed):
                return Incomplete(
                    RuntimeEffect(
                        "string float conversion runtime boundary: "
                        "crime=StringValue.__float__ parsed a non-finite float; "
                        "owner=StringValue; "
                        f"shape=value `{self.value}`; "
                        "replacement=add a cited non-finite numeric floor before "
                        "treating NaN/Infinity as proof-bearing; "
                        f"blame={operation.blame}"
                    )
                )
            if not parsed.is_integer():
                return Incomplete(
                    RuntimeEffect(
                        "string float conversion runtime boundary: "
                        "crime=StringValue.__float__ parsed a non-integral Real; "
                        "owner=StringValue; "
                        f"shape=value `{self.value}`; "
                        "replacement=add a deterministic Real-return floor before "
                        "treating this as proof-bearing; "
                        f"blame={operation.blame}"
                    )
                )
            return Complete(TermValue(parsed))
        if operation.name == "format":
            from sugar_lift_py_tests.effect import RuntimeEffect
            from sugar_lift_py_tests.floor.term_value import TermValue
            from sugar_lift_py_tests.outcome import Complete, Incomplete

            args: list[str | int | float] = []
            for arg in operation.arguments:
                if isinstance(arg, StringValue):
                    args.append(arg.value)
                elif isinstance(arg, TermValue):
                    args.append(arg.value)
                else:
                    return Incomplete(
                        RuntimeEffect(
                            "string format runtime boundary: "
                            "crime=StringValue.format argument is not a static "
                            "string/numeric floor; "
                            "owner=StringValue; "
                            f"shape={type(arg).__name__}; "
                            "replacement=add a cited str.format floor for this "
                            "argument type or keep the method call as typed red; "
                            f"blame={operation.blame}"
                        )
                    )
            try:
                return Complete(StringValue(self.value.format(*args)))
            except (IndexError, KeyError, ValueError) as exc:
                return Incomplete(
                    RuntimeEffect(
                        "string format runtime boundary: "
                        "crime=StringValue.format raised while applying a static "
                        "format string; "
                        "owner=StringValue; "
                        f"shape={type(exc).__name__}; "
                        "replacement=prove a narrower format-string floor or keep "
                        "the method call as typed red; "
                        f"blame={operation.blame}"
                    )
                )
        if operation.name == "__format__" and len(operation.arguments) == 1:
            from sugar_lift_py_tests.outcome import Complete

            spec = operation.arguments[0]
            if isinstance(spec, StringValue):
                return Complete(StringValue(format(self.value, spec.value)))
        _call_method_gap(
            owner=operation.owner,
            blame=operation.blame,
            observed=f"StringValue.{operation.name}",
            requested="string builtin method floor",
            fix=f"add StringValue method floor for `{operation.name}`",
        )

    def contains_with(self, operation, ctx):
        return operation.contains_string(self, ctx)

    def subscript_with(self, operation, ctx):
        return operation.subscript_string(self, ctx)

    def str_with(self, operation, ctx):
        return operation.str_string(self, ctx)

    def format_value_with(self, operation, ctx):
        return operation.format_string(self, ctx)

    def binary_operator_with(self, operation, ctx):
        return operation.binary_string(self, ctx)


def _call_method_gap(
    *,
    owner: str,
    blame: str,
    observed: str,
    requested: str,
    fix: str,
) -> NoReturn:
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
