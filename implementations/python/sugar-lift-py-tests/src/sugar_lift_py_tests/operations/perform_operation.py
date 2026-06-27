from __future__ import annotations

from typing import Any

from sugar_lift_py_tests.factory import FactoryGap, FactoryGapInfo
from sugar_lift_py_tests.factory.factory_audit_row import FactoryAuditRow
from sugar_lift_py_tests.floor import FloorValue
from sugar_lift_py_tests.outcome import Outcome


def perform_operation(
    *,
    owner: str,
    blame: str,
    receiver: FloorValue,
    method_name: str,
    operation: object,
    ctx: Any,
) -> Outcome:
    method = getattr(receiver, method_name, None)
    if method is None:
        info = FactoryGapInfo(
            owner=owner,
            blame=blame,
            observed=type(receiver).__name__,
            requested=method_name,
            fix=f"add {method_name} to {type(receiver).__name__} or emit a real effect",
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
    return method(operation, ctx)
