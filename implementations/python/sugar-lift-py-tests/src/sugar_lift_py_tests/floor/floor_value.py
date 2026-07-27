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


# The term coordinate each binary-operation floor constructs when the pair is
# undecided. These are the SAME constructor names SymbolicValue already emits;
# the map exists so one law covers all thirteen operators instead of thirteen
# copies of it. It is keyed by floor method name -- the dispatch surface's own
# vocabulary -- never by a lexical spelling read off a source node.
_BINARY_OPERATOR_COORDINATE = {
    "add": "+",
    "subtract": "-",
    "multiply": "*",
    "divide": "/",
    "floor_divide": "//",
    "modulo": "%",
    "power": "**",
    "matrix_multiply": "@",
    "bitwise_and": "&",
    "bitwise_or": "|",
    "bitwise_xor": "^",
    "left_shift": "<<",
    "right_shift": ">>",
}


class FloorValue:
    def _floor_gap(
        self,
        *,
        owner: str,
        blame: object,
        observed: str,
        requested: str,
        fix: str,
    ) -> NoReturn:
        """The common loud arm for unsupported floor protocol construction.

        ``blame`` accepts the SourceFragment itself; it is projected to prose
        here, at the ConstructionGap boundary, and nowhere earlier.
        """
        from sugar_lift_py_tests.gap.panic import construction_panic
        from sugar_lift_py_tests.gap.info import ConstructionGap, GapKind, GapLocus

        info = ConstructionGap(
            owner=owner,
            blame=str(blame),
            observed=observed,
            requested=requested,
            fix=fix,
            gap_kind=(
                GapKind.CONSTRUCTOR
                if requested.startswith("constructor-bound ")
                else GapKind.FLOOR
            ),
            gap_locus=GapLocus.CONSTRUCTION,
        )
        construction_panic(info)

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
        # implements append_with (ListValue folds the history; CallSiteValue
        # rebinds through py.list_append). Absence here is the honest "no".
        del value
        from sugar_lift_py_tests.gap.panic import construction_panic
        from sugar_lift_py_tests.gap.info import ConstructionGap, GapKind, GapLocus

        observed = type(self).__name__
        info = ConstructionGap(
            owner="append_with",
            blame=str(site),
            observed=observed,
            requested="stand on the append floor",
            fix=f"write more Floor: implement {observed}.append_with",
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )
        construction_panic(info)

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

    def follow_rest(self):
        # Default: an ordinary statement value lets the block go on.
        from sugar_lift_py_tests.outcome.follow_step import FollowStep

        return FollowStep.continue_with()

    def denotes_a_value(self) -> bool:
        """Does this floor testify that it DENOTES a value?

        A membership test needs to know the difference between "I am a value
        whose identity is not decidable yet" and "I am not a member at all".
        The first is an obligation (emit the typed ``python.*.contains`` atom);
        the second is a gap. Nothing about the carrier's SHAPE separates them
        -- ``FunctionCallable`` carries a term exactly like ``SymbolicValue``
        does, and is a callable, never a member -- so this is testimony the
        floor states about itself, not something a caller infers.

        Default: no. A floor that denotes a value says so by overriding, which
        keeps every unwritten floor loud rather than quietly admitted.
        """
        return False

    def guarded(self, formula):
        # Default: this value cannot ride under a guard. The record entries
        # that CAN override: a return becomes a GuardedReturn, an inv becomes
        # an implication. Absence is the honest no.
        from sugar_lift_py_tests.gap.panic import construction_panic
        from sugar_lift_py_tests.gap.info import ConstructionGap, GapKind, GapLocus

        del formula
        observed = type(self).__name__
        info = ConstructionGap(
            owner="guarded",
            blame=observed,
            observed=observed,
            requested="ride under a guard",
            fix=f"write more Floor: implement {observed}.guarded",
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )
        construction_panic(info)

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

    def callable_application_with(
        self,
        operation: CallableApplication,
        ctx: FactoryBuildContext | None,
    ) -> Outcome:
        del ctx
        return self._operation_construction_gap(operation, "callable_application_with")

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
        from sugar_lift_py_tests.gap.panic import construction_panic
        from sugar_lift_py_tests.gap.info import ConstructionGap, GapKind, GapLocus

        observed = type(self).__name__
        info = ConstructionGap(
            owner="truth",
            blame=str(site),
            observed=observed,
            requested="stand as a condition",
            fix=f"write more Floor: implement {observed}.truth",
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )
        construction_panic(info)

    def length(self, site):
        # Default: this value does not stand on the length floor -- it cannot
        # answer len(...). Values that CAN implement length (concrete folds,
        # symbolic stays the call:len coordinate); absence here is the honest "no".
        from sugar_lift_py_tests.gap.panic import construction_panic
        from sugar_lift_py_tests.gap.info import ConstructionGap, GapKind, GapLocus

        observed = type(self).__name__
        info = ConstructionGap(
            owner="length",
            blame=str(site),
            observed=observed,
            requested="stand on the length floor",
            fix=f"write more Floor: implement {observed}.length",
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )
        construction_panic(info)

    def subscript(self, index, site):
        # Default: this value does not stand on the subscript floor -- it cannot
        # answer what it yields at an index. Values that CAN implement subscript
        # (concrete folds, symbolic stays the py.subscript coordinate); absence
        # here is the honest "no".
        del index
        from sugar_lift_py_tests.gap.panic import construction_panic
        from sugar_lift_py_tests.gap.info import ConstructionGap, GapKind, GapLocus

        observed = type(self).__name__
        info = ConstructionGap(
            owner="subscript",
            blame=str(site),
            observed=observed,
            requested="stand on the subscript floor",
            fix=f"write more Floor: implement {observed}.subscript",
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )
        construction_panic(info)

    def undecided_subscript(self, index, site, *, owner: str):
        """Refuse a lookup whose runtime dispatch is not source-decided.

        This is accounted named-refusal semantics (``SugarNotWritten``), not a
        construction-panic harness failure: the producer names the missing
        testimony without inventing KeyError, IndexError, or a completed
        ``py.subscript`` coordinate.
        """
        from sugar_source_tree.panic import SugarNotWritten

        del site
        raise SugarNotWritten(
            owner=owner,
            observed=(
                "undecided receiver runtime type or index semantics: "
                f"{type(self).__name__}[{type(index).__name__}]"
            ),
            requested="a source-authenticated subscript success or exceptional exit",
            fix=(
                "carry receiver-type and index testimony to its native floor; "
                "do not guess KeyError, IndexError, or a generic runtime effect"
            ),
        )

    def python_index_protocol(self) -> bool | None:
        """Whether this value's source-decided type implements ``__index__``.

        ``None`` is the third value: construction has not authenticated the
        runtime type or its index protocol. Receiver floors may emit TypeError
        only for ``False``; they must keep ``None`` named-loud.
        """
        return None

    def attribute(self, name, site):
        # Default: this value does not stand on the attribute floor -- it cannot
        # answer what it yields at `.name`. A symbolic receiver stays the
        # py.getattr coordinate; a value that owns a field folds; absence here is
        # the honest "no".
        del name
        from sugar_lift_py_tests.gap.panic import construction_panic
        from sugar_lift_py_tests.gap.info import ConstructionGap, GapKind, GapLocus

        observed = type(self).__name__
        info = ConstructionGap(
            owner="attribute",
            blame=str(site),
            observed=observed,
            requested="stand on the attribute floor",
            fix=f"write more Floor: implement {observed}.attribute",
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )
        construction_panic(info)

    def undecided_attribute(self, name, site, *, owner: str):
        """Refuse lookup when source testimony decides neither outgoing edge.

        This is an accounted named refusal, not a construction failure.  The
        producer knows the native operation and the missing testimony, but it
        cannot choose either the completed or AttributeError edge honestly.
        """
        from sugar_source_tree.panic import SugarNotWritten

        del site
        raise SugarNotWritten(
            owner=owner,
            observed=(
                "undecided receiver runtime type or member semantics: "
                f"{type(self).__name__}.{name}"
            ),
            requested="a source-authenticated attribute success or exceptional exit",
            fix=(
                "carry receiver-type and member testimony to the attribute floor; "
                "do not guess AttributeError or invent a completed projection"
            ),
        )

    def contains(self, item, site):
        # Default: this value does not stand on the membership floor -- it cannot
        # answer whether it holds `item`. A symbolic container stays the py.in
        # coordinate; a concrete container folds; absence here is the honest "no".
        del item
        from sugar_lift_py_tests.gap.panic import construction_panic
        from sugar_lift_py_tests.gap.info import ConstructionGap, GapKind, GapLocus

        observed = type(self).__name__
        info = ConstructionGap(
            owner="contains",
            blame=str(site),
            observed=observed,
            requested="stand on the membership floor",
            fix=f"write more Floor: implement {observed}.contains",
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )
        construction_panic(info)

    def setitem(self, index, value, site):
        del index, value
        from sugar_lift_py_tests.gap.panic import construction_panic
        from sugar_lift_py_tests.gap.info import ConstructionGap, GapKind, GapLocus

        observed = type(self).__name__
        info = ConstructionGap(
            owner="setitem",
            blame=str(site),
            observed=observed,
            requested="stand on the subscript-store floor",
            fix=f"write more Floor: implement {observed}.setitem",
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )
        construction_panic(info)

    def delitem(self, index, site):
        del index
        from sugar_lift_py_tests.gap.panic import construction_panic
        from sugar_lift_py_tests.gap.info import ConstructionGap, GapKind, GapLocus

        observed = type(self).__name__
        info = ConstructionGap(
            owner="delitem",
            blame=str(site),
            observed=observed,
            requested="stand on the subscript-delete floor",
            fix=f"write more Floor: implement {observed}.delitem",
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )
        construction_panic(info)

    def absolute(self, site):
        from sugar_lift_py_tests.gap.panic import construction_panic
        from sugar_lift_py_tests.gap.info import ConstructionGap, GapKind, GapLocus

        observed = type(self).__name__
        info = ConstructionGap(
            owner="absolute",
            blame=str(site),
            observed=observed,
            requested="stand on the abs floor",
            fix=f"write more Floor: implement {observed}.absolute",
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )
        construction_panic(info)

    def py_subscript_coordinate(self, index, site):
        # The legacy symbolic spelling: ctor("py.subscript", [recv, index]).
        # Match symbolic_term.py so coordinates join that vocabulary.
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.outcome import Complete

        return Complete(
            CallSiteValue(
                target_name="py.subscript",
                arg_values=(self, index),
                parameters=(),
                term=ctor(
                    "py.subscript",
                    [
                        self.to_term(owner=str(site)),
                        index.to_term(owner=str(site)),
                    ],
                ),
                body=None,
                site=site,
            )
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
        from sugar_lift_py_tests.gap.panic import construction_panic
        from sugar_lift_py_tests.gap.info import ConstructionGap, GapKind, GapLocus

        observed = type(self).__name__
        info = ConstructionGap(
            owner="negate",
            blame=observed,
            observed=observed,
            requested="stand on the negate floor",
            fix=f"write more Floor: implement {observed}.negate",
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )
        construction_panic(info)

    def _undecided_unary_law(self, site, operator: str):
        """The ONE law for a unary operation with an undecided operand type.

        ``-x``, ``+x``, and ``~x`` select ``__neg__`` / ``__pos__`` / ``__invert__``
        (or raise TypeError) from the operand's runtime type.  When that type is
        undecided, inventing a success coordinate (``py.neg``, identity, ``py.invert``)
        erases the exceptional face, and inventing TypeError invents an exception
        identity.  Both stay refused until source-visible type testimony decides.
        """
        denotes = getattr(self, "denotes_value", None)
        decided = getattr(self, "runtime_type_is_decided", None)
        if not callable(denotes) or not callable(decided):
            return None
        if not denotes() or decided():
            return None

        from sugar_source_tree.panic import SugarNotWritten

        raise SugarNotWritten(
            owner="unary_operation_exception_floor",
            observed=f"{type(self).__name__} {operator}",
            requested=(
                "source-visible native unary-operator testimony selecting "
                "completion or an authenticated exceptional exit"
            ),
            fix=(
                "preserve the undecided third value at the UnaryOp producer; "
                "resolve the operand's runtime type and its unary operator body "
                "from source, or retain this named refusal without inventing an "
                "exception identity"
            ),
        )

    def unary_minus(self, site):
        # Default: no arithmetic negation floor. TermValue folds; an undecided
        # operand type refuses (success versus TypeError is not source-decidable).
        refused = self._undecided_unary_law(site, "-")
        if refused is not None:
            return refused
        from sugar_lift_py_tests.gap.panic import construction_panic
        from sugar_lift_py_tests.gap.info import ConstructionGap, GapKind, GapLocus

        observed = type(self).__name__
        info = ConstructionGap(
            owner="unary_minus",
            blame=str(site),
            observed=observed,
            requested="stand on the unary-minus floor",
            fix=f"write more Floor: implement {observed}.unary_minus",
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )
        construction_panic(info)

    def unary_plus(self, site):
        # Default: no unary-plus floor. TermValue folds; undecided types refuse.
        refused = self._undecided_unary_law(site, "+")
        if refused is not None:
            return refused
        from sugar_lift_py_tests.gap.panic import construction_panic
        from sugar_lift_py_tests.gap.info import ConstructionGap, GapKind, GapLocus

        observed = type(self).__name__
        info = ConstructionGap(
            owner="unary_plus",
            blame=str(site),
            observed=observed,
            requested="stand on the unary-plus floor",
            fix=f"write more Floor: implement {observed}.unary_plus",
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )
        construction_panic(info)

    def bitwise_invert(self, site):
        # Default: no bitwise-not floor. TermValue decides concrete operands;
        # an untyped symbol refuses because success versus TypeError is not
        # source-decidable.
        refused = self._undecided_unary_law(site, "~")
        if refused is not None:
            return refused
        from sugar_lift_py_tests.gap.panic import construction_panic
        from sugar_lift_py_tests.gap.info import ConstructionGap, GapKind, GapLocus

        observed = type(self).__name__
        info = ConstructionGap(
            owner="bitwise_invert",
            blame=str(site),
            observed=observed,
            requested="stand on the bitwise-invert floor",
            fix=f"write more Floor: implement {observed}.bitwise_invert",
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )
        construction_panic(info)

    def equals(self, other, site):
        # Equality vocabulary is resolved here, once, from construction-time
        # sort testimony. Ill-sorted bare equality cannot leave this door.
        from sugar_lift_py_tests.floor.equality_atom import resolve_equality_atom
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.outcome import Complete

        formula, bridges = resolve_equality_atom(self, other, owner=str(site))
        return Complete(
            PredicateValue(
                formula,
                site,
                operand_callsites=(*self.callsites(), *other.callsites()),
                derived_formulas=bridges,
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
                identity(self.to_term(owner=str(site)), other.to_term(owner=str(site))),
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
        from sugar_lift_py_tests.floor.guarded_value import GuardedValue
        from sugar_lift_py_tests.floor.named_expression_value import (
            NamedExpressionValue,
        )
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.floor.comparison_atom import resolve_comparison_atom
        from sugar_lift_py_tests.outcome import Complete

        if isinstance(other, GuardedValue):
            return other.predicate_from_left("less_than", self, site)
        if isinstance(other, NamedExpressionValue):
            return other.predicate_from_left("less_than", self, site)

        return Complete(
            PredicateValue(
                resolve_comparison_atom("lt", self, other, owner=str(site)),
                site,
                operand_callsites=(*self.callsites(), *other.callsites()),
            )
        )

    def less_equal(self, other, site):
        from sugar_lift_py_tests.floor.comparison_atom import resolve_comparison_atom
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.outcome import Complete

        return Complete(
            PredicateValue(
                resolve_comparison_atom("le", self, other, owner=str(site)),
                site,
                operand_callsites=(*self.callsites(), *other.callsites()),
            )
        )

    def greater_than(self, other, site):
        from sugar_lift_py_tests.floor.comparison_atom import resolve_comparison_atom
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.outcome import Complete

        return Complete(
            PredicateValue(
                resolve_comparison_atom("gt", self, other, owner=str(site)),
                site,
                operand_callsites=(*self.callsites(), *other.callsites()),
            )
        )

    def greater_equal(self, other, site):
        from sugar_lift_py_tests.floor.comparison_atom import resolve_comparison_atom
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.outcome import Complete

        return Complete(
            PredicateValue(
                resolve_comparison_atom("ge", self, other, owner=str(site)),
                site,
                operand_callsites=(*self.callsites(), *other.callsites()),
            )
        )

    def denotes_value(self) -> bool:
        """Testimony: does this floor value DENOTE a Python runtime value?

        The default is the honest "no". A floor value is not automatically a
        value: ``LambdaCallable`` and ``FunctionCallable`` denote callables,
        ``EffectCoordinate`` denotes a pending effect, exit values denote a
        halt. Carrying a term is NOT the discriminator -- ``FunctionCallable``
        carries one and is never an operand. Only the class itself can say,
        and a class that has not said stays loud.
        """
        return False

    def runtime_type_is_decided(self) -> bool:
        """Testimony: is this value's Python runtime TYPE known at lift time?

        ``StringValue`` knows it is a ``str``; ``ComprehensionValue`` knows it
        is the sequence its own fold constructor names. ``SymbolicValue`` and
        ``CallSiteValue`` do not know -- an unexecuted call's result type is
        undecided, so which ``__op__``/``__rop__`` Python would select is
        undecided too.

        The default is ``True`` (decided), which keeps a class that has not
        spoken on the LOUD side of :meth:`_undecided_binary_law`.
        """
        return True

    def _undecided_binary_law(self, other, site, operator):
        """The ONE law for a binary operation with an undecided operand.

        Every binary-operation floor gap measured on pandas came in the same
        shape wearing eight operator names: a left value with no arm named for
        THIS right operand, falling through to the pair gap. Most of those
        pairs are not eight separate arms to write. They are one law: when at
        least one operand's runtime TYPE is undecided, Python's own operator
        dispatch for the pair is undecided. That is a third value, not a
        completed symbolic coordinate: without source-visible native dispatch
        testimony this law refuses to choose completion or manufacture an
        exception identity.

        Two refusals are deliberate and stay loud:

        * An operand that does not DENOTE a value (a callable, a class, an
          exit) is not an operand at all. No coordinate is invented for it.
        * Two operands of DECIDED type are a ground question -- ``list + bool``
          is Python's ``TypeError``, not an unknown. Constructing a coordinate
          there would launder a ground exit into a value. That pair belongs to
          the ground field laws, and absence there is still a gap.

        Returns ``None`` when the law does not apply, so the caller falls
        through to its own pair gap.
        """
        if not (self.denotes_value() and other.denotes_value()):
            return None
        if self.runtime_type_is_decided() and other.runtime_type_is_decided():
            return None

        from sugar_lift_py_tests.gap.info import GapKind, GapLocus
        from sugar_lift_py_tests.gap.panic import construction_panic_gap

        construction_panic_gap(
            owner="binary_operation_exception_floor",
            blame=site,
            observed=f"{type(self).__name__} {operator} {type(other).__name__}",
            requested=(
                "source-visible native operator testimony selecting completion "
                "or an authenticated exceptional exit"
            ),
            fix=(
                "preserve the undecided third value at the BinOp producer; "
                "resolve native operand types and their operator bodies from "
                "source, or retain this named refusal without inventing an "
                "exception identity"
            ),
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )

    def _binary_floor_gap(self, other, site, owner, floor):
        """The ONE None arm for every binary-operation floor.

        A binary operation stands on a floor only for a NAMED PAIR of operand
        categories, so the gap names both: the left value's own category
        (``observed``) and the right operand's, in ``requested``/``fix``.
        Discarding the right operand made every gap of one owner look alike --
        34 ``add`` panics on the installed pandas tree said only "TermValue
        does not stand on the addition floor" and named nothing to implement.
        The pair IS the dispatch unit; a gap that cannot name its pair cannot
        be worked.

        The category is read from the operand's own type, which is its
        authenticated construction coordinate -- never from a lexical name.
        """
        constructed = self._undecided_binary_law(
            other, site, _BINARY_OPERATOR_COORDINATE[owner]
        )
        if constructed is not None:
            return constructed

        from sugar_lift_py_tests.gap.panic import construction_panic_gap

        observed = type(self).__name__
        operand = type(other).__name__
        construction_panic_gap(
            owner=owner,
            blame=str(site),
            observed=observed,
            requested=f"stand on the {floor} floor for a {operand} right operand",
            fix=f"write more Floor: implement {observed}.{owner} for {operand}",
        )

    def add(self, other, site):
        # Default: this value does not stand on the addition floor -- it cannot answer
        # what it is to add another value. The None arm: a value that CAN implements
        # add and gives back the sum (or concat); absence here is the honest "no".
        return self._binary_floor_gap(other, site, "add", "addition")

    def subtract(self, other, site):
        # Default: this value does not stand on the subtraction floor -- it cannot
        # answer what it is minus another value. The None arm: a value that CAN
        # implements subtract and gives back a term; absence here is the honest "no".
        return self._binary_floor_gap(other, site, "subtract", "subtraction")

    def multiply(self, other, site):
        # Default: this value does not stand on the multiplication floor -- it cannot
        # answer what it multiplies by another value to. The None arm: a value that CAN
        # implements multiply and gives back a product; absence here is the honest "no".
        return self._binary_floor_gap(other, site, "multiply", "multiplication")

    def power(self, other, site):
        return self._binary_floor_gap(other, site, "power", "power")

    def divide(self, other, site):
        # Default: this value does not stand on the division floor -- it cannot answer
        # what it divides by another value to. The None arm: a value that CAN
        # implements divide and gives back a quotient; absence here is the honest "no".
        return self._binary_floor_gap(other, site, "divide", "division")

    def modulo(self, other, site):
        # Default: this value does not stand on the modulo floor -- it cannot answer
        # what remainder it leaves by another value. The None arm: a value that CAN
        # implements modulo and gives back a remainder; absence here is the honest "no".
        return self._binary_floor_gap(other, site, "modulo", "modulo")

    def floor_divide(self, other, site):
        return self._binary_floor_gap(other, site, "floor_divide", "floor-division")

    def right_shift(self, other, site):
        return self._binary_floor_gap(other, site, "right_shift", "right-shift")

    def bitwise_and(self, other, site):
        return self._runtime_bitwise_gap(other, site, "bitwise_and", "and")

    def bitwise_xor(self, other, site):
        return self._runtime_bitwise_gap(other, site, "bitwise_xor", "xor")

    def bitwise_or(self, other, site):
        return self._runtime_bitwise_gap(other, site, "bitwise_or", "or")

    def left_shift(self, other, site):
        return self._runtime_bitwise_gap(other, site, "left_shift", "left-shift")

    def matrix_multiply(self, other, site):
        return self._binary_floor_gap(
            other, site, "matrix_multiply", "matrix-multiplication"
        )

    def _runtime_bitwise_gap(self, other, site, owner, label):
        return self._binary_floor_gap(other, site, owner, f"runtime bitwise {label}")

    def to_term(self, *, owner: str) -> "Term":
        from sugar_lift_py_tests.gap.panic import construction_panic
        from sugar_lift_py_tests.gap.info import ConstructionGap, GapKind, GapLocus

        observed = type(self).__name__
        info = ConstructionGap(
            owner=owner,
            blame=observed,
            observed=observed,
            requested="project this floor value to a term",
            fix=f"write more Floor: implement {observed}.to_term",
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.PROJECTION,
        )
        construction_panic(info)

    def _operation_construction_gap(self, operation: Any, method_name: str) -> NoReturn:
        from sugar_lift_py_tests.gap.panic import construction_panic
        from sugar_lift_py_tests.gap.info import ConstructionGap, GapKind, GapLocus

        observed = type(self).__name__
        owner = getattr(operation, "owner", type(operation).__name__)
        blame = getattr(operation, "blame", getattr(operation, "site", observed))
        info = ConstructionGap(
            owner=owner,
            blame=str(blame),
            observed=observed,
            requested=method_name,
            fix=f"add {method_name} to {observed} or emit a real effect",
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )
        construction_panic(info)

    def test_python_type(self, value, site):
        """Only a ``python:type`` coordinate may dispatch a vendor type test."""
        del value
        from sugar_lift_py_tests.gap.panic import construction_panic_gap

        construction_panic_gap(
            owner="FloorValue.test_python_type",
            blame=str(site),
            observed=type(self).__name__,
            requested="python:type coordinate dispatch",
            fix=(
                "reduce the second isinstance argument through "
                "BuiltinTypeNameSugar; tuple and unknown local types stay loud"
            ),
        )

    def python_isinstance(self, type_name: str, type_term, site):
        """Emit the reserved tester atom when this value is not ground-known."""
        del type_name
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.ir import atomic
        from sugar_lift_py_tests.outcome import Complete

        return Complete(
            PredicateValue(
                atomic(
                    "adt.is_python_type",
                    [self.to_term(owner="FloorValue.python_isinstance"), type_term],
                ),
                site,
            )
        )

    def format_data_model(self, spec, site, ctx):
        del spec, ctx
        return self._floor_gap(
            owner="FormatDunderCallSugar",
            blame=str(site),
            observed=type(self).__name__,
            requested="format data-model method",
            fix="construct __format__",
        )
