from __future__ import annotations

import weakref
from dataclasses import dataclass, field as dataclass_field
from typing import Any, NoReturn

from sugar_lift_py_tests.call_symbol import call_symbol
from sugar_lift_py_tests.ir import Term, TermTableBuilder
from sugar_lift_py_tests.sugar.function_body_universe import FunctionBodyUniverse
from sugar_lift_py_tests.sugar_body import SugarBody


from .floor_value import FloorValue, undecided_attribute_result

_FORCE_FLOOR_BUDGET = 64

# Authenticated-coordinate memo: id(CallSiteValue) -> (weakref, coordinate).
# Weakrefs only, so a dead callsite is never pinned for process lifetime and a
# recycled address cannot inherit its identity (the ``is``-guard rejects it).
# Not a WeakKeyDictionary: that would call ``CallSiteValue.__hash__``, which is
# the seat being memoized.
_CALLSITE_COORDINATE: dict[int, tuple["weakref.ReferenceType", tuple]] = {}


def _callsite_coordinate_memo_size() -> int:
    """Live memo entries (test / diagnostics only)."""
    return len(_CALLSITE_COORDINATE)


def _term_cycle_key(term: Term) -> str:
    """Return a permanent content coordinate for an arbitrarily deep term.

    Always a TermTableBuilder wire CID — never ``id(_intern_term(...))``.
    Object-id keys made ``CallSiteValue.__hash__`` change across
    ``term_intern_scope`` and corrupted dict/set membership (#5569). Volume
    under an active intern scope is preserved by scope-local CID memoization
    in ``ir._term_content_cid`` (first materialize pays; repeats are O(1)).

    The encoder remains heap-backed (no native recursion on deep spines).
    """
    from sugar_lift_py_tests.ir import _term_content_cid

    return _term_content_cid(term)


def names_a_string(value) -> bool:
    """Whether ``value`` is known to be a ``str`` (if it is a call, when it
    completes): a ground string, or a call result whose mint names a string
    (``CallSiteValue.names_a_string``: a ``str.join`` result among them,
    by its binding ``LanguageCallee.STR_JOIN``, never its spelling)."""
    from sugar_lift_py_tests.floor.string_value import StringValue

    if type(value) is StringValue:
        return True
    return type(value) is CallSiteValue and value.names_a_string()


