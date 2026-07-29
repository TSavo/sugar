from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from sugar_lift_py_tests.context import ReduceContext
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
    from sugar_lift_py_tests.callable_application import CallableApplication
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
    from sugar_lift_py_tests.operations.iterator_operation import IteratorOperation
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
    "callable_application_with",
    "call_method_with",
    "construct_sequence_with",
    "contains_with",
    "context_manager_with",
    "delitem_with",
    "descriptor_with",
    "format_value_with",
    "guard_with",
    "inplace_binary_operator_with",
    "iter_with",
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
        self, operation: AddOperation, ctx: ReduceContext | None
    ) -> Outcome: ...


class AsyncContextManagerFloor(Protocol):
    def async_context_manager_with(
        self,
        operation: AsyncContextManagerOperation,
        ctx: ReduceContext | None,
    ) -> Outcome: ...


class AsyncIteratorFloor(Protocol):
    def async_iter_with(
        self, operation: AsyncIteratorOperation, ctx: ReduceContext | None
    ) -> Outcome: ...


class AsyncNextFloor(Protocol):
    def async_next_with(
        self, operation: AsyncNextOperation, ctx: ReduceContext | None
    ) -> Outcome: ...


class AttributeAssignFloor(Protocol):
    def attribute_assign_with(
        self,
        operation: AttributeMutationOperation,
        ctx: ReduceContext | None,
    ) -> Outcome: ...


class AttributeDeleteFloor(Protocol):
    def attribute_delete_with(
        self, operation: AttributeDeleteOperation, ctx: ReduceContext | None
    ) -> Outcome: ...


class AttributeLookupFloor(Protocol):
    def attribute_with(
        self, operation: AttributeLookupOperation, ctx: ReduceContext | None
    ) -> Outcome: ...


class AwaitFloor(Protocol):
    def await_with(
        self, operation: AwaitOperation, ctx: ReduceContext | None
    ) -> Outcome: ...


class BinaryOperatorFloor(Protocol):
    def binary_operator_with(
        self,
        operation: BinaryOperatorOperation,
        ctx: ReduceContext | None,
    ) -> Outcome: ...


class BitwiseFloor(Protocol):
    def bitwise_with(
        self, operation: BitwiseOperation, ctx: ReduceContext | None
    ) -> Outcome: ...


class CallableApplicationFloor(Protocol):
    def callable_application_with(
        self,
        operation: CallableApplication,
        ctx: ReduceContext | None,
    ) -> Outcome: ...


class MethodCallFloor(Protocol):
    def call_method_with(
        self, operation: MethodCallOperation, ctx: ReduceContext | None
    ) -> Outcome: ...


class SequenceConstructionFloor(Protocol):
    def construct_sequence_with(
        self,
        operation: SequenceConstructionOperation,
        ctx: ReduceContext | None,
    ) -> Outcome: ...


class ContainsFloor(Protocol):
    def contains_with(
        self, operation: ContainsOperation, ctx: ReduceContext | None
    ) -> Outcome: ...


class ContextManagerFloor(Protocol):
    def context_manager_with(
        self, operation: ContextManagerOperation, ctx: ReduceContext | None
    ) -> Outcome: ...


class DelItemFloor(Protocol):
    def delitem_with(
        self, operation: DelItemOperation, ctx: ReduceContext | None
    ) -> Outcome: ...


class DescriptorFloor(Protocol):
    def descriptor_with(
        self, operation: DescriptorOperation, ctx: ReduceContext | None
    ) -> Outcome: ...


class FormatValueFloor(Protocol):
    def format_value_with(
        self, operation: FormatValueOperation, ctx: ReduceContext | None
    ) -> Outcome: ...


class ControlFlowGuardFloor(Protocol):
    def guard_with(
        self, operation: ControlFlowGuardOperation, ctx: ReduceContext | None
    ) -> Outcome: ...


class InplaceBinaryOperatorFloor(Protocol):
    def inplace_binary_operator_with(
        self,
        operation: InplaceBinaryOperatorOperation,
        ctx: ReduceContext | None,
    ) -> Outcome: ...


class MapFloor(Protocol):
    def map_with(
        self,
        operation: CallableMapOperation | MapOperation,
        ctx: ReduceContext | None,
    ) -> Outcome: ...


class MaterializeFloor(Protocol):
    def materialize_with(
        self, operation: MaterializeOperation, ctx: ReduceContext | None
    ) -> Outcome: ...


class FinallyFallthroughFloor(Protocol):
    def merge_finally_with(
        self,
        operation: FinallyFallthroughOperation,
        ctx: ReduceContext | None,
    ) -> Outcome: ...


class DictMissingFloor(Protocol):
    def missing_with(
        self, operation: DictMissingOperation, ctx: ReduceContext | None
    ) -> Outcome: ...


class IteratorFloor(Protocol):
    def iter_with(
        self, operation: IteratorOperation, ctx: ReduceContext | None
    ) -> Outcome: ...


class NextFloor(Protocol):
    def next_with(
        self, operation: NextOperation, ctx: ReduceContext | None
    ) -> Outcome: ...


class CallsiteProjectionFloor(Protocol):
    def project_callsite_with(
        self,
        operation: CallsiteProjectionOperation,
        ctx: ReduceContext | None,
    ) -> Formula | None: ...


class SequenceProjectionFloor(Protocol):
    def project_sequence_with(
        self,
        operation: SequenceProjectionOperation,
        ctx: ReduceContext | None,
    ) -> Outcome: ...


class ReflectedBinaryOperatorFloor(Protocol):
    def reflected_binary_operator_with(
        self,
        operation: ReflectedBinaryOperatorOperation,
        ctx: ReduceContext | None,
    ) -> Outcome: ...


class RouteRaisesFloor(Protocol):
    def route_raises_with(
        self, operation: RouteRaisesOperation, ctx: ReduceContext | None
    ) -> Outcome: ...


class SetItemFloor(Protocol):
    def setitem_with(
        self, operation: SetItemOperation, ctx: ReduceContext | None
    ) -> Outcome: ...


class StrCoercionFloor(Protocol):
    def str_with(
        self, operation: StrCoercionOperation, ctx: ReduceContext | None
    ) -> Outcome: ...


class SubscriptFloor(Protocol):
    def subscript_with(
        self, operation: SubscriptOperation, ctx: ReduceContext | None
    ) -> Outcome: ...


class UnaryOperatorFloor(Protocol):
    def unary_operator_with(
        self, operation: UnaryOperatorOperation, ctx: ReduceContext | None
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
    CallableApplicationFloor,
    MethodCallFloor,
    SequenceConstructionFloor,
    ContainsFloor,
    ContextManagerFloor,
    DelItemFloor,
    DescriptorFloor,
    FormatValueFloor,
    ControlFlowGuardFloor,
    InplaceBinaryOperatorFloor,
    IteratorFloor,
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
