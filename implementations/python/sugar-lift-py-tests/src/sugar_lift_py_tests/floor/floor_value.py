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


# The one explicit call of each binary-operation floor, keyed by the same floor
# method name (#7757). A producer that holds the operation as data (BinOpSugar's
# operator kind, a guarded right operand's rejoin, a dug call result) applies
# it here: every call is written out,
# so the law tests read it, and no floor method is ever looked up by a string.
BINARY_FLOOR_OPERATIONS = {
    "add": lambda left, right, site, ctx: left.add(right, site, ctx),
    "subtract": lambda left, right, site, ctx: left.subtract(right, site, ctx),
    "multiply": lambda left, right, site, ctx: left.multiply(right, site, ctx),
    "divide": lambda left, right, site, ctx: left.divide(right, site, ctx),
    "floor_divide": lambda left, right, site, ctx: left.floor_divide(right, site, ctx),
    "modulo": lambda left, right, site, ctx: left.modulo(right, site, ctx),
    "power": lambda left, right, site, ctx: left.power(right, site, ctx),
    "matrix_multiply": lambda left, right, site, ctx: left.matrix_multiply(
        right, site, ctx
    ),
    "bitwise_and": lambda left, right, site, ctx: left.bitwise_and(right, site, ctx),
    "bitwise_or": lambda left, right, site, ctx: left.bitwise_or(right, site, ctx),
    "bitwise_xor": lambda left, right, site, ctx: left.bitwise_xor(right, site, ctx),
    "left_shift": lambda left, right, site, ctx: left.left_shift(right, site, ctx),
    "right_shift": lambda left, right, site, ctx: left.right_shift(right, site, ctx),
}