@dataclass(frozen=True)
class CallSiteValue(FloorValue):
    """A callsite as two things at once.

    The `term` is the bridge/culture coordinate used by contract composition.
    The factory-built `body` is only reduced when a downstream floor demands a
    concrete value (for example, a list literal index). `site` is the fragment
    that owned the call -- carried for edge projection, never compared.
    """

    target_name: str
    arg_values: tuple[FloorValue, ...]
    parameters: tuple[str, ...]
    term: Term
    # Any is the open membrane here, matching FactoryBuildResult.sugar and
    # ObjectMethodValue.body: a callsite's factory-built body varies in
    # reduction shape with the SugarRole it was built under.
    body: SugarBody[Any] | FunctionBodyUniverse | None
    keyword_names: tuple[str, ...] = dataclass_field(default=(), compare=False)
    site: object = dataclass_field(default=None, compare=False)
    call_occurrence: object | None = dataclass_field(default=None, compare=False)
    # A callee contract may cite the Python type object returned by this call.
    # Absent that citation, Python must execute the call to know whether its
    # result is a valid isinstance type operand.
    python_type_coordinate: Term | None = dataclass_field(default=None, compare=False)
    # The receiver whose runtime type selects a method body. Plain calls and
    # exact imported methods leave this absent; it is not inferred from args.
    runtime_dispatch_receiver: FloorValue | None = dataclass_field(
        default=None, compare=False
    )
    # Definition-owned class cell for a source method body.  Runtime receiver
    # type is deliberately insufficient: inherited methods must bind the class
    # that defined the body for zero-argument ``super()``.
    lexical_defining_class: FloorValue | None = dataclass_field(
        default=None, compare=False, repr=False
    )
    # Authority to treat this call result as an exception instance.  This is
    # issued only for ``type(caught_exception)(...)``: the coordinate names the
    # genuinely runtime-selected exception class.  Ordinary call-result shapes
    # and ``type(ground_value)(...)`` cannot acquire it.
    exception_type_coordinate: Term | None = dataclass_field(
        default=None, compare=False
    )
    exception_type_mro: tuple[Term, ...] | None = dataclass_field(
        default=None, compare=False
    )
    # Issued by a registered Call Sugar from an authenticated import target.
    # The target spelling alone never grants native behavior.
    native_shape: object | None = None
    # Semantic ContractDecl CID installed by the linker authority. This is
    # never an attestation/member CID and is absent for ordinary unresolved
    # call sites.
    target_contract_cid: str | None = dataclass_field(default=None, compare=False)
    authenticated_target_symbol: str | None = dataclass_field(
        default=None, compare=False
    )
    source_call_frame_cid: str | None = dataclass_field(default=None, compare=False)
    formal_coordinate_cids: tuple[str, ...] = dataclass_field(default=(), compare=False)
    bound_source_actuals: object | None = dataclass_field(default=None, compare=False)
    # The language-owned builtin exception class this call applied, read from
    # the temporal binding of the callee (a user rebinding replaces it). It
    # authorizes only what every builtin exception instance shares; it is not
    # the exception-type authority above, because ``OSError(...)`` and
    # ``ExceptionGroup(...)`` construct a runtime-selected subclass.
    builtin_exception_class: FloorValue | None = dataclass_field(
        default=None, compare=False, repr=False
    )
    # The ``args`` tuple a bodiless builtin exception construction stored,
    # decided where the call was constructed
    # (``CallSiteSugar._builtin_exception_construction``): the pinned
    # interpreter's over ground actuals (``builtin_exception_cited_fold``),
    # else the positional actuals where the constructor stores them as they
    # are (``builtin_exception_construction_reads_values`` False).  None
    # where nothing decided it; ``.args`` is then refused by name.
    constructed_args: FloorValue | None = dataclass_field(
        default=None, compare=False, repr=False
    )
    # The dynamic occurrence path this call was evaluated under
    # (``occurrence.current_path`` at mint). Its body reduces as the frame
    # ``path + (this call,)``: two calls of one function are two frames, and
    # every site in the body is evaluated once per frame.
    occurrence_path: tuple[str, ...] = dataclass_field(
        default_factory=lambda: _current_occurrence_path(),
        compare=False,
        repr=False,
    )
    # The ``LanguageCallee`` the Call node bound this call's callee to (its
    # binding, never its spelling), carried from ``CallSiteSugar``.
    language_callee: object | None = dataclass_field(
        default=None, compare=False, repr=False
    )
    # True only on the ``py.subscript(recv, index)`` coordinate that
    # ``FloorValue.py_subscript_coordinate`` mints: a reader asks this marker,
    # never whether a call is spelled ``py.subscript`` (#7757).
    subscript_coordinate: bool = dataclass_field(
        default=False, compare=False, repr=False
    )
    # True only on the ``attr:__name__`` / ``attr:__qualname__`` coordinate
    # that an attribute read mints (``CallSiteValue.attribute``,
    # ``SymbolicValue.attribute``): ``names_a_string`` asks this marker, never
    # whether a call is spelled ``__name__``, so a user function named
    # ``__name__`` never names a string (#7757).
    type_name_attribute: bool = dataclass_field(
        default=False, compare=False, repr=False
    )
    # True only on the string-concatenation coordinate the lifter mints over a
    # named string (``CallSiteValue.named_string_concat``'s ``call:__add__``,
    # ``JoinedStrSugar``'s ``python:fstring``): ``names_a_string`` asks this
    # marker, never the term's name, so a user function named ``__add__``
    # never names a string (#7757).
    string_concatenation: bool = dataclass_field(
        default=False, compare=False, repr=False
    )
    # The closure of the lambda this call applies (``LambdaCallable.closure``):
    # each final-member coordinate its body reads through an enclosing
    # comprehension's cell, with what the cell holds.  Bound before the body
    # reduces, which is after the comprehension is done (#7757 item 7).
    closure: tuple[tuple[str, FloorValue], ...] = dataclass_field(
        default=(), compare=False, repr=False
    )
    # True only on the result of a call of a same-file class that is its
    # coordinate and edge (``ClassDefinitionValue.callable_application_with``,
    # #7757 step 7): the instance as its construction left it, whose fields
    # the class's contract states (``python:after(out, "out")``,
    # ``ConstructedInstanceValue.post_formula``).  A reader that holds the
    # object after code may have changed it holds another value
    # (``builtin_container_call_sugar._may_change``,
    # ``ReceiverFieldStoreStateSugar``), never this one.
    constructed_by_edge: bool = dataclass_field(
        default=False, compare=False, repr=False
    )
    # On such a result (``constructed_by_edge``) of a class whose call
    # ``type.__call__`` makes with a builtin ``__new__`` (no source
    # ``__new__``, no metaclass, ``ClassDefinitionValue.
    # callable_application_with``): the class's join symbol.  The instance is
    # of that class; the class's contract states it, with what its
    # ``__dict__`` may hold, on every completed face
    # (``ConstructedInstanceValue.post_formula``).  A method call on it, and
    # a ``with``'s implicit ``__enter__``/``__exit__``, are dispatched over
    # that statement at prove (``receiver_dispatch.class_value``:
    # ``python:constructed(<class>)``, #7757 step 8).
    instance_of: str | None = dataclass_field(default=None, compare=False, repr=False)
    # ``((slot, formal), ...)`` on a same-file definition's edge
    # (``lambda_callable.definition_edge_call``): for each operand of the
    # call (``("arg", i)``, ``("kw", name)``, ``("cell", name)``,
    # ``container_mutation._call_slot``) whose object the call may change,
    # the formal of the callee's contract the one binder binds it to.  The
    # call's completed face binds them under the call's key
    # (``bind_after_call``), and the caller reads each object after the call
    # as ``python:after(<call result>, <formal>)`` (#7757 step 7).
    after_labels: tuple = dataclass_field(default=(), compare=False, repr=False)
    # True only on a same-file definition's edge
    # (``lambda_callable.definition_edge_call``): what the call may reach of
    # the module's globals is what its contract names (``after_labels``).
    # Any other call -- a callee nothing here answers, an import-bound or a
    # builtin call over undecided operands, a class construction, a value
    # call -- runs code no contract here states, which may reach every
    # module global (``bind_after_call``, #7757 H7).
    definition_edge: bool = dataclass_field(default=False, compare=False, repr=False)

    def denotes_value(self) -> bool:
        """A call result denotes a Python runtime value."""
        return True

    def project_operation_receiver(self, ctx: object, *, owner: str):
        """The receiver an operation over this call's result dispatches on:
        the call itself.  Its value is its coordinate; no callee body is
        applied at lift to expose a return (#7757 step 6)."""
        del ctx, owner
        return self

    def project_operation_receiver_outcome(self, ctx: object, *, owner: str):
        """``project_operation_receiver`` as an outcome: the call itself,
        completed.  What it returns is what the callee's contract states,
        joined at prove (#7757 step 6)."""
        del ctx, owner
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.completed(self)

    def runtime_type_is_decided(self) -> bool:
        """Undecided: no citation fixes an unexecuted call's result type.

        Which ``__op__``/``__rop__`` Python would select for an operation
        over this value is undecided too, so a binary operation reaches the
        named producer refusal rather than standing on a ground field law or
        claiming completion.
        """
        return False

    def exception_type_identity(self) -> Term | None:
        return self.exception_type_coordinate

    def iter_with(self, operation, ctx):
        """``iter(<call result>)``: what the call returned is its callee's
        contract's, joined at prove (#7757 steps 5 and 6), so its
        ``__iter__`` is not decided here.  The one two-faced undecided read
        (``FloorValue.undecided_iteration``), as for any symbolic receiver
        (``SymbolicValue.iter_with``): a ``for`` over a
        same-file call's result (``for i in g():``) follows the completed
        face, never a construction panic and never a value read off the
        callee's body."""
        del ctx
        return self.undecided_iteration(operation.blame, owner="CallSiteValue.iter")

    def next_with(self, operation, ctx):
        """``next(<call result>)``: the one two-faced undecided read
        (``FloorValue.undecided_next``), for the reason ``iter_with``
        gives."""
        del ctx
        return self.undecided_next(operation.blame, owner="CallSiteValue.next")

    def attribute(self, name, site, ctx):
        """Name ``__name__`` / ``__qualname__`` as a coordinate, without inventing the string.

        An unexecuted call authenticates which call produced the receiver, not
        its runtime type. Guessing AttributeError or inventing a concrete type
        name is dishonest. RaisesExc's absent-effect diagnostic still reads
        ``self.expected_exceptions[0].__name__`` after that lookup is named as
        ``py.subscript``. The spelling is decidable: emit
        ``attr:__name__(receiver)`` the same way a symbolic receiver names the
        attribute, without inventing the type name. Every other member is not
        decided here: the one two-faced unanswered read, keyed per evaluation
        (``floor_value.undecided_attribute_result``).
        """
        if name in {"__name__", "__qualname__"}:
            from sugar_lift_py_tests.ir import ctor
            from sugar_lift_py_tests.outcome import ExitSet

            return ExitSet.completed(
                CallSiteValue(
                    target_name=name,
                    arg_values=(self,),
                    parameters=(),
                    term=ctor(
                        f"attr:{name}",
                        [self.to_term(owner=str(site))],
                        symbol_kind="method-coordinate",
                    ),
                    body=None,
                    site=site,
                    type_name_attribute=True,
                )
            )
        if name == "args" and self.exception_type_coordinate is not None:
            # BaseException.args is the constructor's positional arguments.
            # Only an authenticated exception instance has that field; an
            # ordinary unexecuted call still has no runtime type, so .args
            # is the two-faced undecided read rather than an invented tuple.
            from sugar_lift_py_tests.outcome import ExitSet

            # A bodiless builtin construction's ``args`` is what it stored
            # (``constructed_args``), decided where the call was constructed:
            # ``OSError(2, 'x', 'f').args`` is ``(2, 'x')`` by the pinned
            # interpreter.  A source, imported or runtime-selected class runs
            # a constructor nothing here applies (#7757 step 6): ``.args`` is
            # the two-faced undecided read, what the constructor's contract
            # states joined at prove, never the actuals.
            if self.bound_source_actuals is None and self.constructed_args is not None:
                return ExitSet.completed(self.constructed_args)
            return undecided_attribute_result(
                self, name, site, owner="CallSiteValue.attribute"
            )
        if self.constructed_by_edge:
            # A field of a same-file class call's result, as its construction
            # left it (#7757 step 7): the read names the object by the state
            # the class's contract states, ``python:after(<call result>,
            # "out")``, so the join decides it at prove where the contract
            # states the field (its value and that the read completes,
            # ``ConstructedInstanceValue.post_formula``) and leaves it owed
            # where it does not.  Still the one two-faced read: nothing is
            # decided here.
            from sugar_lift_py_tests.source_call_resolution import (
                CALL_RESULT_LABEL,
                object_after_call,
            )

            return undecided_attribute_result(
                self,
                name,
                site,
                owner="CallSiteValue.attribute",
                receiver_term=object_after_call(
                    self.to_term(owner=str(site)), CALL_RESULT_LABEL
                ),
            )
        # Any other member -- of an opaque call result or of an authenticated
        # exception instance (``__context__``) -- is not decided here.
        return undecided_attribute_result(
            self, name, site, owner="CallSiteValue.attribute"
        )

    def _identity(self) -> tuple:
        """Authenticate this immutable callsite's finite coordinate once.

        ``__hash__`` and ``__eq__`` both read this one seat, so they cannot
        disagree. Before the memo, every comparison rebuilt the coordinate —
        including ``_term_cycle_key``, a full content CID of the term. The
        pandas reproducer measured 35,339,381 ``_term_content_cid`` calls
        arriving through this path on a single file, because ``ExitSet``
        merging compares the same callsites repeatedly.

        A ``CallSiteValue`` is a frozen dataclass, so a coordinate computed
        once cannot go stale. The memo carries the same discipline as
        ``ir._TERM_CONTENT_CID``: identity is the coordinate, ``id()`` only
        indexes, and a weakref ``is``-guard rejects recycled addresses so a
        reused id can never inherit a dead callsite's identity.
        """
        cid = id(self)
        entry = _CALLSITE_COORDINATE.get(cid)
        if entry is not None:
            ref, coordinate = entry
            if ref() is self:
                return coordinate
            if ref() is None:
                _CALLSITE_COORDINATE.pop(cid, None)

        coordinate = (
            type(self),
            self.target_name,
            self.parameters,
            _term_cycle_key(self.term),
        )

        def _on_die(ref: weakref.ReferenceType, *, _cid: int = cid) -> None:
            current = _CALLSITE_COORDINATE.get(_cid)
            if current is not None and current[0] is ref:
                _CALLSITE_COORDINATE.pop(_cid, None)

        try:
            _CALLSITE_COORDINATE[cid] = (weakref.ref(self, _on_die), coordinate)
        except TypeError:
            # Not weak-referenceable: recompute every time rather than pin the
            # object for process lifetime.
            pass
        return coordinate

    def __hash__(self) -> int:
        """Hash the finite call coordinate, never the recursively-owned body.

        ``body`` can contain the callsite that owns it (recursive functions and
        deferred constructor graphs). The frozen-dataclass-generated hash
        walked that graph until Python raised ``RecursionError``. The term is
        the authenticated structural coordinate; ``target_name`` and the
        parameter shape disambiguate otherwise equal coordinates. Omitting
        recursive payload fields is safe for hash equality (equal values still
        receive the same hash) and makes identity total over cyclic bodies.
        """
        return hash(self._identity())

    def __eq__(self, other: object) -> bool:
        """Compare the same finite authenticated coordinate used by ``__hash__``.

        The dataclass-generated equality walks ``body`` recursively; deferred
        callsites can retain themselves, so that path is not total.  Body is
        intentionally excluded from identity: the finite term coordinate is
        the authenticated callsite identity and already distinguishes twins.
        """
        if not isinstance(other, CallSiteValue):
            return NotImplemented
        if self is other:
            return True
        return self._identity() == other._identity()

    def to_term(self, *, owner: str):
        del owner
        return self.result_term()

    def result_term(self):
        """The value this call returned: the application
        ``call:<target>(<args>)``, the bridge coordinate contract composition
        and cycle keys use.  No callee body is applied at lift (#7757 step
        6), so a call's result is its coordinate, and its faces mint it
        (#7585)."""
        return self.term

    def denotes_a_value(self) -> bool:
        # A call's RESULT is a value; what it is equal to is undecided until
        # the callee floors. That makes membership over it an obligation, not
        # a gap. A LambdaCallable is the callee itself and stays no.
        return True

    def guarded(self, formula):
        """A callsite coordinate rides under a guard unchanged.

        The authenticated call term is the value. It is not a return or inv that becomes an implication; the
        branch guard already owns control. Absence of this arm was
        ``write more Floor: implement CallSiteValue.guarded`` (to_dict /
        base_parser residual).
        """
        del formula
        return self

    def callable_application_with(self, operation, ctx):
        """Applying what a call returned is the named construction gap.

        A call's value is its coordinate: no callee body is applied at lift
        (#7757 step 6), so the callable it returned is not in hand, and
        ``force_floor`` refuses by name; the call spelling is never callable
        authority.
        """
        del operation
        self.force_floor(ctx, owner="CallSiteValue.callable_application_with")

    def truth(self, site):
        # A call result's truth is the one truth rule's two faces
        # (``bool_op_sugar._unanswered_truth``): its type is not decided, so
        # its ``__bool__`` / ``__len__`` may raise, and the truth completes
        # with ``python:truth_result(<result>, <key>)`` only under
        # ``python:truth.completes``, the halt kept, as ``truth_of`` answers
        # for it (#7757 NEW-5).
        # Ground (lift-time-decidable) coordinates must construct, never mint
        # RuntimeEffect authority via py.truthy (#4993 / #5147).
        from sugar_lift_py_tests.effect import is_lift_time_decidable
        from sugar_lift_py_tests.gap.panic import construction_panic_gap
        from sugar_lift_py_tests.sugar.bool_op_sugar import _unanswered_truth

        if is_lift_time_decidable(self.term):
            # No callee body is applied at lift (#7757 step 6): a ground
            # call's truth is not in hand, and is refused by name.
            construction_panic_gap(
                owner="CallSiteValue.truth",
                blame=site,
                observed=f"ground callsite term {self.term!r}",
                requested="constructed lift-time truth value",
                fix=(
                    "construct the concrete callsite/comprehension result before "
                    "truth(); a ground coordinate cannot mint RuntimeEffect authority"
                ),
            )
        return _unanswered_truth(self, site, owner="CallSiteValue.truth")

    def python_isinstance(self, type_name: str, type_term, site):
        """``type(x)`` always returns a type object.

        RaisesExc's ``_exception_type_name(type(exception))`` first asks
        ``isinstance(e, type)``. When that stays an open predicate, the
        else-arm asks ``len(e) == 1`` of this callsite and panics
        ComparisonOpSugar.Eq (plain ``call:len`` is not a decided int). The
        one-arg builtin never fails and never returns a non-type, so
        ``isinstance(type(x), type)`` is True. The builtin is known by its
        binding, never the spelling: only the call ``bind_call`` cited a
        ``python_type_coordinate`` for (``CallSiteSugar._applied_builtin_type_of``)
        is one.  Other callsites keep the reserved tester atom.
        """
        if self.python_type_coordinate is None:
            return super().python_isinstance(type_name, type_term, site)
        from sugar_lift_py_tests.floor.class_value import _CLASS_OBJECT_DISJOINT_TYPES
        from sugar_lift_py_tests.floor.python_type_coordinate import (
            authenticated_python_type_spelling,
        )
        from sugar_lift_py_tests.outcome import ExitSet
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        del type_name
        authenticated = authenticated_python_type_spelling(
            type_term, owner="CallSiteValue.python_isinstance", site=site
        )
        if authenticated in {"type", "object"}:
            return ExitSet.completed(TrueBoolLiteralSugar(site=site))
        if authenticated in _CLASS_OBJECT_DISJOINT_TYPES:
            return ExitSet.completed(FalseBoolLiteralSugar(site=site))
        return super().python_isinstance(authenticated, type_term, site)

    def test_python_type(self, value, site):
        type_coordinate = self.python_type_coordinate
        if type_coordinate is None:
            from sugar_lift_py_tests.effect import (
                CallResultTypeRuntimeEffect,
                runtime_effect_evidence,
            )
            from sugar_lift_py_tests.outcome import ExitSet

            return ExitSet.halted(
                CallResultTypeRuntimeEffect(
                    "call-result type runtime boundary: "
                    f"`{self.target_name}(...)` has no cited return-type/native "
                    "tester coordinate; Python must execute the call before its "
                    f"result can serve as an isinstance type operand; site={site}",
                    **runtime_effect_evidence("adt.is_python_type", self, site),
                )
            )
        from sugar_lift_py_tests.floor.type_tester import native_type_tester

        return native_type_tester(
            value,
            type_coordinate,
            site,
            type_callsites=(self,),
        )

    def test_python_subtype(self, supertype, site):
        """``issubclass(call(...), T)`` when the call is cited to return a class.

        A cited ``python_type_coordinate`` (``type(obj)`` through the builtin
        binding) testifies the result is a class, so CPython's non-class
        ``TypeError`` is not a face: which class is undecided, so the answer
        is the two-faced ``python.subtype`` obligation over the coordinate.
        An uncited call result has no class testimony and stays loud.
        """
        if self.python_type_coordinate is None:
            from sugar_source_tree.panic import SugarNotWritten

            raise SugarNotWritten(
                blame=site,
                owner="CallSiteValue.test_python_subtype",
                observed=(
                    "issubclass operand without class testimony: "
                    f"call result of `{self.target_name}(...)`"
                ),
                requested="a cited class coordinate for the call result",
                fix="cite the callee's returned type object, or keep the call loud",
            )
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.ir import atomic
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.completed(
            PredicateValue(
                atomic(
                    "python.subtype",
                    [
                        self.python_type_coordinate,
                        supertype.to_term(owner="python.issubclass supertype"),
                    ],
                ),
                site,
                operand_callsites=(*self.callsites(), *supertype.callsites()),
            )
        )

    def length(self, site):
        """``len(<call result>)``: no callee body is applied at lift (#7757
        step 6), so the result's type and its ``__len__`` are undecided:
        the builtin's one unanswered call (``floor_value.unanswered_length``),
        two faces, owed, the halt face kept.  Never a completed ``call:len``
        with no halt."""
        from .floor_value import unanswered_length

        return unanswered_length(
            self,
            lambda at: self.to_term(owner=str(at)),
            site,
            owner="CallSiteValue.length",
        )

    def contains(self, item, site):
        # The call result's container type is undecided (no callee body is
        # applied at lift, #7757 step 6) — never ExitSet.completed(py.in)
        # fabrication.
        return self.undecided_contains(item, site, owner="CallSiteValue.contains")

    def _builtin_exception_instance_subscript(self, site):
        """``ValueError("a")[0]``: a builtin exception instance is not subscriptable.

        Decided only when the callee was the language-owned builtin exception
        class and the running interpreter confirms that neither it nor any
        builtins subclass its construction may select defines ``__getitem__``.
        The result is the same ground TypeError as ``ExceptionValue.subscript``.
        """
        cls_value = self.builtin_exception_class
        name = getattr(cls_value, "name", None)
        if not isinstance(name, str):
            return None
        import builtins

        runtime_class = getattr(builtins, name, None)
        if not isinstance(runtime_class, type) or not issubclass(
            runtime_class, BaseException
        ):
            return None
        pending = [runtime_class]
        while pending:
            current = pending.pop()
            if current.__module__ != "builtins":
                continue
            if hasattr(current, "__getitem__"):
                return None
            pending.extend(current.__subclasses__())
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError", site=site, owner="CallSiteValue.subscript"
        )

    def subscript(self, index, site):
        decided = self._builtin_exception_instance_subscript(site)
        if decided is not None:
            return decided
        return self.undecided_subscript(index, site, owner="CallSiteValue.subscript")

    # No ``setitem``/``delitem`` here: what a call returned is its callee's
    # contract's, so its type is not decided and its item store or delete is
    # the one item mutation (``store_effect_sugar.item_mutation``): the
    # dispatched edge for a same-file class's call result, else the undecided
    # arm (completes under its own atom or raises something undetermined,
    # owed).  A path that reaches the floor's own method instead refuses by
    # name (``FloorValue.setitem``), never completes with the halt dropped
    # (#7757 step 7).

    def callsites(self):
        # A CallSiteValue carries itself -- equals emit collects it so the
        # inv that consumes the term can still project the edge later.
        return (self,)

    def names_a_string(self) -> bool:
        """Whether this callsite is known to produce a ``str`` if it completes.

        ``type(x).__name__`` / ``__qualname__`` always return ``str``. A named
        string concat (the ``call:__add__`` or ``python:fstring`` coordinate
        the lifter mints) does too, so ``backquote`` can join
        ``"`" + name + "`"`` without inventing text.

        A source call's result names a string only where its contract states
        it, joined at prove: its body is never read here (#7757 step 6).

        The ``__name__`` / ``__qualname__`` read is known by the marker its
        attribute read mints (``type_name_attribute``), never by the spelling
        of ``target_name``.  The concatenation is known by the marker its mint
        sets (``string_concatenation``), never by the term's name: a user
        function named ``__add__`` is spelled ``call:__add__`` too, and is not
        one.  A ``str.join`` result is known by the callee its mint decided
        (``LanguageCallee.STR_JOIN``, ``string_value.str_join_result``): no
        name binds that callee, so no source call carries it.
        """
        from sugar_source_tree.nodes import LanguageCallee

        return (
            self.type_name_attribute
            or self.string_concatenation
            or self.language_callee is LanguageCallee.STR_JOIN
        )

    @staticmethod
    def named_string_concat(left, right, site):
        """Name ``str + named-string-coordinate`` without inventing the string."""
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.completed(
            CallSiteValue(
                target_name="__add__",
                arg_values=(left, right),
                parameters=(),
                term=ctor(
                    call_symbol("__add__"),
                    [
                        left.to_term(owner="CallSiteValue.named_string_concat"),
                        right.to_term(owner="CallSiteValue.named_string_concat"),
                    ],
                    symbol_kind="coordinate",
                ),
                body=None,
                site=site,
                string_concatenation=True,
            )
        )

    def add(self, other, site, ctx):
        """Addition floor via interface dispatch: concatenation or undecided.

        BinOpSugar calls left.add(right, site, ctx) — not binary_operator_with.
        Without this totalizer, `want_bytes(x) + self.sep`
        construction_panics mid-body.
        A named string coordinate plus a ground string
        (``type(exc).__name__ + "()"``) is concatenation: emit ``call:__add__``
        without inventing the string or falling through ``_undecided_binary_law``.
        """
        from sugar_lift_py_tests.floor.string_value import StringValue

        if type(other) is StringValue and self.names_a_string():
            return self.named_string_concat(self, other, site)
        return self._undecided_binop(
            other, site, ctx, op="+", floor_method="add", undecided=super().add
        )

    def subtract(self, other, site, ctx):
        return self._undecided_binop(
            other,
            site,
            ctx,
            op="-",
            floor_method="subtract",
            undecided=super().subtract,
        )

    def multiply(self, other, site, ctx):
        return self._undecided_binop(
            other,
            site,
            ctx,
            op="*",
            floor_method="multiply",
            undecided=super().multiply,
        )

    def power(self, other, site, ctx):
        return self._undecided_binop(
            other, site, ctx, op="**", floor_method="power", undecided=super().power
        )

    def divide(self, other, site, ctx):
        return self._undecided_binop(
            other, site, ctx, op="/", floor_method="divide", undecided=super().divide
        )

    def modulo(self, other, site, ctx):
        return self._undecided_binop(
            other, site, ctx, op="%", floor_method="modulo", undecided=super().modulo
        )

    def floor_divide(self, other, site, ctx):
        return self._undecided_binop(
            other,
            site,
            ctx,
            op="//",
            floor_method="floor_divide",
            undecided=super().floor_divide,
        )

    def left_shift(self, other, site, ctx):
        return self._undecided_binop(
            other,
            site,
            ctx,
            op="<<",
            floor_method="left_shift",
            undecided=super().left_shift,
        )

    def right_shift(self, other, site, ctx):
        # Base64 / alphabet index math: `ord(c) >> 2` on call results.
        # Without this, FloorValue.right_shift panics (A2 mint-failed on
        # python-literal-base64 / base64-federation).
        return self._undecided_binop(
            other,
            site,
            ctx,
            op=">>",
            floor_method="right_shift",
            undecided=super().right_shift,
        )

    def bitwise_and(self, other, site, ctx):
        # Same family as left_shift / bitwise_or: the undecided dispatch, or
        # retain the named undecided-dispatch refusal.
        return self._undecided_binop(
            other,
            site,
            ctx,
            op="&",
            floor_method="bitwise_and",
            undecided=super().bitwise_and,
        )

    def bitwise_xor(self, other, site, ctx):
        return self._undecided_binop(
            other,
            site,
            ctx,
            op="^",
            floor_method="bitwise_xor",
            undecided=super().bitwise_xor,
        )

    def bitwise_or(self, other, site, ctx):
        return self._undecided_binop(
            other,
            site,
            ctx,
            op="|",
            floor_method="bitwise_or",
            undecided=super().bitwise_or,
        )

    def matrix_multiply(self, other, site, ctx):
        return self._undecided_binop(
            other,
            site,
            ctx,
            op="@",
            floor_method="matrix_multiply",
            undecided=super().matrix_multiply,
        )

    def _undecided_binop(
        self, other, site, ctx, *, op: str, floor_method: str, undecided
    ):
        """Retain undecided dispatch: no invent of concrete sums.

        A call's result is its coordinate (no callee body is applied at lift,
        #7757 step 6), so the operator over it is the undecided dispatch,
        run under the caller's context.

        Every call here is written out (#7757): each arm of a guarded right
        operand answers through the binary floor's own explicit call
        (``BINARY_FLOOR_OPERATIONS``), and ``undecided`` is the caller's own
        ``super()`` floor (``super().subtract``), never a method looked up by
        its name.
        """
        from sugar_lift_py_tests.floor.floor_value import BINARY_FLOOR_OPERATIONS
        from sugar_lift_py_tests.floor.guarded_value import GuardedValue

        operate = BINARY_FLOOR_OPERATIONS[floor_method]
        if isinstance(other, GuardedValue):
            return other.map_from_left(
                lambda arm: operate(self, arm, site, ctx), site, operation=floor_method
            )

        refused = self._undecided_binary_law(other, site, op)
        if refused is not None:
            return refused
        return undecided(other, site, ctx)

    def edge_contribution(self, source_contract):
        # Project one call-edge row: the coordinates this value already carries.
        # Seal/link fields (targetContract, cids) stay absent -- never faked.
        #
        # The symbol has ONE speller, this value, and one source, the import
        # door's receipt (#7762). A call with no such symbol names no target
        # an imported proof could answer, so it projects no edge: there is no
        # `call:<name>` spelling to fall back on.
        if self.authenticated_target_symbol is None:
            return ()
        edge = {
            "kind": "call-edge",
            "sourceContract": source_contract,
            "targetSymbol": self.authenticated_target_symbol,
        }
        if self.target_contract_cid is not None:
            edge["targetContractCid"] = self.target_contract_cid
        if self.site is not None:
            edge["callSiteLocus"] = {
                "file": self.site.filename,
                "line": self.site.line,
                "col": self.site.col,
            }
            from sugar_lift_py_tests.occurrence import site_coordinate_cid

            edge["callsite"] = site_coordinate_cid(self.site)
        return (edge,)

    def subscript_with(self, operation, ctx):
        """Subscript on a callsite result.

        The read of this callsite's result is undecided (no callee body is
        applied at lift, #7757 step 6) and answers the one two-faced form
        (:meth:`FloorValue.undecided_subscript`), produced once. The operation
        owns the submission door -- the deleted central dispatcher must never
        be rediscovered here.
        """
        del ctx
        if self.builtin_exception_class is not None:
            decided = self._builtin_exception_instance_subscript(operation.blame)
            if decided is not None:
                return decided
        return self.undecided_subscript(
            operation.index, operation.blame, owner="CallSiteValue.subscript"
        )

    def project_sequence_with(self, operation, ctx):
        """``a, b = f(...)``: unpack of a callsite result.

        A call's value is its coordinate (no callee body is applied at lift,
        #7757 step 6, the owner's ruling of 2026-11-15, "Edge, join at
        prove"), so the unpack hands the CALLSITE ITSELF to
        ``project_symbolic``, whose runtime unpack is two-faced over the
        callsite's own term (``runtime_unpack_faces``): the retained
        obligation names ``call:<callee>(...)`` -- the coordinate the unpack
        actually demands members of -- and never a fabricated element.  It
        neither invents a member nor assumes the count matched.
        """
        return operation.project_symbolic(self, ctx)

    def force_floor(
        self,
        ctx: Any,
        *,
        owner: str,
        seen: frozenset[str] = frozenset(),
        depth: int = 0,
        budget: int = _FORCE_FLOOR_BUDGET,
        project_callsite: bool = True,
    ):
        """A call's value is its coordinate: no callee body is applied at
        lift (#7757 step 6), so a demand for its concrete floor is the named
        construction gap, never a value read off the callee's body."""
        del ctx, seen, depth, budget, project_callsite
        _force_floor_gap(
            owner=owner,
            target_name=self.target_name,
            observed="a call's value is its coordinate; no callee body is applied",
            fix=(
                f"read callsite `{self.target_name}` as its coordinate, joined "
                "at prove to the callee's contract, or leave the bridge as axiomatic"
            ),
        )


