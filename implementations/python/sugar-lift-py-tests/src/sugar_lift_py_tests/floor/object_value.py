from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, NoReturn

from .floor_value import FloorValue
from .object_field import ObjectField
from .object_method_value import ObjectMethodValue
from sugar_lift_py_tests.factory.factory_audit_row import FactoryAuditStatus

if TYPE_CHECKING:
    from sugar_lift_py_tests.context import FactoryBuildContext
    from sugar_lift_py_tests.operations.attribute_delete_operation import (
        AttributeDeleteOperation,
    )
    from sugar_lift_py_tests.operations.attribute_lookup_operation import (
        AttributeLookupOperation,
    )
    from sugar_lift_py_tests.operations.attribute_mutation_operation import (
        AttributeMutationOperation,
    )
    from sugar_lift_py_tests.operations.async_context_manager_operation import (
        AsyncContextManagerOperation,
    )
    from sugar_lift_py_tests.operations.async_iterator_operation import (
        AsyncIteratorOperation,
        AsyncNextOperation,
    )
    from sugar_lift_py_tests.operations.await_operation import AwaitOperation
    from sugar_lift_py_tests.operations.binary_operator_operation import (
        BinaryOperatorOperation,
    )
    from sugar_lift_py_tests.operations.bitwise_operation import BitwiseOperation
    from sugar_lift_py_tests.operations.context_manager_operation import (
        ContextManagerOperation,
    )
    from sugar_lift_py_tests.operations.contains_operation import ContainsOperation
    from sugar_lift_py_tests.operations.delitem_operation import DelItemOperation
    from sugar_lift_py_tests.operations.descriptor_operation import DescriptorOperation
    from sugar_lift_py_tests.operations.dict_missing_operation import (
        DictMissingOperation,
    )
    from sugar_lift_py_tests.operations.inplace_binary_operator_operation import (
        InplaceBinaryOperatorOperation,
    )
    from sugar_lift_py_tests.operations.method_call_operation import (
        MethodCallOperation,
    )
    from sugar_lift_py_tests.operations.next_operation import NextOperation
    from sugar_lift_py_tests.operations.reflected_binary_operator_operation import (
        ReflectedBinaryOperatorOperation,
    )
    from sugar_lift_py_tests.operations.sequence_projection_operation import (
        SequenceProjectionOperation,
    )
    from sugar_lift_py_tests.operations.setitem_operation import SetItemOperation
    from sugar_lift_py_tests.operations.str_coercion_operation import (
        StrCoercionOperation,
    )
    from sugar_lift_py_tests.operations.subscript_operation import SubscriptOperation
    from sugar_lift_py_tests.operations.unary_operator_operation import (
        UnaryOperatorOperation,
    )
    from sugar_lift_py_tests.outcome import Outcome


@dataclass(frozen=True)
class ObjectValue(FloorValue):
    class_name: str
    fields: tuple[ObjectField, ...]
    methods: tuple[ObjectMethodValue, ...] = ()
    class_fields: tuple[ObjectField, ...] = ()
    identity: str = ""

    def format_data_model(self, spec, site, ctx):
        return self.call_method_value(
            "__format__",
            (spec,),
            owner="FormatDunderCallSugar",
            blame=str(site),
            ctx=ctx,
        )

    def attribute_with(
        self, operation: AttributeLookupOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        return operation.attribute_object(self, ctx)

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "py.object.identity",
            [str_const(self.class_name), str_const(self.identity)],
        )

    def attribute_assign_with(
        self, operation: AttributeMutationOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        return operation.assign_object(self, ctx)

    def attribute_delete_with(
        self, operation: AttributeDeleteOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        return operation.delete_object(self, ctx)

    def call_method_with(
        self, operation: MethodCallOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        return self.call_method_value(
            operation.name,
            operation.arguments,
            owner=operation.owner,
            blame=operation.blame,
            ctx=ctx,
        )

    def descriptor_with(
        self, operation: DescriptorOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        return operation.descriptor_object(self, ctx)

    def contains_with(
        self, operation: ContainsOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        del ctx
        return self.call_method_value(
            "__contains__",
            (operation.item,),
            owner=operation.owner,
            blame=operation.blame,
        )

    def context_manager_with(
        self, operation: ContextManagerOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        return operation.context_object(self, ctx)

    def async_context_manager_with(
        self,
        operation: AsyncContextManagerOperation,
        ctx: FactoryBuildContext | None,
    ) -> Outcome:
        return operation.async_context_object(self, ctx)

    def await_with(
        self, operation: AwaitOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        return operation.await_object(self, ctx)

    def async_iter_with(
        self, operation: AsyncIteratorOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        return operation.async_iter_object(self, ctx)

    def async_next_with(
        self, operation: AsyncNextOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        return operation.async_next_object(self, ctx)

    def next_with(
        self, operation: NextOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        del ctx
        return self.call_method_value(
            "__next__",
            (),
            owner=operation.owner,
            blame=operation.blame,
        )

    def subscript_with(
        self, operation: SubscriptOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        return operation.subscript_object(self, ctx)

    def setitem_with(
        self, operation: SetItemOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        return operation.setitem_object(self, ctx)

    def delitem_with(
        self, operation: DelItemOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        return operation.delitem_object(self, ctx)

    def missing_with(
        self, operation: DictMissingOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        return operation.missing_object(self, ctx)

    def str_with(
        self, operation: StrCoercionOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        return operation.str_object(self, ctx)

    def bitwise_with(
        self, operation: BitwiseOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
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

    def project_sequence_with(
        self, operation: SequenceProjectionOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        return operation.project_object(self, ctx)

    def binary_operator_with(
        self,
        operation: BinaryOperatorOperation,
        ctx: FactoryBuildContext | None,
    ) -> Outcome:
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
            return self._floor_gap(
                owner=operation.owner,
                blame=operation.blame,
                observed=f"{self.class_name}=={operation.right.class_name}",
                requested="object identity equality",
                fix="lift method-less object identity equality",
            )
        return self.call_method_value(
            method_name,
            (operation.right,),
            owner=operation.owner,
            blame=operation.blame,
            ctx=ctx,
        )

    def reflected_binary_operator_with(
        self,
        operation: ReflectedBinaryOperatorOperation,
        ctx: FactoryBuildContext | None,
    ) -> Outcome:
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

    def inplace_binary_operator_with(
        self,
        operation: InplaceBinaryOperatorOperation,
        ctx: FactoryBuildContext | None,
    ) -> Outcome:
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

    def unary_operator_with(
        self, operation: UnaryOperatorOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
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
        ctx: Any | None = None,
    ) -> Outcome:
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
                term=ctor(
                    f"call:{target_name}",
                    arg_terms,
                    symbol_kind="contract-target",
                ),
                body=method.body,
            )
            if not any(
                isinstance(value, (SymbolicValue, CallSiteValue))
                for value in arg_values
            ):
                sink = ctx.dig_sink if ctx is not None else None
                if sink is not None:
                    sink.append(call_value)
            return Complete(call_value)
        return self._floor_gap(
            owner=owner,
            blame=blame,
            observed=f"{self.class_name}.{name}",
            requested="constructor-bound method",
            fix=f"construct a diggable body for `{self.class_name}.{name}`",
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
    ) -> NoReturn:
        from sugar_lift_py_tests.factory import (
            FactoryAuditRow,
            factory_panic,
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
        factory_panic(
            info,
            FactoryAuditRow(
                role=requested,
                status=FactoryAuditStatus.FLOOR_GAP,
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
