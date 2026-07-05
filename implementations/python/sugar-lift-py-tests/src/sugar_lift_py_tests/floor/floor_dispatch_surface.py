from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

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


@runtime_checkable
class FloorDispatchSurface(Protocol):
    """Every registered floor must answer every declared operation method.

    The runtime law stays explicit dispatch through ``perform_operation``. This
    protocol makes the obligation surface type-visible: each answer is either a
    floor-owned reduction/effect arm or the inherited construction-gap arm.
    """

    def add_with(self, operation: Any, ctx: Any) -> Any: ...

    def async_context_manager_with(self, operation: Any, ctx: Any) -> Any: ...

    def async_iter_with(self, operation: Any, ctx: Any) -> Any: ...

    def async_next_with(self, operation: Any, ctx: Any) -> Any: ...

    def attribute_assign_with(self, operation: Any, ctx: Any) -> Any: ...

    def attribute_delete_with(self, operation: Any, ctx: Any) -> Any: ...

    def attribute_with(self, operation: Any, ctx: Any) -> Any: ...

    def await_with(self, operation: Any, ctx: Any) -> Any: ...

    def binary_operator_with(self, operation: Any, ctx: Any) -> Any: ...

    def bitwise_with(self, operation: Any, ctx: Any) -> Any: ...

    def call_method_with(self, operation: Any, ctx: Any) -> Any: ...

    def construct_sequence_with(self, operation: Any, ctx: Any) -> Any: ...

    def contains_with(self, operation: Any, ctx: Any) -> Any: ...

    def context_manager_with(self, operation: Any, ctx: Any) -> Any: ...

    def delitem_with(self, operation: Any, ctx: Any) -> Any: ...

    def descriptor_with(self, operation: Any, ctx: Any) -> Any: ...

    def format_value_with(self, operation: Any, ctx: Any) -> Any: ...

    def guard_with(self, operation: Any, ctx: Any) -> Any: ...

    def inplace_binary_operator_with(self, operation: Any, ctx: Any) -> Any: ...

    def map_with(self, operation: Any, ctx: Any) -> Any: ...

    def materialize_with(self, operation: Any, ctx: Any) -> Any: ...

    def merge_finally_with(self, operation: Any, ctx: Any) -> Any: ...

    def missing_with(self, operation: Any, ctx: Any) -> Any: ...

    def next_with(self, operation: Any, ctx: Any) -> Any: ...

    def project_callsite_with(self, operation: Any, ctx: Any) -> Any: ...

    def project_sequence_with(self, operation: Any, ctx: Any) -> Any: ...

    def reflected_binary_operator_with(self, operation: Any, ctx: Any) -> Any: ...

    def route_raises_with(self, operation: Any, ctx: Any) -> Any: ...

    def setitem_with(self, operation: Any, ctx: Any) -> Any: ...

    def str_with(self, operation: Any, ctx: Any) -> Any: ...

    def subscript_with(self, operation: Any, ctx: Any) -> Any: ...

    def unary_operator_with(self, operation: Any, ctx: Any) -> Any: ...


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