def receiver_after_its_call(receiver, result):
    """``receiver`` as an ordinary call made on it left it (``result``, the
    call's completed value), where the call states that; None where it does
    not, and the receiver is then unknown after the call (the one exposure
    rule, ``PathContainerCallSugar``).

    The only call that states it here is a builtin's own transition of it
    (``ReceiverOwnedMutationResult``): the receiver after that transition.
    A source call states nothing about it: its body is never applied at
    lift (#7757 step 6), and what it did to the receiver is what its
    contract states, joined at prove (step 7).

    What the call states is ``receiver``'s object after it, never a newer
    currency: the state is current only where ``receiver`` was and the call's
    own state is (``object_identity.as_the_alias_holds``), and it keeps
    ``receiver``'s arrival.  A receiver that arrived by binding stays one
    after the call -- its fields are read undecided (``contents_current``) --
    whatever object the callee or a builtin base held for it."""
    from .named_expression_value import peel_walrus_binds
    from .object_value import ObjectValue

    if not isinstance(receiver, ObjectValue):
        return None
    _binds, call = peel_walrus_binds(result)
    return _stated_after(call, receiver)


def _stated_after(call, receiver):
    """``receiver`` after ``call`` (a call's completed value) where the call
    states it (``receiver_after_its_call``), else None: a builtin base's own
    transition of it.  A source call states nothing here: its body is never
    applied at lift, and what it did to the receiver is what its contract
    states, joined at prove (#7757 steps 6 and 7)."""
    from .object_identity import as_the_alias_holds
    from .receiver_owned_mutation_result import ReceiverOwnedMutationResult

    if isinstance(call, ReceiverOwnedMutationResult) and _same_object_value(
        call.receiver_before, receiver
    ):
        # The builtin base's transition, as ``receiver`` holds the object:
        # its currency and arrival, never the base's own receiver's.
        return as_the_alias_holds(call.receiver_after, receiver)
    return None


