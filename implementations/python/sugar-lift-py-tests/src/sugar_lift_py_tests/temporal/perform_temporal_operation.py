from __future__ import annotations

from typing import Any

from .temporal_context import TemporalContext
from sugar_lift_py_tests.gap.audit_row import FactoryAuditStatus

_DECLARED_OPERATION_MODULE = "sugar_lift_py_tests.temporal."


def _operation_method_name(*, owner: str, blame: str, operation: object) -> str:
    from sugar_lift_py_tests.gap.panic import factory_panic
    from sugar_lift_py_tests.gap.info import FactoryGapInfo, GapKind, GapLocus

    operation_name = type(operation).__name__
    method_name = getattr(operation, "method_name", None)
    if isinstance(method_name, str):
        return method_name
    info = FactoryGapInfo(
        owner=owner,
        blame=blame,
        observed=operation_name,
        requested="method_name",
        fix=(
            f"declare {operation_name}.method_name as a ClassVar[str] "
            "owned by the operation"
        ),
        gap_kind=GapKind.OPERATION,
        gap_locus=GapLocus.METHOD_NAME,
    )
    factory_panic(info)


def _is_declared_operation(operation: object) -> bool:
    return type(operation).__module__.startswith(_DECLARED_OPERATION_MODULE)


def _missing_temporal_floor_gap(
    *,
    owner: str,
    blame: str,
    receiver: TemporalContext,
    method_name: str,
):
    from sugar_lift_py_tests.gap.panic import factory_panic
    from sugar_lift_py_tests.gap.info import FactoryGapInfo, GapKind, GapLocus

    observed = type(receiver).__name__
    info = FactoryGapInfo(
        owner=owner,
        blame=blame,
        observed=observed,
        requested=method_name,
        fix=(
            f"add {method_name} to {observed} or route this curry/rewrite "
            "through the temporal floor"
        ),
        gap_kind=GapKind.FLOOR,
        gap_locus=GapLocus.CONSTRUCTION,
    )
    factory_panic(info)


def perform_temporal_operation(
    *,
    owner: str,
    blame: str,
    receiver: TemporalContext,
    operation: object,
    ctx: Any,
) -> TemporalContext:
    method_name = _operation_method_name(owner=owner, blame=blame, operation=operation)
    method = getattr(receiver, method_name, None)
    if method is None:
        if _is_declared_operation(operation):
            _missing_temporal_floor_gap(
                owner=owner,
                blame=blame,
                receiver=receiver,
                method_name=method_name,
            )
        from sugar_lift_py_tests.gap.panic import factory_panic
        from sugar_lift_py_tests.gap.info import FactoryGapInfo, GapKind, GapLocus

        operation_name = type(operation).__name__
        info = FactoryGapInfo(
            owner=owner,
            blame=blame,
            observed=operation_name,
            requested=method_name,
            fix=(
                f"check {operation_name}.method_name or add "
                f"{type(receiver).__name__}.{method_name}"
            ),
            gap_kind=GapKind.OPERATION,
            gap_locus=GapLocus.METHOD_NAME,
        )
        factory_panic(info)
    recorder = None if ctx is None else ctx.record_operation
    if recorder is not None:
        recorder(owner=owner, method_name=method_name, operation=operation)
    return method(operation, ctx)
