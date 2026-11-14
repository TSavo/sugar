from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from sugar_lift_py_tests.context import ReduceContext
    from sugar_lift_py_tests.callable_application import CallableApplication
    from sugar_lift_py_tests.operations.inplace_binary_operator_operation import (
        InplaceBinaryOperatorOperation,
    )
    from sugar_lift_py_tests.operations.iterator_operation import IteratorOperation
    from sugar_lift_py_tests.operations.next_operation import NextOperation
    from sugar_lift_py_tests.operations.sequence_projection_operation import (
        SequenceProjectionOperation,
    )
    from sugar_lift_py_tests.operations.subscript_operation import SubscriptOperation
    from sugar_lift_py_tests.outcome import ExitSet

FLOOR_OPERATION_METHOD_NAMES = (
    "callable_application_with",
    "inplace_binary_operator_with",
    "iter_with",
    "next_with",
    "project_sequence_with",
    "subscript_with",
)


class CallableApplicationFloor(Protocol):
    def callable_application_with(
        self,
        operation: CallableApplication,
        ctx: ReduceContext | None,
    ) -> ExitSet: ...


class InplaceBinaryOperatorFloor(Protocol):
    def inplace_binary_operator_with(
        self,
        operation: InplaceBinaryOperatorOperation,
        ctx: ReduceContext | None,
    ) -> ExitSet: ...


class IteratorFloor(Protocol):
    def iter_with(
        self, operation: IteratorOperation, ctx: ReduceContext | None
    ) -> ExitSet: ...


class NextFloor(Protocol):
    def next_with(
        self, operation: NextOperation, ctx: ReduceContext | None
    ) -> ExitSet: ...


class SequenceProjectionFloor(Protocol):
    def project_sequence_with(
        self,
        operation: SequenceProjectionOperation,
        ctx: ReduceContext | None,
    ) -> ExitSet: ...


class SubscriptFloor(Protocol):
    def subscript_with(
        self, operation: SubscriptOperation, ctx: ReduceContext | None
    ) -> ExitSet: ...


@runtime_checkable
class FloorDispatchSurface(
    CallableApplicationFloor,
    InplaceBinaryOperatorFloor,
    IteratorFloor,
    NextFloor,
    SequenceProjectionFloor,
    SubscriptFloor,
    Protocol,
):
    """Every registered floor must answer every declared operation method.

    Each operation submits itself to its receiver by ``method_name``. This
    protocol makes the obligation surface type-visible: each per-operation base
    (``IteratorFloor``, ``SubscriptFloor``, ...) pins the SIGNATURE for its
    method, not just its presence, so a floor with the right method name and
    the wrong operation/ctx/return shape reds pyright instead of passing
    silently. Only operations that exist are declared here.
    """


def require_floor_dispatch_surface(
    cls: type[FloorDispatchSurface],
) -> type[FloorDispatchSurface]:
    missing = tuple(
        name for name in FLOOR_OPERATION_METHOD_NAMES if not hasattr(cls, name)
    )
    if missing:
        joined = ", ".join(missing)
        from sugar_lift_py_tests.gap.panic import construction_panic_gap

        construction_panic_gap(
            owner="require_floor_dispatch_surface",
            blame=cls.__name__,
            observed=f"{cls.__name__} is missing floor operation method(s): {joined}",
            requested="every FLOOR_OPERATION_METHOD_NAMES method present on the floor class",
            fix=f"implement missing methods on {cls.__name__}: {joined}",
        )
    return cls
