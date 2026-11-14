from __future__ import annotations

import weakref
from dataclasses import dataclass, field as dataclass_field
from typing import Any, NoReturn

from sugar_lift_py_tests.call_symbol import call_symbol
from sugar_lift_py_tests.ir import Term, TermTableBuilder
from sugar_source_tree.construction_cache import AmbientVar
from sugar_lift_py_tests.sugar.function_body_universe import FunctionBodyUniverse
from sugar_lift_py_tests.sugar_body import SugarBody


from .floor_value import FloorValue
from .source_return_projection import (
    project_authenticated_source_return as _project_authenticated_source_return,
)

_FORCE_FLOOR_BUDGET = 64
_NESTED_DIG_DEMAND_BUDGET = 8
_ACTIVE_DIG_DEMAND: AmbientVar = AmbientVar(
    "sugar_callsite_active_dig_demand", default=0
)

# Authenticated-coordinate memo: id(CallSiteValue) -> (weakref, coordinate).
# Weakrefs only, so a dead callsite is never pinned for process lifetime and a
# recycled address cannot inherit its identity (the ``is``-guard rejects it).
# Not a WeakKeyDictionary: that would call ``CallSiteValue.__hash__``, which is
# the seat being memoized.
_CALLSITE_COORDINATE: dict[int, tuple["weakref.ReferenceType", tuple]] = {}


@dataclass(frozen=True)
class _RetainedSourceCompletionV1:
    """Private exact completed Floor carried by one projected arm.

    The constant hash is deliberate: completion Floors may be unhashable, while
    equality must still compare their exact immutable content.  Hash collisions
    are resolved by equality and never grant identity.
    """

    value: object

    def __hash__(self) -> int:
        return 0x52455441