def _same_object_value(value, receiver) -> bool:
    """``value`` is ``receiver``'s object: an instance of its exact floor
    type with its identity (``ReceiverFieldStoreValue.extend_scope``)."""
    identity = getattr(receiver, "identity", None)
    return (
        isinstance(identity, str)
        and bool(identity)
        and type(value) is type(receiver)
        and getattr(value, "identity", None) == identity
    )


def force_floor(
    value: FloorValue,
    ctx: Any,
    *,
    owner: str,
    seen: frozenset[str] = frozenset(),
    depth: int = 0,
    budget: int = _FORCE_FLOOR_BUDGET,
    project_callsite: bool = True,
) -> FloorValue:
    if isinstance(value, CallSiteValue):
        return value.force_floor(
            ctx,
            owner=owner,
            seen=seen,
            depth=depth,
            budget=budget,
            project_callsite=project_callsite,
        )
    return value


def _current_occurrence_path() -> tuple[str, ...]:
    from sugar_lift_py_tests.occurrence import current_path

    return current_path()


def _force_floor_gap(
    *,
    owner: str,
    target_name: str,
    observed: str,
    fix: str,
) -> NoReturn:
    from sugar_lift_py_tests.gap.panic import construction_panic
    from sugar_lift_py_tests.gap.info import ConstructionGap, GapKind, GapLocus

    info = ConstructionGap(
        owner=owner,
        blame=target_name,
        observed=observed,
        requested="force callsite floor",
        fix=fix,
        gap_kind=GapKind.FLOOR,
        gap_locus=GapLocus.PROJECTION,
    )
    construction_panic(info)


