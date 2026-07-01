from __future__ import annotations

from typing import Any

from .temporal_context import TemporalContext


def perform_temporal_operation(
    *,
    owner: str,
    blame: str,
    receiver: TemporalContext,
    method_name: str,
    operation: object,
    ctx: Any,
) -> TemporalContext:
    method = getattr(receiver, method_name, None)
    if method is None:
        from sugar_lift_py_tests.factory import (
            FactoryAuditRow,
            FactoryGap,
            FactoryGapInfo,
        )

        info = FactoryGapInfo(
            owner=owner,
            blame=blame,
            observed=type(receiver).__name__,
            requested=method_name,
            fix=(
                f"add {method_name} to {type(receiver).__name__} or route this "
                "curry/rewrite through the temporal floor"
            ),
            gap_kind="Floor",
            gap_locus="construction",
        )
        raise FactoryGap(
            info,
            FactoryAuditRow(
                role=method_name,
                status="floor-gap",
                observed=type(receiver).__name__,
                blame=blame,
                selected=None,
                candidates=[],
                message=info.message,
            ),
        )
    recorder = getattr(ctx, "record_operation", None)
    if recorder is not None:
        recorder(owner=owner, method_name=method_name, operation=operation)
    return method(operation, ctx)
