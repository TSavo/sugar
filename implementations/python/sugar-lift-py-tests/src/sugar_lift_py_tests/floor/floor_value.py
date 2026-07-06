from __future__ import annotations

from typing import TYPE_CHECKING, Any, NoReturn

from .floor_dispatch_surface import FLOOR_OPERATION_METHOD_NAMES

if TYPE_CHECKING:
    from sugar_lift_py_tests.ir import Term
    from sugar_lift_py_tests.operations.callsite_projection_operation import (
        CallsiteProjectionOperation,
    )
    from sugar_lift_py_tests.operations.inplace_binary_operator_operation import (
        InplaceBinaryOperatorOperation,
    )
    from sugar_lift_py_tests.outcome import Outcome

BASE_CONSTRUCTION_GAP_METHOD_NAMES = tuple(
    name
    for name in FLOOR_OPERATION_METHOD_NAMES
    if name
    not in {
        "inplace_binary_operator_with",
        "project_callsite_with",
    }
)


class FloorValue:
    non_fol_support = False

    def add_with(self, operation: Any, ctx: Any) -> NoReturn:
        del ctx
        return self._operation_construction_gap(operation, "add_with")

    def async_context_manager_with(self, operation: Any, ctx: Any) -> NoReturn:
        del ctx
        return self._operation_construction_gap(operation, "async_context_manager_with")

    def async_iter_with(self, operation: Any, ctx: Any) -> NoReturn:
        del ctx
        return self._operation_construction_gap(operation, "async_iter_with")

    def async_next_with(self, operation: Any, ctx: Any) -> NoReturn:
        del ctx
        return self._operation_construction_gap(operation, "async_next_with")

    def attribute_assign_with(self, operation: Any, ctx: Any) -> NoReturn:
        del ctx
        return self._operation_construction_gap(operation, "attribute_assign_with")

    def attribute_delete_with(self, operation: Any, ctx: Any) -> NoReturn:
        del ctx
        return self._operation_construction_gap(operation, "attribute_delete_with")

    def attribute_with(self, operation: Any, ctx: Any) -> NoReturn:
        del ctx
        return self._operation_construction_gap(operation, "attribute_with")

    def await_with(self, operation: Any, ctx: Any) -> NoReturn:
        del ctx
        return self._operation_construction_gap(operation, "await_with")

    def binary_operator_with(self, operation: Any, ctx: Any) -> NoReturn:
        del ctx
        return self._operation_construction_gap(operation, "binary_operator_with")

    def bitwise_with(self, operation: Any, ctx: Any) -> NoReturn:
        del ctx
        return self._operation_construction_gap(operation, "bitwise_with")

    def call_method_with(self, operation: Any, ctx: Any) -> NoReturn:
        del ctx
        return self._operation_construction_gap(operation, "call_method_with")

    def construct_sequence_with(self, operation: Any, ctx: Any) -> NoReturn:
        del ctx
        return self._operation_construction_gap(operation, "construct_sequence_with")

    def contains_with(self, operation: Any, ctx: Any) -> NoReturn:
        del ctx
        return self._operation_construction_gap(operation, "contains_with")

    def context_manager_with(self, operation: Any, ctx: Any) -> NoReturn:
        del ctx
        return self._operation_construction_gap(operation, "context_manager_with")

    def delitem_with(self, operation: Any, ctx: Any) -> NoReturn:
        del ctx
        return self._operation_construction_gap(operation, "delitem_with")

    def descriptor_with(self, operation: Any, ctx: Any) -> NoReturn:
        del ctx
        return self._operation_construction_gap(operation, "descriptor_with")

    def format_value_with(self, operation: Any, ctx: Any) -> NoReturn:
        del ctx
        return self._operation_construction_gap(operation, "format_value_with")

    def guard_with(self, operation: Any, ctx: Any) -> NoReturn:
        del ctx
        return self._operation_construction_gap(operation, "guard_with")

    def inplace_binary_operator_with(
        self,
        operation: InplaceBinaryOperatorOperation,
        ctx: Any,
    ) -> Outcome:
        return operation.inplace_default(self, ctx)

    def map_with(self, operation: Any, ctx: Any) -> NoReturn:
        del ctx
        return self._operation_construction_gap(operation, "map_with")

    def materialize_with(self, operation: Any, ctx: Any) -> NoReturn:
        del ctx
        return self._operation_construction_gap(operation, "materialize_with")

    def merge_finally_with(self, operation: Any, ctx: Any) -> NoReturn:
        del ctx
        return self._operation_construction_gap(operation, "merge_finally_with")

    def missing_with(self, operation: Any, ctx: Any) -> NoReturn:
        del ctx
        return self._operation_construction_gap(operation, "missing_with")

    def next_with(self, operation: Any, ctx: Any) -> NoReturn:
        del ctx
        return self._operation_construction_gap(operation, "next_with")

    def project_callsite_with(
        self,
        operation: CallsiteProjectionOperation,
        ctx: Any,
    ) -> NoReturn:
        return operation.project_unknown(self, ctx)

    def project_sequence_with(self, operation: Any, ctx: Any) -> NoReturn:
        del ctx
        return self._operation_construction_gap(operation, "project_sequence_with")

    def reflected_binary_operator_with(self, operation: Any, ctx: Any) -> NoReturn:
        del ctx
        return self._operation_construction_gap(
            operation, "reflected_binary_operator_with"
        )

    def route_raises_with(self, operation: Any, ctx: Any) -> NoReturn:
        del ctx
        return self._operation_construction_gap(operation, "route_raises_with")

    def setitem_with(self, operation: Any, ctx: Any) -> NoReturn:
        del ctx
        return self._operation_construction_gap(operation, "setitem_with")

    def str_with(self, operation: Any, ctx: Any) -> NoReturn:
        del ctx
        return self._operation_construction_gap(operation, "str_with")

    def subscript_with(self, operation: Any, ctx: Any) -> NoReturn:
        del ctx
        return self._operation_construction_gap(operation, "subscript_with")

    def unary_operator_with(self, operation: Any, ctx: Any) -> NoReturn:
        del ctx
        return self._operation_construction_gap(operation, "unary_operator_with")

    def to_term(self, *, owner: str) -> "Term":
        from sugar_lift_py_tests.factory import (
            FactoryAuditRow,
            FactoryGap,
            FactoryGapInfo,
            GapKind,
            GapLocus,
        )

        observed = type(self).__name__
        info = FactoryGapInfo(
            owner=owner,
            blame=observed,
            observed=observed,
            requested="project this floor value to a term",
            fix=f"write more Floor: implement {observed}.to_term",
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.PROJECTION,
        )
        gap = FactoryGap(
            info,
            FactoryAuditRow(
                role="to_term",
                status="floor-gap",
                observed=observed,
                blame=observed,
                selected=None,
                candidates=[],
                message=info.message,
            ),
        )
        raise gap

    def _operation_construction_gap(self, operation: Any, method_name: str) -> NoReturn:
        from sugar_lift_py_tests.factory import (
            FactoryAuditRow,
            FactoryGap,
            FactoryGapInfo,
            GapKind,
            GapLocus,
        )

        observed = type(self).__name__
        owner = getattr(operation, "owner", type(operation).__name__)
        blame = getattr(operation, "blame", observed)
        info = FactoryGapInfo(
            owner=owner,
            blame=blame,
            observed=observed,
            requested=method_name,
            fix=f"add {method_name} to {observed} or emit a real effect",
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )
        raise FactoryGap(
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
