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

    def extend_scope(self, ctx):
        # Default: a statement value does not rebind the rest of the block.
        return ctx

    def as_expression_statement(self):
        # An expression statement discards ordinary values as support. A rebind
        # (ScopeRebind) overrides to keep itself so the block threads the scope.
        from sugar_lift_py_tests.floor.support_value import SupportValue
        from sugar_lift_py_tests.outcome import Complete

        return Complete(SupportValue())

    def answer(self, ctx=None):
        # Default: a binding stands as itself (NameSugar asks; the value answers).
        from sugar_lift_py_tests.outcome import Complete

        del ctx
        return Complete(self)

    def append_with(self, value, site):
        # Default: this value does not stand on the append floor -- it cannot answer
        # what appending another value yields. The None arm: a value that CAN
        # implements append_with (ListValue folds the history); absence here is the
        # honest "no". Symbolic append is out of scope this tranche.
        del value
        from sugar_lift_py_tests.factory import (
            FactoryAuditRow,
            FactoryGapInfo,
            GapKind,
            GapLocus,
            factory_panic,
        )

        observed = type(self).__name__
        info = FactoryGapInfo(
            owner="append_with",
            blame=str(site),
            observed=observed,
            requested="stand on the append floor",
            fix=f"write more Floor: implement {observed}.append_with",
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )
        factory_panic(
            info,
            FactoryAuditRow(
                role="append_with",
                status="floor-gap",
                observed=observed,
                blame=str(site),
                selected=None,
                candidates=[],
                message=info.message,
            ),
        )


    def mint_contribution(self, name, formals):
        # Default: a record entry mints no row of its own.
        del name, formals
        return ()

    def callsites(self):
        # Default: this value carries no CallSiteValue. CallSiteValue overrides
        # to yield itself; equals/less_than emit collect from both operands.
        return ()

    def edge_contribution(self, source_contract):
        # Default: a record entry projects no call edge of its own.
        del source_contract
        return ()

    def follow_rest(self, rest, reduce):
        # Default: an ordinary statement value lets the block go on.
        return reduce(rest)

    def guarded(self, formula):
        # Default: this value cannot ride under a guard. The record entries
        # that CAN override: a return becomes a GuardedReturn, an inv becomes
        # an implication. Absence is the honest no.
        from sugar_lift_py_tests.factory import (
            FactoryAuditRow,
            FactoryGapInfo,
            GapKind,
            GapLocus,
            factory_panic,
        )

        del formula
        observed = type(self).__name__
        info = FactoryGapInfo(
            owner="guarded",
            blame=observed,
            observed=observed,
            requested="ride under a guard",
            fix=f"write more Floor: implement {observed}.guarded",
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )
        factory_panic(
            info,
            FactoryAuditRow(
                role="guarded",
                status="floor-gap",
                observed=observed,
                blame=observed,
                selected=None,
                candidates=[],
                message=info.message,
            ),
        )

    def inv_contribution(self):
        # Default: a record entry states no inv. InvValue overrides.
        return ()

    def post_contribution(self):
        # Default: a record entry posts no exit. ReturnValue overrides.
        return ()

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

    def truth(self, site):
        # Default: this value has no Python truth -- it cannot stand as a
        # condition. Values that CAN answer implement truth (concrete folds,
        # symbolic emits py.truthy); absence here is the honest "no".
        from sugar_lift_py_tests.factory import (
            FactoryAuditRow,
            FactoryGapInfo,
            GapKind,
            GapLocus,
            factory_panic,
        )

        observed = type(self).__name__
        info = FactoryGapInfo(
            owner="truth",
            blame=str(site),
            observed=observed,
            requested="stand as a condition",
            fix=f"write more Floor: implement {observed}.truth",
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )
        factory_panic(
            info,
            FactoryAuditRow(
                role="truth",
                status="floor-gap",
                observed=observed,
                blame=str(site),
                selected=None,
                candidates=[],
                message=info.message,
            ),
        )

    def length(self, site):
        # Default: this value does not stand on the length floor -- it cannot
        # answer len(...). Values that CAN implement length (concrete folds,
        # symbolic stays the call:len coordinate); absence here is the honest "no".
        from sugar_lift_py_tests.factory import (
            FactoryAuditRow,
            FactoryGapInfo,
            GapKind,
            GapLocus,
            factory_panic,
        )

        observed = type(self).__name__
        info = FactoryGapInfo(
            owner="length",
            blame=str(site),
            observed=observed,
            requested="stand on the length floor",
            fix=f"write more Floor: implement {observed}.length",
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )
        factory_panic(
            info,
            FactoryAuditRow(
                role="length",
                status="floor-gap",
                observed=observed,
                blame=str(site),
                selected=None,
                candidates=[],
                message=info.message,
            ),
        )

    def binary_conditional(self, then, else_body, ctx=None, site=None):
        # Default: ask truth, then the standing dispatches the two faces.
        # Base cases (True/False literals, PredicateValue) override.
        return self.truth(site).and_then(
            lambda standing: standing.binary_conditional(then, else_body, ctx, site)
        )

    def stated(self, site):
        # Default: ask truth, then the standing states itself. Base cases
        # (True/False literals, PredicateValue) override.
        return self.truth(site).and_then(lambda standing: standing.stated(site))

    def negate(self):
        # Default: this value does not stand on the negate floor -- it cannot flip.
        # The None arm: a value that CAN implements negate (the bool literals); absence
        # here is the honest "no". No blame arg -- mirror binary_conditional.
        from sugar_lift_py_tests.factory import (
            FactoryAuditRow,
            FactoryGapInfo,
            GapKind,
            GapLocus,
            factory_panic,
        )

        observed = type(self).__name__
        info = FactoryGapInfo(
            owner="negate",
            blame=observed,
            observed=observed,
            requested="stand on the negate floor",
            fix=f"write more Floor: implement {observed}.negate",
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )
        factory_panic(
            info,
            FactoryAuditRow(
                role="negate",
                status="floor-gap",
                observed=observed,
                blame=observed,
                selected=None,
                candidates=[],
                message=info.message,
            ),
        )

    def equals(self, other, site):
        # Default: EMIT an operator-indexed atom. Fold when both sides are
        # ground (the literal pair overrides); emit when either side stands on
        # the term floor; panic only inside to_term when a side cannot enter
        # FOL at all. Vendor `==` is py.eq -- not SMT = -- because Python float
        # equality is not reflexive (nan == nan is False) and the sort universe
        # adjudicates later. Operand CallSiteValues ride as operand_callsites.
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.ir import py_eq
        from sugar_lift_py_tests.outcome import Complete

        return Complete(
            PredicateValue(
                py_eq(self.to_term(owner=str(site)), other.to_term(owner=str(site))),
                site,
                operand_callsites=(*self.callsites(), *other.callsites()),
            )
        )

    def is_identical(self, other, site):
        # Default: EMIT. Identity is the ONE comparison whose SMT lowering is
        # honestly `=` -- reflexive, sort-independent, total (nan is nan is True
        # even when nan == nan is False). Fold only language singletons
        # (None / True / False) in overrides. Do not fold numbers or strings:
        # CPython interning is an implementation detail, not language semantics
        # -- `1 is 1` folding would state something the language does not promise.
        # Panic lives inside to_term when a side cannot enter FOL at all.
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.ir import identity
        from sugar_lift_py_tests.outcome import Complete

        return Complete(
            PredicateValue(
                identity(
                    self.to_term(owner=str(site)), other.to_term(owner=str(site))
                ),
                site,
                operand_callsites=(*self.callsites(), *other.callsites()),
            )
        )

    def less_than(self, other, site):
        # Default: EMIT an operator-indexed atom. Fold when both sides are
        # ground (the literal pair overrides); emit when either side stands on
        # the term floor; panic only inside to_term when a side cannot enter
        # FOL at all. Vendor `<` is py.lt -- not SMT < -- so the sort universe
        # adjudicates (same NaN/reflexivity split as py.eq). Operand
        # CallSiteValues ride as operand_callsites.
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.ir import py_lt
        from sugar_lift_py_tests.outcome import Complete

        return Complete(
            PredicateValue(
                py_lt(self.to_term(owner=str(site)), other.to_term(owner=str(site))),
                site,
                operand_callsites=(*self.callsites(), *other.callsites()),
            )
        )

    def add(self, other, site):
        # Default: this value does not stand on the addition floor -- it cannot answer
        # what it is to add another value. The None arm: a value that CAN implements
        # add and gives back the sum (or concat); absence here is the honest "no".
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
            owner="add",
            blame=str(site),
            observed=observed,
            requested="stand on the addition floor",
            fix=f"write more Floor: implement {observed}.add",
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )
        factory_panic(
            info,
            FactoryAuditRow(
                role="add",
                status="floor-gap",
                observed=observed,
                blame=str(site),
                selected=None,
                candidates=[],
                message=info.message,
            ),
        )

    def subtract(self, other, site):
        # Default: this value does not stand on the subtraction floor -- it cannot
        # answer what it is minus another value. The None arm: a value that CAN
        # implements subtract and gives back a term; absence here is the honest "no".
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
            owner="subtract",
            blame=str(site),
            observed=observed,
            requested="stand on the subtraction floor",
            fix=f"write more Floor: implement {observed}.subtract",
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )
        factory_panic(
            info,
            FactoryAuditRow(
                role="subtract",
                status="floor-gap",
                observed=observed,
                blame=str(site),
                selected=None,
                candidates=[],
                message=info.message,
            ),
        )

    def multiply(self, other, site):
        # Default: this value does not stand on the multiplication floor -- it cannot
        # answer what it multiplies by another value to. The None arm: a value that CAN
        # implements multiply and gives back a product; absence here is the honest "no".
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
            owner="multiply",
            blame=str(site),
            observed=observed,
            requested="stand on the multiplication floor",
            fix=f"write more Floor: implement {observed}.multiply",
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )
        factory_panic(
            info,
            FactoryAuditRow(
                role="multiply",
                status="floor-gap",
                observed=observed,
                blame=str(site),
                selected=None,
                candidates=[],
                message=info.message,
            ),
        )

    def divide(self, other, site):
        # Default: this value does not stand on the division floor -- it cannot answer
        # what it divides by another value to. The None arm: a value that CAN
        # implements divide and gives back a quotient; absence here is the honest "no".
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
            owner="divide",
            blame=str(site),
            observed=observed,
            requested="stand on the division floor",
            fix=f"write more Floor: implement {observed}.divide",
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )
        factory_panic(
            info,
            FactoryAuditRow(
                role="divide",
                status="floor-gap",
                observed=observed,
                blame=str(site),
                selected=None,
                candidates=[],
                message=info.message,
            ),
        )

    def modulo(self, other, site):
        # Default: this value does not stand on the modulo floor -- it cannot answer
        # what remainder it leaves by another value. The None arm: a value that CAN
        # implements modulo and gives back a remainder; absence here is the honest "no".
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
            owner="modulo",
            blame=str(site),
            observed=observed,
            requested="stand on the modulo floor",
            fix=f"write more Floor: implement {observed}.modulo",
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )
        factory_panic(
            info,
            FactoryAuditRow(
                role="modulo",
                status="floor-gap",
                observed=observed,
                blame=str(site),
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
            blame=str(site),
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
                blame=str(site),
                selected=None,
                candidates=[],
                message=info.message,
            ),
        )
