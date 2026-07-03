from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue


@dataclass(frozen=True)
class StringValue(FloorValue):
    value: str

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import str_const

        return str_const(self.value)

    def project_callsite_with(self, operation, ctx):
        return operation.project_literal(self, ctx)

    def call_method_with(self, operation, ctx):
        del ctx
        if operation.name == "__int__" and not operation.arguments:
            from sugar_lift_py_tests.floor.term_value import TermValue
            from sugar_lift_py_tests.outcome import Complete

            return Complete(TermValue(int(self.value)))
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

    def binary_operator_with(self, operation, ctx):
        return operation.binary_string(self, ctx)


def _call_method_gap(
    *,
    owner: str,
    blame: str,
    observed: str,
    requested: str,
    fix: str,
):
    from sugar_lift_py_tests.factory import FactoryAuditRow, FactoryGap, FactoryGapInfo

    info = FactoryGapInfo(
        owner=owner,
        blame=blame,
        observed=observed,
        requested=requested,
        fix=fix,
        gap_kind="Floor",
        gap_locus="construction",
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
