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
    class_fields: tuple[ObjectField, ...] = ()
    identity: str = ""

    def attribute_with(self, operation, ctx):
        return operation.attribute_object(self, ctx)

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "py.object.identity",
            [str_const(self.class_name), str_const(self.identity)],
        )

    def attribute_assign_with(self, operation, ctx):
        return operation.assign_object(self, ctx)

    def attribute_delete_with(self, operation, ctx):
        return operation.delete_object(self, ctx)

    def call_method_with(self, operation, ctx):
        return self.call_method_value(
            operation.name,
            operation.arguments,
            owner=operation.owner,
            blame=operation.blame,
            ctx=ctx,
        )

    def descriptor_with(self, operation, ctx):
        return operation.descriptor_object(self, ctx)

    def contains_with(self, operation, ctx):
        del ctx
        return self.call_method_value(
            "__contains__",
            (operation.item,),
            owner=operation.owner,
            blame=operation.blame,
        )

    def context_manager_with(self, operation, ctx):
        return operation.context_object(self, ctx)

    def async_context_manager_with(self, operation, ctx):
        return operation.async_context_object(self, ctx)

    def await_with(self, operation, ctx):
        return operation.await_object(self, ctx)

    def async_iter_with(self, operation, ctx):
        return operation.async_iter_object(self, ctx)

    def async_next_with(self, operation, ctx):
        return operation.async_next_object(self, ctx)

    def next_with(self, operation, ctx):
        del ctx
        return self.call_method_value(
            "__next__",
            (),
            owner=operation.owner,
            blame=operation.blame,
        )

    def subscript_with(self, operation, ctx):
        return operation.subscript_object(self, ctx)

    def setitem_with(self, operation, ctx):
        return operation.setitem_object(self, ctx)

    def delitem_with(self, operation, ctx):
        return operation.delitem_object(self, ctx)

    def missing_with(self, operation, ctx):
        return operation.missing_object(self, ctx)

    def str_with(self, operation, ctx):
        return operation.str_object(self, ctx)

    def bitwise_with(self, operation, ctx):
        del ctx
        method_name = _BITWISE_DUNDER_METHODS.get(operation.operator)
        if method_name is None:
            return self._floor_gap(
                owner=operation.owner,
                blame=operation.blame,
                observed=f"{self.class_name}{operation.operator}{type(operation.operand).__name__}",
                requested="object bitwise data-model method",
                fix=(
                    f"add ObjectValue data-model dispatch for bitwise "
                    f"operator `{operation.operator}`"
                ),
            )
        return self.call_method_value(
            method_name,
            (operation.operand,),
            owner=operation.owner,
            blame=operation.blame,
        )

    def project_sequence_with(self, operation, ctx):
        return operation.project_object(self, ctx)

    def binary_operator_with(self, operation, ctx):
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
        if (
            operation.operator == "=="
            and isinstance(operation.right, ObjectValue)
            and not self.has_method(method_name)
        ):
            from sugar_lift_py_tests.floor.bool_value import BoolValue
            from sugar_lift_py_tests.outcome import Complete

            if not self.identity or not operation.right.identity:
                return self._floor_gap(
                    owner=operation.owner,
                    blame=operation.blame,
                    observed=f"{self.class_name}=={operation.right.class_name}",
                    requested="object identity equality",
                    fix=(
                        "construct ObjectValue identities before applying "
                        "method-less equality"
                    ),
                )
            return Complete(
                BoolValue(
                    self.class_name == operation.right.class_name
                    and self.identity == operation.right.identity
                )
            )
        return self.call_method_value(
            method_name,
            (operation.right,),
            owner=operation.owner,
            blame=operation.blame,
            ctx=ctx,
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

    def inplace_binary_operator_with(self, operation, ctx):
        del ctx
        method_name = _INPLACE_BINARY_DUNDER_METHODS.get(operation.operator)
        if method_name is None:
            return self._floor_gap(
                owner=operation.owner,
                blame=operation.blame,
                observed=f"{self.class_name}{operation.operator}={type(operation.right).__name__}",
                requested="object in-place binary data-model method",
                fix=(
                    f"add ObjectValue in-place data-model dispatch for "
                    f"operator `{operation.operator}`"
                ),
            )
        return self.call_method_value(
            method_name,
            (operation.right,),
            owner=operation.owner,
            blame=operation.blame,
        )

    def unary_operator_with(self, operation, ctx):
        del ctx
        method_name = _UNARY_DUNDER_METHODS.get(operation.operator)
        if method_name is None:
            return self._floor_gap(
                owner=operation.owner,
                blame=operation.blame,
                observed=f"{operation.operator}({self.class_name})",
                requested="object unary data-model method",
                fix=(
                    f"add ObjectValue unary data-model dispatch for "
                    f"operator `{operation.operator}`"
                ),
            )
        return self.call_method_value(
            method_name,
            (),
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
        ctx: object | None = None,
    ):
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
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
            call_value = CallSiteValue(
                target_name=target_name,
                arg_values=arg_values,
                parameters=method.parameters,
                term=ctor(f"call:{target_name}", arg_terms),
                body=method.body,
            )
            if not any(
                isinstance(value, (SymbolicValue, CallSiteValue))
                for value in arg_values
            ):
                sink = getattr(ctx, "dig_sink", None) if ctx is not None else None
                if sink is not None:
                    sink.append(call_value)
            return Complete(call_value)
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

    def has_method(self, name: str) -> bool:
        return any(method.name == name for method in self.methods)

    def class_field_value(self, name: str) -> FloorValue | None:
        for field in reversed(self.class_fields):
            if field.name == name:
                return field.value
        return None

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
            GapKind,
            GapLocus,
        )

        info = FactoryGapInfo(
            owner=owner,
            blame=blame,
            observed=observed,
            requested=requested,
            fix=fix,
            gap_kind=(
                GapKind.CONSTRUCTOR
                if requested.startswith("constructor-bound ")
                else GapKind.FLOOR
            ),
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


_BINARY_DUNDER_METHODS = {
    "==": "__eq__",
    "+": "__add__",
    "-": "__sub__",
    "*": "__mul__",
    "/": "__truediv__",
    "//": "__floordiv__",
    "%": "__mod__",
    "divmod": "__divmod__",
    "**": "__pow__",
    "@": "__matmul__",
}

_BITWISE_DUNDER_METHODS = {
    "&": "__and__",
    "|": "__or__",
    "^": "__xor__",
    "<<": "__lshift__",
    ">>": "__rshift__",
}

_REFLECTED_BINARY_DUNDER_METHODS = {
    "+": "__radd__",
    "-": "__rsub__",
    "*": "__rmul__",
    "/": "__rtruediv__",
    "//": "__rfloordiv__",
    "%": "__rmod__",
    "divmod": "__rdivmod__",
    "**": "__rpow__",
    "@": "__rmatmul__",
    "&": "__rand__",
    "|": "__ror__",
    "^": "__rxor__",
    "<<": "__rlshift__",
    ">>": "__rrshift__",
}

_INPLACE_BINARY_DUNDER_METHODS = {
    "+": "__iadd__",
    "-": "__isub__",
    "*": "__imul__",
    "/": "__itruediv__",
    "//": "__ifloordiv__",
    "%": "__imod__",
    "**": "__ipow__",
    "@": "__imatmul__",
    "&": "__iand__",
    "|": "__ior__",
    "^": "__ixor__",
    "<<": "__ilshift__",
    ">>": "__irshift__",
}

_UNARY_DUNDER_METHODS = {
    "py.pos": "__pos__",
    "py.neg": "__neg__",
    "py.invert": "__invert__",
}