def _ctx_with_curried_args(
    ctx: Any,
    parameters: tuple[str, ...],
    arg_values: tuple[FloorValue, ...],
    formal_coordinate_cids: tuple[str, ...] = (),
    closure: tuple[tuple[str, FloorValue], ...] = (),
):
    from sugar_lift_py_tests.temporal import curry_temporal
    from sugar_lift_py_tests.temporal.temporal_binding import FormalActualBinding

    from .object_identity import as_bound_formals

    if closure:
        # The callee lambda's closure cells (``CallSiteValue.closure``):
        # coordinates, never names, so no formal masks one.
        ctx = curry_temporal(
            ctx,
            tuple(coordinate for coordinate, _ in closure),
            tuple(value for _, value in closure),
            owner="CallSiteValue.force_floor closure cells",
            blame="<callsite-closure>",
        )
    # Each formal holds its actual as the alias rule binds it
    # (``object_identity.as_bound_formals``): the caller's actual, with its
    # currency, unless another actual of this call may reach one of its
    # objects.  Named by its coordinate where the frame carries one.
    coordinates = len(formal_coordinate_cids) == len(arg_values)
    arg_values = as_bound_formals(
        arg_values, formal_coordinate_cids if coordinates else parameters
    )
    # The binding's kind is its type (``FormalActualBinding``), under the
    # formal's name and under its coordinate alike.
    result = curry_temporal(
        ctx,
        parameters,
        arg_values,
        owner="CallSiteValue.force_floor",
        blame="<callsite>",
        kind=FormalActualBinding,
    )
    if formal_coordinate_cids:
        if not coordinates:
            return result
        result = curry_temporal(
            result,
            formal_coordinate_cids,
            arg_values,
            owner="CallSiteValue.force_floor formal coordinates",
            blame="<callsite-coordinate>",
            kind=FormalActualBinding,
        )
    return result