# The one explicit call of each ordering floor, keyed by floor method name, for
# the same reason (#7757): ``ComparisonOpSugar`` applies it here.
ORDERING_FLOOR_OPERATIONS = {
    "less_than": lambda left, right, site, ctx: left.less_than(right, site, ctx),
    "less_equal": lambda left, right, site, ctx: left.less_equal(right, site, ctx),
    "greater_than": lambda left, right, site, ctx: left.greater_than(right, site, ctx),
    "greater_equal": lambda left, right, site, ctx: left.greater_equal(
        right, site, ctx
    ),
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

        Membership's value equality (``membership.member_equal``) needs to
        know the difference between "I am a value whose equality is not
        decidable yet" (undecided, ``None``) and "I am an object the floor
        has no value equality for" -- a class, a function, a bound method
        (``NotImplemented``).  Nothing about the carrier's SHAPE separates
        them -- ``LambdaCallable`` carries a term exactly like
        ``SymbolicValue`` does -- so this is testimony the floor states about
        itself, not something a caller infers.  The second is still a
        member like any object: membership answers its ``==`` by identity
        where Python does (``object_identity.equality_by_identity``), else
        undecided -- never a refusal (#7757 H11).

        Default: no.
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
        # Whether this right-hand side iterates, and what it yields, is not
        # decided: the store is the one undecided item mutation, the receiver
        # after it unknown.
        from sugar_lift_py_tests.sugar.store_effect_sugar import (
            undecided_item_mutation_faces,
        )

        return undecided_item_mutation_faces(site, method="__setitem__", owner=owner)

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
        # answer len(...). Values that CAN implement length (concrete folds;
        # an undecided operand is len's one unanswered call,
        # ``unanswered_length``); absence here is the honest "no".
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
        """``self[index]`` whose dispatch is not decided here: the two faces.

        The receiver's runtime type and ``__getitem__`` (or the index's
        ``__index__`` / ``__hash__`` / ``__eq__``) are not decided here, so
        the lookup may complete with any member or raise anything -- the #7587
        opaque-subscript law.  It is the one two-faced unanswered outcome
        (``ExitSet.two_faced``), and the one form every undecided subscript
        takes -- ``SymbolicValue.subscript_with`` and the opaque arm of
        ``CallSiteValue.subscript_with`` answer through it too.  Its value is
        keyed per evaluation (#7757, audit 2 row NEW-1, the owner's key
        rule): ``python:subscript_result(<receiver>, <index>, <key>)``, the
        key ``occurrence_key(site)`` taken where the read evaluates (inside a
        live loop item it carries that item's path), so two evaluations of
        one read are never one term -- a counting ``__getitem__`` read twice
        is two unknowns.  It completes only under
        ``python:subscript_op.completes(python:subscript_op(<result>,
        <key>))`` (``undecided_result_terms``), and the complement halts with
        an ``UndeterminedRaiseEffect`` (producer ``owner``, occurrence the
        same key); both arms owe the ``undecided`` member (reason
        ``unanswered``) at the read's site.  No ``KeyError`` or
        ``IndexError`` is guessed and no member is chosen.  ``py.subscript``
        stays the decided and typed paths' term.

        A read that reached the floor with no site is the lifter's own gap:
        it cannot key the completes atom or the debt, so it refuses by name.
        """
        if site is None:
            _siteless_undecided_read(
                owner, f"{type(self).__name__}[{type(index).__name__}]", "Subscript"
            )
        from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
        from sugar_lift_py_tests.floor.object_identity import identity_term
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
        from sugar_lift_py_tests.occurrence import occurrence_key
        from sugar_lift_py_tests.outcome import ExitSet

        key = occurrence_key(site)
        term, completes = undecided_result_terms(
            "subscript",
            (
                identity_term(self, site, "receiver", owner=owner),
                identity_term(index, site, "operand0", owner=owner),
            ),
            key,
        )
        return ExitSet.two_faced(
            SymbolicValue(term),
            UndeterminedRaiseEffect(
                blame=str(site),
                occurrence=key,
                producer_node_owner=owner,
                site=site,
            ),
            guard=completes,
            site=site,
        )

    def undecided_iteration(self, site, *, owner: str):
        """``iter(self)`` whose ``__iter__`` is not decided here: the two faces.

        The receiver's runtime type and ``__iter__`` (or ``__getitem__``) are
        not decided here, so ``iter`` may hand back any iterator or raise
        anything.  The opaque iterator is ``python:iter_result(<receiver>,
        <key>)``, one per evaluation (:meth:`_undecided_result_faces`); it
        completes only under ``python:iter_op.completes``, the complement
        halts with an ``UndeterminedRaiseEffect`` (producer ``owner``), and
        both arms owe the ``undecided`` member (reason ``unanswered``) at the
        call's site.  No ``TypeError`` is guessed.  A ``for`` over an iterable
        the reduction has not decided submits the same operation: its
        recurrence is what follows the completed face
        (``LoopRecurrenceSugar._desugar_with_iterable``).
        """
        return self._undecided_result_faces(
            "iter",
            (),
            site,
            owner=owner,
            read=f"iter({type(self).__name__})",
            node="Call",
        )

    def undecided_next(self, site, *, owner: str):
        """``next(self)`` whose ``__next__`` is not decided here: the two faces.

        The iterator's runtime type and ``__next__`` are not decided here, so
        ``next`` may yield any value or raise anything -- ``StopIteration``
        among them, never named here.  The opaque next value is
        ``python:next_result(<receiver>, <key>)``, one per evaluation
        (:meth:`_undecided_result_faces`): two ``next`` of one iterator are
        two unknowns.  It completes only under ``python:next_op.completes``,
        the complement halts with an ``UndeterminedRaiseEffect`` (producer
        ``owner``), and both arms owe the ``undecided`` member at the call's
        site.
        """
        return self._undecided_result_faces(
            "next",
            (),
            site,
            owner=owner,
            read=f"next({type(self).__name__})",
            node="Call",
        )

    def undecided_unary(self, operator: str, site, *, owner: str):
        """``-self`` / ``+self`` / ``~self`` whose ``__neg__`` / ``__pos__`` /
        ``__invert__`` is not decided here: the two faces.

        The result is ``python:unary_result("<op>", <operand>, <key>)``, one
        per evaluation (:meth:`_undecided_result_faces`); it completes only
        under ``python:unary_op.completes``, the complement halts with an
        ``UndeterminedRaiseEffect`` (producer ``owner``), and both arms owe
        the ``undecided`` member at the operation's site.  No ``TypeError``
        is guessed and no result is folded.  Every operand whose type is
        undecided takes it, formal or not (:meth:`_unary_operand_undecided`,
        #7757 NEW-8).
        """
        from sugar_lift_py_tests.ir import str_const

        return self._undecided_result_faces(
            "unary",
            (str_const(operator),),
            site,
            owner=owner,
            read=f"{operator}{type(self).__name__}",
            node="UnaryOp",
        )

    def undecided_truth(self, site, *, owner: str):
        """``bool(self)`` whose answer is not decided here: a two-faced boolean.

        The value's truth is the one keyed undecided truth,
        ``python:truth_result(<term>, <key>)``
        (:func:`undecided_truth_result`, the form the one truth rule's
        two faces complete with), keyed on the exact source site so two truth
        tests of the same term are never forced to agree.  ``<term>`` is the
        container's identity (``object_identity.identity_term``: its contents
        are not current, so never its display), so prove never reads it from
        the contents it arrived with.  It completes as that one
        ``PredicateValue``, so every
        guarded construct splits on it (``if_sugar.predicate_formula``,
        ``BoolOpSugar``'s selection, ``not``) and neither face is chosen.

        It owes one ``undecided`` debt only when taking the truth may run
        user code (``__bool__`` / ``__len__``), which this frame did not look
        at: that is the two-faced unanswered outcome of
        :meth:`_undecided_protocol_faces`, never this.  This form is for a
        receiver whose truth dispatch is the builtin one (a ``list`` /
        ``dict`` / ``set`` whose contents are not current,
        ``object_identity.contents_current``): it cannot raise and runs no
        code, so it is a guarded split with no halt and no debt.

        A read that reached the floor with no site is the lifter's own gap:
        it cannot key the truth, so it refuses by name.
        """
        if site is None:
            _siteless_undecided_read(owner, f"bool({type(self).__name__})", "Call")
        from sugar_lift_py_tests.floor.object_identity import identity_term
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.occurrence import occurrence_key
        from sugar_lift_py_tests.outcome import ExitSet

        truth = undecided_truth_result(
            identity_term(self, site, "receiver", owner=owner),
            occurrence_key(site),
        )
        return ExitSet.completed(
            PredicateValue(truth, site, operand_callsites=self.callsites())
        )

    def _undecided_protocol_faces(
        self, protocol: str, operands, site, *, owner: str, read: str, node: str
    ):
        """The one producer of an undecided protocol read's two faces.

        ``py.<protocol>(<receiver>, *operands)`` completes under
        ``python:<protocol>.completes(python:<protocol>(<term>, <site>))``,
        keyed on the exact source site so two reads of the same term are
        never forced to agree; the complement halts with an
        ``UndeterminedRaiseEffect`` owned by ``owner``; ``ExitSet.two_faced``
        owes the read at ``site`` on both arms.  A siteless read is the
        lifter's own gap and refuses by name.
        """
        if site is None:
            _siteless_undecided_read(owner, read, node)
        from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
        from sugar_lift_py_tests.floor.object_identity import identity_term
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
        from sugar_lift_py_tests.ir import atomic, ctor, str_const
        from sugar_lift_py_tests.occurrence import occurrence_key
        from sugar_lift_py_tests.outcome import ExitSet

        term = ctor(
            f"py.{protocol}",
            [
                identity_term(self, site, "receiver", owner=owner),
                *(
                    identity_term(operand, site, f"operand{position}", owner=owner)
                    for position, operand in enumerate(operands)
                ),
            ],
        )
        key = occurrence_key(site)
        completes = atomic(
            f"python:{protocol}.completes",
            [ctor(f"python:{protocol}", (term, str_const(key)))],
        )
        return ExitSet.two_faced(
            SymbolicValue(term),
            UndeterminedRaiseEffect(
                blame=str(site),
                occurrence=key,
                producer_node_owner=owner,
                site=site,
            ),
            guard=completes,
            site=site,
        )

    def _undecided_result_faces(
        self, name: str, leading, site, *, owner: str, read: str, node: str
    ):
        """The two faces of an undecided operation on ``self`` whose value is
        one per evaluation (#7757 NEW-1).

        ``python:<name>_result(*leading, <operand>, <key>)`` completes under
        ``python:<name>_op.completes(python:<name>_op(<result>, <key>))``
        (:func:`undecided_result_terms`), ``<key>`` the occurrence key taken
        where the operation evaluates, so inside a live loop item it carries
        that item's path: two evaluations over one operand term are two
        unknowns, as the binary law's are, and a truthful ``a != b`` over
        them cannot read ``unsat``.  The complement halts with an
        ``UndeterminedRaiseEffect`` owned by ``owner`` at the same key;
        ``ExitSet.two_faced`` owes the operation at ``site`` on both arms.
        The operand is named by ``object_identity.identity_term``.  A
        siteless operation is the lifter's own gap and refuses by name.
        """
        if site is None:
            _siteless_undecided_read(owner, read, node)
        from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
        from sugar_lift_py_tests.floor.object_identity import identity_term
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
        from sugar_lift_py_tests.occurrence import occurrence_key
        from sugar_lift_py_tests.outcome import ExitSet

        key = occurrence_key(site)
        term, completes = undecided_result_terms(
            name,
            (*leading, identity_term(self, site, "operand", owner=owner)),
            key,
        )
        return ExitSet.two_faced(
            SymbolicValue(term),
            UndeterminedRaiseEffect(
                blame=str(site),
                occurrence=key,
                producer_node_owner=owner,
                site=site,
            ),
            guard=completes,
            site=site,
        )

    def python_index_protocol(self) -> bool | None:
        """Whether this value's source-decided type implements ``__index__``.

        ``None`` is the third value: construction has not authenticated the
        runtime type or its index protocol. Receiver floors may emit TypeError
        only for ``False``; ``None`` is the two-faced undecided read
        (:meth:`undecided_subscript`).
        """
        return None

    def attribute(self, name, site, ctx):
        # Default: this value does not stand on the attribute floor -- it cannot
        # answer what it yields at `.name`. A symbolic receiver stays the
        # py.getattr coordinate; a value that owns a field folds; absence here is
        # the honest "no".  ``ctx`` is the reading caller's context; no
        # member applies a body here (a property getter is the dispatched
        # read prove's walk decides, ``ObjectValue.attribute``).
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

    def undecided_contains(self, item, site, *, owner: str):
        """Membership whose container dispatch is not source-decided: two faces.

        The container's runtime type selects ``__contains__`` (or iteration
        with ``__eq__``), which this frame did not look at, so ``item in self``
        may raise anything -- the #7585 law.  It completes with the undecided
        ``py.in(item, container)`` predicate, keyed per evaluation: the truth
        of the comparison's value (``python:truth_result(
        python:compare_result("In", item, container, <key>), <key>)``,
        ``comparison_op_sugar.keyed_comparison``), only under
        ``python:compare.completes(python:compare("In", item, container,
        site))`` and halts with
        an ``UndeterminedRaiseEffect`` (owner ``UndecidedCompare:In``) under the
        complement.  No exception type is named and no membership is decided.
        ``not in`` dispatches the same ``__contains__``: the caller negates the
        completed face only.
        """
        del owner
        from sugar_lift_py_tests.floor.object_identity import identity_term
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.ir import atomic
        from sugar_lift_py_tests.sugar.comparison_op_sugar import (
            undecided_dispatch_faces,
        )

        predicate = PredicateValue(
            atomic(
                "py.in",
                [
                    identity_term(
                        item, site, "item", owner="undecided membership item"
                    ),
                    identity_term(
                        self,
                        site,
                        "container",
                        owner="undecided membership container",
                    ),
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

    def lacks_item_method(self, method: str) -> bool:
        """Whether this value's type is decided to bind no item method
        ``method`` (``__getitem__``, ``__setitem__``, ``__delitem__``), so
        the item operation raises ``TypeError`` whatever its key is.  The
        item doors ask it first: the receiver's own answer needs neither the
        key nor the value.  Default False: only a value
        that reads its type's namespace (a source instance,
        ``ObjectValue.lacks_item_method``) decides absence."""
        del method
        return False

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
        # Default: ``assert value`` takes ``bool(value)`` through the one
        # truth rule (``bool_op_sugar.truth_of``), then the standing states
        # itself. Base cases (True/False literals, PredicateValue) override.
        from sugar_lift_py_tests.sugar.bool_op_sugar import truth_of

        return truth_of(self, site, owner="AssertSugar.test").and_then(
            lambda standing: standing.stated(site)
        )

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

    def _unary_operand_undecided(self) -> bool:
        """``-x``, ``+x`` and ``~x`` select ``__neg__`` / ``__pos__`` /
        ``__invert__`` (or raise) from the operand's runtime type.  A value
        whose type nothing here decided -- a formal, a free symbol, a call's
        result (``+f()`` included), an import member -- takes the one
        undecided unary (:meth:`undecided_unary`): both faces, keyed per
        evaluation, owed.  No success is folded and no ``TypeError`` is
        guessed (#7757 NEW-8)."""
        return self.denotes_value() and not self.runtime_type_is_decided()

    def unary_minus(self, site):
        # Default: no arithmetic negation floor. TermValue folds; an operand
        # whose type is undecided is the one undecided unary's two faces.
        if self._unary_operand_undecided():
            return self.undecided_unary(
                "-", site, owner=f"{type(self).__name__}.unary_minus"
            )
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
        # Default: no unary-plus floor. TermValue folds; an operand whose type
        # is undecided is the one undecided unary's two faces.
        if self._unary_operand_undecided():
            return self.undecided_unary(
                "+", site, owner=f"{type(self).__name__}.unary_plus"
            )
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
        # an operand whose type is undecided is the one undecided unary's two
        # faces.
        if self._unary_operand_undecided():
            return self.undecided_unary(
                "~", site, owner=f"{type(self).__name__}.bitwise_invert"
            )
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
        from sugar_lift_py_tests.floor.object_identity import equality_by_identity
        from sugar_lift_py_tests.floor.object_value import ObjectValue

        # Two operands whose ``__eq__`` is ``object``'s or ``type``'s (or a
        # singleton's, which defers): Python answers ``==`` by identity, the
        # one identity rule, never a free ``py.eq`` (``equality_by_identity``).
        by_identity = equality_by_identity(self, other, site)
        if by_identity is not None:
            return by_identity
        if type(other) is NoneValue and decided_builtin_other_than_none(self):
            # ``x == None`` for a decided builtin ``x``: identity, so False.
            from sugar_lift_py_tests.outcome import ExitSet
            from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
                FalseBoolLiteralSugar,
            )

            return ExitSet.completed(FalseBoolLiteralSugar(site=site))
        if isinstance(other, ObjectValue) and other.has_method("__eq__") is not False:
            # ``1 == obj``: Python's order runs the right operand's
            # reflection, ``type(obj).__eq__(obj, 1)``, after the left's
            # ``NotImplemented`` (or first, for a subclass of the left's
            # type).  Which one answers is prove's dispatch walk; here it is
            # the one unanswered call of the reflection, two faces, owed, its
            # halt kept -- never a construction refusal (#7757 H13).
            return other.unanswered_method_call("__eq__", (self,), (), site)
        from sugar_lift_py_tests.floor.guarded_value import GuardedValue

        if isinstance(other, GuardedValue):
            # ``x == (a if c else b)`` compares ``x`` to the one arm the
            # guard selects: each arm's own equality, rejoined
            # (``GuardedValue.predicate_from_left``), an arm that is the
            # undecided equality kept two-faced under its polarity.
            return other.predicate_from_left(
                lambda arm: self.equals(arm, site, ctx), site, operation="equals"
            )
        # Equality vocabulary is resolved here, once, from construction-time
        # sort testimony. Ill-sorted bare equality cannot leave this door.
        from sugar_lift_py_tests.floor.equality_atom import (
            answered_equality,
            resolve_equality_atom,
        )
        from sugar_lift_py_tests.floor.object_identity import (
            holds_stale,
            identity_term,
        )
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue

        if holds_stale(self) or holds_stale(other):
            # ``==`` reads both operands' contents all the way down; a
            # container whose contents are not current
            # (``object_identity.contents_current``) is not read: the
            # undecided equality, two-faced (``undecided_dispatch_faces``),
            # over the objects it compares (``identity_term``), never the
            # contents they arrived with.
            from sugar_lift_py_tests.ir import py_eq
            from sugar_lift_py_tests.sugar.comparison_op_sugar import (
                undecided_dispatch_faces,
            )

            owner = str(site)
            predicate = PredicateValue(
                py_eq(
                    identity_term(self, site, "left", owner=owner),
                    identity_term(other, site, "right", owner=owner),
                ),
                site,
                operand_callsites=(*self.callsites(), *other.callsites()),
            )
            return undecided_dispatch_faces(predicate, site, "Eq")
        # The stated equality is the whole answer only where neither
        # operand's ``==`` runs code this frame did not read; anything else
        # -- a formal, a call result, a class object, an effect slot, a
        # container holding one -- is the one undecided equality, two-faced,
        # answered here and never patched afterwards (``answered_equality``,
        # #7757).
        formula, bridges = resolve_equality_atom(self, other, owner=str(site))
        return answered_equality(
            self,
            other,
            PredicateValue(
                formula,
                site,
                operand_callsites=(*self.callsites(), *other.callsites()),
                derived_formulas=bridges,
            ),
            site,
        )

    def is_identical(self, other, site):
        # An ``except ... as e`` / ``with ... as x`` / ``pytest.raises ... as
        # ei`` slot answers identity on either side (``slot_identity``): its
        # coordinate is a value prove does not interpret, so ``x is e`` owes
        # exactly as ``e is x`` does.
        from sugar_lift_py_tests.floor.effect_coordinate import reads_an_effect_slot

        if reads_an_effect_slot(other) and not reads_an_effect_slot(self):
            return other.is_identical(self, site)
        # A reduced object whose value term is not its object (a container,
        # an instance, a tuple/str/bytes/number value) answers by the one
        # object rule, on either side: its value term would state `1 is 1`
        # and `(x,) is (x,)` by value, which the language does not promise.
        from sugar_lift_py_tests.floor.object_identity import (
            answers_identity_by_object,
            object_identity,
            term_identity,
        )

        if answers_identity_by_object(self) or answers_identity_by_object(other):
            return object_identity(self, other, site)
        # Otherwise the identity is stated over the operands' own terms, and
        # owes wherever nothing decides it (``term_identity``).
        return term_identity(self, other, site)

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
          ``python:compare.completes(python:compare(op, left, right,
          site))`` and an
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

    def less_than_from_left(self, left, site, ctx):
        """Default RHS law for ``left < self`` — never invents FOL meaning.

        Overrides (TermValue, StringValue, GuardedValue, NamedExpressionValue, …)
        construct Sugar or distribute. Does not call ``left.less_than(self)``.
        """
        return left._refuse_ordering_meaning(
            self, site, owner="FloorValue.less_than_from_left", operator="<"
        )

    # Every ordering operator is the same operator-owned double dispatch as
    # ``less_than``: the RHS answers its typed ``<op>_from_left`` door, which
    # a value that presents another (a walrus, ``NamedExpressionValue``)
    # overrides to run the operation on what it presents through the one
    # operand door.  The default door refuses exactly as before.

    def less_equal(self, other, site, ctx):
        return other.less_equal_from_left(self, site, ctx)

    def greater_than(self, other, site, ctx):
        return other.greater_than_from_left(self, site, ctx)

    def greater_equal(self, other, site, ctx):
        return other.greater_equal_from_left(self, site, ctx)

    def less_equal_from_left(self, left, site, ctx):
        """Default RHS law for ``left <= self`` — never invents FOL meaning."""
        return left._refuse_ordering_meaning(
            self, site, owner="FloorValue.less_equal", operator="<="
        )

    def greater_than_from_left(self, left, site, ctx):
        """Default RHS law for ``left > self`` — never invents FOL meaning."""
        return left._refuse_ordering_meaning(
            self, site, owner="FloorValue.greater_than", operator=">"
        )

    def greater_equal_from_left(self, left, site, ctx):
        """Default RHS law for ``left >= self`` — never invents FOL meaning."""
        return left._refuse_ordering_meaning(
            self, site, owner="FloorValue.greater_equal", operator=">="
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
        ``python:binary_op.completes(python:binary_op(<result>, <occurrence>))`` and
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
        """``isinstance(self, <builtin type>)`` where this value's own floor
        does not know its type: the undecided type test, its halt kept
        (:func:`undecided_type_test`, #7757).

        A floor that knows its value's type answers ``True`` / ``False`` in
        its own override (a ``str``, a tuple, an int, a class object,
        ``type(x)``'s result).  Here nothing does: ``type(self)`` may be no
        subclass of the builtin, and then ``object_isinstance`` asks this
        value for its ``__class__``, which a property or a
        ``__getattribute__`` of its type may answer by raising.  Never a
        halt-free completion."""
        del type_name
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue

        return undecided_type_test(
            self,
            SymbolicValue(type_term),
            site,
            owner="FloorValue.python_isinstance",
        )


def receiver_lacks_item_method(receiver, method: str) -> bool:
    """Whether an item operation's ``receiver`` -- itself no formal -- is a
    floor value whose type is decided to bind no item ``method``
    (``FloorValue.lacks_item_method``).  Each item door (subscript, store,
    delete) asks it first: the receiver answers with its ``TypeError``
    whatever the key and the value are."""
    return (
        isinstance(receiver, FloorValue)
        and getattr(receiver, "formal_coordinate", None) is None
        and receiver.lacks_item_method(method)
    )


def index_type_undecided(index) -> bool:
    """Whether the lift leaves the runtime type of a read's ``index`` -- or,
    for a slice, of any bound it carries -- undecided (a parameter's, an
    opaque call result's): its ``__index__``, ``__hash__`` and ``__eq__``
    are then not decided, so the read may select any member or raise
    anything.  A receiver whose own read cannot say more over such a key
    reads it as the one undecided read (``FloorValue.undecided_subscript``),
    never as a completion with its halt dropped (#7757)."""
    from sugar_lift_py_tests.floor.slice_value import SliceValue

    if isinstance(index, SliceValue):
        return any(
            isinstance(bound, FloorValue) and not bound.runtime_type_is_decided()
            for bound in (index.lower, index.upper, index.step)
        )
    return isinstance(index, FloorValue) and not index.runtime_type_is_decided()


def _siteless_undecided_read(owner: str, read: str, node: str) -> NoReturn:
    """The lifter's own gap: an undecided read reached its floor with no site.

    Not the program's undecided behaviour (that is the two-faced outcome):
    the lifter dropped the read's source fragment, so it cannot key the
    completes atom or the ``unanswered`` debt the read owes.
    """
    from sugar_source_tree.panic import SugarNotWritten

    # No site to blame: the floor that reached the read without it (``owner``)
    # is the coordinate this refusal names.
    raise SugarNotWritten(
        blame=owner,
        owner=owner,
        observed=f"undecided read with no source site: {read}",
        requested="the read's source site, to key its two faces and its debt",
        fix=f"carry the {node} node's fragment to the receiver floor",
    )


def unanswered_length(operand, operand_term, site, *, owner: str):
    """``len(<operand>)`` over an operand whose type is not a decided
    builtin: the builtin's one unanswered call (#7757).

    ``len(c)`` runs ``type(c).__len__``, which is not CPython's own here
    (``builtin_dunder_call``): Python raises ``TypeError`` when the type has
    no ``__len__``, and checks what it returns (``__index__``, else
    ``TypeError``; ``>= 0``, else ``ValueError``; ``<= sys.maxsize``, else
    ``OverflowError``).  Nothing here decides any of that, so the call is
    ``UnknownCalleeCallV1("len")``'s two faces: it completes with
    ``python:call_result(call:len(<operand>), <occurrence>)`` under
    ``python:unknown_callee_call.completes`` and halts undetermined under
    the complement, owed either way.  One form for every undecided operand
    (a formal, a call's result, a source-class instance); a completed
    ``call:len`` with no halt face is never stated.

    ``operand_term(site)`` names the operand (its term, or
    ``object_identity.identity_term`` for an instance).  A siteless read is
    the lifter's own gap and refuses by name."""
    if site is None:
        _siteless_undecided_read(owner, "len(operand)", "Call")
    from sugar_lift_py_tests.call_symbol import call_symbol
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.ir import ctor
    from sugar_lift_py_tests.source_call_resolution import UnknownCalleeCallV1
    from sugar_source_tree.nodes import LanguageCallee

    callsite = CallSiteValue(
        target_name="len",
        arg_values=(operand,),
        parameters=(),
        term=ctor(
            call_symbol("len"),
            [operand_term(site)],
            symbol_kind="builtin",
        ),
        body=None,
        site=site,
        language_callee=LanguageCallee.BUILTIN_LEN,
    )
    return UnknownCalleeCallV1("len").faces(callsite, site)


def undecided_binary_terms(operator: str, left_term, right_term, key: str):
    """The one form of an undecided ``left <operator> right``: its result
    term ``python:binary_result(op, left, right, <key>)`` and its completes
    atom ``python:binary_op.completes(python:binary_op(<result>, <key>))``.

    The completes atom names the operation it is about -- its result term,
    operands and all -- as every undecided protocol read's does
    (``python:subscript(<term>, <key>)``): where a joined actual decides the
    operands' types, the solver reads whether Python completes it and what
    it returns (#7763).
    """
    from sugar_lift_py_tests.ir import atomic, ctor, str_const

    term = ctor(
        "python:binary_result",
        (str_const(operator), left_term, right_term, str_const(key)),
    )
    completes = atomic(
        "python:binary_op.completes",
        [ctor("python:binary_op", (term, str_const(key)))],
    )
    return term, completes


def undecided_result_terms(name: str, operand_terms, key):
    """The one form of an undecided operation's value, one per evaluation
    (#7757 NEW-1): its result term ``python:<name>_result(*operands,
    <key>)`` and its completes atom ``python:<name>_op.completes(
    python:<name>_op(<result>, <key>))``, the shape
    :func:`undecided_binary_terms` states a binary operation in.

    ``key`` is the occurrence key taken where the operation evaluates, so
    two evaluations over the same operand terms (two ``next(it)``, one
    ``-p`` per live loop item) are two unknowns, never one term.  The
    result names no Python operation the prover decides: it is the
    uninterpreted application, and its operands are the inputs a joined
    actual binds.

    A contract that states what every evaluation of a read gives
    (``class_constructor_body_sugar.stored_field_facts``) passes the bound
    variable that ranges over the keys instead of one key: the same terms,
    quantified.
    """
    from sugar_lift_py_tests.ir import atomic, ctor, str_const

    key_term = str_const(key) if isinstance(key, str) else key
    term = ctor(f"python:{name}_result", (*operand_terms, key_term))
    completes = atomic(
        f"python:{name}_op.completes",
        [ctor(f"python:{name}_op", (term, key_term))],
    )
    return term, completes


def undecided_truth_result(operand, key: str):
    """The one truth rule's atom: ``bool(<operand>)`` not decided here, one
    per evaluation (#7757 NEW-1, the owner's key rule):
    ``python:truth_result(<operand>, <key>)``.

    ``key`` is the occurrence key taken where the truth is taken, the key its
    completes atom (``python:truth.completes(python:truth(<operand>,
    <key>))``) and its halt already carry, so two evaluations over the same
    operand term (``bool(p)`` in two live loop items) are two unknowns, never
    one atom.  It is the only predicate an undecided operation states: an
    undecided comparison is a value (:func:`undecided_compare_result`) and
    its truth is this atom over that value.  Where prove decides the
    operand's builtin type (a joined actual, a stated ``int`` / ``str``), or
    the operand is a comparison value over such operands, the SMT emitter
    reads it exactly as the unkeyed ``py.truthy`` / ``py.eq`` / ordering;
    otherwise it is the uninterpreted application.
    """
    from sugar_lift_py_tests.ir import atomic, str_const

    return atomic("python:truth_result", [operand, str_const(key)])


def undecided_compare_result(kind: str, left, right, key: str):
    """The value of an undecided comparison, one per evaluation (#7757
    NEW-1): ``python:compare_result("<Kind>", <left>, <right>, <key>)``.

    A rich comparison returns whatever ``__eq__`` / ``__lt__`` /
    ``__contains__`` returns, so ``l == r`` is a value, never a predicate:
    stored (``out.append(c == 0)``) it is this term, and every truth test of
    it is the one truth rule's atom over it (:func:`undecided_truth_result`),
    keyed where that truth is taken.  ``key`` is the occurrence key taken
    where the comparison evaluates, the key its completes atom
    (``python:compare.completes(python:compare(<kind>, ..., <key>))``) and
    its halt already carry.
    """
    from sugar_lift_py_tests.ir import ctor, str_const

    return ctor("python:compare_result", [str_const(kind), left, right, str_const(key)])


def undecided_attribute_result(
    receiver, name: str, site, *, owner: str, receiver_term=None
):
    """``receiver.name`` whose behaviour is not decided here, whatever the
    receiver is (a parameter, a captured cell, a free name, a module alias,
    a call's result, an object of this reduction): the one two-faced
    undecided read, keyed per evaluation (``undecided_result_terms``,
    #7757 NEW-3).  There is no other builder of an undecided read.

    A read is ``type(receiver).__getattribute__`` then ``__getattr__`` and
    the descriptors they find: a protocol with a fallback no one dispatched
    method states, so nothing here decides it whatever the caller binds.  It
    completes with ``python:attribute_result("<name>", <receiver>, <key>)``
    only under ``python:attribute_op.completes(python:attribute_op(<result>,
    <key>))``; the complement halts with an ``UndeterminedRaiseEffect``
    (``owner``) at the same key.  Both arms owe the ``undecided`` member.
    No ``AttributeError`` is named.

    ``receiver_term`` names the object the read reads when the receiver's
    own value names a state another proof states (a class call's result as
    its construction left it, ``CallSiteValue.attribute``); by default the
    receiver's identity (``identity_term``).  A contract that states such a
    field answers the read at prove over the same terms
    (``class_constructor_body_sugar.stored_field_facts``).  The
    ``attr:<name>(<object>)`` coordinate is the decided paths' only: the
    field's value a contract states, and the type-name read.

    A read that reached here with no site is the lifter's own gap: it
    cannot key the completes atom or the debt, so it refuses by name."""
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.floor.object_identity import identity_term
    from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
    from sugar_lift_py_tests.ir import str_const
    from sugar_lift_py_tests.occurrence import occurrence_key
    from sugar_lift_py_tests.outcome.exit_set import ExitSet

    if site is None:
        _siteless_undecided_read(
            owner, f"{type(receiver).__name__}.{name}", "Attribute"
        )
    key = occurrence_key(site)
    if receiver_term is None:
        receiver_term = identity_term(receiver, site, "receiver", owner=str(site))
    term, completes = undecided_result_terms(
        "attribute", (str_const(name), receiver_term), key
    )
    return ExitSet.two_faced(
        SymbolicValue(term),
        UndeterminedRaiseEffect(
            blame=str(site),
            occurrence=key,
            producer_node_owner=owner,
            site=site,
        ),
        guard=completes,
        site=site,
    )


_TYPE_TESTS = frozenset({"isinstance", "issubclass"})
_TYPE_TEST_RESULTS = frozenset(f"python:{test}_result" for test in _TYPE_TESTS)


def is_undecided_type_test_result(value) -> bool:
    """Whether ``value`` is the completed value of the undecided type test
    (:func:`undecided_type_test`): ``python:isinstance_result(...)`` or
    ``python:issubclass_result(...)``.  It is a ``bool`` -- both builtins
    return one, whatever a metaclass's check answered -- so its truth is
    the one truth rule's completion alone (``bool_op_sugar._unanswered_truth``):
    ``bool.__bool__`` cannot raise."""
    from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
    from sugar_lift_py_tests.ir import _Ctor

    return (
        type(value) is SymbolicValue
        and type(value.term) is _Ctor
        and value.term.name in _TYPE_TEST_RESULTS
    )


def undecided_type_test(
    value, classinfo, site, *, owner: str, test: str = "isinstance"
):
    """``isinstance(<value>, <classinfo>)`` -- or, with ``test="issubclass"``,
    ``issubclass(<value>, <classinfo>)`` -- that nothing here decides: the
    undecided truth, its halt kept (#7757).  Every type test over an operand
    whose floor does not decide it takes this one form; nothing else answers
    an undecided type test.

    ``PyObject_IsInstance`` (Objects/abstract.c) answers ``True`` at once
    only where ``type(value) is classinfo``.  Otherwise a class whose
    metaclass is not decided to be ``type`` runs its metaclass's
    ``__instancecheck__``, which may answer anything or raise; and under
    ``type``'s own check (``object_isinstance``) a value whose type is no
    subclass is asked for its ``__class__``, which a property or a
    ``__getattribute__`` of its type may answer by raising.
    ``PyObject_IsSubclass`` is the same shape: a metaclass's
    ``__subclasscheck__`` may raise, and under ``type``'s own check
    (``recursive_issubclass``) an operand that is no class is asked for its
    ``__bases__`` (``abstract_get_bases``), which may raise, and is a
    ``TypeError`` where it answers none.  So the test is the one form of an
    undecided operation's value (``undecided_result_terms``): it completes
    with ``python:<test>_result(<classinfo>, <value>, <key>)`` only under
    ``python:<test>_op.completes``, keyed per evaluation, and halts with an
    ``UndeterminedRaiseEffect`` (``owner``) under the complement, owed on
    both faces.  No ``TypeError`` is named and no truth is chosen.  Prove
    relates nothing to it: the isinstance law (``consistency::
    isinstance_law_facts``) reads only ``python:isinstance(<x>, "<C>")``
    over a class whose namespace row states its order.

    A test that reached here with no site is the lifter's own gap: it cannot
    key the completes atom or the debt, so it refuses by name."""
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.floor.object_identity import identity_term
    from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
    from sugar_lift_py_tests.occurrence import occurrence_key
    from sugar_lift_py_tests.outcome.exit_set import ExitSet

    if test not in _TYPE_TESTS:
        raise ValueError(f"undecided_type_test: no type test {test!r}")
    if site is None:
        _siteless_undecided_read(
            owner,
            f"{test}({type(value).__name__}, {type(classinfo).__name__})",
            "Call",
        )
    key = occurrence_key(site)
    term, completes = undecided_result_terms(
        test,
        (
            identity_term(classinfo, site, "classinfo", owner=owner),
            identity_term(value, site, "operand", owner=owner),
        ),
        key,
    )
    return ExitSet.two_faced(
        SymbolicValue(term),
        UndeterminedRaiseEffect(
            blame=str(site),
            occurrence=key,
            producer_node_owner=owner,
            site=site,
        ),
        guard=completes,
        site=site,
    )


def class_subtype_test(subtype, supertype, site, *, owner: str, subtype_term=None):
    """``issubclass(<subtype>, <supertype>)`` where ``subtype``'s floor
    testifies it is a class (``type(x)``'s result, a raised exception's
    class) but not which one; ``subtype_term`` names it where its own term
    does not (a cited ``type(x)`` coordinate).

    Halt-free only where ``supertype`` is a builtin class (``ClassValue``,
    metaclass ``type``): ``recursive_issubclass`` then asks
    ``PyType_IsSubtype`` of two classes, which cannot raise, so the open
    truth is the ``python.subtype`` predicate.  A finite tuple distributes
    (``TupleValue.test_python_subtype``).  Any other supertype -- an
    undecided value, a source class, an import -- may be no class (the
    ``TypeError``) or run a metaclass's ``__subclasscheck__``, so the test
    is the undecided type test (:func:`undecided_type_test`), its halt
    kept."""
    from sugar_lift_py_tests.floor.class_value import ClassValue
    from sugar_lift_py_tests.floor.predicate_value import PredicateValue
    from sugar_lift_py_tests.floor.tuple_value import TupleValue
    from sugar_lift_py_tests.ir import atomic
    from sugar_lift_py_tests.outcome.exit_set import ExitSet

    if type(supertype) is TupleValue:
        return supertype.test_python_subtype(subtype, site)
    if not isinstance(supertype, ClassValue):
        return undecided_type_test(
            subtype, supertype, site, owner=owner, test="issubclass"
        )
    if subtype_term is None:
        subtype_term = subtype.to_term(owner="python.issubclass subtype")
    return ExitSet.completed(
        PredicateValue(
            atomic(
                "python.subtype",
                [
                    subtype_term,
                    supertype.to_term(owner="python.issubclass supertype"),
                ],
            ),
            site,
            operand_callsites=(*subtype.callsites(), *supertype.callsites()),
        )
    )


def undecided_binary_faces(left, right, site, operator: str):
    """Two faces for ``left <operator> right`` over an undecided operand type.

    ``site`` is the BinOp's own fragment: the occurrence the result and the
    completes atom are keyed on, and the fragment the halt states (#7766).
    A binary operation that reached here with no site is refused by name at
    its key (``occurrence.site_coordinate_cid``), as every other undecided
    operation is; no empty key stands in for it.
    """
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.floor.object_identity import identity_term
    from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
    from sugar_lift_py_tests.occurrence import occurrence_key
    from sugar_lift_py_tests.outcome.exit_set import ExitSet

    key = occurrence_key(site)
    owner = f"python:binary_op {operator} at {site}"
    term, completes = undecided_binary_terms(
        operator,
        identity_term(left, site, "left", owner=owner),
        identity_term(right, site, "right", owner=owner),
        key,
    )
    return ExitSet.two_faced(
        SymbolicValue(term),
        UndeterminedRaiseEffect(
            blame=str(site),
            occurrence=key,
            producer_node_owner=f"UndecidedBinary:{operator}",
            site=site,
        ),
        guard=completes,
        site=site,
    )
