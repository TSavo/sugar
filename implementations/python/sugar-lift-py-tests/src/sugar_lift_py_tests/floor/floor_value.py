from __future__ import annotations

from typing import TYPE_CHECKING, Any, NoReturn

from .floor_dispatch_surface import FLOOR_OPERATION_METHOD_NAMES

if TYPE_CHECKING:
    from sugar_lift_py_tests.context import FactoryBuildContext
    from sugar_lift_py_tests.ir import Formula, Term
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

    def contribution(self):
        # A floor value contributes itself to the block record. Support overrides
        # to contribute nothing (absorbed).
        return (self,)

    def add_with(
        self, operation: AddOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        del ctx
        return self._operation_construction_gap(operation, "add_with")

    def async_context_manager_with(
        self,
        operation: AsyncContextManagerOperation,
        ctx: FactoryBuildContext | None,
    ) -> Outcome:
        del ctx
        return self._operation_construction_gap(operation, "async_context_manager_with")

    def async_iter_with(
        self, operation: AsyncIteratorOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        del ctx
        return self._operation_construction_gap(operation, "async_iter_with")

    def async_next_with(
        self, operation: AsyncNextOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        del ctx
        return self._operation_construction_gap(operation, "async_next_with")

    def attribute_assign_with(
        self,
        operation: AttributeMutationOperation,
        ctx: FactoryBuildContext | None,
    ) -> Outcome:
        del ctx
        return self._operation_construction_gap(operation, "attribute_assign_with")

    def attribute_delete_with(
        self, operation: AttributeDeleteOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        del ctx
        return self._operation_construction_gap(operation, "attribute_delete_with")

    def attribute_with(
        self, operation: AttributeLookupOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        del ctx
        return self._operation_construction_gap(operation, "attribute_with")

    def await_with(
        self, operation: AwaitOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        del ctx
        return self._operation_construction_gap(operation, "await_with")

    def binary_operator_with(
        self, operation: BinaryOperatorOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        del ctx
        return self._operation_construction_gap(operation, "binary_operator_with")

    def bitwise_with(
        self, operation: BitwiseOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        del ctx
        return self._operation_construction_gap(operation, "bitwise_with")

    def call_method_with(
        self, operation: MethodCallOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        del ctx
        return self._operation_construction_gap(operation, "call_method_with")

    def construct_sequence_with(
        self,
        operation: SequenceConstructionOperation,
        ctx: FactoryBuildContext | None,
    ) -> Outcome:
        del ctx
        return self._operation_construction_gap(operation, "construct_sequence_with")

    def contains_with(
        self, operation: ContainsOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        del ctx
        return self._operation_construction_gap(operation, "contains_with")

    def context_manager_with(
        self, operation: ContextManagerOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        del ctx
        return self._operation_construction_gap(operation, "context_manager_with")

    def delitem_with(
        self, operation: DelItemOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        del ctx
        return self._operation_construction_gap(operation, "delitem_with")

    def descriptor_with(
        self, operation: DescriptorOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        del ctx
        return self._operation_construction_gap(operation, "descriptor_with")

    def format_value_with(
        self, operation: FormatValueOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        del ctx
        return self._operation_construction_gap(operation, "format_value_with")

    def guard_with(
        self, operation: ControlFlowGuardOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        del ctx
        return self._operation_construction_gap(operation, "guard_with")

    def inplace_binary_operator_with(
        self,
        operation: InplaceBinaryOperatorOperation,
        ctx: FactoryBuildContext | None,
    ) -> Outcome:
        return operation.inplace_default(self, ctx)

    def map_with(
        self,
        operation: CallableMapOperation | MapOperation,
        ctx: FactoryBuildContext | None,
    ) -> Outcome:
        del ctx
        return self._operation_construction_gap(operation, "map_with")

    def materialize_with(
        self, operation: MaterializeOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        del ctx
        return self._operation_construction_gap(operation, "materialize_with")

    def merge_finally_with(
        self,
        operation: FinallyFallthroughOperation,
        ctx: FactoryBuildContext | None,
    ) -> Outcome:
        del ctx
        return self._operation_construction_gap(operation, "merge_finally_with")

    def missing_with(
        self, operation: DictMissingOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        del ctx
        return self._operation_construction_gap(operation, "missing_with")

    def next_with(
        self, operation: NextOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        del ctx
        return self._operation_construction_gap(operation, "next_with")

    def project_callsite_with(
        self,
        operation: CallsiteProjectionOperation,
        ctx: FactoryBuildContext | None,
    ) -> Formula | None:
        return operation.project_unknown(self, ctx)

    def project_sequence_with(
        self,
        operation: SequenceProjectionOperation,
        ctx: FactoryBuildContext | None,
    ) -> Outcome:
        del ctx
        return self._operation_construction_gap(operation, "project_sequence_with")

    def reflected_binary_operator_with(
        self,
        operation: ReflectedBinaryOperatorOperation,
        ctx: FactoryBuildContext | None,
    ) -> Outcome:
        del ctx
        return self._operation_construction_gap(
            operation, "reflected_binary_operator_with"
        )

    def route_raises_with(
        self, operation: RouteRaisesOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        del ctx
        return self._operation_construction_gap(operation, "route_raises_with")

    def setitem_with(
        self, operation: SetItemOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        del ctx
        return self._operation_construction_gap(operation, "setitem_with")

    def str_with(
        self, operation: StrCoercionOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        del ctx
        return self._operation_construction_gap(operation, "str_with")

    def subscript_with(
        self, operation: SubscriptOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        del ctx
        return self._operation_construction_gap(operation, "subscript_with")

    def unary_operator_with(
        self, operation: UnaryOperatorOperation, ctx: FactoryBuildContext | None
    ) -> Outcome:
        del ctx
        return self._operation_construction_gap(operation, "unary_operator_with")

    def binary_conditional(self, then, else_body, ctx=None):
        # Default: this value does not stand on the bool floor -- it cannot decide a
        # two-way branch. That is the None arm, a construction gap. A value that CAN
        # do the bool thing implements binary_conditional; its absence here is the
        # honest "no", and this panic is that no.
        del then, else_body, ctx
        from sugar_lift_py_tests.factory import (
            FactoryAuditRow,
            FactoryGapInfo,
            GapKind,
            GapLocus,
            factory_panic,
        )

        observed = type(self).__name__
        info = FactoryGapInfo(
            owner="binary_conditional",
            blame=observed,
            observed=observed,
            requested="stand on the bool floor",
            fix=f"write more Floor: implement {observed}.binary_conditional",
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )
        factory_panic(
            info,
            FactoryAuditRow(
                role="binary_conditional",
                status="floor-gap",
                observed=observed,
                blame=observed,
                selected=None,
                candidates=[],
                message=info.message,
            ),
        )

    def equals(self, other, blame):
        # Default: this value does not stand on the equals floor -- it cannot answer
        # whether it equals another value. The None arm: a value that CAN implements
        # equals and gives back a True/False literal; absence here is the honest "no".
        del other
        from sugar_lift_py_tests.factory import (
            FactoryAuditRow,
            FactoryGapInfo,
            GapKind,
            GapLocus,
            factory_panic,
        )

        observed = type(self).__name__
        info = FactoryGapInfo(
            owner="equals",
            blame=blame,
            observed=observed,
            requested="stand on the equals floor",
            fix=f"write more Floor: implement {observed}.equals",
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )
        factory_panic(
            info,
            FactoryAuditRow(
                role="equals",
                status="floor-gap",
                observed=observed,
                blame=blame,
                selected=None,
                candidates=[],
                message=info.message,
            ),
        )

    def less_than(self, other, blame):
        # Default: this value does not stand on the ordering floor -- it cannot answer
        # whether it is less than another value. The None arm: a value that CAN
        # implements less_than and gives back a True/False literal; absence here is
        # the honest "no".
        del other
        from sugar_lift_py_tests.factory import (
            FactoryAuditRow,
            FactoryGapInfo,
            GapKind,
            GapLocus,
            factory_panic,
        )

        observed = type(self).__name__
        info = FactoryGapInfo(
            owner="less_than",
            blame=blame,
            observed=observed,
            requested="stand on the ordering floor",
            fix=f"write more Floor: implement {observed}.less_than",
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )
        factory_panic(
            info,
            FactoryAuditRow(
                role="less_than",
                status="floor-gap",
                observed=observed,
                blame=blame,
                selected=None,
                candidates=[],
                message=info.message,
            ),
        )

    def to_term(self, *, owner: str) -> "Term":
        from sugar_lift_py_tests.factory import (
            FactoryAuditRow, factory_panic,
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
        factory_panic(
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

    def _operation_construction_gap(self, operation: Any, method_name: str) -> NoReturn:
        from sugar_lift_py_tests.factory import (
            FactoryAuditRow, factory_panic,
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