@dataclass(frozen=True)
class AfterCallRecordValue(FloorValue):
    """What one completed evaluation of a same-file definition's call names
    of the operands it was handed (#7757 step 7): the call's result term
    (``python:call_result(<call term>, <occurrence>)``) and, for each
    operand slot, the formal of the callee's contract the one binder binds
    it to (``CallSiteValue.after_labels``).

    Bound under the call's key on the call's completed face, and in the
    record its halted face halts with (``bind_after_call``): a handler, a
    ``finally`` and the frame's exit read what the call left before it
    raised (#7757 H7).  No source name
    holds it: the exposure rule reads it for each object the call may have
    changed (``stated_after_call``), and a later call that reads a module
    global reads the global after it (``call_site_sugar._global_after_call``).

    A call that may reach every module global (``EVERY_GLOBAL_SLOT`` among
    its labels: a call no contract here states, or a same-file call handed
    an object that may be or hold one, ``lambda_callable._after_labels``)
    names each global ``global:<name>``, the formal a contract binds the
    global to: what no contract states of it is the free
    ``python:after(<call result>, "global:<name>")``.

    ``guard``: where the record stands only on some of the paths that reach
    a read -- the call ran in one arm of an ``if`` and the other arm did not
    run it -- the formula under which it stands
    (``if_sugar._arm_evaluations``); None where it stands on every one.  A
    read after the join takes the global as this call left it under the
    guard and as it was before the ``if`` under its complement: the phi of
    the arms, never one arm's state on both (#7757 H7)."""

    result: Term
    labels: tuple
    guard: object = None

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor

        del owner
        return ctor(
            "python:after-call-record", (self.result,), symbol_kind="coordinate"
        )

    def names(self, slot) -> bool:
        """Whether a label names the operand ``slot`` itself."""
        return any(tuple(known) == tuple(slot) for known, _formal in self.labels)

    def reaches_every_global(self) -> bool:
        """Whether the call may reach every module global
        (``EVERY_GLOBAL_SLOT``)."""
        return self.names(EVERY_GLOBAL_SLOT)

    def formal_of(self, slot):
        """The formal the binder bound the operand ``slot`` to, or None.  A
        module global no label names, of a call that may reach every one, is
        its ``global:<name>`` formal."""
        for known, formal in self.labels:
            if tuple(known) == tuple(slot):
                return formal
        slot = tuple(slot)
        if (
            len(slot) == 2
            and slot[0] == "global"
            and slot != EVERY_GLOBAL_SLOT
            and self.reaches_every_global()
        ):
            from sugar_lift_py_tests.contract_input import GLOBAL_INPUT, input_formal

            return input_formal(GLOBAL_INPUT, slot[1])
        return None


