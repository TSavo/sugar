from __future__ import annotations

import weakref
from dataclasses import dataclass, field as dataclass_field
from typing import Any, NoReturn

from sugar_lift_py_tests.call_symbol import call_symbol
from sugar_lift_py_tests.ir import Term, TermTableBuilder
from sugar_lift_py_tests.sugar.function_body_universe import FunctionBodyUniverse
from sugar_lift_py_tests.sugar_body import SugarBody


from .floor_value import FloorValue

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
    completes): a ground string, a call coordinate whose mint names a string
    (``CallSiteValue.names_a_string``), or the opaque ``str.join`` coordinate
    (``LanguageCallee.STR_JOIN``, its binding, never its spelling)."""
    from sugar_lift_py_tests.floor.opaque_op_callsite import OpaqueOpCallsite
    from sugar_lift_py_tests.floor.string_value import StringValue
    from sugar_source_tree.nodes import LanguageCallee

    if type(value) is StringValue:
        return True
    if type(value) is CallSiteValue:
        return value.names_a_string()
    return (
        type(value) is OpaqueOpCallsite
        and value.language_callee is LanguageCallee.STR_JOIN
    )


@dataclass(frozen=True)
class ExitSuppressionContract:
    """Static evidence for one context manager's exceptional exit.

    An empty coordinate set proves propagation. A non-empty set proves that
    exactly those **authenticated type coordinates** are suppressed. Names
    enter only through :meth:`suppresses`, which resolves each name to a
    builtin ``python:exception_type_identity`` once at construction — the
    one door. Match sites never see a spelling; they compare
    ``effect.exception_type_coordinate`` against this frozenset.

    Runtime-dependent exits carry no contract at all and therefore remain
    loud in WithSugar.

    Retirement path for residual name suppress: the deleted
    ``exception_names`` / ``suppresses_exception(str)`` shell. If a caller
    needs foreign (non-builtin) types, promote this field to carry
    source-authenticated coordinates from the tree rather than the builtin
    table — then the string door can refuse non-empty names entirely.
    """

    exception_type_coordinates: frozenset

    @classmethod
    def never_suppresses(cls) -> "ExitSuppressionContract":
        return cls(frozenset())

    @classmethod
    def suppresses(cls, exception_names: tuple[str, ...]) -> "ExitSuppressionContract":
        """ONE door: resolve source-facing names to type coordinates at mint."""
        if not exception_names:
            raise ValueError("a suppressing exit contract must name an exception")
        from sugar_lift_py_tests.floor.ground_exit import _builtin_exception_identity

        coordinates = []
        for name in exception_names:
            if not isinstance(name, str) or not name:
                raise ValueError(
                    "ExitSuppressionContract.suppresses requires non-empty "
                    f"exception type names; got {name!r}"
                )
            identity, _mro = _builtin_exception_identity(name)
            if identity is None:
                raise ValueError(
                    f"matcher name {name!r} has no builtin type coordinate; "
                    "use a language-owned exception or thread an authenticated "
                    "coordinate into ExitSuppressionContract"
                )
            coordinates.append(identity)
        return cls(frozenset(coordinates))

    def suppresses_coordinate(self, coordinate) -> bool:
        """True when ``coordinate`` is one of the contract's type identities."""
        return coordinate in self.exception_type_coordinates


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
    # Source-authenticated context-manager evidence.  None means undecidable,
    # never "does not suppress".
    exit_suppression: ExitSuppressionContract | None = None
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
    bound_native_actuals_by_coordinate: dict[str, FloorValue] | None = dataclass_field(
        default=None, compare=False
    )
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
    # On such a result (``constructed_by_edge``) of a class whose
    # construction runs no source code (``object.__new__`` and
    # ``object.__init__``, ``ClassDefinitionValue.callable_application_with``):
    # the class's join symbol.  The instance is of that class with nothing in
    # its ``__dict__``, so a method call on it is dispatched on that class at
    # prove (``receiver_dispatch.class_value``, #7757 step 8).
    instance_of: str | None = dataclass_field(default=None, compare=False, repr=False)

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
        that is no formal (``SymbolicValue.iter_with``): a ``for`` over a
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
        attribute and ``format_data_model`` names ``call:__format__`` without
        inventing the formatted string. Every other member is not decided
        here: the one two-faced unanswered read (``undecided_attribute``).
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
            return self.undecided_attribute(
                name, site, owner="CallSiteValue.attribute"
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

            return self.undecided_attribute(
                name,
                site,
                owner="CallSiteValue.attribute",
                receiver_term=object_after_call(
                    self.to_term(owner=str(site)), CALL_RESULT_LABEL
                ),
            )
        # Any other member -- of an opaque call result or of an authenticated
        # exception instance (``__context__``) -- is not decided here.
        return self.undecided_attribute(name, site, owner="CallSiteValue.attribute")

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
        """Apply the authenticated value returned by a source-backed call.

        Decorator factories commonly return another callable.  The call
        occurrence remains the producer coordinate, but Python applies the
        returned floor.  Opaque or self-recursive projection stays loud rather
        than treating the call spelling as callable authority.
        """
        projected = self.force_floor(
            ctx, owner="CallSiteValue.callable_application_with"
        )
        if projected is self:
            from sugar_source_tree.panic import SugarNotWritten

            raise SugarNotWritten(
                owner="CallSiteValue.callable_application_with",
                blame=operation.site,
                observed="source call projected to its own call coordinate",
                requested="authenticated returned callable Floor",
                fix="retain the factory return or keep decorator application loud",
            )
        return operation.apply(projected, ctx)

    def truth(self, site):
        # A callsite EMITS py.truthy over its term, carrying itself as an operand.
        # Ground (lift-time-decidable) coordinates must construct, never mint
        # RuntimeEffect authority via py.truthy (#4993 / #5147).
        from sugar_lift_py_tests.effect import is_lift_time_decidable
        from sugar_lift_py_tests.gap.panic import construction_panic_gap
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.ir import py_truthy
        from sugar_lift_py_tests.outcome import ExitSet

        if is_lift_time_decidable(self.term):
            constructed = self._construct_decidable_truth(site)
            if constructed is not None:
                return constructed
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
        return ExitSet.completed(
            PredicateValue(
                py_truthy(self.result_term()), site, operand_callsites=(self,)
            )
        )

    def _construct_decidable_truth(self, site):
        """Construct truth for a ground callsite, or return None to stay loud.

        - Dug body answers with its truth, taken through the one truth rule
          (``bool_op_sugar.truth_of``): a dug value whose truth is not decided
          is its two faces.
        Unconstructable ground residual returns None so the caller panics.
        """
        from sugar_lift_py_tests.sugar.bool_op_sugar import truth_of

        dug = self._dig_floor_or_none(None, owner="CallSiteValue.truth")
        if dug is not None and dug is not self:
            return truth_of(dug, site, owner="CallSiteValue.truth")
        return None

    def bitwise_invert(self, site):
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue

        return SymbolicValue(self.result_term()).bitwise_invert(site)

    def unary_minus(self, site):
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue

        return SymbolicValue(self.result_term()).unary_minus(site)

    def unary_plus(self, site):
        dug = self._dig_floor_or_none(None, owner="CallSiteValue.unary_plus")
        if dug is not None and dug is not self:
            return dug.unary_plus(site)
        if self.body is not None:
            return super().unary_plus(site)

        from sugar_lift_py_tests.effect import runtime_unary_plus

        return runtime_unary_plus(self, site)

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
        # A callsite length stays the call:len coordinate over this value's term.
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.completed(
            CallSiteValue(
                target_name="len",
                arg_values=(self,),
                parameters=(),
                term=ctor(
                    call_symbol("len"),
                    [self.to_term(owner=str(site))],
                    symbol_kind="builtin",
                ),
                body=None,
                site=site,
            )
        )

    def contains(self, item, site):
        # Dig a concrete container when the body yields one; otherwise the call
        # result's container type is undecided — named refusal, never
        # ExitSet.completed(py.in) fabrication.
        dug = self._dig_floor_or_none(None, owner="CallSiteValue.contains")
        if dug is not None and dug is not self:
            return dug.contains(item, site)
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

    def setitem(self, index, value, site, ctx):
        """Rebind an opaque mapping/list-shaped callsite after ``xs[k] = v``.

        Concrete containers fold post-state. A callsite receiver has no element
        history, but the store still rebinds the name: carry prior coordinate,
        index, and value on ``py.setitem``. Non-name receivers stay halted
        at the sugar layer (``SubscriptAssignSugar._cite_update``) because no
        name exists to rebind. Do not invent members.
        """
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.outcome import ExitSet

        index_term = index.to_term(owner="CallSiteValue.setitem index")
        value_term = value.to_term(owner="CallSiteValue.setitem value")
        return ExitSet.completed(
            CallSiteValue(
                target_name="setitem",
                arg_values=(self, index, value),
                parameters=(),
                term=ctor(
                    "py.setitem",
                    [self.to_term(owner=str(site)), index_term, value_term],
                    symbol_kind="method-coordinate",
                ),
                body=None,
                site=site,
            )
        )

    def append_with(self, value, site):
        """Construct a proven list-shaped callsite after ``.append(v)``.

        Concrete ``ListValue`` folds element history. A callsite (for example
        ``list(xs)`` over an opaque ``xs``) has no element history to fold,
        but the append statement still rebinds the name: carry the prior list coordinate and
        appended value on ``py.list_append`` so later statements keep a
        FloorValue. (A ``typing.cast`` never arrives as a receiver: the Call
        node constructs its second operand.) A call bound to the builtin
        ``list`` (its ``LanguageCallee``, never its spelling) is list-shaped.
        The ``py.subscript`` coordinate (its marker, never its spelling) of a
        diggable tuple/list projects the element when the index is a ground
        int (unpack residual: ``handles`` from a returned triple).
        A curried For post-state (``loop:…`` target) that carried a list via
        append-rebind is still list-shaped: further appends rebind through
        ``py.list_append`` without re-digging the loop body. Chained
        ``py.list_append`` coordinates do the same.
        Opaque subscript/iter faces stay loud; a call result is not proof
        that the receiver is a mutable list, and a callee's spelling is not
        proof of what it binds (#7757). Never mint RuntimeEffect over a
        ground list proof.
        """
        from sugar_lift_py_tests.floor.comprehension_value import ComprehensionValue
        from sugar_lift_py_tests.floor.list_value import ListValue
        from sugar_lift_py_tests.floor.term_value import TermValue
        from sugar_lift_py_tests.floor.tuple_value import TupleValue
        from sugar_lift_py_tests.outcome import ExitSet, complete_value

        def is_list_floor(floor) -> bool:
            return isinstance(floor, (ListValue, ComprehensionValue))

        def is_constructed_list_callsite(receiver: CallSiteValue) -> bool:
            # Proven list constructors and post-states that already rebind through
            # ``py.list_append``. ``loop:…`` is the curried For floor's single
            # (or projected) list-shaped carried output after append-rebinding
            # iterations (#5338 / public_api residual after #5574).
            # ``py.list_append`` is the coordinate this door itself mints —
            # chained appends must not re-panic. Content identity stays on
            # term CID (#5569).
            from sugar_source_tree.nodes import LanguageCallee

            if receiver.language_callee is LanguageCallee.BUILTIN_LIST:
                return True
            if receiver.target_name.startswith("loop:"):
                return True
            if getattr(receiver.term, "name", None) == "py.list_append":
                return True
            return (
                receiver.subscript_coordinate
                and bool(receiver.arg_values)
                and isinstance(receiver.arg_values[0], CallSiteValue)
                and is_constructed_list_callsite(receiver.arg_values[0])
            )

        def dig_floor(operand):
            if isinstance(operand, CallSiteValue):
                return operand._dig_floor_or_none(
                    None, owner="CallSiteValue.append_with"
                )
            return None

        def list_append_coordinate(prior):
            return ExitSet.completed(list_append_coordinate_value(prior, value, site))

        def project_list_operand(operand):
            """Fold to a list floor, rebind through list_append, or None (loud)."""
            from sugar_lift_py_tests.floor.opaque_op_callsite import OpaqueOpCallsite

            if is_list_floor(operand):
                return operand.append_with(value, site)
            if (
                isinstance(operand, OpaqueOpCallsite)
                and operand.stands_on_append_floor()
            ):
                # ``str.split`` by an opaque separator (its marker).
                return operand.append_with(value, site)
            if not isinstance(operand, CallSiteValue):
                return None
            dug = dig_floor(operand)
            if is_list_floor(dug):
                return dug.append_with(value, site)
            if is_constructed_list_callsite(operand):
                return list_append_coordinate(operand)
            return resolve_receiver(operand)

        def resolve_receiver(receiver: CallSiteValue):
            # Unpack residual: handles = returned_triple[2] where the call digs
            # to a TupleValue/ListValue and the index is a ground int.
            if receiver.subscript_coordinate and len(receiver.arg_values) == 2:
                base, index = receiver.arg_values
                if isinstance(index, TermValue) and type(index.value) is int:
                    floor_base = base
                    if isinstance(base, CallSiteValue):
                        dug_base = dig_floor(base)
                        if dug_base is not None:
                            floor_base = dug_base
                    if isinstance(floor_base, (ListValue, TupleValue)):
                        from sugar_lift_py_tests.operations.subscript_operation import (
                            discharge_subscript,
                        )

                        projected = discharge_subscript(
                            floor_base,
                            index,
                            site,
                            None,
                            owner="CallSiteValue.append_with subscript",
                        )
                        if projected.halts() == projected.exits:
                            return None
                        element = complete_value(
                            projected, owner="CallSiteValue.append_with subscript"
                        )
                        return project_list_operand(element)
                if is_constructed_list_callsite(receiver):
                    return list_append_coordinate(receiver)
                return None

            if is_constructed_list_callsite(receiver):
                return list_append_coordinate(receiver)
            return None

        constructed = resolve_receiver(self)
        if constructed is not None:
            return constructed

        from sugar_lift_py_tests.gap.panic import construction_panic_gap

        construction_panic_gap(
            owner="CallSiteValue.append_with",
            blame=str(site),
            observed=f"CallSiteValue({self.target_name})",
            requested="classified append contract",
            fix=(
                "prove that the call result is a mutable list and construct "
                "its post-append state, or leave it loud"
            ),
        )

    def delitem(self, index, site, ctx):
        """Rebind an opaque mapping/list-shaped callsite after ``del xs[k]``.

        Concrete containers fold post-state. A callsite receiver (for example
        ``dict_class(...)``) has no element history, but the delete still
        rebinds the name: carry prior coordinate and index on ``py.delitem``.
        Do not invent members; do not hide the gap — silence stays illegal.
        """
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.outcome import ExitSet

        index_term = index.to_term(owner="CallSiteValue.delitem index")
        return ExitSet.completed(
            CallSiteValue(
                target_name="delitem",
                arg_values=(self, index),
                parameters=(),
                term=ctor(
                    "py.delitem",
                    [self.to_term(owner=str(site)), index_term],
                    symbol_kind="method-coordinate",
                ),
                body=None,
                site=site,
            )
        )

    def callsites(self):
        # A CallSiteValue carries itself -- equals emit collects it so the
        # inv that consumes the term can still project the edge later.
        return (self,)

    def derived_equality_residue(self, ctx):
        """Return the callsite's ground body fact when its dig warrants one.

        The function universe already owns the body post.  Equality testimony
        additionally needs the callsite-keyed residue so the stated assertion
        and the derived value remain independently visible at the EUF join.
        Only a single ``out = ground-value`` post is a derived value pin;
        opaque, effectful, symbolic, and multi-exit bodies stay absent and
        therefore loud at the existing construction-gap boundary.

        Ground values are primitive consts *and* data constructors the
        verifier treats as structural values (``None``, ``py.ellipsis``,
        ``py.complex``, tuples/arrays/… — see ``_is_ground_value_term``).
        That parity is load-bearing: without a callsite-keyed Derived dual,
        ``assert A() == None`` against a body that returns ``...`` soft-SATs
        (#4387 ellipsis E2E residue).
        """
        floor = self._dig_floor_or_none(
            ctx,
            owner="CallSiteValue.derived_equality_residue",
        )
        if floor is None:
            return None
        posts = tuple(floor.post_contribution())

        from sugar_lift_py_tests.ir import (
            _Atomic,
            _Var,
            eq,
        )

        if not posts:
            rhs = floor.to_term(owner="CallSiteValue.derived_equality_residue")
        elif len(posts) == 1:
            post = posts[0]
            if not (
                isinstance(post, _Atomic)
                and post.name == "="
                and len(post.args) == 2
                and isinstance(post.args[0], _Var)
                and post.args[0].name == "out"
            ):
                return None
            rhs = post.args[1]
        else:
            return None
        if not _is_ground_value_term(rhs):
            return None
        return eq(self.result_term(), rhs)

    def linear_method_call(self, method_name: str, args: tuple, site):
        """Name the next link in a timeless receiver-method rewrite."""
        from sugar_lift_py_tests.ir import ctor

        return CallSiteValue(
            target_name=method_name,
            arg_values=(self, *args),
            parameters=(),
            term=ctor(
                call_symbol(method_name),
                [
                    self.to_term(owner=str(site)),
                    *(arg.to_term(owner=str(site)) for arg in args),
                ],
                symbol_kind="method-coordinate",
            ),
            body=None,
            site=site,
        )

    def format_data_model(self, spec, site, ctx) -> Any:
        """Construct ``format(call(), spec)`` at the Python data-model seam.

        A carried body is statically decidable and must reduce (or panic) before
        dispatch.  A body-less callsite still has an exact receiver coordinate:
        preserve it as the symbolic ``__format__`` method call without claiming
        a concrete return value and without manufacturing a RuntimeEffect.
        """
        if self.body is not None:
            floor = self._dig_floor_or_none(
                ctx,
                owner="FormatDunderCallSugar callsite receiver",
            )
            if floor is None:
                from sugar_lift_py_tests.outcome import ExitSet

                return ExitSet.completed(
                    self.linear_method_call("__format__", (spec,), site)
                )
            return floor.format_data_model(spec, site, ctx)
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.completed(self.linear_method_call("__format__", (spec,), site))

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
        one.
        """
        return self.type_name_attribute or self.string_concatenation

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
        """Addition floor via interface dispatch: dig, redispatch, or refuse.

        BinOpSugar calls left.add(right, site, ctx) — not binary_operator_with.
        Without this totalizer, dig of `want_bytes(x) + self.sep`
        construction_panics mid-body.
        A named string coordinate plus a ground string
        (``type(exc).__name__ + "()"``) is concatenation: emit ``call:__add__``
        without inventing the string or falling through ``_undecided_binary_law``.
        """
        from sugar_lift_py_tests.floor.string_value import StringValue

        if type(other) is StringValue and self.names_a_string():
            return self.named_string_concat(self, other, site)
        return self._dig_or_undecided_binop(
            other, site, ctx, op="+", floor_method="add", undecided=super().add
        )

    def subtract(self, other, site, ctx):
        return self._dig_or_undecided_binop(
            other,
            site,
            ctx,
            op="-",
            floor_method="subtract",
            undecided=super().subtract,
        )

    def multiply(self, other, site, ctx):
        return self._dig_or_undecided_binop(
            other,
            site,
            ctx,
            op="*",
            floor_method="multiply",
            undecided=super().multiply,
        )

    def power(self, other, site, ctx):
        return self._dig_or_undecided_binop(
            other, site, ctx, op="**", floor_method="power", undecided=super().power
        )

    def divide(self, other, site, ctx):
        return self._dig_or_undecided_binop(
            other, site, ctx, op="/", floor_method="divide", undecided=super().divide
        )

    def modulo(self, other, site, ctx):
        return self._dig_or_undecided_binop(
            other, site, ctx, op="%", floor_method="modulo", undecided=super().modulo
        )

    def floor_divide(self, other, site, ctx):
        return self._dig_or_undecided_binop(
            other,
            site,
            ctx,
            op="//",
            floor_method="floor_divide",
            undecided=super().floor_divide,
        )

    def left_shift(self, other, site, ctx):
        return self._dig_or_undecided_binop(
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
        return self._dig_or_undecided_binop(
            other,
            site,
            ctx,
            op=">>",
            floor_method="right_shift",
            undecided=super().right_shift,
        )

    def bitwise_and(self, other, site, ctx):
        # Same family as left_shift / bitwise_or: dig then redispatch, else
        # retain the named undecided-dispatch refusal.
        return self._dig_or_undecided_binop(
            other,
            site,
            ctx,
            op="&",
            floor_method="bitwise_and",
            undecided=super().bitwise_and,
        )

    def bitwise_xor(self, other, site, ctx):
        return self._dig_or_undecided_binop(
            other,
            site,
            ctx,
            op="^",
            floor_method="bitwise_xor",
            undecided=super().bitwise_xor,
        )

    def bitwise_or(self, other, site, ctx):
        return self._dig_or_undecided_binop(
            other,
            site,
            ctx,
            op="|",
            floor_method="bitwise_or",
            undecided=super().bitwise_or,
        )

    def matrix_multiply(self, other, site, ctx):
        return self._dig_or_undecided_binop(
            other,
            site,
            ctx,
            op="@",
            floor_method="matrix_multiply",
            undecided=super().matrix_multiply,
        )

    def _dig_or_undecided_binop(
        self, other, site, ctx, *, op: str, floor_method: str, undecided
    ):
        """Dig source body when present; otherwise retain undecided dispatch.

        No invent of concrete sums. The dig and the redispatch run under the
        caller's context (#7757): a body is never applied context-free.
        Mid-dig ConstructionPanic propagates (process-terminal; never dig opacity).

        Keep an opaque named leaf (``preserve_opaque_leaf``). ``_exception_type_name``
        reduces to ``attr:__name__``, which has no further body; discarding that
        leaf would refuse ``helper() + "()"`` on the helper callsite itself
        instead of naming concat of the known string coordinate.

        Every call here is written out (#7757): the dug floor and each arm of a
        guarded right operand answer through the binary floor's own explicit
        call (``BINARY_FLOOR_OPERATIONS``), and ``undecided`` is the caller's
        own ``super()`` floor (``super().subtract``), never a method looked up
        by its name.
        """
        from sugar_lift_py_tests.floor.floor_value import BINARY_FLOOR_OPERATIONS
        from sugar_lift_py_tests.floor.guarded_value import GuardedValue

        operate = BINARY_FLOOR_OPERATIONS[floor_method]
        if isinstance(other, GuardedValue):
            return other.map_from_left(
                lambda arm: operate(self, arm, site, ctx), site, operation=floor_method
            )

        dug = self._dig_floor_or_none(
            ctx,
            owner=f"CallSiteValue.{floor_method}",
            preserve_opaque_leaf=True,
        )
        if dug is not None and dug is not self:
            return operate(dug, other, site, ctx)

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

        Dig when the body floors; otherwise the read of this callsite's
        result is undecided and answers the one two-faced form
        (:meth:`FloorValue.undecided_subscript`), produced once. The operation
        owns the submission door -- the deleted central dispatcher must never
        be rediscovered here.
        """
        if self.builtin_exception_class is not None:
            decided = self._builtin_exception_instance_subscript(operation.blame)
            if decided is not None:
                return decided
        floor = self._dig_floor_or_none(
            ctx,
            owner=f"{operation.owner} callsite subscript receiver",
        )
        if floor is not None:
            return operation.submit(floor, ctx)
        return self.undecided_subscript(
            operation.index, operation.blame, owner="CallSiteValue.subscript"
        )

    def project_sequence_with(self, operation, ctx):
        """``a, b = f(...)``: unpack of a callsite result.

        Same dig-or-symbolic totalizer as subscript_with, and the same route
        ``OpaqueOpCallsite`` already documents for this exact operation: dig
        the callsite floor when the
        body floors, so a callee returning a display makes the arity lift-time
        decidable and the members bind from the values already in hand;
        otherwise re-dispatch on ``SymbolicValue(self.term)``, whose runtime
        unpack is two-faced over the callsite's own term
        (``runtime_unpack_faces``).

        Neither arm invents a member and neither assumes the count matched --
        which is what ``SequenceProjectionOperation`` requires of a value that
        answers at all. Absence of this arm was the ``project_sequence_with``
        panic on six of the measured rows.

        It dispatches on the dug floor's own port. The opaque arm
        hands the CALLSITE ITSELF to ``project_symbolic``, so the retained
        obligation names ``call:<callee>(...)`` -- the coordinate the unpack
        actually demands members of -- and never a fabricated element.
        """
        floor = self._dig_floor_or_none(
            ctx, owner=f"{operation.owner} callsite unpack right-hand side"
        )
        if floor is not None:
            return floor.project_sequence_with(operation, ctx)
        return operation.project_symbolic(self, ctx)

    def _dig_floor_or_none(
        self,
        ctx: Any,
        *,
        owner: str,
        incomplete_outcome: list | None = None,
        preserve_opaque_leaf: bool = False,
        seen: frozenset[str] = frozenset(),
        depth: int = 0,
        budget: int = _FORCE_FLOOR_BUDGET,
    ) -> FloorValue | None:
        """Return a concrete floor when dig succeeds; None when the receiver is opaque.

        A call's value is its coordinate: no callee body is applied at lift
        (#7757 step 6, the owner's ruling of 2026-11-15, "Edge, join at
        prove"), so every call is opaque here -- an EUF-join residual, not a
        panic -- and what it returns is what the callee's contract states,
        joined at prove.  Budget / recursive demand still panics: those are
        non-composable, not joinable coordinates.
        """
        del ctx, incomplete_outcome
        key = _term_cycle_key(self.term)
        if depth >= budget or len(seen) >= budget:
            _force_floor_gap(
                owner=owner,
                target_name=self.target_name,
                observed="callsite value demand budget exhausted",
                fix=(
                    f"callsite `{self.target_name}` exceeded force_floor dig budget "
                    f"{budget}; leave the bridge as axiomatic"
                ),
            )
        if key in seen:
            _force_floor_gap(
                owner=owner,
                target_name=self.target_name,
                observed="recursive callsite value demand",
                fix=(
                    f"callsite `{self.target_name}` recursively demanded its own "
                    "floor; leave the bridge as axiomatic"
                ),
            )
        return self if preserve_opaque_leaf else None

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


def caller_visible_stores(entries) -> tuple:
    """The receiver field stores among a callee record's ``entries`` that
    reach its caller: every unconditional one, as a ``ReceiverFieldStoreValue``.

    A store whose guard is truth -- a nested empty ``and`` included -- is
    unconditional: a folded ``isinstance(match, str)`` still stamps the tail
    with ``true_guard``, and that is not a branch.  A store under a real
    branch guard stays in the callee's nested record; it is never flattened
    onto the receiver."""
    from sugar_lift_py_tests.floor.guarded_receiver_field_store_value import (
        GuardedReceiverFieldStoreValue,
    )
    from sugar_lift_py_tests.floor.receiver_field_store_value import (
        ReceiverFieldStoreValue,
    )

    stores = []
    for entry in entries:
        if isinstance(entry, GuardedReceiverFieldStoreValue):
            if _unconditional(entry.guard):
                stores.append(
                    ReceiverFieldStoreValue(entry.receiver, entry.attr, entry.value)
                )
        elif isinstance(entry, ReceiverFieldStoreValue):
            stores.append(entry)
    return tuple(stores)


def _unconditional(guard) -> bool:
    """A guard that is truth, a nested empty ``and`` included."""
    from sugar_lift_py_tests.outcome.exit_set import _is_true

    if _is_true(guard):
        return True
    if getattr(guard, "kind", None) == "and":
        return all(
            _unconditional(operand) for operand in getattr(guard, "operands", ())
        )
    return False


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


def at_the_call(ctx, carried=()):
    """The state a call's halt carries once it leaves the callee (#7757).

    A halt raised inside a called function reaches its caller at the call:
    what the callee bound is the callee's frame, gone with it, and a name the
    callee binds never shadows the caller's. So the halt leaves the callee in
    the caller's record at the call site: the caller's context there
    (``ctx``, the context the call was reduced in) -- the caller's reducer
    splices every entry the caller made before the call in front
    (``function_universe_sugar._halt_state``), as it does for any statement's
    halt. The halt keeps the callee's effect, and its arm keeps what the
    callee owes (``ExitSet.and_then``).

    What the call did before its halt to an object the caller can see is
    not rolled back: ``carried`` are the writes the call carries on this
    arm, each applied to the caller's context (``bind_walrus_binds``) as a
    completed call's value carries them to its statement; the receiver field
    stores among them are the record's entries.  A class call publishes no
    halt of its class statement: the statement ran where it stands, and the
    call reads the class it bound."""
    from sugar_lift_py_tests.floor.named_expression_value import (
        bind_walrus_binds,
        caller_stores_of,
    )
    from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock

    _writes, stores = caller_stores_of(tuple(carried))
    context = bind_walrus_binds(tuple(carried), ctx)
    return _ReducedBlock(tuple(stores), True, (), context=context)


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


# Data constructors the verifier treats as structural *values* (not operators /
# callsites). Must stay aligned with sugar-verifier `is_ground_data_ctor_name`
# so Derived residue duals leave the same ground faces as gaps structurally.
_GROUND_DATA_CTOR_NAMES = frozenset(
    {
        "tuple",
        "array",
        "None",
        "py.complex",
        "py.ellipsis",
        "python:module",
        "python:type",
        "python:dict",
        "python:dict_entry",
        "python:set",
        "python:frozenset",
        "python:bytes",
        "python:bytearray",
        "python:list",
        "python:tuple",
    }
)


def _is_ground_value_term(term) -> bool:
    """True when ``term`` is a structural ground value for Derived EUF residue.

    Mirrors sugar-verifier ``is_const_value``: primitive consts, plus ground
    data constructors whose args are themselves ground. Operator/callsite
    ctors (``+``, ``call:…``, ``py.attr``, …) stay out so dig residue cannot
    invent a dual that structural consistency would not mark as a gap.
    """
    from sugar_lift_py_tests.ir import (
        _ConstBool,
        _ConstInt,
        _ConstReal,
        _ConstStr,
        _Ctor,
    )

    if isinstance(term, (_ConstBool, _ConstInt, _ConstReal, _ConstStr)):
        return True
    if not isinstance(term, _Ctor):
        return False
    if term.name not in _GROUND_DATA_CTOR_NAMES:
        return False
    return all(_is_ground_value_term(arg) for arg in term.args)


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


def list_append_coordinate_value(prior, value, site) -> CallSiteValue:
    """``prior`` after ``.append(value)``: the ``py.list_append`` coordinate.

    The one mint for a list-shaped receiver with no element history to fold
    (``CallSiteValue.append_with``, ``OpaqueOpCallsite.append_with``).  The
    coordinate is itself list-shaped: a chained append reads its term.
    """
    from sugar_lift_py_tests.ir import ctor

    value_term = value.to_term(owner="CallSiteValue.append_with value")
    return CallSiteValue(
        target_name="list.append",
        arg_values=(prior, value),
        parameters=(),
        term=ctor(
            "py.list_append",
            [prior.to_term(owner=str(site)), value_term],
            symbol_kind="method-coordinate",
        ),
        body=None,
        site=site,
    )
