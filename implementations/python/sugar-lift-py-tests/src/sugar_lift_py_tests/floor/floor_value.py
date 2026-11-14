from __future__ import annotations

from typing import TYPE_CHECKING, Any, NoReturn

from .floor_dispatch_surface import FLOOR_OPERATION_METHOD_NAMES

if TYPE_CHECKING:
    from sugar_lift_py_tests.context import ReduceContext
    from sugar_lift_py_tests.ir import Term
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

BASE_CONSTRUCTION_GAP_METHOD_NAMES = tuple(
    name
    for name in FLOOR_OPERATION_METHOD_NAMES
    if name != "inplace_binary_operator_with"
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
    def project_operation_receiver(self, ctx: object, *, owner: str):
        """Return the value that owns the next operation dispatch.

        Ordinary Floors already are their operation receiver. Producers whose
        authenticated result is deferred may override this one protocol before
        any operation family selects its concrete floor method.
        """
        del ctx, owner
        return self

    def project_operation_receiver_outcome(self, ctx: object, *, owner: str):
        """Sequence an ordinary scalar receiver through the exit algebra."""
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.completed(self.project_operation_receiver(ctx, owner=owner))

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
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.completed(SupportValue(site=None))

    def answer(self, ctx=None):
        # Default: a binding stands as itself (NameSugar asks; the value answers).
        from sugar_lift_py_tests.outcome import ExitSet

        del ctx
        return ExitSet.completed(self)

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
        -- ``LambdaCallable`` carries a term exactly like ``SymbolicValue``
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

    def callable_application_with(
        self,
        operation: CallableApplication,
        ctx: ReduceContext | None,
    ) -> ExitSet:
        del ctx
        return self._operation_construction_gap(operation, "callable_application_with")

    def subscript_with_occurrence(self, index, site, occurrence):
        """Typed source occurrence is optional; ordinary floors retain site law."""
        del occurrence
        return self.subscript(index, site)

    def inplace_binary_operator_with(
        self,
        operation: InplaceBinaryOperatorOperation,
        ctx: ReduceContext | None,
    ) -> ExitSet:
        return operation.inplace_default(self, ctx)

    def slice_assign_iterable_with(self, operation, ctx):
        """Slice-assignment RHS materialization — default Floor door.

        Exact sequences override with authenticated members.  A decided
        non-iterable is Python's TypeError.  Unresolved iterability stays a
        named runtime boundary (never a getattr species probe).
        """
        del ctx
        site = operation.blame
        owner = operation.owner
        if self.runtime_type_is_decided():
            from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

            return ground_exceptional_exit(
                exception_name="TypeError",
                site=site,
                owner=owner,
            )
        from sugar_lift_py_tests.effect import SubscriptStoreRuntimeEffect
        from sugar_lift_py_tests.effect import runtime_effect_evidence
        from sugar_lift_py_tests.floor.store_outcome_coordinate import store_faces

        return store_faces(
            SubscriptStoreRuntimeEffect(
                "list slice assignment RHS iterability is undecided at lift; "
                f"owner={owner} site={site}",
                **runtime_effect_evidence("py.setitem", self, site),
            )
        )

    def iter_with(
        self, operation: IteratorOperation, ctx: ReduceContext | None
    ) -> ExitSet:
        del ctx
        return self._operation_construction_gap(operation, "iter_with")

    def next_with(self, operation: NextOperation, ctx: ReduceContext | None) -> ExitSet:
        del ctx
        return self._operation_construction_gap(operation, "next_with")

    def project_sequence_with(
        self,
        operation: SequenceProjectionOperation,
        ctx: ReduceContext | None,
    ) -> ExitSet:
        del ctx
        return self._operation_construction_gap(operation, "project_sequence_with")

    def subscript_with(
        self, operation: SubscriptOperation, ctx: ReduceContext | None
    ) -> ExitSet:
        del ctx
        return self._operation_construction_gap(operation, "subscript_with")

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

        raise SugarNotWritten(
            blame=site,
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

    def attribute(self, name, site, ctx):
        # Default: this value does not stand on the attribute floor -- it cannot
        # answer what it yields at `.name`. A symbolic receiver stays the
        # py.getattr coordinate; a value that owns a field folds; absence here is
        # the honest "no".  ``ctx`` is the reading caller's context: a member
        # that applies a body (a property getter) applies under it.
        del name, ctx
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

    def attribute_named(self, name_value, site, ctx):
        """Carrier adapter for ``receiver.<static name>`` after discharge.

        ``NativeOperationDemandV1`` records ordered Floor values.  Attribute's
        second operand is the source-written static identifier, represented as
        a ground StringValue; it is never runtime spelling authority.  The read
        applies under ``ctx``, the discharging caller's context.
        """
        from sugar_lift_py_tests.floor.string_value import StringValue
        from sugar_source_tree.panic import SugarNotWritten

        if not isinstance(name_value, StringValue):
            raise SugarNotWritten(
                blame=site,
                owner="FloorValue.attribute_named",
                observed=type(name_value).__name__,
                requested="source-written static attribute identifier",
                fix="preserve the Attribute node's identifier as StringValue",
            )
        return self.attribute(name_value.value, site, ctx)

    def unary_truth(self, unit, site):
        """Carrier adapter for ``bool(operand)`` under UnaryOp ``not`` after discharge.

        ``NativeOperationDemandV1`` records two ordered Floor values.  Unary
        ``not`` has one operand; the second slot is an inert unit (``NoneValue``)
        with a null coordinate so discharge does not invent a second actual.
        The producer then negates only a *completed* truth face — never a halt
        (``ExitSet.and_then`` / ``ExitSet.sequence`` already skip halted tails).

        An undecided actual must not emit ``py.truthy`` here: that would invent
        a total ``bool`` completion after the formal door deferred honestly.
        """
        del unit
        denotes = getattr(self, "denotes_value", None)
        decided = getattr(self, "runtime_type_is_decided", None)
        if callable(denotes) and callable(decided) and denotes() and not decided():
            from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
            from sugar_source_tree.panic import SugarNotWritten

            if not isinstance(self, CallSiteValue):
                raise SugarNotWritten(
                    blame=site,
                    owner="unary_operation_exception_floor",
                    observed=f"{type(self).__name__} not",
                    requested=(
                        "source-visible native truth testimony selecting completion "
                        "or an authenticated exceptional exit"
                    ),
                    fix=(
                        "preserve the undecided third value at unary_truth discharge; "
                        "resolve the actual's runtime type and __bool__/__len__ from "
                        "source before completing or halting"
                    ),
                )
        return self.truth(site)

    def boolop_truth(self, site):
        """Truth-test once while retaining the actual operand BoolOp returns.

        This unary carrier adapter is deliberately distinct from ``truth``:
        ``a and b`` / ``a or b`` select using ``bool(a)`` but return ``a`` on
        the stopping face.  After formal-coordinate discharge, ``self`` is the
        authenticated caller actual, so packaging it here prevents the
        definition-time formal from leaking into the result.

        An actual whose runtime type remains undecided stays a named refusal;
        neither a generic halt nor a total symbolic truth is invented.
        """
        denotes = getattr(self, "denotes_value", None)
        decided = getattr(self, "runtime_type_is_decided", None)
        if callable(denotes) and callable(decided) and denotes() and not decided():
            from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
            from sugar_source_tree.panic import SugarNotWritten

            if not isinstance(self, CallSiteValue):
                raise SugarNotWritten(
                    blame=site,
                    owner="boolean_operation_exception_floor",
                    observed=f"{type(self).__name__} BoolOp truth",
                    requested=(
                        "source-visible native truth testimony selecting completion "
                        "or an authenticated exceptional exit"
                    ),
                    fix=(
                        "preserve the undecided third value at boolop_truth discharge; "
                        "resolve the actual's runtime type and __bool__/__len__ from "
                        "source before completing or halting"
                    ),
                )

        from sugar_lift_py_tests.floor.boolop_truth_selection import (
            BoolOpTruthSelection,
        )

        from sugar_lift_py_tests.outcome import ExitSet

        return self.truth(site).and_then(
            lambda truth_value: ExitSet.completed(
                BoolOpTruthSelection(self, truth_value)
            )
        )

    def undecided_attribute(self, name, site, *, owner: str):
        """Refuse lookup when source testimony decides neither outgoing edge.

        This is an accounted named refusal, not a construction failure.  The
        producer knows the native operation and the missing testimony, but it
        cannot choose either the completed or AttributeError edge honestly.

        Distinct from the default :meth:`attribute` construction panic: that
        door means a decided-type floor arm is missing (OUR defect). This door
        means the receiver's runtime type is not source-decided, so neither
        completion nor AttributeError is honest yet.
        """
        from sugar_source_tree.panic import SugarNotWritten

        raise SugarNotWritten(
            blame=site,
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

    def undecided_contains(self, item, site, *, owner: str):
        """Membership whose container dispatch is not source-decided: two faces.

        The container's runtime type selects ``__contains__`` (or iteration
        with ``__eq__``), which this frame did not look at, so ``item in self``
        may raise anything -- the #7585 law.  It completes with the undecided
        ``py.in(item, container)`` predicate only under
        ``python:compare.completes(python:compare("In", site))`` and halts with
        an ``UndeterminedRaiseEffect`` (owner ``UndecidedCompare:In``) under the
        complement.  No exception type is named and no membership is decided.
        ``not in`` dispatches the same ``__contains__``: the caller negates the
        completed face only.
        """
        del owner
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.ir import atomic
        from sugar_lift_py_tests.sugar.comparison_op_sugar import (
            undecided_dispatch_faces,
        )

        predicate = PredicateValue(
            atomic(
                "py.in",
                [
                    item.to_term(owner="undecided membership item"),
                    self.to_term(owner="undecided membership container"),
                ],
            ),
            site,
            operand_callsites=(*item.callsites(), *self.callsites()),
        )
        return undecided_dispatch_faces(predicate, site, "In")

    def contains(self, item, site):
        # Default: this value does not stand on the membership floor -- it cannot
        # answer whether it holds `item`. Decided containers override and fold
        # or TypeError; undecided containers use :meth:`undecided_contains`.
        # Absence of a decided arm here is the honest construction gap.
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

    def setitem(self, index, value, site, ctx):
        """``receiver[index] = value`` under the store statement's context.

        Every floor's store family (``setitem``, ``delitem``, ``setattr``,
        ``delattr``) takes the statement's ``ctx``: an operation a store
        submits applies under it, never under none (#7757).
        """
        del index, value, ctx
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

    def setattr(self, name, value, site, ctx):
        """``receiver.name = value`` — the store path, never the read path.

        Distinct from :meth:`attribute` / ``__getattr__`` / ``__getattribute__``.
        A readable name does not license a write. Default: loud floor gap.
        """
        del name, value, ctx
        from sugar_lift_py_tests.gap.panic import construction_panic
        from sugar_lift_py_tests.gap.info import ConstructionGap, GapKind, GapLocus

        observed = type(self).__name__
        info = ConstructionGap(
            owner="setattr",
            blame=str(site),
            observed=observed,
            requested="stand on the attribute-store floor",
            fix=f"write more Floor: implement {observed}.setattr",
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )
        construction_panic(info)

    def delitem(self, index, site, ctx):
        del index, ctx
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

    def delattr(self, name, site, ctx):
        del name, ctx
        from sugar_lift_py_tests.gap.panic import construction_panic
        from sugar_lift_py_tests.gap.info import ConstructionGap, GapKind, GapLocus

        observed = type(self).__name__
        info = ConstructionGap(
            owner="delattr",
            blame=str(site),
            observed=observed,
            requested="stand on the attribute-delete floor",
            fix=f"write more Floor: implement {observed}.delattr",
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )
        construction_panic(info)

    def py_subscript_coordinate(self, index, site):
        # The legacy symbolic spelling: ctor("py.subscript", [recv, index]).
        # Match symbolic_term.py so coordinates join that vocabulary.
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.completed(
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
                subscript_coordinate=True,
            )
        )

    def stated(self, site):
        # Default: ask truth, then the standing states itself. Base cases
        # (True/False literals, PredicateValue) override.
        return self.truth(site).and_then(lambda standing: standing.stated(site))

    def negate(self):
        # Default: this value does not stand on the negate floor -- it cannot flip.
        # The None arm: a value that CAN implements negate (the bool literals); absence
        # here is the honest "no". No blame arg.
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
            blame=site,
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

    def equals(self, other, site, ctx):
        from sugar_lift_py_tests.floor.none_value import (
            NoneValue,
            decided_builtin_other_than_none,
        )
        from sugar_lift_py_tests.floor.object_value import ObjectValue

        if type(other) is NoneValue and decided_builtin_other_than_none(self):
            # ``x == None`` for a decided builtin ``x``: identity, so False.
            from sugar_lift_py_tests.outcome import ExitSet
            from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
                FalseBoolLiteralSugar,
            )

            return ExitSet.completed(FalseBoolLiteralSugar(site=site))
        if isinstance(other, ObjectValue) and other.has_method("__eq__"):
            return self._floor_gap(
                owner="FloorValue.equals",
                blame=site,
                observed="reflected source equality method is not constructed",
                requested="authenticated reflected/subclass equality dispatch",
                fix="invoke the native reflected method before emitting equality",
            )
        # Equality vocabulary is resolved here, once, from construction-time
        # sort testimony. Ill-sorted bare equality cannot leave this door.
        from sugar_lift_py_tests.floor.equality_atom import resolve_equality_atom
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.outcome import ExitSet

        formula, bridges = resolve_equality_atom(self, other, owner=str(site))
        return ExitSet.completed(
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
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.completed(
            PredicateValue(
                identity(self.to_term(owner=str(site)), other.to_term(owner=str(site))),
                site,
                operand_callsites=(*self.callsites(), *other.callsites()),
            )
        )

    def less_than(self, other, site, ctx):
        # Operator-owned double dispatch: the RHS answers ``less_than_from_left``.
        # LAW_OF_ONE: ordering meaning is Sugar (or a ground arm that constructs
        # Sugar / an authenticated ground exit). The default door never mints
        # ExitSet.completed(PredicateValue) — that is a second mechanism.
        return other.less_than_from_left(self, site, ctx)

    def _refuse_ordering_meaning(
        self, other, site, *, owner: str, operator: str
    ) -> None:
        """LAW_OF_ONE door for ordering: never mint FOL meaning.

        Exactly one mechanism produces meaning: AST shadows → temporal rewrite
        → Sugar. An ordering OUTCOME is meaning. Minting
        ``ExitSet.completed(PredicateValue(py.lt/…))`` from a Python helper — even when
        both types are source-decided and the atom would be "right" — is a
        second mechanism.

        Two exits only:

        * **Undecided** (operands denote values but runtime type is not
          source-decided): the operands' runtime types select ``__lt__`` /
          ``__le__`` / ``__gt__`` / ``__ge__`` (and their reflections), which
          this frame did not look at, so the comparison may raise anything --
          the #7585 law, exactly as for ``==``.  Returned as two faces: the
          undecided ``py.lt/le/gt/ge`` predicate completes only under
          ``python:compare.completes(python:compare(op, site))`` and an
          ``UndeterminedRaiseEffect`` (owner ``UndecidedCompare:<op>``) halts
          under the complement.  Never a sole ``ExitSet.completed(PredicateValue)``.
        * **Decided (or non-undecided) with no ground arm**: construction
          panic. That is OUR missing Floor/Sugar arm, not source
          undecidability. Binary floor already panics decided missing pairs
          via ``_binary_floor_gap``; ordering matches that law.
        """
        denotes_self = getattr(self, "denotes_value", None)
        denotes_other = getattr(other, "denotes_value", None)
        both_denote = (
            callable(denotes_self)
            and callable(denotes_other)
            and denotes_self()
            and denotes_other()
        )
        decided_self = getattr(self, "runtime_type_is_decided", None)
        decided_other = getattr(other, "runtime_type_is_decided", None)
        both_decided = (
            both_denote
            and callable(decided_self)
            and callable(decided_other)
            and decided_self()
            and decided_other()
        )
        pair = f"{type(self).__name__} {operator} {type(other).__name__}"
        if both_denote and not both_decided:
            from sugar_lift_py_tests.sugar.comparison_op_sugar import (
                undecided_ordering_faces,
            )

            return undecided_ordering_faces(self, other, site, operator=operator)

        # Decided pair with no arm — or non-denoting pair on this door: OUR gap.
        from sugar_lift_py_tests.gap.panic import construction_panic_gap

        construction_panic_gap(
            owner=owner,
            blame=site,
            observed=f"default ordering floor has no Sugar arm for {pair}",
            requested=(
                "Sugar-owned ordering meaning (TrueBoolLiteralSugar / "
                "FalseBoolLiteralSugar / an authenticated ground exit)"
            ),
            fix=(
                "LAW_OF_ONE / PANIC=GAP: implement a ground pair arm that "
                "constructs Sugar; never resolve_comparison_atom / "
                "ExitSet.completed(PredicateValue) on FloorValue defaults; never label "
                "a decided missing arm as SugarNotWritten"
            ),
        )

    def _undecided_ordering_law(self, other, site, *, owner: str, operator: str):
        """Backward-compatible name for :meth:`_refuse_ordering_meaning`."""
        return self._refuse_ordering_meaning(
            other, site, owner=owner, operator=operator
        )

    def less_than_from_left(self, left, site, ctx):
        """Default RHS law for ``left < self`` — never invents FOL meaning.

        Overrides (TermValue, StringValue, GuardedValue, NamedExpressionValue, …)
        construct Sugar or distribute. Does not call ``left.less_than(self)``.
        """
        return left._refuse_ordering_meaning(
            self, site, owner="FloorValue.less_than_from_left", operator="<"
        )

    def less_equal(self, other, site, ctx):
        return self._refuse_ordering_meaning(
            other, site, owner="FloorValue.less_equal", operator="<="
        )

    def greater_than(self, other, site, ctx):
        return self._refuse_ordering_meaning(
            other, site, owner="FloorValue.greater_than", operator=">"
        )

    def greater_equal(self, other, site, ctx):
        return self._refuse_ordering_meaning(
            other, site, owner="FloorValue.greater_equal", operator=">="
        )

    def denotes_value(self) -> bool:
        """Testimony: does this floor value DENOTE a Python runtime value?

        The default is the honest "no". A floor value is not automatically a
        value: ``LambdaCallable`` denotes a callable,
        ``EffectCoordinate`` denotes a pending effect, exit values denote a
        halt. Carrying a term is NOT the discriminator -- ``LambdaCallable``
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

        When at least one operand's runtime TYPE is undecided, Python selects
        ``__op__``/``__rop__`` from types this frame did not look at, so the
        operation may raise anything -- the #7585 law, as for ordering
        (#7622).  It completes with the undecided result
        ``python:binary_result(op, left, right, <occurrence>)`` -- each
        evaluation its own unknown -- only under
        ``python:binary_op.completes(python:binary_op(op, <occurrence>))`` and
        halts with an ``UndeterminedRaiseEffect`` (owner
        ``UndecidedBinary:<op>``) under the complement.  No exception type is
        named and no result is folded.

        Two cases stay outside this door:

        * An operand that does not DENOTE a value (a callable, a class, an
          exit) is not an operand at all. No coordinate is invented for it.
        * Two operands of DECIDED type are a ground question -- ``list + bool``
          is Python's ``TypeError``, not an unknown. That pair belongs to the
          ground field laws, and absence there is still a gap.

        Returns ``None`` when the law does not apply, so the caller falls
        through to its own pair gap.
        """
        if not (self.denotes_value() and other.denotes_value()):
            return None
        if self.runtime_type_is_decided() and other.runtime_type_is_decided():
            return None
        return undecided_binary_faces(self, other, site, operator)

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

    def add(self, other, site, ctx):
        # Default: this value does not stand on the addition floor -- it cannot answer
        # what it is to add another value. The None arm: a value that CAN implements
        # add and gives back the sum (or concat); absence here is the honest "no".
        return self._binary_floor_gap(other, site, "add", "addition")

    def subtract(self, other, site, ctx):
        # Default: this value does not stand on the subtraction floor -- it cannot
        # answer what it is minus another value. The None arm: a value that CAN
        # implements subtract and gives back a term; absence here is the honest "no".
        return self._binary_floor_gap(other, site, "subtract", "subtraction")

    def multiply(self, other, site, ctx):
        # Default: this value does not stand on the multiplication floor -- it cannot
        # answer what it multiplies by another value to. The None arm: a value that CAN
        # implements multiply and gives back a product; absence here is the honest "no".
        return self._binary_floor_gap(other, site, "multiply", "multiplication")

    def power(self, other, site, ctx):
        return self._binary_floor_gap(other, site, "power", "power")

    def divide(self, other, site, ctx):
        # Default: this value does not stand on the division floor -- it cannot answer
        # what it divides by another value to. The None arm: a value that CAN
        # implements divide and gives back a quotient; absence here is the honest "no".
        return self._binary_floor_gap(other, site, "divide", "division")

    def modulo(self, other, site, ctx):
        # Default: this value does not stand on the modulo floor -- it cannot answer
        # what remainder it leaves by another value. The None arm: a value that CAN
        # implements modulo and gives back a remainder; absence here is the honest "no".
        return self._binary_floor_gap(other, site, "modulo", "modulo")

    def floor_divide(self, other, site, ctx):
        return self._binary_floor_gap(other, site, "floor_divide", "floor-division")

    def right_shift(self, other, site, ctx):
        return self._binary_floor_gap(other, site, "right_shift", "right-shift")

    def bitwise_and(self, other, site, ctx):
        return self._runtime_bitwise_gap(other, site, "bitwise_and", "and")

    def bitwise_xor(self, other, site, ctx):
        return self._runtime_bitwise_gap(other, site, "bitwise_xor", "xor")

    def bitwise_or(self, other, site, ctx):
        return self._runtime_bitwise_gap(other, site, "bitwise_or", "or")

    def left_shift(self, other, site, ctx):
        return self._runtime_bitwise_gap(other, site, "left_shift", "left-shift")

    def matrix_multiply(self, other, site, ctx):
        return self._binary_floor_gap(
            other, site, "matrix_multiply", "matrix-multiplication"
        )

    def _runtime_bitwise_gap(self, other, site, owner, label):
        return self._binary_floor_gap(other, site, owner, f"runtime bitwise {label}")

    def match_raise_effect(self, effect):
        """A scalar handler uses the shared authenticated identity/MRO law."""
        from sugar_lift_py_tests.authenticated_exception_matching import (
            _matches_single_raise_effect,
        )

        return _matches_single_raise_effect(effect, self)

    def to_term(self, *, owner: str) -> "Term":
        from sugar_lift_py_tests.gap.panic import construction_panic
        from sugar_lift_py_tests.gap.info import ConstructionGap, GapKind, GapLocus

        observed = type(self).__name__
        info = ConstructionGap(
            owner=f"{observed}.to_term",
            blame=owner,
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
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.completed(
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


def undecided_binary_faces(left, right, site, operator: str):
    """Two faces for ``left <operator> right`` over an undecided operand type."""
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
    from sugar_lift_py_tests.ir import atomic, ctor, str_const
    from sugar_lift_py_tests.occurrence import occurrence_key
    from sugar_lift_py_tests.outcome.exit_set import ExitSet

    key = occurrence_key(site) if site is not None else ""
    owner = f"python:binary_op {operator} at {site}"
    result = SymbolicValue(
        ctor(
            "python:binary_result",
            (
                str_const(operator),
                left.to_term(owner=owner),
                right.to_term(owner=owner),
                str_const(key),
            ),
        )
    )
    completes = atomic(
        "python:binary_op.completes",
        [ctor("python:binary_op", (str_const(operator), str_const(key)))],
    )
    return ExitSet.two_faced(
        result,
        UndeterminedRaiseEffect(
            blame=str(site) if site is not None else None,
            occurrence=key if site is not None else None,
            producer_node_owner=f"UndecidedBinary:{operator}",
        ),
        guard=completes,
    )
