from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from sugar_lift_py_tests.context import FactoryBuildContext
    from sugar_lift_py_tests.ir import Formula
    from sugar_lift_py_tests.operations.add_operation import AddOperation
    from sugar_lift_py_tests.operations.async_context_manager_operation import (
        AsyncContextManagerOperation,
    )
    from sugar_lift_py_tests.operations.async_iterator_operation import (
        AsyncIteratorOperation,
        AsyncNextOperation,
    )
    from sugar_lift_py_tests.operations.attribute_delete_operation import (
        AttributeDeleteOperation,
    )
    from sugar_lift_py_tests.operations.attribute_lookup_operation import (
        AttributeLookupOperation,
    )
    from sugar_lift_py_tests.operations.attribute_mutation_operation import (
        AttributeMutationOperation,
    )
    from sugar_lift_py_tests.operations.await_operation import AwaitOperation
    from sugar_lift_py_tests.operations.binary_operator_operation import (
        BinaryOperatorOperation,
    )
    from sugar_lift_py_tests.operations.bitwise_operation import BitwiseOperation
    from sugar_lift_py_tests.operations.callable_map_operation import (
        CallableMapOperation,
    )
    from sugar_lift_py_tests.operations.callsite_projection_operation import (
        CallsiteProjectionOperation,
    )
    from sugar_lift_py_tests.operations.contains_operation import ContainsOperation
    from sugar_lift_py_tests.operations.context_manager_operation import (
        ContextManagerOperation,
    )
    from sugar_lift_py_tests.operations.control_flow_guard_operation import (
        ControlFlowGuardOperation,
    )
    from sugar_lift_py_tests.operations.delitem_operation import DelItemOperation
    from sugar_lift_py_tests.operations.descriptor_operation import DescriptorOperation
    from sugar_lift_py_tests.operations.dict_missing_operation import (
        DictMissingOperation,
    )
    from sugar_lift_py_tests.operations.finally_fallthrough_operation import (
        FinallyFallthroughOperation,
    )
    from sugar_lift_py_tests.operations.format_value_operation import (
        FormatValueOperation,
    )
    from sugar_lift_py_tests.operations.inplace_binary_operator_operation import (
        InplaceBinaryOperatorOperation,
    )
    from sugar_lift_py_tests.operations.map_operation import MapOperation
    from sugar_lift_py_tests.operations.materialize_operation import (
        MaterializeOperation,
    )
    from sugar_lift_py_tests.operations.method_call_operation import (
        MethodCallOperation,
    )
    from sugar_lift_py_tests.operations.next_operation import NextOperation
    from sugar_lift_py_tests.operations.reflected_binary_operator_operation import (
        ReflectedBinaryOperatorOperation,
    )
    from sugar_lift_py_tests.operations.route_raises_operation import (
        RouteRaisesOperation,
    )
    from sugar_lift_py_tests.operations.sequence_construction_operation import (
        SequenceConstructionOperation,
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

FLOOR_OPERATION_METHOD_NAMES = (
    "add_with",
    "async_context_manager_with",
    "async_iter_with",
    "async_next_with",
    "attribute_assign_with",
    "attribute_delete_with",
    "attribute_with",
    "await_with",
    "binary_operator_with",
    "bitwise_with",
    "call_method_with",
    "construct_sequence_with",
    "contains_with",
    "context_manager_with",
    "delitem_with",
    "descriptor_with",
    "format_value_with",
    "guard_with",
    "inplace_binary_operator_with",
    "map_with",
    "materialize_with",
    "merge_finally_with",
    "missing_with",
    "next_with",
    "project_callsite_with",
    "project_sequence_with",
    "reflected_binary_operator_with",
    "route_raises_with",
    "setitem_with",
    "str_with",
    "subscript_with",
    "unary_operator_with",
)


class AddFloor(Protocol):
    def add_with(
        self, operation: AddOperation, ctx: FactoryBuildContext | None
    ) -> Outcome: ...


class AsyncContextManagerFloor(Protocol):
    def async_context_manager_with(
        self,
        operation: AsyncContextManagerOperation,
        ctx: FactoryBuildContext | None,
    ) -> Outcome: ...


class AsyncIteratorFloor(Protocol):
    def async_iter_with(
        self, operation: AsyncIteratorOperation, ctx: FactoryBuildContext | None
    ) -> Outcome: ...


class AsyncNextFloor(Protocol):
    def async_next_with(
        self, operation: AsyncNextOperation, ctx: FactoryBuildContext | None
    ) -> Outcome: ...


class AttributeAssignFloor(Protocol):
    def attribute_assign_with(
        self,
        operation: AttributeMutationOperation,
        ctx: FactoryBuildContext | None,
    ) -> Outcome: ...


class AttributeDeleteFloor(Protocol):
    def attribute_delete_with(
        self, operation: AttributeDeleteOperation, ctx: FactoryBuildContext | None
    ) -> Outcome: ...


class AttributeLookupFloor(Protocol):
    def attribute_with(
        self, operation: AttributeLookupOperation, ctx: FactoryBuildContext | None
    ) -> Outcome: ...


class AwaitFloor(Protocol):
    def await_with(
        self, operation: AwaitOperation, ctx: FactoryBuildContext | None
    ) -> Outcome: ...


class BinaryOperatorFloor(Protocol):
    def binary_operator_with(
        self,
        operation: BinaryOperatorOperation,
        ctx: FactoryBuildContext | None,
    ) -> Outcome: ...


class BitwiseFloor(Protocol):
    def bitwise_with(
        self, operation: BitwiseOperation, ctx: FactoryBuildContext | None
    ) -> Outcome: ...


class MethodCallFloor(Protocol):
    def call_method_with(
        self, operation: MethodCallOperation, ctx: FactoryBuildContext | None
    ) -> Outcome: ...


class SequenceConstructionFloor(Protocol):
    def construct_sequence_with(
        self,
        operation: SequenceConstructionOperation,
        ctx: FactoryBuildContext | None,
    ) -> Outcome: ...


class ContainsFloor(Protocol):
    def contains_with(
        self, operation: ContainsOperation, ctx: FactoryBuildContext | None
    ) -> Outcome: ...


class ContextManagerFloor(Protocol):
    def context_manager_with(
        self, operation: ContextManagerOperation, ctx: FactoryBuildContext | None
    ) -> Outcome: ...


class DelItemFloor(Protocol):
    def delitem_with(
        self, operation: DelItemOperation, ctx: FactoryBuildContext | None
    ) -> Outcome: ...


class DescriptorFloor(Protocol):
    def descriptor_with(
        self, operation: DescriptorOperation, ctx: FactoryBuildContext | None
    ) -> Outcome: ...


class FormatValueFloor(Protocol):
    def format_value_with(
        self, operation: FormatValueOperation, ctx: FactoryBuildContext | None
    ) -> Outcome: ...


class ControlFlowGuardFloor(Protocol):
    def guard_with(
        self, operation: ControlFlowGuardOperation, ctx: FactoryBuildContext | None
    ) -> Outcome: ...


class InplaceBinaryOperatorFloor(Protocol):
    def inplace_binary_operator_with(
        self,
        operation: InplaceBinaryOperatorOperation,
        ctx: FactoryBuildContext | None,
    ) -> Outcome: ...


class MapFloor(Protocol):
    def map_with(
        self,
        operation: CallableMapOperation | MapOperation,
        ctx: FactoryBuildContext | None,
    ) -> Outcome: ...


class MaterializeFloor(Protocol):
    def materialize_with(
        self, operation: MaterializeOperation, ctx: FactoryBuildContext | None
    ) -> Outcome: ...


class FinallyFallthroughFloor(Protocol):
    def merge_finally_with(
        self,
        operation: FinallyFallthroughOperation,
        ctx: FactoryBuildContext | None,
    ) -> Outcome: ...


class DictMissingFloor(Protocol):
    def missing_with(
        self, operation: DictMissingOperation, ctx: FactoryBuildContext | None
    ) -> Outcome: ...


class NextFloor(Protocol):
    def next_with(
        self, operation: NextOperation, ctx: FactoryBuildContext | None
    ) -> Outcome: ...


class CallsiteProjectionFloor(Protocol):
    def project_callsite_with(
        self,
        operation: CallsiteProjectionOperation,
        ctx: FactoryBuildContext | None,
    ) -> Formula | None: ...


class SequenceProjectionFloor(Protocol):
    def project_sequence_with(
        self,
        operation: SequenceProjectionOperation,
        ctx: FactoryBuildContext | None,
    ) -> Outcome: ...


class ReflectedBinaryOperatorFloor(Protocol):
    def reflected_binary_operator_with(
        self,
        operation: ReflectedBinaryOperatorOperation,
        ctx: FactoryBuildContext | None,
    ) -> Outcome: ...


class RouteRaisesFloor(Protocol):
    def route_raises_with(
        self, operation: RouteRaisesOperation, ctx: FactoryBuildContext | None
    ) -> Outcome: ...


class SetItemFloor(Protocol):
    def setitem_with(
        self, operation: SetItemOperation, ctx: FactoryBuildContext | None
    ) -> Outcome: ...


class StrCoercionFloor(Protocol):
    def str_with(
        self, operation: StrCoercionOperation, ctx: FactoryBuildContext | None
    ) -> Outcome: ...


class SubscriptFloor(Protocol):
    def subscript_with(
        self, operation: SubscriptOperation, ctx: FactoryBuildContext | None
    ) -> Outcome: ...


class UnaryOperatorFloor(Protocol):
    def unary_operator_with(
        self, operation: UnaryOperatorOperation, ctx: FactoryBuildContext | None
    ) -> Outcome: ...


@runtime_checkable
class FloorDispatchSurface(
    AddFloor,
    AsyncContextManagerFloor,
    AsyncIteratorFloor,
    AsyncNextFloor,
    AttributeAssignFloor,
    AttributeDeleteFloor,
    AttributeLookupFloor,
    AwaitFloor,
    BinaryOperatorFloor,
    BitwiseFloor,
    MethodCallFloor,
    SequenceConstructionFloor,
    ContainsFloor,
    ContextManagerFloor,
    DelItemFloor,
    DescriptorFloor,
    FormatValueFloor,
    ControlFlowGuardFloor,
    InplaceBinaryOperatorFloor,
    MapFloor,
    MaterializeFloor,
    FinallyFallthroughFloor,
    DictMissingFloor,
    NextFloor,
    CallsiteProjectionFloor,
    SequenceProjectionFloor,
    ReflectedBinaryOperatorFloor,
    RouteRaisesFloor,
    SetItemFloor,
    StrCoercionFloor,
    SubscriptFloor,
    UnaryOperatorFloor,
    Protocol,
):
    """Every registered floor must answer every declared operation method.

    The runtime law stays explicit dispatch through ``perform_operation``. This
    protocol makes the obligation surface type-visible: each per-operation base
    (``AddFloor``, ``BitwiseFloor``, ...) pins the SIGNATURE for its method, not
    just its presence, so a floor with the right method name and the wrong
    operation/ctx/return shape reds pyright instead of passing silently.
    """


def require_floor_dispatch_surface(
    cls: type[FloorDispatchSurface],
) -> type[FloorDispatchSurface]:
    missing = tuple(
        name for name in FLOOR_OPERATION_METHOD_NAMES if not hasattr(cls, name)
    )
    if missing:
        joined = ", ".join(missing)
        raise TypeError(
            f"{cls.__name__} is missing floor operation method(s): {joined}"
        )
    return cls