# The label of a call that may reach every module global
# (``AfterCallRecordValue.reaches_every_global``): ``*`` is no Python name,
# so no global's own slot (``("global", <name>)``) is ever this one.
EVERY_GLOBAL_SLOT = ("global", "*")


def is_call_record(value) -> bool:
    """Whether ``value`` is what a call's key holds: its record
    (``AfterCallRecordValue``), or the join of the records the arms of an
    ``if`` bound it to (``if_sugar._joined_evaluation``: a ``GuardedValue``
    whose every leaf is one).  A join is the record on each arm's path, read
    as each arm's (``call_site_sugar._global_after_call``), never skipped
    (#7757 L4)."""
    from .guarded_value import GuardedValue

    if isinstance(value, AfterCallRecordValue):
        return True
    return (
        isinstance(value, GuardedValue)
        and is_call_record(value.when_true)
        and is_call_record(value.when_false)
    )


def record_under(value, formula):
    """``value`` (``is_call_record``) standing only where ``formula`` holds:
    each record's guard conjoined with it, the join's selection kept."""
    from dataclasses import replace

    from sugar_lift_py_tests.ir import and_

    from .guarded_value import GuardedValue

    if isinstance(value, GuardedValue):
        return GuardedValue(
            value.guard,
            record_under(value.when_true, formula),
            record_under(value.when_false, formula),
        )
    guard = formula if value.guard is None else and_([formula, value.guard])
    return replace(value, guard=guard)


def _call_record(presented):
    """The record (``AfterCallRecordValue``) the call whose completed value
    is ``presented`` (a ``CallSiteValue``) leaves of what it may have
    reached, or None where it may have reached nothing: a same-file
    definition's edge names what its contract names of what it was handed
    (``after_labels``), and any other call every module global
    (``EVERY_GLOBAL_SLOT``).  A call result the floor answers by its own law
    (a subclass: ``TupleLengthValue``, ``tuple.__len__``) ran no code."""
    labels = tuple(presented.after_labels)
    if (
        type(presented) is CallSiteValue
        and not presented.definition_edge
        and EVERY_GLOBAL_SLOT not in (tuple(known) for known, _formal in labels)
    ):
        labels = (*labels, (EVERY_GLOBAL_SLOT, None))
    if not labels:
        return None
    return AfterCallRecordValue(presented.term, labels)


