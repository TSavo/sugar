from __future__ import annotations

from typing import Callable, cast

from sugar_lift_py_tests.context import FactoryBuildContext
from sugar_lift_py_tests.factory import factory_panic, FactoryGapInfo, GapKind, GapLocus
from sugar_lift_py_tests.factory.factory_audit_row import FactoryAuditRow
from sugar_lift_py_tests.floor import BASE_CONSTRUCTION_GAP_METHOD_NAMES, FloorValue
from sugar_lift_py_tests.operations.floor_operation import FloorOperation
from sugar_lift_py_tests.outcome import Outcome

_DECLARED_OPERATION_MODULE = "sugar_lift_py_tests.operations."


def _operation_method_name(*, owner: str, blame: str, operation: FloorOperation) -> str:
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
    factory_panic(
        info,
        FactoryAuditRow(
            role="method_name",
            status="operation-gap",
            observed=operation_name,
            blame=blame,
            selected=None,
            candidates=[],
            message=info.message,
        ),
    )


def _is_declared_operation(operation: object) -> bool:
    return type(operation).__module__.startswith(_DECLARED_OPERATION_MODULE)


def _is_inherited_construction_gap_method(
    *,
    receiver: FloorValue,
    method_name: str,
    method: object,
) -> bool:
    del receiver
    if method_name not in BASE_CONSTRUCTION_GAP_METHOD_NAMES:
        return False
    return getattr(method, "__func__", None) is FloorValue.__dict__.get(method_name)


def _missing_floor_gap(
    *,
    owner: str,
    blame: str,
    receiver: FloorValue,
    method_name: str,
):
    observed = type(receiver).__name__
    info = FactoryGapInfo(
        owner=owner,
        blame=blame,
        observed=observed,
        requested=method_name,
        fix=f"add {method_name} to {observed} or emit a real effect",
        gap_kind=GapKind.FLOOR,
        gap_locus=GapLocus.CONSTRUCTION,
    )
    factory_panic(
        info,
        FactoryAuditRow(
            role=method_name,
            status="floor-gap",
            observed=observed,
            blame=blame,
            selected=None,
            candidates=[],
            message=info.message,
        ),
    )


def perform_operation(
    *,
    owner: str,
    blame: str,
    receiver: FloorValue,
    operation: FloorOperation,
    ctx: FactoryBuildContext | None,
) -> Outcome:
    method_name = _operation_method_name(owner=owner, blame=blame, operation=operation)
    method = getattr(receiver, method_name, None)
    if method is None:
        if _is_declared_operation(operation):
            _missing_floor_gap(
                owner=owner,
                blame=blame,
                receiver=receiver,
                method_name=method_name,
            )
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
        factory_panic(
            info,
            FactoryAuditRow(
                role=method_name,
                status="operation-gap",
                observed=operation_name,
                blame=blame,
                selected=None,
                candidates=[],
                message=info.message,
            ),
        )
    if _is_declared_operation(operation) and _is_inherited_construction_gap_method(
        receiver=receiver,
        method_name=method_name,
        method=method,
    ):
        _missing_floor_gap(
            owner=owner,
            blame=blame,
            receiver=receiver,
            method_name=method_name,
        )
    recorder = None if ctx is None else ctx.record_operation
    if recorder is not None:
        recorder(owner=owner, method_name=method_name, operation=operation)
    operation_method = cast(
        Callable[[FloorOperation, FactoryBuildContext | None], Outcome],
        method,
    )
    return operation_method(operation, ctx)