def _retained_completion_invariant(
    *, owner: str, callsite: "CallSiteValue", observed: str
):
    from sugar_source_tree.panic import BackendDefect

    raise BackendDefect(
        owner=owner,
        blame=callsite.site,
        observed=observed,
        requested="one private retained source completion relation",
        fix="consume the retained completion; never replay or reseat the source producer",
    )


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
    bound_native_source_actuals: object | None = dataclass_field(
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
    # The dynamic occurrence path this call was evaluated under
    # (``occurrence.current_path`` at mint). Its body reduces as the frame
    # ``path + (this call,)``: two calls of one function are two frames, and
    # every site in the body is evaluated once per frame.
    occurrence_path: tuple[str, ...] = dataclass_field(
        default_factory=lambda: _current_occurrence_path(),
        compare=False,
        repr=False,
    )
    # The authenticated callee this value is the completed result of, when
    # that callee was cited off the enrolled population
    # (``OffPopulationSourceCallV1``).  Testimony only: a manager factory that
    # returns this value returns a manager nobody materialized, and the
    # ``with`` over the factory is cited exactly like a ``with`` over the
    # callee itself (#7667).
    off_population_target: str | None = dataclass_field(
        default=None, compare=False, repr=False
    )
    # The ``LanguageCallee`` the Call node bound this call's callee to (its
    # binding, never its spelling), carried from ``CallSiteSugar``.
    language_callee: object | None = dataclass_field(
        default=None, compare=False, repr=False
    )
    _retained_source_completion: object | None = dataclass_field(
        default=None, init=False, compare=False, repr=False
    )

    def denotes_value(self) -> bool:
        """A call result denotes a Python runtime value."""
        return True

    def project_operation_receiver(self, ctx: object, *, owner: str):
        """Project an authenticated sole return before operation dispatch.

        The call remains a CallSiteValue everywhere else. A bodyless or
        multi-exit call stays itself, preserving the loud operation law; only
        this producer can expose the Floor authenticated by its source body.
        """
        from sugar_lift_py_tests.floor.block_value import BlockValue

        projected = self._dig_floor_or_none(ctx, owner=owner)
        if projected is None or isinstance(projected, BlockValue):
            return self
        return projected

    def project_operation_receiver_outcome(self, ctx: object, *, owner: str):
        """Project the completion retained by the sole producer reduction.

        Matches ``project_operation_receiver``: a unique authenticated return
        is exposed; a multi-exit ``BlockValue`` stays this CallSiteValue so
        the call remains the semantic value.  ``backquote(_exception_type_name(
        expected_type))`` must not invent one string for both remaining
        returns (the singleton ``__name__`` arm and the join-names arm).
        """
        del ctx
        from sugar_lift_py_tests.floor.block_value import BlockValue
        from sugar_lift_py_tests.outcome import Complete
        from sugar_source_tree.panic import SugarNotWritten

        if self.body is None:
            return Complete(self)
        retained = self._retained_source_completion
        if retained is None:
            raise SugarNotWritten(
                owner="CallSiteValue.project_operation_receiver_outcome",
                blame=self.site,
                observed="body-bearing call lacks retained source completion",
                requested="producer-retained source completion testimony",
                fix="project the source body once at CallSiteValue.producer_outcome",
            )
        if type(retained) is not _RetainedSourceCompletionV1:
            _retained_completion_invariant(
                owner="CallSiteValue.project_operation_receiver_outcome",
                callsite=self,
                observed="retained source completion has wrong exact type",
            )
        if not isinstance(retained.value, FloorValue):
            _retained_completion_invariant(
                owner="CallSiteValue.project_operation_receiver_outcome",
                callsite=self,
                observed="retained source completion value is not FloorValue",
            )
        projected = _project_authenticated_source_return(retained.value)
        if isinstance(projected, BlockValue):
            return Complete(self)
        return Complete(projected)

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

    def attribute(self, name, site):
        """Name ``__name__`` / ``__qualname__`` as a coordinate, without inventing the string.

        An unexecuted call authenticates which call produced the receiver, not
        its runtime type. Guessing AttributeError or inventing a concrete type
        name is dishonest. RaisesExc's absent-effect diagnostic still reads
        ``self.expected_exceptions[0].__name__`` after that lookup is named as
        ``py.subscript``. The spelling is decidable: emit
        ``attr:__name__(receiver)`` the same way a symbolic receiver names the
        attribute and ``format_data_model`` names ``call:__format__`` without
        inventing the formatted string. Other members stay a named third value.
        """
        if name in {"__name__", "__qualname__"}:
            from sugar_lift_py_tests.ir import ctor
            from sugar_lift_py_tests.outcome import Complete

            return Complete(
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
                )
            )
        if name == "args" and self.exception_type_coordinate is not None:
            # BaseException.args is the constructor's positional arguments.
            # Only an authenticated exception instance has that field; an
            # ordinary unexecuted call still has no runtime type, so .args
            # stays a named third value rather than inventing a tuple.
            from sugar_lift_py_tests.floor.tuple_value import TupleValue
            from sugar_lift_py_tests.outcome import Complete

            return Complete(TupleValue(elements=self.arg_values))
        if self.exception_type_coordinate is not None:
            # An authenticated exception instance has a decided runtime type;
            # its unprojected members (``__context__``) are not opaque-call
            # lookups and stay a named third value.
            return self.undecided_attribute(name, site, owner="CallSiteValue.attribute")
        return _opaque_attribute_faces(self, name, site)

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
        if self._retained_source_completion is not None:
            coordinate = (
                *coordinate,
                self._retained_source_completion,
                _term_cycle_key(self.result_term()),
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
        """The value ONE evaluation of this call returned.

        ``term`` is the application ``call:<target>(<args>)``: the bridge
        coordinate contract composition and cycle keys use.  As a value it
        claims every evaluation of that application returns the same object
        -- ``(g(), g())`` two equal results, a loop's second pass the first
        pass's -- which nothing testified.  A call whose source body this
        producer reduced is ``python:call_result(<application>,
        <occurrence>)``, keyed on the site and the dynamic occurrence path it
        was evaluated under; the body's post is applied at that term
        (:meth:`derived_equality_residue`).  Calls the producer did not reduce
        keep the application (their own faces mint the result, #7585).

        A body that returns one ground immutable scalar (an int, str, bytes,
        bool or None literal) returns that value on every evaluation: the
        result stays ground."""
        retained = self._retained_source_completion
        if type(retained) is not _RetainedSourceCompletionV1 or self.site is None:
            return self.term
        ground = _ground_scalar_return(retained.value)
        if ground is not None:
            return ground
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.occurrence import occurrence_term

        return ctor(
            "python:call_result",
            (self.term, occurrence_term(self.site, self.occurrence_path)),
        )

    def denotes_a_value(self) -> bool:
        # A call's RESULT is a value; what it is equal to is undecided until
        # the callee floors. That makes membership over it an obligation, not
        # a gap. A FunctionCallable is the callee itself and stays no.
        return True

    def guarded(self, formula):
        """A callsite coordinate rides under a guard unchanged.

        Like FunctionCallable: the authenticated call term is
        the value. It is not a return or inv that becomes an implication; the
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
        from sugar_lift_py_tests.outcome import Complete

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
        return Complete(
            PredicateValue(
                py_truthy(self.result_term()), site, operand_callsites=(self,)
            )
        )

    def _construct_decidable_truth(self, site):
        """Construct truth for a ground callsite, or return None to stay loud.

        - Dug body answers with its own truth.
        Unconstructable ground residual returns None so the caller panics.
        """
        dug = self._dig_floor_or_none(None, owner="CallSiteValue.truth")
        if dug is not None and dug is not self:
            return dug.truth(site)
        return None

    def is_identical(self, other, site):
        from sugar_lift_py_tests.gap.panic import construction_panic_gap
        from sugar_lift_py_tests.floor.none_value import NoneValue
        from sugar_lift_py_tests.outcome import Complete
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )

        if self.target_name == "except" and isinstance(other, NoneValue):
            return Complete(FalseBoolLiteralSugar(site))
        return super().is_identical(other, site)

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

    def absolute(self, site):
        """Cite ``abs(call(...))`` without claiming the call's concrete value."""
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue

        return SymbolicValue(self.result_term()).absolute(site)

    def python_isinstance(self, type_name: str, type_term, site):
        """``type(x)`` always returns a type object.

        RaisesExc's ``_exception_type_name(type(exception))`` first asks
        ``isinstance(e, type)``. When that stays an open predicate, the
        else-arm asks ``len(e) == 1`` of this callsite and panics
        ComparisonOpSugar.Eq (plain ``call:len`` is not a decided int). The
        one-arg builtin never fails and never returns a non-type, so
        ``isinstance(type(x), type)`` is True. Other callsites keep the
        reserved tester atom.
        """
        if self.target_name != "type":
            return super().python_isinstance(type_name, type_term, site)
        from sugar_lift_py_tests.floor.class_value import _CLASS_OBJECT_DISJOINT_TYPES
        from sugar_lift_py_tests.floor.python_type_coordinate import (
            authenticated_python_type_spelling,
        )
        from sugar_lift_py_tests.outcome import Complete
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
            return Complete(TrueBoolLiteralSugar(site=site))
        if authenticated in _CLASS_OBJECT_DISJOINT_TYPES:
            return Complete(FalseBoolLiteralSugar(site=site))
        return super().python_isinstance(authenticated, type_term, site)

    def test_python_type(self, value, site):
        type_coordinate = self.python_type_coordinate
        if type_coordinate is None and self.target_name == "type":
            type_coordinate = self.term
        if type_coordinate is None:
            from sugar_lift_py_tests.effect import (
                CallResultTypeRuntimeEffect,
                runtime_effect_evidence,
            )
            from sugar_lift_py_tests.outcome import Incomplete

            return Incomplete(
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
        from sugar_lift_py_tests.outcome import Complete

        return Complete(
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
        from sugar_lift_py_tests.outcome import Complete

        return Complete(
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
        # Complete(py.in) fabrication.
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

    def setitem(self, index, value, site):
        """Rebind an opaque mapping/list-shaped callsite after ``xs[k] = v``.

        Concrete containers fold post-state. A callsite receiver has no element
        history, but the store still rebinds the name: carry prior coordinate,
        index, and value on ``py.setitem``. Non-name receivers stay Incomplete
        at the sugar layer (``SubscriptAssignSugar._cite_update``) because no
        name exists to rebind. Do not invent members.
        """
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.outcome import Complete

        index_term = index.to_term(owner="CallSiteValue.setitem index")
        value_term = value.to_term(owner="CallSiteValue.setitem value")
        return Complete(
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
        ``s.split(".")[:3]``) has no element history to fold, but the append
        statement still rebinds the name: carry the prior list coordinate and
        appended value on ``py.list_append`` so later statements keep a
        FloorValue. (A ``typing.cast`` never arrives as a receiver: the Call
        node constructs its second operand.) ``list.copy()`` of a finite list
        folds exactly; ``copy`` of a
        proven list-shaped callsite rebinds through ``py.list_append``.
        ``py.subscript`` of a diggable tuple/list projects the element when the
        index is a ground int (unpack residual: ``handles`` from a returned
        triple). ``iter_elem`` of a proven list-of-lists (or a listcomp whose
        element expression is a list literal) rebinds through ``py.list_append``.
        A curried For post-state (``loop:…`` target) that carried a list via
        append-rebind is still list-shaped: further appends rebind through
        ``py.list_append`` without re-digging the loop body. Chained
        ``list.append`` / ``py.list_append`` coordinates do the same.
        Opaque subscript/iter faces stay loud; a call result is not proof
        that the receiver is a mutable list. Never mint RuntimeEffect over a
        ground list proof.
        """
        from sugar_lift_py_tests.floor.comprehension_value import ComprehensionValue
        from sugar_lift_py_tests.floor.list_value import ListValue
        from sugar_lift_py_tests.floor.term_value import TermValue
        from sugar_lift_py_tests.floor.tuple_value import TupleValue
        from sugar_lift_py_tests.outcome import Complete, Incomplete, complete_value

        def is_list_floor(floor) -> bool:
            return isinstance(floor, (ListValue, ComprehensionValue))

        def is_constructed_list_callsite(receiver: CallSiteValue) -> bool:
            # Proven list constructors and post-states that already rebind through
            # ``py.list_append``. ``loop:…`` is the curried For floor's single
            # (or projected) list-shaped carried output after append-rebinding
            # iterations (#5338 / public_api residual after #5574). ``list.append``
            # is the coordinate this door itself mints — chained appends must not
            # re-panic. Content identity stays on term CID (#5569).
            from sugar_source_tree.nodes import LanguageCallee

            if receiver.language_callee is LanguageCallee.BUILTIN_LIST:
                return True
            if receiver.target_name in {
                "list",
                "split",
                "list.append",
            }:
                return True
            if receiver.target_name.startswith("loop:"):
                return True
            if getattr(receiver.term, "name", None) == "py.list_append":
                return True
            if receiver.target_name == "copy" and receiver.arg_values:
                base = receiver.arg_values[0]
                if is_list_floor(base):
                    return True
                return isinstance(base, CallSiteValue) and is_constructed_list_callsite(
                    base
                )
            return (
                receiver.target_name == "py.subscript"
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
            from sugar_lift_py_tests.ir import ctor

            value_term = value.to_term(owner="CallSiteValue.append_with value")
            return Complete(
                CallSiteValue(
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
            )

        def elements_are_lists(elements) -> bool:
            if not elements:
                return False
            for element in elements:
                if is_list_floor(element):
                    continue
                if isinstance(element, CallSiteValue) and is_constructed_list_callsite(
                    element
                ):
                    continue
                return False
            return True

        def iter_elem_is_list_shaped(iterable) -> bool:
            """True when every iteration face is proven list-shaped."""
            elements = None
            if isinstance(iterable, (ListValue, TupleValue)):
                elements = iterable.elements
            elif isinstance(iterable, ComprehensionValue):
                if iterable.finite_elements is not None:
                    elements = iterable.finite_elements
                else:
                    # ``[[label] for label in header]``: element expression is
                    # a list literal (``array(...)``) even when the iterable is
                    # opaque — format.py str_columns residual.
                    term = iterable.term
                    if (
                        getattr(term, "name", None) == "py.listcomp"
                        and term.args
                        and getattr(term.args[0], "name", None) == "array"
                    ):
                        return True
                    return False
            if elements is None:
                return False
            return elements_are_lists(elements)

        def project_list_operand(operand):
            """Fold to a list floor, rebind through list_append, or None (loud)."""
            if is_list_floor(operand):
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
            # Shallow copy of a finite list is the same element history.
            if receiver.target_name == "copy" and receiver.arg_values:
                base = receiver.arg_values[0]
                if is_list_floor(base):
                    return base.append_with(value, site)
                if isinstance(base, CallSiteValue) and is_constructed_list_callsite(
                    base
                ):
                    return list_append_coordinate(receiver)
                return None

            # Unpack residual: handles = returned_triple[2] where the call digs
            # to a TupleValue/ListValue and the index is a ground int.
            if receiver.target_name == "py.subscript" and len(receiver.arg_values) == 2:
                base, index = receiver.arg_values
                if isinstance(index, TermValue) and type(index.value) is int:
                    floor_base = base
                    if isinstance(base, CallSiteValue):
                        dug_base = dig_floor(base)
                        if dug_base is not None:
                            floor_base = dug_base
                    if isinstance(floor_base, (ListValue, TupleValue)):
                        projected = floor_base.subscript(index, site)
                        if isinstance(projected, Incomplete):
                            return None
                        element = complete_value(
                            projected, owner="CallSiteValue.append_with subscript"
                        )
                        return project_list_operand(element)
                if is_constructed_list_callsite(receiver):
                    return list_append_coordinate(receiver)
                return None

            # Loop-face residual: for x in list_of_lists / listcomp-of-lists.
            if receiver.target_name == "iter_elem" and receiver.arg_values:
                if iter_elem_is_list_shaped(receiver.arg_values[0]):
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

    def delitem(self, index, site):
        """Rebind an opaque mapping/list-shaped callsite after ``del xs[k]``.

        Concrete containers fold post-state. A callsite receiver (for example
        ``dict_class(...)``) has no element history, but the delete still
        rebinds the name: carry prior coordinate and index on ``py.delitem``.
        Do not invent members; do not hide the gap — silence stays illegal.
        """
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.outcome import Complete

        index_term = index.to_term(owner="CallSiteValue.delitem index")
        return Complete(
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
                from sugar_lift_py_tests.outcome import Complete

                return Complete(self.linear_method_call("__format__", (spec,), site))
            return floor.format_data_model(spec, site, ctx)
        from sugar_lift_py_tests.outcome import Complete

        return Complete(self.linear_method_call("__format__", (spec,), site))

    def names_a_string(self) -> bool:
        """Whether this callsite is known to produce a ``str`` if it completes.

        ``type(x).__name__`` / ``__qualname__`` always return ``str``. A named
        string concat (``call:__add__`` or ``python:fstring``) does too, so
        ``backquote`` can join ``"`" + name + "`"`` without inventing text.

        A retained source body whose every return face already names a string
        does too: ``_exception_type_name`` of an unfloored tuple still has both
        the singleton ``__name__`` arm and the join-names arm, but both are
        string coordinates. Do not invent which arm returns.
        """
        if self.target_name in {"__name__", "__qualname__"}:
            return True
        from sugar_lift_py_tests.ir import _Ctor

        term = self.term
        if type(term) is _Ctor and term.name in {
            call_symbol("__add__"),
            "python:fstring",
        }:
            return True
        return self._retained_completion_names_a_string()

    def _retained_completion_names_a_string(self) -> bool:
        retained = self._retained_source_completion
        if type(retained) is not _RetainedSourceCompletionV1:
            return False
        from sugar_lift_py_tests.floor.block_value import BlockValue
        from sugar_lift_py_tests.floor.guarded_return import GuardedReturn
        from sugar_lift_py_tests.floor.opaque_op_callsite import OpaqueOpCallsite
        from sugar_lift_py_tests.floor.return_value import ReturnValue
        from sugar_lift_py_tests.floor.string_value import StringValue

        def face_names_a_string(face) -> bool:
            if type(face) is StringValue:
                return True
            if type(face) is CallSiteValue:
                return face.names_a_string()
            if type(face) is OpaqueOpCallsite and face.callee == "join":
                return True
            return False

        value = retained.value
        if not isinstance(value, BlockValue):
            return face_names_a_string(value)
        faces = tuple(
            statement.value
            for statement in value.statements
            if isinstance(statement, (ReturnValue, GuardedReturn))
        )
        return bool(faces) and all(face_names_a_string(face) for face in faces)

    @staticmethod
    def named_string_concat(left, right, site):
        """Name ``str + named-string-coordinate`` without inventing the string."""
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.outcome import Complete

        return Complete(
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
            )
        )

    def add(self, other, site):
        """Addition floor via interface dispatch: dig, redispatch, or refuse.

        AddOpSugar calls left.add(right) — not binary_operator_with. Without this
        totalizer, dig of `want_bytes(x) + self.sep` construction_panics mid-body.
        A named string coordinate plus a ground string
        (``type(exc).__name__ + "()"``) is concatenation: emit ``call:__add__``
        without inventing the string or falling through ``_undecided_binary_law``.
        """
        from sugar_lift_py_tests.floor.string_value import StringValue

        if type(other) is StringValue and self.names_a_string():
            return self.named_string_concat(self, other, site)
        return self._dig_or_refuse_binop(other, site, op="+", floor_method="add")

    def subtract(self, other, site):
        return self._dig_or_refuse_binop(other, site, op="-", floor_method="subtract")

    def multiply(self, other, site):
        return self._dig_or_refuse_binop(other, site, op="*", floor_method="multiply")

    def power(self, other, site):
        return self._dig_or_refuse_binop(other, site, op="**", floor_method="power")

    def divide(self, other, site):
        return self._dig_or_refuse_binop(other, site, op="/", floor_method="divide")

    def modulo(self, other, site):
        return self._dig_or_refuse_binop(other, site, op="%", floor_method="modulo")

    def floor_divide(self, other, site):
        return self._dig_or_refuse_binop(
            other, site, op="//", floor_method="floor_divide"
        )

    def left_shift(self, other, site):
        return self._dig_or_refuse_binop(
            other, site, op="<<", floor_method="left_shift"
        )

    def right_shift(self, other, site):
        # Base64 / alphabet index math: `ord(c) >> 2` on call results.
        # Without this, FloorValue.right_shift panics (A2 mint-failed on
        # python-literal-base64 / base64-federation).
        return self._dig_or_refuse_binop(
            other, site, op=">>", floor_method="right_shift"
        )

    def bitwise_and(self, other, site):
        # Same family as left_shift / bitwise_or: dig then redispatch, else
        # retain the named undecided-dispatch refusal.
        return self._dig_or_refuse_binop(
            other, site, op="&", floor_method="bitwise_and"
        )

    def bitwise_xor(self, other, site):
        return self._dig_or_refuse_binop(
            other, site, op="^", floor_method="bitwise_xor"
        )

    def bitwise_or(self, other, site):
        return self._dig_or_refuse_binop(other, site, op="|", floor_method="bitwise_or")

    def matrix_multiply(self, other, site):
        return self._dig_or_refuse_binop(
            other, site, op="@", floor_method="matrix_multiply"
        )

    def _dig_or_refuse_binop(self, other, site, *, op: str, floor_method: str):
        """Dig source body when present; otherwise retain undecided dispatch.

        No invent of concrete sums. Ctx is None-tolerant (add(site) has no ctx).
        Mid-dig ConstructionPanic propagates (process-terminal; never dig opacity).

        Keep an opaque named leaf (``preserve_opaque_leaf``). ``_exception_type_name``
        reduces to ``attr:__name__``, which has no further body; discarding that
        leaf would refuse ``helper() + "()"`` on the helper callsite itself
        instead of naming concat of the known string coordinate.
        """
        from sugar_lift_py_tests.floor.guarded_value import GuardedValue

        if isinstance(other, GuardedValue):
            return other.map_from_left(floor_method, self, site)

        dug = self._dig_floor_or_none(
            None,
            owner=f"CallSiteValue.{floor_method}",
            preserve_opaque_leaf=True,
        )
        if dug is not None and dug is not self:
            method = getattr(dug, floor_method, None)
            if callable(method):
                return method(other, site)

        refused = self._undecided_binary_law(other, site, op)
        if refused is not None:
            return refused
        return getattr(super(), floor_method)(other, site)

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

        Dig when the body floors; otherwise retain this callsite's symbolic
        term. The operation owns the submission door -- the deleted central
        dispatcher must never be rediscovered here.
        """
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue

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
        outcome = operation.submit(SymbolicValue(self.result_term()), ctx)
        return _opaque_subscript_faces(outcome, getattr(operation, "blame", None))

    def project_sequence_with(self, operation, ctx):
        """``a, b = f(...)``: unpack of a callsite result.

        Same dig-or-symbolic totalizer as subscript_with, and the same route
        ``OpaqueOpCallsite`` already documents for this exact operation: dig
        the callsite floor when the
        body floors, so a callee returning a display makes the arity lift-time
        decidable and the members bind from the values already in hand;
        otherwise re-dispatch on ``SymbolicValue(self.term)``, which retains
        the typed ``SequenceUnpackRuntimeEffect`` over the callsite's own term.

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

        Opaque (missing body, Incomplete reduce) is an EUF-join residual — not a
        panic and not a soft DigBoundary row. Budget / recursive demand still
        panics: those are non-composable, not joinable coordinates.
        """
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
        if (body := self.body) is None:
            return self if preserve_opaque_leaf else None
        if len(self.parameters) != len(self.arg_values):
            return None
        from sugar_lift_py_tests.outcome import ExitSet, Incomplete, complete_value

        reduce_ctx = _ctx_with_curried_args(
            ctx,
            self.parameters,
            self.arg_values,
            self.formal_coordinate_cids,
        )
        retained = self._retained_source_completion
        if retained is not None:
            if type(retained) is not _RetainedSourceCompletionV1:
                _retained_completion_invariant(
                    owner="CallSiteValue._dig_floor_or_none",
                    callsite=self,
                    observed="retained source completion has wrong exact type",
                )
            if not isinstance(retained.value, FloorValue):
                _retained_completion_invariant(
                    owner="CallSiteValue._dig_floor_or_none",
                    callsite=self,
                    observed="retained source completion value is not FloorValue",
                )
            value = _project_authenticated_source_return(retained.value)
        else:
            active_demand = _ACTIVE_DIG_DEMAND.get()
            nested_budget = min(budget, _NESTED_DIG_DEMAND_BUDGET)
            if active_demand >= nested_budget:
                _force_floor_gap(
                    owner=owner,
                    target_name=self.target_name,
                    observed="callsite value demand budget exhausted",
                    fix=(
                        f"nested callsite dig exceeded force_floor budget "
                        f"{nested_budget}; "
                        "leave the recursive bridge as axiomatic"
                    ),
                )
            token = _ACTIVE_DIG_DEMAND.set(active_demand + 1)
            try:
                outcome = _reduce_callsite_body(
                    body, reduce_ctx, blame=self.target_name, frame=self
                )
            finally:
                _ACTIVE_DIG_DEMAND.reset(token)
            from sugar_lift_py_tests.caller_parameter_contract import (
                NativeOperationExitCarrierV1,
            )

            if isinstance(outcome, NativeOperationExitCarrierV1):
                actuals = self.bound_native_actuals_by_coordinate
                if actuals is None and self.bound_source_actuals is not None:
                    outcome = self.bound_source_actuals.project_native_carrier(outcome)
                if actuals is not None:
                    outcome = outcome.discharge(actuals)
            if isinstance(outcome, Incomplete):
                if incomplete_outcome is not None:
                    incomplete_outcome.append(outcome)
                return None
            if isinstance(outcome, ExitSet):
                # complete_value's written law: multi-arm store/control
                # outcomes cannot force_floor to a single value; leave the
                # projection absent. ``not self.matches(...)`` then stands on
                # CallSiteValue.truth (py.truthy of the call) instead of
                # inventing one bool for two completed predicate returns.
                return None
            if isinstance(outcome, NativeOperationExitCarrierV1):
                # An undischarged lookup is not a completed floor value.
                # Forcing it through complete_value panics; leave the
                # projection absent so ``not self.matches(...)`` stands on
                # the call instead of inventing a bool for exc.message.
                return None
            value = _project_authenticated_source_return(
                complete_value(outcome, owner=owner)
            )
        from sugar_lift_py_tests.floor.block_value import BlockValue

        if isinstance(value, BlockValue):
            # A block is control-flow testimony, not a semantic value.
            # ``matches()`` retains several GuardedReturns (early ``return False``
            # arms and ``return self._check_check(...)``). Leave the projection
            # absent so ``not self.matches(...)`` stands on CallSiteValue.truth
            # instead of inventing one bool via BlockValue.truth.
            return None
        if isinstance(value, CallSiteValue):
            return value._dig_floor_or_none(
                reduce_ctx,
                owner=owner,
                preserve_opaque_leaf=preserve_opaque_leaf,
                seen=seen | {key},
                depth=depth + 1,
                budget=budget,
            )
        return value

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
        key = _term_cycle_key(self.term)
        if depth >= budget or len(seen) >= budget:
            _force_floor_gap(
                owner=owner,
                target_name=self.target_name,
                observed="callsite value demand budget exhausted",
                fix=(
                    f"callsite `{self.target_name}` exceeded force_floor dig budget "
                    f"{budget}; leave the bridge as axiomatic and record a DigBoundary"
                ),
            )
        if key in seen:
            _force_floor_gap(
                owner=owner,
                target_name=self.target_name,
                observed="recursive callsite value demand",
                fix=(
                    f"callsite `{self.target_name}` recursively demanded its own "
                    "floor; leave the bridge as axiomatic and record a DigBoundary"
                ),
            )
        if (body := self.body) is None:
            _force_floor_gap(
                owner=owner,
                target_name=self.target_name,
                observed="missing callsite body",
                fix=(
                    f"carry a factory-built body for callsite `{self.target_name}` "
                    "or leave the bridge as axiomatic"
                ),
            )
        if len(self.parameters) != len(self.arg_values):
            _force_floor_gap(
                owner=owner,
                target_name=self.target_name,
                observed="callsite arity mismatch",
                fix=(
                    f"callsite `{self.target_name}` argument count does not match "
                    "its body; add argument binding sugar or leave the bridge axiomatic"
                ),
            )
        from sugar_lift_py_tests.outcome import Incomplete, complete_value

        reduce_ctx = _ctx_with_curried_args(
            ctx,
            self.parameters,
            self.arg_values,
            self.formal_coordinate_cids,
        )
        retained = self._retained_source_completion
        if retained is not None:
            if type(retained) is not _RetainedSourceCompletionV1:
                _retained_completion_invariant(
                    owner="CallSiteValue.force_floor",
                    callsite=self,
                    observed="retained source completion has wrong exact type",
                )
            if not isinstance(retained.value, FloorValue):
                _retained_completion_invariant(
                    owner="CallSiteValue.force_floor",
                    callsite=self,
                    observed="retained source completion value is not FloorValue",
                )
            value = retained.value
        else:
            outcome = _reduce_callsite_body(
                body, reduce_ctx, blame=self.target_name, frame=self
            )
            if isinstance(outcome, Incomplete):
                _force_floor_gap(
                    owner=owner,
                    target_name=self.target_name,
                    observed="Incomplete",
                    fix=(
                        f"callsite `{self.target_name}` reduced to a runtime effect: "
                        f"{outcome.reason}; leave the floor absent and record a DigBoundary"
                    ),
                )
            value = complete_value(outcome, owner=owner)
        floor = force_floor(
            value,
            reduce_ctx,
            owner=owner,
            seen=seen | {key},
            depth=depth + 1,
            budget=budget,
            project_callsite=project_callsite,
        )
        if project_callsite:
            _project_callsite_floor(
                floor,
                reduce_ctx,
                owner=owner,
                target_name=self.target_name,
                arg_values=self.arg_values,
            )
        return floor

    def retained_source_completion_outcome(self):
        """The completed body the Call producer already reduced, or None.

        ``producer_outcome`` reduces a source body once, publishes its halts
        at the Call, and seats the completed Floor here. A consumer that needs
        that body (a statement-position call splicing its field stores) reads
        it; reducing it again would replay the producer.
        """
        from sugar_lift_py_tests.outcome import Complete

        retained = self._retained_source_completion
        if retained is None:
            return None
        if type(retained) is not _RetainedSourceCompletionV1 or not isinstance(
            retained.value, FloorValue
        ):
            _retained_completion_invariant(
                owner="CallSiteValue.retained_source_completion_outcome",
                callsite=self,
                observed="retained source completion has wrong exact type",
            )
        return Complete(retained.value)

    def reduce_source_outcome(self, ctx: Any = None):
        """Reduce this already-constructed source body without floor projection.

        Context-manager protocol construction needs the body's complete
        ExitSet, including method halts.  This uses the identical explicit call
        frame/curry path as ``force_floor`` and never reconstructs source.
        """
        if self._retained_source_completion is not None:
            _retained_completion_invariant(
                owner="CallSiteValue.reduce_source_outcome",
                callsite=self,
                observed="retained source completion already seated",
            )
        if self.body is None or len(self.parameters) != len(self.arg_values):
            _force_floor_gap(
                owner="CallSiteValue.reduce_source_outcome",
                target_name=self.target_name,
                observed="missing body or callsite arity mismatch",
                fix="retain the source-visible call frame or keep the call loud",
            )
        reduce_ctx = _ctx_with_curried_args(
            ctx,
            self.parameters,
            self.arg_values,
            self.formal_coordinate_cids,
        )
        if self.lexical_defining_class is not None:
            from sugar_lift_py_tests.temporal import curry_temporal

            reduce_ctx = curry_temporal(
                reduce_ctx,
                ("__class__",),
                (self.lexical_defining_class,),
                owner="CallSiteValue lexical class cell",
                blame=self.target_name,
            )
        return _reduce_callsite_body(
            self.body, reduce_ctx, blame=self.target_name, frame=self
        )

    def producer_outcome(self, ctx: Any = None, *, carrier_actuals: dict | None = None):
        """Publish authenticated source-body halts at the Call expression.

        A completed source body still denotes this ordinary call coordinate;
        later consumers may demand its returned floor exactly as before.  A
        halted body is already the Call producer's authenticated exceptional
        face and must not wait for an assertion (or any other consumer) to dig
        it out.  Mixed bodies retain every guard and arm testimony while only
        replacing completed block records with the call coordinate they
        compute.
        """
        if self._retained_source_completion is not None:
            _retained_completion_invariant(
                owner="CallSiteValue.producer_outcome",
                callsite=self,
                observed="retained source completion already seated",
            )
        if self.body is None:
            from sugar_lift_py_tests.outcome import Complete

            return Complete(self)

        outcome = self.reduce_source_outcome(ctx)
        return self.project_producer_outcome(outcome, carrier_actuals=carrier_actuals)

    def project_producer_outcome(self, outcome, *, carrier_actuals: dict | None = None):
        """Project a source-authenticated callee outcome onto this Call node."""

        if self._retained_source_completion is not None:
            _retained_completion_invariant(
                owner="CallSiteValue.project_producer_outcome",
                callsite=self,
                observed="retained source completion already seated",
            )

        from dataclasses import replace

        from sugar_lift_py_tests.effect import RaiseEffect
        from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet, Halted
        from sugar_lift_py_tests.outcome.exit_set import outcome_to_exitset

        def retaining(value):
            if not isinstance(value, FloorValue):
                _retained_completion_invariant(
                    owner="CallSiteValue.project_producer_outcome",
                    callsite=self,
                    observed="source producer completion is not FloorValue",
                )
            retained = replace(self)
            object.__setattr__(
                retained,
                "_retained_source_completion",
                _RetainedSourceCompletionV1(value),
            )
            return retained

        def call_owned(effect):
            if isinstance(effect, RaiseEffect):
                return replace(effect, producer_node_owner="Call")
            return effect

        if isinstance(outcome, Complete):
            # A completed body seats its value on the Call.  A raise is never
            # a completion (#7821): it arrives as a halt and takes the arm
            # below, where it becomes the Call's own halted face.
            return outcome.and_then(lambda value: Complete(retaining(value)))
        from sugar_lift_py_tests.caller_parameter_contract import (
            NativeOperationExitCarrierV1,
        )

        if isinstance(outcome, NativeOperationExitCarrierV1):
            if self.bound_source_actuals is not None:
                outcome = self.bound_source_actuals.project_native_carrier(outcome)
                actuals = None
            else:
                actuals = self.bound_native_actuals_by_coordinate
            if actuals is None:
                # A discharged ExitSet returns here. A still-pending carrier
                # names an outer exit value this frame already substituted
                # and cannot discharge as a formal.
                return outcome
            outcome = outcome.discharge(actuals)
        exits = outcome_to_exitset(outcome)
        return ExitSet(
            tuple(
                (
                    Completed(
                        exit_.guard,
                        retaining(exit_.value),
                        exit_.faces,
                        exit_.owed,
                    )
                    if isinstance(exit_, Completed)
                    else Halted(
                        exit_.guard,
                        call_owned(exit_.effect),
                        exit_.state,
                        exit_.faces,
                        exit_.owed,
                    )
                )
                for exit_ in exits.exits
            )
        ).normalize()


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


def _reduce_callsite_body(
    body: SugarBody[Any] | FunctionBodyUniverse,
    ctx: Any,
    *,
    blame: str,
    frame: "CallSiteValue | None" = None,
):
    """Reduce a callee body as the frame of ``frame``'s call occurrence."""
    if frame is None or frame.site is None:
        return _reduce_callsite_body_in_frame(body, ctx, blame=blame)
    from sugar_lift_py_tests.occurrence import call_frame_path, occurrence_path

    with occurrence_path(call_frame_path(frame.site, frame.occurrence_path)):
        return _reduce_callsite_body_in_frame(body, ctx, blame=blame)


def _reduce_callsite_body_in_frame(
    body: SugarBody[Any] | FunctionBodyUniverse,
    ctx: Any,
    *,
    blame: str,
):
    from sugar_lift_py_tests.sugar.source_visible_function_body_sugar import (
        SourceVisibleFunctionBodySugar,
    )
    from sugar_lift_py_tests.sugar.class_constructor_body_sugar import (
        ClassConstructorBodySugar,
    )

    if isinstance(body, SourceVisibleFunctionBodySugar):
        return body.desugar(ctx)
    if isinstance(body, ClassConstructorBodySugar):
        return body.desugar(ctx)
    if isinstance(body, SugarBody):
        return body.reduce(ctx)
    if isinstance(body, FunctionBodyUniverse):
        from sugar_lift_py_tests.sugar.block_sugar import BlockSugar

        return BlockSugar(statements=body.statements, blame=blame).desugar(ctx)
    _force_floor_gap(
        owner="CallSiteValue.force_floor",
        target_name=blame,
        observed=type(body).__name__,
        fix="carry a closed ordinary source-body variant before demanding a callsite floor",
    )


def _project_callsite_floor(
    floor: FloorValue,
    ctx: Any,
    *,
    owner: str,
    target_name: str,
    arg_values: tuple[FloorValue, ...],
) -> None:
    # Currying is already recorded by curry_temporal. Projection contributes
    # proof/callsite state but must not fabricate a second operation event.
    del floor, ctx, owner, target_name, arg_values


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
):
    from sugar_lift_py_tests.temporal import curry_temporal

    result = curry_temporal(
        ctx,
        parameters,
        arg_values,
        owner="CallSiteValue.force_floor",
        blame="<callsite>",
    )
    if formal_coordinate_cids:
        if len(formal_coordinate_cids) != len(arg_values):
            return result
        result = curry_temporal(
            result,
            formal_coordinate_cids,
            arg_values,
            owner="CallSiteValue.force_floor formal coordinates",
            blame="<callsite-coordinate>",
        )
    return result


def _opaque_attribute_faces(receiver, name, site):
    """``opaque().name`` may raise: complete only under an opaque atom.

    The #7585 two-faced law, the attribute twin of the #7587 subscript law.
    The receiver is a call result with no projected body, so its runtime type
    and ``__getattribute__`` / ``__getattr__`` are undecided.  The member
    completes as the coordinate ``attr:<name>(<receiver>)`` -- the same
    spelling ``__name__`` already uses, no value invented -- only under
    ``python:attribute.completes(python:attribute(<receiver>, <name>,
    <site>))``, keyed on the exact source site; the complement halts with an
    ``UndeterminedRaiseEffect``.  No exception type is named.
    """
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.ir import atomic, ctor, str_const
    from sugar_lift_py_tests.occurrence import occurrence_key
    from sugar_lift_py_tests.outcome.exit_set import (
        Completed,
        ExitSet,
        Halted,
        complement_guard,
    )

    if site is None:
        return receiver.undecided_attribute(name, site, owner="CallSiteValue.attribute")
    receiver_term = receiver.to_term(owner=str(site))
    member = CallSiteValue(
        target_name=name,
        arg_values=(receiver,),
        parameters=(),
        term=ctor(f"attr:{name}", [receiver_term], symbol_kind="method-coordinate"),
        body=None,
        site=site,
    )
    key = occurrence_key(site)
    completes = atomic(
        "python:attribute.completes",
        [ctor("python:attribute", (receiver_term, str_const(name), str_const(key)))],
    )
    return ExitSet(
        (
            Completed(completes, member),
            Halted(
                complement_guard(completes),
                UndeterminedRaiseEffect(
                    blame=str(site),
                    occurrence=key,
                    producer_node_owner="CallSiteValue.attribute",
                ),
                None,
            ),
        )
    ).normalize()


def _opaque_subscript_faces(outcome, site, *, producer="CallSiteValue.subscript"):
    """``opaque()[k]`` may raise: complete only under an opaque partition atom.

    The receiver is a call result with no projected body, so its runtime type
    and ``__getitem__`` are undecided. A completed symbolic ``py.subscript``
    stands only under ``python:subscript.completes(python:subscript(<that
    term>, <site>))``, keyed on the exact source site so two subscripts of the
    same term are never forced to agree; the complement halts with an
    ``UndeterminedRaiseEffect``. No exception type is guessed and no member is
    invented. Any other outcome is left as produced.
    """
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.ir import atomic, ctor, str_const
    from sugar_lift_py_tests.outcome import Complete
    from sugar_lift_py_tests.outcome.exit_set import (
        Completed,
        ExitSet,
        Halted,
        complement_guard,
    )

    from sugar_lift_py_tests.occurrence import occurrence_key

    if not isinstance(outcome, Complete):
        return outcome
    value = outcome.value
    key = occurrence_key(site)
    subscript = ctor(
        "python:subscript",
        (
            value.to_term(owner="CallSiteValue.subscript"),
            str_const(key),
        ),
    )
    completes = atomic("python:subscript.completes", [subscript])
    return ExitSet(
        (
            Completed(completes, value),
            Halted(
                complement_guard(completes),
                UndeterminedRaiseEffect(
                    blame=str(site) if site is not None else None,
                    occurrence=key if site is not None else None,
                    producer_node_owner=producer,
                ),
                None,
            ),
        )
    ).normalize()


def _ground_scalar_return(value):
    """The term of a sole returned ground immutable scalar, else None."""
    from sugar_lift_py_tests.effect import is_lift_time_decidable
    from sugar_lift_py_tests.floor.bytes_value import BytesValue
    from sugar_lift_py_tests.floor.none_value import NoneValue
    from sugar_lift_py_tests.floor.string_value import StringValue
    from sugar_lift_py_tests.floor.term_value import TermValue
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

    projected = _project_authenticated_source_return(value)
    if type(projected) not in (
        TermValue,
        StringValue,
        BytesValue,
        NoneValue,
        TrueBoolLiteralSugar,
        FalseBoolLiteralSugar,
    ):
        return None
    term = projected.to_term(owner="CallSiteValue ground return")
    return term if is_lift_time_decidable(term) else None
