from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue
from .object_field import ObjectField
from .object_method_value import ObjectMethodValue


@dataclass(frozen=True)
class ObjectValue(FloorValue):
    class_name: str
    fields: tuple[ObjectField, ...]
    methods: tuple[ObjectMethodValue, ...] = ()
    identity: str = ""

    def attribute_with(self, operation, ctx):
        return operation.attribute_object(self, ctx)

    def call_method_with(self, operation, ctx):
        del ctx
        return self.call_method_value(
            operation.name,
            operation.arguments,
            owner=operation.owner,
            blame=operation.blame,
        )

    def binary_operator_with(self, operation, ctx):
        del ctx
        method_name = _BINARY_DUNDER_METHODS.get(operation.operator)
        if method_name is None:
            return self._floor_gap(
                owner=operation.owner,
                blame=operation.blame,
                observed=f"{self.class_name}{operation.operator}{type(operation.right).__name__}",
                requested="object binary data-model method",
                fix=(
                    f"add ObjectValue data-model dispatch for operator "
                    f"`{operation.operator}`"
                ),
            )
        return self.call_method_value(
            method_name,
            (operation.right,),
            owner=operation.owner,
            blame=operation.blame,
        )

    def reflected_binary_operator_with(self, operation, ctx):
        del ctx
        method_name = _REFLECTED_BINARY_DUNDER_METHODS.get(operation.operator)
        if method_name is None:
            return self._floor_gap(
                owner=operation.owner,
                blame=operation.blame,
                observed=f"{type(operation.left).__name__}{operation.operator}{self.class_name}",
                requested="object reflected binary data-model method",
                fix=(
                    f"add ObjectValue reflected data-model dispatch for "
                    f"operator `{operation.operator}`"
                ),
            )
        return self.call_method_value(
            method_name,
            (operation.left,),
            owner=operation.owner,
            blame=operation.blame,
        )

    def call_method_value(
        self,
        name: str,
        arguments: tuple[FloorValue, ...],
        *,
        owner: str,
        blame: str,
    ):
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.outcome import Complete
        from sugar_lift_py_tests.sugar.floor_terms import floor_to_term

        for method in reversed(self.methods):
            if method.name != name:
                continue
            if not method.parameters:
                return self._floor_gap(
                    owner=owner,
                    blame=blame,
                    observed=f"{self.class_name}.{name}",
                    requested="method self parameter",
                    fix=f"add method binding sugar for `{self.class_name}.{name}`",
                )
            expected = len(method.parameters) - 1
            if len(arguments) != expected:
                return self._floor_gap(
                    owner=owner,
                    blame=blame,
                    observed=f"{self.class_name}.{name}",
                    requested=f"{expected} method arguments",
                    fix=(
                        f"add method argument binding sugar for "
                        f"`{self.class_name}.{name}`"
                    ),
                )
            target_name = f"{self.class_name}.{name}"
            arg_values = (self, *arguments)
            arg_terms = [
                floor_to_term(value, owner=f"{owner} method argument")
                for value in arg_values
            ]
            return Complete(
                CallSiteValue(
                    target_name=target_name,
                    arg_values=arg_values,
                    parameters=method.parameters,
                    term=ctor(f"call:{target_name}", arg_terms),
                    body=method.body,
                )
            )
        return self._floor_gap(
            owner=owner,
            blame=blame,
            observed=f"{self.class_name}.{name}",
            requested="constructor-bound method",
            fix=(
                f"define `{name}` on `{self.class_name}` or add the "
                "floor that owns this method"
            ),
        )

    def _floor_gap(
        self,
        *,
        owner: str,
        blame: str,
        observed: str,
        requested: str,
        fix: str,
    ) -> None:
        from sugar_lift_py_tests.factory import (
            FactoryAuditRow,
            FactoryGap,
            FactoryGapInfo,
        )

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


_BINARY_DUNDER_METHODS = {
    "==": "__eq__",
    "+": "__add__",
    "-": "__sub__",
    "*": "__mul__",
}

_REFLECTED_BINARY_DUNDER_METHODS = {
    "+": "__radd__",
    "-": "__rsub__",
    "*": "__rmul__",
}