def _its_other_face(halt_guard, completed_guard) -> bool:
    """Whether ``halt_guard`` is the halted face of the one two-faced
    outcome whose completed face stands under ``completed_guard``
    (``ExitSet.two_faced``: the halt under the complement of the completion
    atom), each under the same prefix of guards the call was reached under:
    the halt where the call ran and raised, never a halt of something that
    ran before the call."""
    from sugar_lift_py_tests.outcome.exit_set import _conjuncts, complement_guard

    if halt_guard == complement_guard(completed_guard):
        return True
    halted = frozenset(_conjuncts(halt_guard))
    done = frozenset(_conjuncts(completed_guard))
    only_done = done - halted
    return bool(only_done) and halted - done == frozenset(
        complement_guard(literal) for literal in only_done
    )


def _halts_carrying_the_record(outcome, after_call_key, ctx, record_of):
    """``outcome`` with each halted face of the call that offers no record
    of its own (``Halted.state`` None) recorded where the call halted:
    ``ctx`` -- the context the call ran in, every operand's write applied --
    with the call's record bound under its key, as its completed face binds
    it (#7757 H7).

    A call that changed what it can reach and then raised left it changed:
    ``def g(): G[0] = 2; raise E``.  A halted face that carried nothing
    reached the handler, the ``finally`` and the frame's exit in the context
    before the call, so a later call that read the global was handed the
    entry's contents (``call_site_sugar._global_after_call``) and a lie
    could read ``sat``.  The halt now reads the object as the call left it,
    ``python:after(<call result>, <formal>)``, the one record a completed
    face carries: decided at prove only under the completed arms of the
    callee's contract (each post under its arm's guard), so free on the
    halted one.

    The record is the completed face's (``record_of``: ``_call_record``, the
    one object that face binds), carried only to the halt that is that
    face's other side (``_its_other_face``); a halt
    with no such completed face (a call that only halts) is left as it is,
    and so is every outcome when ``ctx`` holds no temporal."""
    from dataclasses import replace

    from sugar_lift_py_tests.outcome.exit_set import Completed, ExitSet, Halted
    from sugar_lift_py_tests.sugar.function_universe_sugar import halt_record

    from .named_expression_value import (
        NamedExpressionValue,
        bind_walrus_binds,
        peel_walrus_binds,
    )

    if getattr(ctx, "temporal", None) is None or not any(
        isinstance(exit_, Halted) and exit_.state is None for exit_ in outcome.exits
    ):
        return outcome
    faces = []
    for exit_ in outcome.exits:
        if not isinstance(exit_, Completed):
            continue
        _binds, presented = peel_walrus_binds(exit_.value)
        if isinstance(presented, CallSiteValue):
            record = record_of(presented)
            if record is not None:
                faces.append((exit_.guard, record))
    if not faces:
        return outcome
    key = after_call_key()
    exits = []
    for exit_ in outcome.exits:
        if isinstance(exit_, Halted) and exit_.state is None:
            record = next(
                (
                    record
                    for guard, record in faces
                    if _its_other_face(exit_.guard, guard)
                ),
                None,
            )
            if record is not None:
                bound = bind_walrus_binds(
                    (NamedExpressionValue(key, record, evaluation=key),), ctx
                )
                exit_ = replace(exit_, state=halt_record(bound))
        exits.append(exit_)
    return ExitSet(tuple(exits))


def bind_after_call(outcome, site, ctx=None):
    """``outcome`` (the exits of the call whose fragment is ``site``, run
    in ``ctx``) with each completed face that is a same-file definition's
    edge naming what it was handed (``CallSiteValue.after_labels``) carrying
    its record (``AfterCallRecordValue``) as a walrus carries its write:
    bound under the call's key (``Call.after_call_key``) where the statement
    applies its writes (``bind_walrus_binds``) (#7757 step 7).

    Every other completed call -- one that is no same-file definition's
    edge (``CallSiteValue.definition_edge``): a callee nothing here answers
    (a formal, an unbound name, an import, a builtin over undecided
    operands, a method no class here answers), a class construction, a
    value call -- runs code no contract here states, which may reach every
    module global: its record names ``EVERY_GLOBAL_SLOT``, and a later call
    that reads a mutable global reads it as this call left it
    (``call_site_sugar._global_after_call``: ``python:after(<call result>,
    "global:<name>")``, which no contract states), never as it was before
    (#7757 H7).

    The halted face of the same call carries the same record, in the
    record it halts with (``_halts_carrying_the_record``): what the call
    left before it raised is read where the halt is caught, never what was
    there before the call (#7757 H7).  Every other outcome comes back as it
    is."""
    from sugar_lift_py_tests.outcome import ExitSet

    from .named_expression_value import (
        NamedExpressionValue,
        carry_walrus_binds,
        peel_walrus_binds,
    )

    after_call_key = getattr(getattr(site, "node", None), "after_call_key", None)
    if not isinstance(outcome, ExitSet) or after_call_key is None:
        return outcome

    # One record per completed value, the same object on its completed face
    # and on the halted face that is its other side: a join over both faces
    # (an ``if`` arm holding a ``try`` around the call) finds the record it
    # carries one value (``if_sugar._joined_evaluation``), never two.
    made: dict = {}

    def record_of(presented):
        held = made.get(id(presented))
        if held is None:
            held = made[id(presented)] = (presented, _call_record(presented))
        return held[1]

    def carrying(value):
        binds, presented = peel_walrus_binds(value)
        if not isinstance(presented, CallSiteValue):
            return ExitSet.completed(value)
        after = record_of(presented)
        if after is None:
            return ExitSet.completed(value)
        key = after_call_key()
        record = NamedExpressionValue(key, after, evaluation=key)
        return ExitSet.completed(carry_walrus_binds((*binds, record), presented))

    return _halts_carrying_the_record(
        outcome, after_call_key, ctx, record_of
    ).and_then(carrying)


def stated_after_call(ctx, key, slot):
    """The object a call reached through ``slot`` as the call left it, read
    where the reduction runs: ``python:after(<call result>, <formal>)``
    (``source_call_resolution.object_after_call``), where the call's
    completed face, or the halted face that is its other side, bound its
    record under ``key`` (``bind_after_call``) and the binder bound ``slot``
    to a formal; None elsewhere -- a call no contract names, a halt that is
    no face of the call -- and the value stays undecided (#7757 step 7)."""
    temporal = getattr(ctx, "temporal", None)
    if temporal is None:
        return None
    from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
    from sugar_lift_py_tests.source_call_resolution import object_after_call
    from sugar_lift_py_tests.sugar.evaluation_ref_sugar import evaluation_read_here

    record = temporal.value_if_bound(evaluation_read_here(temporal, key))
    if not isinstance(record, AfterCallRecordValue):
        return None
    formal = record.formal_of(slot)
    if formal is None:
        return None
    return SymbolicValue(object_after_call(record.result, formal))
