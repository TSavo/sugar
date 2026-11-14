"""The source tree: the class hierarchy IS the grammar.

``Node`` is the abstract base; ``Call``, ``FunctionDef``,
``Assert``, ``Name``, ... subclass it. Which fields exist is answered by
which class you hold — you cannot ask a non-Call for its args because you do
not have one. Arity lives in the field types (``Expression`` vs
``Expression | None`` vs ``tuple[Expression, ...]``). There is no
``NodeKind`` dispatch, no ``match`` on tags, no ASDL table.

``Typeable`` is the interface: "you may ask me for my type."
``Typed`` is the abstract class: "I have a resolved type, here it is."
The transition between them IS the construction event: a backend handle is
``Typeable`` (it can be asked to resolve, and panics as a MISSING if it
cannot); every constructed node is ``Typed`` by virtue of being an
instance of its concrete class. A ``Typeable`` that cannot resolve NEVER
becomes a quiet ``False`` or a bare ``None``.

Asking "which node is this" is ``isinstance`` on THESE classes — blessed
and encouraged (design review, #5940 section 6). What is banned is tag
dispatch on strings.

Field *data* is memoized once per backend site on the unit (source or
shadow ref + control context). Node shells may be constructed freely over
that memo — memoize data, construct the class as often as needed. Structural
equality across sources is a CID question (mementos), not ``__eq__`` on shells.

Nothing is written onto a backend node (no stamping). Shadow rewrite is the
same construction door with a different backend: a ShadowNode that already
carries the rewritten shape, then memoized like any other ref.
"""

from __future__ import annotations

import bisect
import builtins as _builtins_module
import enum as _enum
import symtable
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, ClassVar, Iterator, Optional, Tuple

if TYPE_CHECKING:  # pragma: no cover
    from .fragment import SourceFragment

from .occurrence import SourceOccurrenceIdentityV1
from .operators import (
    BinaryOperator,
    BooleanOperator,
    ComparisonOperator,
    UnaryOperator,
)
from .panic import (
    BackendDefect,
    backend_defect,
    RuntimeSelectedContextManager,
    SourceTreePanic,
    SubstituteNotWritten,
    SugarNotWritten,
    vocabulary_missing,
)
from .reporter import NULL_REPORTER, AuditReporter
from .construction_cache import (
    AmbientSet,
    AmbientVar,
    abandon_row,
    close_row,
    open_row,
    serve,
    testify,
)
from .spans import LineColSpan, LineTable, Span
from .binding_state import (
    BindingEntryV1,
    BindingMap,
    BindingState,
    BindingStateWireGap,
    BranchResultSlot,
    GuardedBinding,
    LoopProjectedBinding,
    RuntimeBindingEntryFactoryV1,
    SubstitutionTraceBuilderV1,
    UnboundBinding,
    binding_state_read_node,
    branch_result_slot,
    join_binding_state,
    try_route_site,
    try_edge_slot,
    try_route_slot,
    unwrap_binding_state,
)

# Scope metadata travels beside temporal bindings under an unforgeable key.
# It lets recognition distinguish a builtin spelling from a lexically bound
# formal without substituting a fake value for that formal.
_LEXICALLY_BOUND_NAMES = object()
_SCOPE_OWNER_CID = object()
_SUBSTITUTION_TRACE_BUILDER = object()
_BINDING_ENTRY_FACTORY = object()
_RECEIVER_FIELD_PROJECTIONS = object()
# The iteration segments (innermost first) of the unrolled loop copy a body is
# being substituted for.  A statement substituted once per iteration is one
# evaluation per iteration; its evaluation coordinate
# (``AugAssign._evaluation_key``) carries these so two iterations never share
# one key.
_EVALUATION_OCCURRENCE = object()
# The exit paths (innermost first) of the clause copy a body is being
# substituted for.  A ``finally`` is substituted once for the try's completion
# and once more for its halted faces (``Try.substitute``): the same statement,
# under the same iterations, evaluated on two exit paths.  Its evaluation
# coordinate carries these so the two copies never share one key.
_EVALUATION_EXIT_PATH = object()
# Set by a door that threads a module body for what it does AT IMPORT
# (``SourceUnit.module_binding_states``).  A ``def`` statement binds a
# function object; its body does not run until something calls it.  Under
# this key the body is not substituted: whoever calls the function
# substitutes it in its own frame, and a refusal there is that caller's, not
# testimony about the statement that merely defined it.
DEFER_DEFINITION_BODY_REFUSAL = object()
# Set by ``SourceUnit.module_binding_states`` while it threads the module
# body: the table ``_substitute_body_tracked`` records the binding scope
# standing before every statement it threads into, at any depth
# (``ModuleBindingStatesV1.at``).
_MODULE_STATEMENT_STATES = object()
# A module binding the module body does not decide where it is read
# (``SourceUnit.module_bindings_at``): the reader cites it by name and never
# reads the name in its place.
UNDECIDED_MODULE_BINDING = object()
_MISSING = object()

# Names the interpreter binds without a source binding: the module attributes
# the import system sets, the class-body names, and the implicit ``__class__``
# cell of a method.
_INTERPRETER_BOUND_NAMES = frozenset(
    (
        "__name__",
        "__file__",
        "__doc__",
        "__spec__",
        "__loader__",
        "__package__",
        "__path__",
        "__cached__",
        "__builtins__",
        "__annotations__",
        "__dict__",
        "__module__",
        "__qualname__",
        "__class__",
    )
)

# A read of one of these can write a global (or a builtin) the source never
# spells as a binding, so no read in that module is called unbound.
_DYNAMIC_GLOBAL_WRITERS = frozenset(
    ("globals", "vars", "locals", "exec", "eval", "builtins", "__builtins__")
)


class LanguageCallee(_enum.Enum):
    """A callee whose behaviour the Python language fixes, named by identity
    (and ``pytest.importorskip``, fixed by the harness lifted tests run under).

    A call reaches a member only through its callee's BINDING: the one import
    reference table (``from typing import cast`` -> ``python:typing.cast``,
    ``importlib.import_module`` under ``import importlib``) or the builtin
    namespace a bare name falls through to (no parameter, local, enclosing or
    module binding; ``SourceUnit.builtin_reference_at``).  The spelling at the
    call is never read: a module that binds its own ``cast``, ``getattr`` or
    ``super`` reaches no member, and ``from typing import cast as c`` does.

    A decorator and a class base are read the same way: ``@abstractmethod``
    under ``from abc import abstractmethod`` and ``@abc.abstractmethod`` under
    ``import abc`` reach ``ABC_ABSTRACTMETHOD``; ``object`` nothing rebinds
    reaches ``BUILTIN_OBJECT``.

    The unit owns the dispatch (``SourceUnit.language_callee_of``, which
    ``Call.language_callee`` asks for its callee); consumers ask the node,
    never the name.
    """

    # ``typing.cast(typ, val)`` returns ``val`` unchanged
    # (https://docs.python.org/3/library/typing.html#typing.cast).
    TYPING_CAST = "python:typing.cast"
    # ``getattr(obj, name)``: the attribute a run-time string names.
    BUILTIN_GETATTR = "python:builtins.getattr"
    # ``super(...)``: the language's MRO proxy constructor.
    BUILTIN_SUPER = "python:builtins.super"
    # ``importlib.import_module(name)``: ``sys.modules[name]`` once imported.
    IMPORTLIB_IMPORT_MODULE = "python:importlib.import_module"
    # ``operator.index(a)``: ``_operator.index`` -> ``PyNumber_Index(a)``
    # (Modules/_operator.c, Objects/abstract.c).
    OPERATOR_INDEX = "python:operator.index"
    # ``warnings.warn(message, category, ...)``: CPython's fixed signature.
    WARNINGS_WARN = "python:warnings.warn"
    # ``list(iterable)``: the builtin list constructor.
    BUILTIN_LIST = "python:builtins.list"
    # ``typing.final(f)``: sets ``f.__final__`` if it can and returns ``f``.
    TYPING_FINAL = "python:typing.final"
    # ``re.search`` / ``re.match`` / ``re.fullmatch``: the C-floor matchers.
    RE_SEARCH = "python:re.search"
    RE_MATCH = "python:re.match"
    RE_FULLMATCH = "python:re.fullmatch"
    # ``pytest.importorskip(name)``: the harness the lifted tests run under
    # skips the test unless ``name`` imports.
    PYTEST_IMPORTORSKIP = "python:pytest.importorskip"
    # ``object``: the root of every MRO and a ``class`` statement's implicit
    # base.
    BUILTIN_OBJECT = "python:builtins.object"
    # ``abc.ABC``: the helper base whose metaclass is ``abc.ABCMeta``.
    ABC_ABC = "python:abc.ABC"
    # ``abc.abstractmethod(f)``: marks ``f`` abstract and returns ``f``.
    ABC_ABSTRACTMETHOD = "python:abc.abstractmethod"
    # ``classmethod`` / ``staticmethod`` / ``property``: the builtin method
    # descriptor constructors.
    BUILTIN_CLASSMETHOD = "python:builtins.classmethod"
    BUILTIN_STATICMETHOD = "python:builtins.staticmethod"
    BUILTIN_PROPERTY = "python:builtins.property"
    # ``functools.wraps(wrapped)``: a decorator factory whose decorator copies
    # ``wrapped``'s metadata onto the wrapper and returns the wrapper.
    FUNCTOOLS_WRAPS = "python:functools.wraps"
    # ``dataclasses.dataclass`` / ``dataclasses.field``: the class decorator
    # that writes ``__init__`` from the annotated fields, and its field
    # specifier (Lib/dataclasses.py).
    DATACLASSES_DATACLASS = "python:dataclasses.dataclass"
    DATACLASSES_FIELD = "python:dataclasses.field"
    # ``typing.Generic``: the parameterisable base that contributes no
    # fields.
    TYPING_GENERIC = "python:typing.Generic"
    # ``enum.Enum`` / ``enum.Flag`` / ``enum.IntFlag`` / ``enum.IntEnum`` /
    # ``enum.StrEnum``: the enumeration bases whose metaclass fixes members
    # at class creation (Lib/enum.py).
    ENUM_ENUM = "python:enum.Enum"
    ENUM_FLAG = "python:enum.Flag"
    ENUM_INTFLAG = "python:enum.IntFlag"
    ENUM_INTENUM = "python:enum.IntEnum"
    ENUM_STRENUM = "python:enum.StrEnum"

    @classmethod
    def of(cls, target_symbol: Optional[str]) -> Optional["LanguageCallee"]:
        """The member a binding's target symbol names, else ``None``."""
        if target_symbol is None:
            return None
        try:
            return cls(target_symbol)
        except ValueError:
            return None


# The builtin method descriptor constructors a decorator's binding may reach,
# by the descriptor kind ``ClassDef._method_descriptor_kind`` answers.
_METHOD_DESCRIPTOR_KINDS = {
    LanguageCallee.BUILTIN_PROPERTY: "property",
    LanguageCallee.BUILTIN_CLASSMETHOD: "classmethod",
    LanguageCallee.BUILTIN_STATICMETHOD: "staticmethod",
}


@dataclass(frozen=True)
class _GeneratorNamedStepV1:
    step: object


@dataclass(frozen=True)
class _GeneratorTryFinallyStepsV1:
    steps: tuple[object, ...]


@dataclass(frozen=True)
class _GeneratorTryFinallyExpansionV1:
    statement: object
    cleanup: "_GeneratorCleanupTermsV1 | _GeneratorCleanupAbsentV1"


@dataclass(frozen=True)
class _GeneratorStepAbsentV1:
    pass


@dataclass(frozen=True)
class _GeneratorCleanupTermsV1:
    terms: tuple[object, ...]


@dataclass(frozen=True)
class _GeneratorCleanupAbsentV1:
    pass


@dataclass(frozen=True)
class _ReceiverFieldProjection:
    receiver_coordinate_cid: str
    selector: str
    store_occurrence: object
    value: "Node"


def _receiver_coordinate_cid(receiver) -> str | None:
    if isinstance(receiver, BindingCoordinateRef):
        return receiver.coordinate.cid
    if isinstance(receiver, ConstructedReceiverRef):
        return receiver.binding_coordinate_cid
    return None


@dataclass(frozen=True)
class ControlConstructionContextV1:
    loop_targets: tuple[object, ...] = ()
    exception_slots: tuple[str, ...] = ()

    def enter_loop(self, target: object) -> "ControlConstructionContextV1":
        return ControlConstructionContextV1(
            (*self.loop_targets, target), self.exception_slots
        )

    def enter_exception(self, slot_id: str) -> "ControlConstructionContextV1":
        return ControlConstructionContextV1(
            self.loop_targets, (*self.exception_slots, slot_id)
        )

    def nearest_loop_target(self):
        if not self.loop_targets:
            from sugar_lift_py_tests.loop_construction import LoopWireError

            raise LoopWireError("loop-control occurrence has no enclosing loop")
        return self.loop_targets[-1]

    def nearest_exception_slot(self, *, blame: object) -> str:
        if not self.exception_slots:
            raise SugarNotWritten(
                blame=blame,
                owner="ControlConstructionContextV1.nearest_exception_slot",
                observed="bare raise has no authenticated in-flight exception slot",
                requested="an enclosing except handler effect-slot coordinate",
                fix="construct bare raise only inside the handler that owns its effect",
            )
        return self.exception_slots[-1]


def _explicit_state(name: str, state):
    if name in state:
        return unwrap_binding_state(state[name])
    return _MISSING


_NESTED_COMPREHENSION_TEMPLATE = object()
# The closure cells of the eager comprehensions enclosing a substitution
# (#7757 item 7), one layer per comprehension, outermost first: the lambdas it
# stores unevaluated in what it produces, and, for each name its targets bind,
# what the cell holds once it is done (``_closure_cell_scope``).
_CLOSURE_CELLS = object()

# Set in the scope a generator expression substitutes its conditions and
# element in: a walrus there writes when the generator is consumed, not where
# it is made (``NamedExpr.substitute`` marks it ``deferred``).
_DEFERRED_WALRUS = object()


class TargetPatternConstructionGapV1(TypeError):
    """A target-pattern coordinate does not belong to its eager source owner."""

    def __init__(
        self,
        reason: str,
        *,
        consumer_occurrence: object,
        target_occurrence: object,
        target_pattern: object | None = None,
        expected_coordinates: object | None = None,
        actual_coordinates: object | None = None,
    ) -> None:
        super().__init__(reason, consumer_occurrence, target_occurrence)
        self.reason = reason
        self.consumer_occurrence = consumer_occurrence
        self.target_occurrence = target_occurrence
        self.target_pattern = target_pattern
        self.expected_coordinates = expected_coordinates
        self.actual_coordinates = actual_coordinates


_TARGET_PATTERN_ENROLLMENT_AUTHORITY = object()


class TargetPatternEnrollmentV1:
    """Closed producer-owned applicability outcome for the target relation.

    ``SourceUnit.bind_typed_module`` already decides, during its one structural
    walk, whether a constructed node is a target-pattern consumer.  Before this
    type existed the walk published only positive rows, so a consumer that
    wanted the applicability answer had to read the relation and treat an empty
    tuple as "not enrolled" -- which also swallowed "the table was never built"
    and "the enrolled row was stranded by a rewrite".

    Exactly two variants exist and only the producer may mint them.  This type
    answers *"is this shape enrolled?"* and nothing else; *"did my lookup find
    the row?"* is answered separately and loudly by ``require_target_pattern``
    / ``require_target_patterns``.  The two questions never share a value.
    """

    __slots__ = ("consumer_occurrence",)

    _variants_closed = False

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        if TargetPatternEnrollmentV1._variants_closed:
            raise TargetPatternConstructionGapV1(
                "target-pattern-enrollment-variant-not-closed",
                consumer_occurrence=cls,
                target_occurrence=None,
            )

    def __init__(self, *, consumer_occurrence, _authority=None) -> None:
        if _authority is not _TARGET_PATTERN_ENROLLMENT_AUTHORITY:
            raise TargetPatternConstructionGapV1(
                "target-pattern-enrollment-not-producer-minted",
                consumer_occurrence=consumer_occurrence,
                target_occurrence=None,
            )
        object.__setattr__(self, "consumer_occurrence", consumer_occurrence)

    def __setattr__(self, name, value):  # pragma: no cover - immutability guard
        raise TargetPatternConstructionGapV1(
            "target-pattern-enrollment-is-immutable",
            consumer_occurrence=self.consumer_occurrence,
            target_occurrence=None,
        )


class TargetPatternEnrolledV1(TargetPatternEnrollmentV1):
    """This occurrence is an enrolled target-pattern consumer.

    ``enrolled_targets`` are the exact target occurrences the producer minted a
    ``TargetPatternV1`` for.  The row itself is deliberately NOT carried here:
    this value answers *"is this shape enrolled?"* and the relation read answers
    *"did my lookup find the row?"*.  Merging them would let a stranded row
    degrade into this value instead of refusing, so they stay separate even
    though the relation is now keyed by durable source occurrence (#7346-A).
    """

    __slots__ = ("enrolled_targets", "_projection_sites")

    def __init__(self, *, consumer_occurrence, projection_sites, _authority=None):
        super().__init__(
            consumer_occurrence=consumer_occurrence, _authority=_authority
        )
        sites = tuple(projection_sites)
        object.__setattr__(self, "_projection_sites", sites)
        object.__setattr__(
            self, "enrolled_targets", tuple(target for target, _ in sites)
        )
        if not self.enrolled_targets:
            raise TargetPatternConstructionGapV1(
                "enrolled-target-pattern-consumer-without-targets",
                consumer_occurrence=consumer_occurrence,
                target_occurrence=None,
            )

    def covers(self, target) -> bool:
        return any(
            candidate is target or candidate.ref is target.ref
            for candidate in self.enrolled_targets
        )

    def __repr__(self) -> str:
        return f"TargetPatternEnrolledV1(targets={len(self.enrolled_targets)})"


_TARGET_PATTERN_NON_ENROLLMENT_REASONS = frozenset(
    {
        # The node kind (or, for ``Assign``, every one of its targets) carries
        # no lexical binding pattern at all.
        "consumer-shape-not-enrolled",
        # Candidate targets exist for this shape, but none of them introduces a
        # lexical binding leaf (e.g. ``self.a, self.b = ...``: pure store).
        "no-binding-leaf-target",
    }
)


class TargetPatternNotEnrolledV1(TargetPatternEnrollmentV1):
    """This occurrence is lawfully outside the target-pattern relation."""

    __slots__ = ("reason",)

    def __init__(self, *, consumer_occurrence, reason, _authority=None):
        super().__init__(
            consumer_occurrence=consumer_occurrence, _authority=_authority
        )
        if reason not in _TARGET_PATTERN_NON_ENROLLMENT_REASONS:
            raise TargetPatternConstructionGapV1(
                "target-pattern-non-enrollment-reason-not-declared",
                consumer_occurrence=consumer_occurrence,
                target_occurrence=None,
            )
        object.__setattr__(self, "reason", reason)

    def __repr__(self) -> str:
        return f"TargetPatternNotEnrolledV1({self.reason!r})"


TargetPatternEnrollmentV1._variants_closed = True


_LEXICAL_CALL_ENROLLMENT_AUTHORITY = object()


def _lexical_enrollment_defect(blame, observed: str, requested: str, fix: str):
    return BackendDefect(
        blame=blame,
        owner="LexicalCallEnrollmentV1",
        observed=observed,
        requested=requested,
        fix=fix,
    )


class LexicalCallEnrollmentV1:
    """Closed producer-owned applicability outcome for the lexical relation.

    ``Backend.materialize_module`` already decides, during its ONE structural
    walk, which call occurrences receive a ``_BackendLexicalCallRowV1``: it
    classifies the callee shape, the enclosing scope, and the binding event the
    name resolves to.  It published only the positive rows.  A consumer that
    wanted the applicability answer therefore read the relation and treated an
    empty tuple as "not enrolled" -- which also swallowed "the enrolled row was
    stranded by a rewrite" and "this occurrence was never walked at all".

    This type transports the decision the walk ALREADY made; it is never
    re-derived.  No consumer may repeat the backend's scope/binding walk.

    Exactly two variants exist and only the producer may mint them.  Mirrors
    ``TargetPatternEnrollmentV1`` deliberately, including the omission of the
    product: the enrolled row is NOT carried here.  Carrying it would make this
    table a second copy of the relation, and a stranded row would then be
    unobservable.  "Is this occurrence enrolled?" is answered here; "did my
    lookup find the row?" is answered separately and loudly by
    ``SourceUnit.require_lexical_call_rows``.  The two questions never share a
    value, and a LOOKUP MISS is a third, typed failure -- it can never
    masquerade as either outcome.
    """

    __slots__ = ("call_occurrence",)

    _variants_closed = False

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        if LexicalCallEnrollmentV1._variants_closed:
            raise _lexical_enrollment_defect(
                blame=getattr(cls, "__name__", cls),
                observed="a third lexical-call enrollment variant",
                requested="exactly two closed variants",
                fix="extend the closed outcome deliberately, not by subclassing",
            )

    def __init__(self, *, call_occurrence, _authority=None) -> None:
        if _authority is not _LEXICAL_CALL_ENROLLMENT_AUTHORITY:
            raise _lexical_enrollment_defect(
                blame=getattr(call_occurrence, "fragment", call_occurrence),
                observed="lexical-call enrollment minted outside the producer",
                requested="the one authoritative structural walk",
                fix="publish enrollment from Backend.materialize_module only",
            )
        object.__setattr__(self, "call_occurrence", call_occurrence)

    def __setattr__(self, name, value):  # pragma: no cover - immutability guard
        raise _lexical_enrollment_defect(
            blame=getattr(self.call_occurrence, "fragment", self.call_occurrence),
            observed="mutation of a sealed lexical-call enrollment",
            requested="an immutable producer outcome",
            fix="mint a new outcome from the producer walk",
        )


class LexicalCallEnrolledV1(LexicalCallEnrollmentV1):
    """This call occurrence IS in the lexical relation.

    The row is deliberately not carried; read it strictly through
    ``SourceUnit.require_lexical_call_rows`` so a stranded row refuses instead
    of degrading into this value.
    """

    __slots__ = ()

    def __repr__(self) -> str:
        return "LexicalCallEnrolledV1()"


_LEXICAL_CALL_NON_ENROLLMENT_REASONS = frozenset(
    {
        # The callee is not a bare Name, so no lexical name resolution applies.
        "non-name-callee",
        # The call occurs at module scope; the relation covers calls inside a
        # function scope only.
        "module-scope-call",
        # Name resolution found no binding event for this spelling in any
        # enclosing function scope (external, builtin, or module-level name).
        "no-lexical-binding-in-scope",
        # A binding event was found, but it is a parameter, local assignment,
        # deletion, rebinding, or a later definition -- not a lexical function
        # definition visible at this call.
        "binding-not-a-function-definition",
        # This unit has no typed module root yet, so no lexical relation has
        # been published for any occurrence in it.
        "no-typed-module",
        # A desugarer-synthesized Call shell (``Node._make_call``) over a
        # borrowed span: it is not a source call occurrence, so it is outside
        # the relation's DOMAIN.  Only shadow-minted nodes may take this arm;
        # a source-backed occurrence with no published decision refuses.
        "synthesized-call-occurrence",
    }
)


class LexicalCallNotEnrolledV1(LexicalCallEnrollmentV1):
    """This call occurrence is lawfully outside the lexical relation."""

    __slots__ = ("reason",)

    def __init__(self, *, call_occurrence, reason, _authority=None):
        super().__init__(call_occurrence=call_occurrence, _authority=_authority)
        if reason not in _LEXICAL_CALL_NON_ENROLLMENT_REASONS:
            raise _lexical_enrollment_defect(
                blame=getattr(call_occurrence, "fragment", call_occurrence),
                observed=f"undeclared non-enrollment reason {reason!r}",
                requested="one of the declared closed reasons",
                fix="declare the reason deliberately in the closed set",
            )
        object.__setattr__(self, "reason", reason)

    def __repr__(self) -> str:
        return f"LexicalCallNotEnrolledV1({self.reason!r})"


LexicalCallEnrollmentV1._variants_closed = True


def mint_lexical_call_enrollment(
    call_occurrence, reason: str | None
) -> LexicalCallEnrollmentV1:
    """The ONE door the producer walk mints its published decision through."""
    if reason is None:
        return LexicalCallEnrolledV1(
            call_occurrence=call_occurrence,
            _authority=_LEXICAL_CALL_ENROLLMENT_AUTHORITY,
        )
    return LexicalCallNotEnrolledV1(
        call_occurrence=call_occurrence,
        reason=reason,
        _authority=_LEXICAL_CALL_ENROLLMENT_AUTHORITY,
    )


_TARGET_PATTERN_RECEIPT_AUTHORITY = object()


@dataclass(frozen=True, init=False)
class TargetPatternReceiptV1:
    """Closed semantic testimony minted with the completed module roster."""

    source_cid: str
    consumer_occurrence_cid: str
    consumer_node_shape_cid: str
    target_occurrence_cid: str
    target_node_shape_cid: str
    leaf_occurrence_cids: tuple[str, ...]
    leaf_node_shape_cids: tuple[str, ...]
    binding_coordinate_cids: tuple[str, ...]
    cid: str
    _authority: object = field(
        default=None, init=False, compare=False, repr=False,
        metadata={"testimony": "authority"},
    )

    @property
    def preimage(self) -> dict[str, object]:
        return {
            "kind": "target-pattern-receipt",
            "schemaVersion": "1",
            "sourceCid": self.source_cid,
            "consumerOccurrenceCid": self.consumer_occurrence_cid,
            "consumerNodeShapeCid": self.consumer_node_shape_cid,
            "targetOccurrenceCid": self.target_occurrence_cid,
            "targetNodeShapeCid": self.target_node_shape_cid,
            "leafOccurrenceCids": list(self.leaf_occurrence_cids),
            "leafNodeShapeCids": list(self.leaf_node_shape_cids),
            "bindingCoordinateCids": list(self.binding_coordinate_cids),
        }

    def __post_init__(self) -> None:
        from sugar_lift_python_source.canonical import cid_of_json

        if self._authority is not _TARGET_PATTERN_RECEIPT_AUTHORITY:
            raise TargetPatternConstructionGapV1(
                "target-pattern-receipt-not-producer-minted",
                consumer_occurrence=self.consumer_occurrence_cid,
                target_occurrence=self.target_occurrence_cid,
            )
        if (
            not self.source_cid
            or not self.consumer_occurrence_cid
            or not self.consumer_node_shape_cid
            or not self.target_occurrence_cid
            or not self.target_node_shape_cid
            or not self.leaf_occurrence_cids
            or len(self.leaf_occurrence_cids) != len(self.leaf_node_shape_cids)
            or len(self.leaf_occurrence_cids) != len(self.binding_coordinate_cids)
            or cid_of_json(self.preimage) != self.cid
        ):
            raise TargetPatternConstructionGapV1(
                "target-pattern-receipt-preimage-mismatch",
                consumer_occurrence=self.consumer_occurrence_cid,
                target_occurrence=self.target_occurrence_cid,
            )


def _mint_target_pattern_receipt(
    *, source_unit, consumer_occurrence, target_occurrence, leaves, coordinates
) -> TargetPatternReceiptV1:
    from sugar_lift_python_source.canonical import cid_of_json
    from sugar_source_tree.binding_state import node_construction_shape_cid

    values = {
        "source_cid": source_unit.source_cid,
        "consumer_occurrence_cid": consumer_occurrence.fragment.seal().cid,
        "consumer_node_shape_cid": node_construction_shape_cid(consumer_occurrence),
        "target_occurrence_cid": target_occurrence.fragment.seal().cid,
        "target_node_shape_cid": node_construction_shape_cid(target_occurrence),
        "leaf_occurrence_cids": tuple(leaf.fragment.seal().cid for leaf in leaves),
        "leaf_node_shape_cids": tuple(
            node_construction_shape_cid(leaf) for leaf in leaves
        ),
        "binding_coordinate_cids": tuple(coordinate.cid for coordinate in coordinates),
    }
    value = object.__new__(TargetPatternReceiptV1)
    for name, field_value in values.items():
        object.__setattr__(value, name, field_value)
    preimage = {
        "kind": "target-pattern-receipt",
        "schemaVersion": "1",
        "sourceCid": values["source_cid"],
        "consumerOccurrenceCid": values["consumer_occurrence_cid"],
        "consumerNodeShapeCid": values["consumer_node_shape_cid"],
        "targetOccurrenceCid": values["target_occurrence_cid"],
        "targetNodeShapeCid": values["target_node_shape_cid"],
        "leafOccurrenceCids": list(values["leaf_occurrence_cids"]),
        "leafNodeShapeCids": list(values["leaf_node_shape_cids"]),
        "bindingCoordinateCids": list(values["binding_coordinate_cids"]),
    }
    object.__setattr__(value, "cid", cid_of_json(preimage))
    object.__setattr__(value, "_authority", _TARGET_PATTERN_RECEIPT_AUTHORITY)
    value.__post_init__()
    return value


@dataclass(frozen=True)
class TargetPatternV1:
    """One eager, occurrence-owned destructuring projection."""

    source_unit: "SourceUnit"
    consumer_occurrence: "Node"
    target_occurrence: "Node"
    leaves: tuple["Name", ...]
    coordinates: tuple[object, ...]
    receipt: TargetPatternReceiptV1 | None = field(
        default=None, init=False, compare=False, repr=False
    )

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(leaf.id for leaf in self.leaves)

    @property
    def target(self):
        return self.target_occurrence

    @property
    def target_coordinates(self) -> tuple[object, ...]:
        return self.coordinates

    @property
    def target_names(self) -> tuple[str, ...]:
        return self.names

    @property
    def scope_owner_cid(self) -> str:
        return self.coordinates[0].scope_owner_cid

    def bindings_for(self, element: "Node") -> "Optional[dict]":
        """Project one concrete display through this exact target tree."""

        def project(target, value):
            if isinstance(target, Name):
                return {target.id: value}
            if not isinstance(target, (Tuple_, List)) or not isinstance(
                value, (Tuple_, List)
            ):
                return None
            starred = [
                index
                for index, child in enumerate(target.elts)
                if isinstance(child, Starred)
            ]
            if len(starred) > 1:
                return None
            if not starred:
                if len(target.elts) != len(value.elts):
                    return None
                pairs = zip(target.elts, value.elts, strict=True)
            else:
                star = starred[0]
                tail = len(target.elts) - star - 1
                if len(value.elts) < len(target.elts) - 1:
                    return None
                from .backend import Children, materialize
                from .shadow import ShadowNode, _handle_of

                captured = value.elts[star : len(value.elts) - tail]
                star_value = materialize(
                    value.unit,
                    ShadowNode(
                        "List",
                        value.span,
                        (("elts", Children(tuple(_handle_of(v) for v in captured))),),
                    ),
                    value.reporter,
                )
                pairs = (
                    *zip(target.elts[:star], value.elts[:star], strict=True),
                    (target.elts[star].value, star_value),
                    *zip(
                        target.elts[star + 1 :],
                        value.elts[len(value.elts) - tail :],
                        strict=True,
                    ),
                )
            result = {}
            for child_target, child_value in pairs:
                child = project(child_target, child_value)
                if child is None:
                    return None
                result.update(child)
            return result

        return project(self.target_occurrence, element)


def _mint_target_pattern(
    *, source_unit, consumer_occurrence, target_occurrence, leaves, coordinates
) -> TargetPatternV1:
    receipt = _mint_target_pattern_receipt(
        source_unit=source_unit,
        consumer_occurrence=consumer_occurrence,
        target_occurrence=target_occurrence,
        leaves=leaves,
        coordinates=coordinates,
    )
    value = TargetPatternV1(
        source_unit, consumer_occurrence, target_occurrence, leaves, coordinates
    )
    object.__setattr__(value, "receipt", receipt)
    return value


def _ordered_binding_keys(names):
    internal_names = (
        _LEXICALLY_BOUND_NAMES,
        _SCOPE_OWNER_CID,
        _SUBSTITUTION_TRACE_BUILDER,
        _BINDING_ENTRY_FACTORY,
        _RECEIVER_FIELD_PROJECTIONS,
        # The evaluation a scope substitutes for (a loop iteration, a
        # duplicated clause's exit path): a full scope carries them, so a
        # try's halt-edge states inside an unrolled loop or a ``finally``
        # copy hold them too.
        _EVALUATION_OCCURRENCE,
        _EVALUATION_EXIT_PATH,
    )
    ordered = sorted(name for name in names if isinstance(name, str))
    ordered.extend(name for name in internal_names if name in names)
    if len(ordered) != len(names):
        unknown = next(name for name in names if name not in ordered)
        from sugar_source_tree.panic import SugarNotWritten

        raise SugarNotWritten(
            blame="binding-map",
            owner="_ordered_binding_keys",
            observed=f"binding-map key species {type(unknown).__name__} is not a str name",
            requested="str binding names only (plus known internal marker keys)",
            fix="do not put non-str keys in the binding map; project to str names first",
        )
    return ordered


def exception_type_identity_of_symbol(target_symbol: str):
    """The exception-class coordinate a target symbol names (#7757).

    ``python:exception_type_identity("import", "<module>.<name>")``: the one
    speller of it. A consumer's import door mints it for an import-bound type
    operand (``SourceUnit.imported_exception_type_identity``), and the module
    that defines the class mints the same coordinate for the facts its proof
    states about that class (``SourceUnit.exception_class_ancestry``), so the
    two meet at prove by the target symbol.
    """
    from sugar_lift_py_tests.ir import ctor, str_const

    qualified = (
        target_symbol[len("python:") :]
        if target_symbol.startswith("python:")
        else target_symbol
    )
    return ctor(
        "python:exception_type_identity",
        [str_const("import"), str_const(qualified)],
    )


def exception_type_identity_of_import_target(target_symbol: str):
    """The exception-class coordinate an import's target symbol reaches.

    Language-owned builtins keep their builtin identity even through an
    import alias: qualification does not create a new exception class, and
    only the language's closed exception vocabulary testifies for that
    namespace (an unknown member is not a foreign exception: ``None``). Any
    other target is ``exception_type_identity_of_symbol``. Read by the import
    door (``SourceUnit.imported_exception_type_identity``) and by a package
    that re-exports a name (``SourceUnit.exception_class_ancestry``).
    """
    qualified = (
        target_symbol[len("python:") :]
        if target_symbol.startswith("python:")
        else target_symbol
    )
    components = qualified.split(".")
    if components[0] == "builtins":
        from sugar_lift_py_tests.floor.ground_exit import _builtin_exception_identity

        if len(components) != 2:
            return None
        identity, _mro = _builtin_exception_identity(components[1])
        return identity
    return exception_type_identity_of_symbol(target_symbol)


@dataclass(frozen=True)
class SourceUnit:
    """One parsed source: oracle-pinned text, its content address, its line table.

    The identity ``(source, filename, source_cid)`` is the SourceOracle's
    triple, carried verbatim. This type never opens a file and never hashes
    text — minting an address is the oracle's job, and a unit that minted
    its own would be a second, unpinned identity for the same bytes.
    """

    filename: str
    source: str
    source_cid: str
    construction_context: object | None = None

    # populated in __post_init__, never by callers
    line_table: LineTable = field(init=False, default=None)  # type: ignore[assignment]
    module_bound_names: frozenset[str] = field(init=False, default_factory=frozenset)
    module_symtable: object = field(init=False, default=None)
    # Bound by SourceFile after the backend materializes the Module — the sole
    # structural authority for module-body identity. Never a second parse.
    typed_module: object = field(init=False, default=None)
    # Field-data memo for materialize (see construction_cache.py).
    construction_cache: object = field(init=False, default=None)
    # Closed producer decision for EVERY constructed occurrence the ONE
    # structural walk classified, published in walk order. Mirrors
    # ``_ConstructedModuleV1.lexical_call_enrollments``: the walk already made
    # this decision, so the roster is transported, never re-derived. ``None``
    # means the walk has not run; an empty tuple means it ran and enrolled
    # nothing. Those are not the same fact and do not share a representation.
    _target_pattern_enrollments: object = field(
        init=False, default=None, repr=False, compare=False
    )
    _target_patterns_by_consumer: object = field(
        init=False, default=None, repr=False, compare=False
    )
    _target_patterns_by_target: object = field(
        init=False, default=None, repr=False, compare=False
    )
    target_pattern_construction_count: int = field(
        init=False, default=0, repr=False, compare=False
    )
    exception_class_values: object = field(init=False, default=None)
    module_direct_bindings: object = field(init=False, default=None)
    function_nodes: Tuple[object, ...] = field(init=False, default=())
    # Memo for exception_type_identity: full-module walk was ~12ms/call on
    # asserters and dominated Raise exclusive heat under Body.If.
    _exception_type_identity_cache: dict = field(init=False, default_factory=dict)
    # Memo for the module's per-occurrence import-binding map (one lexical pass).
    _lexical_value_use_receipts: object = field(init=False, default=None)
    # Final-checked import value-use resolutions at exact use sites of this
    # unit only (source_cid match). Never foreign LineTable spans.
    _import_value_use_resolutions: object = field(init=False, default=None)
    # Reachability-scoped deferrals: value-use coordinates whose target did not
    # resolve.  Manager receipt seating records the marker here instead of
    # voiding the whole manager; the value-use consumer raises the countable
    # ImportValueUseResolutionGap only if the force-floor actually reaches the
    # use.  Kept in its own table so it never enters the strict
    # receipt->resolved state machine of _import_value_use_resolutions.
    _deferred_unresolved_value_uses: object = field(init=False, default=None)
    _constructed_module: object = field(init=False, default=None, repr=False)
    _retained_lexical_call_rows: dict = field(
        init=False, default_factory=dict, repr=False, compare=False
    )
    # READ-ONCE INDEXES over facts this unit already holds.  Every call
    # construction asks three questions of the unit: which enrollment decision
    # the walk published for this occurrence, which function encloses this
    # position, and which CPython symtable that function owns.  Each was a
    # scan of the whole module per call.  The facts are fixed once published,
    # so each is indexed once; an index is tied to the exact tuple it was
    # built from and rebuilt if that tuple is replaced.
    _lexical_call_enrollment_index: object = field(
        init=False, default=None, repr=False, compare=False
    )
    _function_symtable_index: object = field(
        init=False, default=None, repr=False, compare=False
    )
    _function_span_index: object = field(
        init=False, default=None, repr=False, compare=False
    )
    # ``(typed module, names some scope binds, names read)``: one walk of the
    # typed tree, rebuilt if the typed root is replaced.
    _module_name_rows_memo: object = field(
        init=False, default=None, repr=False, compare=False
    )
    # ``(typed module, names an import-time evaluation binds)`` and
    # ``(typed module, refusal, ModuleBindingStatesV1)``: the module body
    # threaded once for its readers outside the module block
    # (``module_binding_states``), rebuilt if the typed root is replaced.
    _module_evaluation_names_memo: object = field(
        init=False, default=None, repr=False, compare=False
    )
    _module_binding_states_memo: object = field(
        init=False, default=None, repr=False, compare=False
    )
    # ``(typed module, start offsets, module statements)``: the module body's
    # statements in source order, for ``module_execution_site``.
    _module_statement_starts_memo: object = field(
        init=False, default=None, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "line_table", LineTable(self.source))
        table = symtable.symtable(self.source, self.filename, "exec")
        object.__setattr__(self, "module_symtable", table)
        symbols = table.get_symbols()
        object.__setattr__(
            self,
            "module_bound_names",
            frozenset(
                symbol.get_name()
                for symbol in symbols
                if symbol.is_assigned() or symbol.is_imported() or symbol.is_namespace()
            ),
        )
        object.__setattr__(self, "typed_module", None)
        object.__setattr__(self, "construction_cache", None)
        object.__setattr__(self, "exception_class_values", {})
        object.__setattr__(self, "module_direct_bindings", None)
        object.__setattr__(self, "function_nodes", ())
        object.__setattr__(self, "_exception_type_identity_cache", {})
        object.__setattr__(self, "_lexical_value_use_receipts", None)
        object.__setattr__(self, "_import_value_use_resolutions", {})
        object.__setattr__(self, "_deferred_unresolved_value_uses", {})
        object.__setattr__(self, "_constructed_module", None)
        object.__setattr__(self, "_target_pattern_enrollments", None)
        object.__setattr__(self, "_retained_lexical_call_rows", {})
        object.__setattr__(self, "_lexical_call_enrollment_index", None)
        object.__setattr__(self, "_function_symtable_index", None)
        object.__setattr__(self, "_function_span_index", None)
        object.__setattr__(self, "_module_name_rows_memo", None)
        object.__setattr__(self, "_module_evaluation_names_memo", None)
        object.__setattr__(self, "_module_binding_states_memo", None)
        object.__setattr__(self, "_module_statement_starts_memo", None)

    def _published_enrollment_decisions(
        self, occurrence: SourceOccurrenceIdentityV1
    ) -> tuple:
        """Every decision the walk published for one occurrence, in walk order.

        The same answer the scan of ``lexical_call_enrollments`` gave --
        occurrence equality is value equality, so it is the dict's key -- read
        from an index built once per published tuple.
        """
        enrollments = self.constructed_module.lexical_call_enrollments
        index = self._lexical_call_enrollment_index
        if index is None or index[0] is not enrollments:
            by_occurrence: dict = {}
            for candidate, decision in enrollments:
                by_occurrence.setdefault(candidate, []).append(decision)
            index = (
                enrollments,
                {key: tuple(found) for key, found in by_occurrence.items()},
            )
            object.__setattr__(self, "_lexical_call_enrollment_index", index)
        return index[1].get(occurrence, ())

    def innermost_function_containing(self, span) -> object | None:
        """The enclosing function with the latest start line, or None.

        The same choice the scan of ``function_nodes`` made -- every function
        whose span contains the position, latest start line, first in
        ``function_nodes`` order on a tie -- answered once per position.
        """
        nodes = self.function_nodes
        index = self._function_span_index
        if index is None or index[0] is not nodes:
            rows = []
            for candidate in nodes:
                owner_span = candidate.line_col_span()
                rows.append(
                    (
                        (owner_span.start_line, owner_span.start_col),
                        (owner_span.end_line, owner_span.end_col),
                        candidate,
                    )
                )
            index = (nodes, tuple(rows), {})
            object.__setattr__(self, "_function_span_index", index)
        position = (span.start_line, span.start_col)
        answers = index[2]
        if position in answers:
            return answers[position]
        owner = None
        owner_line = None
        for start, end, candidate in index[1]:
            if start <= position <= end and (
                owner_line is None or start[0] > owner_line
            ):
                owner = candidate
                owner_line = start[0]
        answers[position] = owner
        return owner

    def lexical_call_enrollment(self, call: "Call") -> LexicalCallEnrollmentV1:
        """The producer's ONE closed applicability decision for a call.

        Keyed by the durable source occurrence (#7346-A), so a rewritten shell
        over the same occurrence gets the same answer.  The producer publishes
        a decision for EVERY call occurrence it walked; therefore a lookup that
        finds no decision is a failed join and REFUSES.  It is never reported
        as not-enrolled: absence and lookup-failure do not share a
        representation here.
        """
        if self.typed_module is None:
            return mint_lexical_call_enrollment(call, "no-typed-module")
        occurrence = SourceOccurrenceIdentityV1.of(call)
        matches = self._published_enrollment_decisions(occurrence)
        if not matches:
            from .shadow import ShadowNode

            if isinstance(call.ref, ShadowNode):
                # Out of DOMAIN, not a failed join.  The desugarer mints fresh
                # Call shells (``Node._make_call``) over a borrowed span of a
                # node that is not itself a source call; the one structural
                # walk never saw them and never could.  ``shadow.rewrite``, by
                # contrast, preserves the origin's span AND kind, so a
                # rewritten source call still joins its published decision --
                # that is exactly what occurrence keying buys (#7346-A).
                #
                # Stated exactly: this arm requires the node to be
                # shadow-minted.  A SOURCE-backed call with no published
                # decision is still a failed join and still refuses below.
                return mint_lexical_call_enrollment(
                    call, "synthesized-call-occurrence"
                )
        if len(matches) != 1:
            raise BackendDefect(
                blame=call.fragment,
                owner="SourceUnit.lexical_call_enrollment",
                observed=f"{len(matches)} published enrollment decisions",
                requested="one decision for this exact call occurrence",
                fix="publish one lexical enrollment per call in the producer walk",
            )
        return matches[0]

    def _seated_lexical_call_rows(self, call: "Call") -> tuple[object, ...]:
        """Raw relation read.  Empty means exactly one thing: lookup missed.

        Callers never see this; ``require_lexical_call_rows`` turns a miss into
        a typed refusal.  Non-enrollment is not expressible here -- that
        question is answered by ``lexical_call_enrollment`` and nothing else.
        """
        retained = self._retained_lexical_call_rows.get(call.ref)
        if retained is not None:
            return retained
        return tuple(
            row
            for row in self.constructed_module.lexical_call_rows
            if row.call_occurrence_identity is call.ref
        )

    def require_lexical_call_rows(self, call: "Call") -> tuple[object, ...]:
        """Strict read of an ENROLLED call's producer-owned row.

        Three facts that used to collapse into one empty tuple now have three
        distinct representations:

        * lawfully not enrolled -> ``LexicalCallNotEnrolledV1`` (a value, from
          ``lexical_call_enrollment``, never from here);
        * enrolled but stranded -> ``BackendDefect`` refusal;
        * never walked / foreign occurrence -> ``BackendDefect`` refusal from
          ``lexical_call_enrollment``.
        """
        enrollment = self.lexical_call_enrollment(call)
        if not isinstance(enrollment, LexicalCallEnrolledV1):
            raise BackendDefect(
                blame=call.fragment,
                owner="SourceUnit.require_lexical_call_rows",
                observed=f"not an enrolled lexical call: {enrollment.reason}",
                requested="an enrolled lexical call occurrence",
                fix="ask lexical_call_enrollment before reading the relation",
            )
        rows = self._seated_lexical_call_rows(call)
        if len(rows) != 1:
            raise BackendDefect(
                blame=call.fragment,
                owner="SourceUnit.require_lexical_call_rows",
                observed=f"{len(rows)} lexical rows for one enrolled call occurrence",
                requested="the one producer-owned row this occurrence is enrolled for",
                fix="retain the enrolled row through the authenticated rewrite",
            )
        return rows

    def lexical_class_owner_for(self, function: "Node") -> "ClassDef | None":
        """Project the exact class owner from the backend's one structural walk.

        The backend already records parent positions while materializing the
        typed module.  Re-walking class bodies here would create a second answer
        to the same ownership question, so consumers use that producer-owned
        relation directly.

        The join is on the SOURCE OCCURRENCE (#7346-A), not on the Python shell
        that views it: ``shadow.rewrite`` mints a fresh shell over the borrowed
        origin span, and a rewritten function denotes the same occurrence the
        producer walked.  Foreign occurrences still miss, and a miss is still
        the loud zero-row ``BackendDefect`` -- there is no span-only fallback
        and no second walk.  Exactly one row per occurrence remains the
        producer's contract: ``None`` as the owner is authenticated no-owner,
        zero rows is a failed join, more than one row is a malformed relation.
        """
        occurrence = SourceOccurrenceIdentityV1.of(function)
        matches = tuple(
            owner
            for candidate, owner in self.constructed_module.function_class_owners
            if candidate == occurrence
        )
        if len(matches) != 1:
            raise BackendDefect(
                blame=function.fragment,
                owner="SourceUnit.lexical_class_owner_for",
                observed=f"{len(matches)} backend owner rows",
                requested="one owner row for this exact function occurrence",
                fix="preserve the backend parent relation through module construction",
            )
        return matches[0]

    def retain_lexical_call_row(self, source: "Call", rewritten: "Call") -> None:
        rows = self.require_lexical_call_rows(source)
        if not rows or type(source) is not type(rewritten):
            raise BackendDefect(
                blame=rewritten.fragment,
                owner="SourceUnit.retain_lexical_call_row",
                observed="missing or foreign lexical call row",
                requested="one source-owned Call row",
                fix="retain the original row through the authenticated rewrite",
            )
        self._retained_lexical_call_rows[rewritten.ref] = rows

    @property
    def constructed_module(self) -> object:
        if self._constructed_module is None:
            from .panic import BackendDefect

            raise BackendDefect(
                blame=self.filename,
                owner="SourceUnit.constructed_module",
                observed="module producer never ran",
                requested="the product from Backend.materialize_module",
                fix="construct this SourceUnit only through SourceFile",
            )
        return self._constructed_module

    def _lexical_import_seat(self):
        """``(root, path)`` this unit's lexical import pass runs under: the
        construction context's workspace root and the unit's file in it, the
        same seat the kit's demand pass uses, so the module name (and so every
        relative import's target) is the one the demands carry."""
        from pathlib import Path

        context = self.construction_context
        root = getattr(context, "workspace_root", None)
        path = Path(self.filename)
        if root is None:
            root = path.parent if path.is_absolute() else Path(".")
        root = Path(root)
        if not path.is_absolute() and root.is_absolute():
            path = root / path
        return root, path

    def module_member_target_symbol(self, name: str) -> Optional[str]:
        """The target symbol of this module's top-level ``name`` (#7757).

        ``python:<module>.<name>``, with the module name the one import table
        spells for this unit's seat (``module_name_for_path``, src layout
        included): the symbol a consumer's ``from <module> import <name>``
        reaches. The one speller of a module's own definition symbol: a
        function's ``bridgeSourceSymbol`` (the join, #7862) and a class's
        ancestry row (``exception_class_ancestry``) both read it, so the two
        joins name a definition once. ``None`` when the seat names no module
        (a path outside the root, or the root's own ``__init__``).
        """
        from sugar_lift_py_tests.import_binding import (
            member_target_symbol,
            module_name_for_path,
        )

        root, path = self._lexical_import_seat()
        try:
            module_name = module_name_for_path(root, path)
        except ValueError:
            return None
        if not module_name:
            return None
        return member_target_symbol(f"python:{module_name}", (name,))

    def _lexical_import_pass(self):
        """The ONE lexical import pass over this unit (#7837), or None before a
        typed root exists. Process-resident: the kit's own demand walk over the
        same content is this walk."""
        module = self.typed_module
        if module is None:
            return None
        from sugar_source_tree.process_resident_file import (
            get_or_prepare_lexical_import_pass,
        )

        root, path = self._lexical_import_seat()
        return get_or_prepare_lexical_import_pass(
            module,
            root=root,
            path=path,
            source=self.source,
            source_cid=self.source_cid,
            module_identities={},
        )

    def import_reference_target(
        self,
        span: Tuple[int, int, int, int],
        *,
        admit_provider_gate: bool = False,
    ) -> Optional[str]:
        """The target symbol of the import-bound reference at ``span`` (#7837).

        ``span`` is the reference's own coordinate: a Name, or a whole
        ``Name.attr...`` chain whose head is import-bound. ``None`` when this
        module has no typed root yet or nothing at that coordinate is uniquely
        import-bound -- the node keeps its ordinary construction.

        The one table is the only source of an imported name's target,
        provider-gated imports included (#7851).  A row whose binding is not
        bound on every path (a ``try: import m`` / ``except ImportError``
        gate: unbound where the provider is absent) answers only a reader
        that admits that gate fact (``admit_provider_gate``).
        """
        runner = self._lexical_import_pass()
        if runner is None:
            return None
        row = runner.reference_targets.get(span)
        if row is None:
            return None
        if not (row.bound_on_every_path or admit_provider_gate):
            return None
        return row.target_symbol

    def import_reference_of(
        self, node, *, admit_provider_gate: bool = False
    ) -> Optional[str]:
        """The target symbol of the import-bound reference ``node`` (#7837).

        A reference written in the source has its own row in the table. A
        static ``Name.attr...`` chain the rewrite produced (``m = np`` then
        ``m.add``: the bound ``np`` Name substituted for ``m``) has no source
        coordinate of its own; its head Name still has its row, and the
        table's one speller follows that row with the chain's static links.
        ``admit_provider_gate`` is ``import_reference_target``'s.
        """
        span = node.line_col_span()
        target = self.import_reference_target(
            (span.start_line, span.start_col, span.end_line, span.end_col),
            admit_provider_gate=admit_provider_gate,
        )
        if target is not None or type(node).__name__ != "Attribute":
            return target
        attributes: list[str] = []
        link = node
        while type(link).__name__ == "Attribute":
            attributes.append(link.attr)
            link = link.value
        if type(link).__name__ != "Name":
            return None
        head = link.line_col_span()
        head_target = self.import_reference_target(
            (head.start_line, head.start_col, head.end_line, head.end_col),
            admit_provider_gate=admit_provider_gate,
        )
        if head_target is None:
            return None
        from sugar_lift_py_tests.import_binding import member_target_symbol

        return member_target_symbol(head_target, tuple(reversed(attributes)))

    def builtin_reference_at(self, name: str, span) -> Optional[str]:
        """``python:builtins.<name>`` when the name read at ``span`` falls
        through to the builtin namespace, else ``None``.

        Python's own resolution, read off this unit's CPython ``symtable``: the
        innermost function around the read neither takes ``name`` as a
        parameter nor binds it (locally, ``nonlocal`` or from an enclosing
        function), the module binds no ``name`` of its own, and the language's
        builtin floor holds it.  The answer is the binding, not the spelling:
        ``getattr = g`` at module level, ``def f(getattr)`` or ``getattr = 1``
        in the function each leave the read with no builtin reference.  A unit
        with no typed root has no function index to consult and answers
        ``None``.
        """
        if self.typed_module is None:
            return None
        from sugar_lift_py_tests.temporal.builtin_name_bindings import (
            builtin_name_temporal,
        )

        if builtin_name_temporal().value_if_bound(name) is None:
            return None
        if name in self.module_bound_names:
            return None
        if "*" in self._module_name_rows()[0]:
            # A star import may bind any name in the module namespace.
            return None
        owner = self.innermost_function_containing(span)
        if owner is not None:
            table = self.function_symtable(owner.name, owner.line_col_span().start_line)
            try:
                symbol = table.lookup(name)
            except KeyError:
                symbol = None
            if symbol is not None and (
                symbol.is_parameter()
                or symbol.is_local()
                or symbol.is_free()
                or symbol.is_nonlocal()
            ):
                return None
        return f"python:builtins.{name}"

    def _module_name_rows(self) -> Tuple[frozenset, frozenset]:
        """``(names some scope binds, names read)`` over the typed tree.

        Each binding site answers for itself (``Node.names_bound_here``; a
        star import answers ``"*"``).  One walk per typed root.
        """
        module = self._require_typed_module(
            "SourceUnit._module_name_rows", blame=self.filename
        )
        rows = self._module_name_rows_memo
        if rows is None or rows[0] is not module:
            bound: set[str] = set()
            read: set[str] = set()
            for node in module.walk():
                bound.update(node.names_bound_here())
                if isinstance(node, Name):
                    read.add(node.id)
            rows = (module, frozenset(bound), frozenset(read))
            object.__setattr__(self, "_module_name_rows_memo", rows)
        return rows[1], rows[2]

    def name_bound_nowhere(self, name: str) -> bool:
        """Whether every read of ``name`` in this module raises ``NameError``.

        True only when nothing binds the name: no scope of the module binds
        it and no star import may (read off the typed tree), it is not a
        builtin, not a name the interpreter binds itself, and the module reads
        no dynamic global writer (``globals``, ``exec``, ...).  Any doubt, and
        a unit with no typed root, answers False.
        """
        if self.typed_module is None:
            return False
        if hasattr(_builtins_module, name) or name in _INTERPRETER_BOUND_NAMES:
            return False
        bound, read = self._module_name_rows()
        if name in bound or "*" in bound:
            return False
        return not (read & _DYNAMIC_GLOBAL_WRITERS)

    def module_evaluation_bound_names(self) -> frozenset:
        """The names the module body binds, as it runs at import, through an
        evaluation a frame reads by its key (``Statement._evaluation_key``):
        ``x += e``, ``a, b = f()`` and ``(x := e)`` (a walrus in a
        comprehension binds the module's name too).

        Read off the typed tree, one walk per typed root.  A ``def``,
        ``lambda`` or ``class`` body is not import-time module code (a class
        body binds its own names) and is not walked.  A unit with no typed
        root answers the empty set.
        """
        module = self.typed_module
        if module is None:
            return frozenset()
        memo = self._module_evaluation_names_memo
        if memo is not None and memo[0] is module:
            return memo[1]
        names: set[str] = set()
        stack: list[Node] = list(module.body)
        while stack:
            node = stack.pop()
            if isinstance(node, AugAssign) and isinstance(node.target, Name):
                names.add(node.target.id)
            elif isinstance(node, Assign):
                target = node._dynamic_unpack_target()
                if target is not None:
                    names.update(_unpack_target_names(target))
            elif isinstance(node, NamedExpr) and isinstance(node.target, Name):
                names.add(node.target.id)
            if isinstance(node, (FunctionDef, AsyncFunctionDef, Lambda, ClassDef)):
                continue
            stack.extend(child for _name, _index, child in node._child_edges())
        result = frozenset(names)
        object.__setattr__(self, "_module_evaluation_names_memo", (module, result))
        return result

    def module_binding_states(self) -> "ModuleBindingStatesV1":
        """The module body threaded once, the way ``Module.substitute``
        threads it: the binding scope standing before every statement it
        runs at import, at any depth (``ModuleBindingStatesV1.at``), and
        after the last (``final``).

        A reader outside the module block takes a module name from here,
        through ``module_bindings_at``.  A ``def`` statement's body is not
        threaded (it does not run at import).  A refusal threading the body
        is remembered and raised to every reader that asks.

        Asked again while the body is being threaded (a statement's
        construction reached a reader of this module: a module-level live
        loop calling a function), the answer is the threading so far:
        ``at`` holds every statement threaded up to here, and ``final`` is
        None.  The threading is the module's own, whoever asked first: it
        runs under no call site (``_MODULE_EXECUTION_SITE``), and each
        statement it records is a new point of it (``_MODULE_THREADING``),
        so an answer read from a partly threaded body is served again only
        at that same point.
        """
        from sugar_lift_py_tests.gap.panic import ConstructionPanic

        module = self._require_typed_module(
            "SourceUnit.module_binding_states", blame=self.filename
        )
        memo = self._module_binding_states_memo
        if memo is not None and memo[0] is module:
            if memo[1] is not None:
                raise memo[1]
            return memo[2]
        record = _ModuleStatementRecord()
        object.__setattr__(
            self,
            "_module_binding_states_memo",
            (module, None, ModuleBindingStatesV1(at=record.at, final=None)),
        )
        site_token = _MODULE_EXECUTION_SITE.set(None)
        threading_token = _MODULE_THREADING.set(object())
        try:
            _statements, _changed, final = module._substitute_body_tracked(
                module.body,
                {
                    DEFER_DEFINITION_BODY_REFUSAL: True,
                    _MODULE_STATEMENT_STATES: record,
                },
            )
        except (SourceTreePanic, ConstructionPanic) as refusal:
            object.__setattr__(
                self, "_module_binding_states_memo", (module, refusal, None)
            )
            raise
        except BaseException:
            object.__setattr__(self, "_module_binding_states_memo", None)
            raise
        finally:
            # A scope that kept the record records nothing after this.
            record.open = False
            _MODULE_THREADING.reset(threading_token)
            _MODULE_EXECUTION_SITE.reset(site_token)
        states = ModuleBindingStatesV1(at=record.at, final=final)
        object.__setattr__(self, "_module_binding_states_memo", (module, None, states))
        return states

    def module_execution_site(self, node) -> "Optional[ModuleExecutionSiteV1]":
        """Where ``node`` (a call, or a class statement) runs while the module
        body runs at import; None when it runs only when some function is
        called (it sits in a ``def`` or ``lambda`` body), or when it sits in
        no module statement.

        The site is the chain of statements the module body runs ``node``
        in, outermost first: the module statement, each compound statement
        it nests in, and last the statement whose own expressions hold it.
        A class body runs once, when its class statement runs, so a node in
        a class body ends the chain at that class statement.  A node in a
        generator expression's element, conditions or later iterables runs
        when the generator is consumed, which the module body does not
        decide (``lazy``).  Read off the typed tree by source span.
        """
        module = self.typed_module
        if module is None:
            return None
        memo = self._module_statement_starts_memo
        if memo is None or memo[0] is not module:
            statements = tuple(module.body)
            memo = (
                module,
                tuple(statement.span.start for statement in statements),
                statements,
            )
            object.__setattr__(self, "_module_statement_starts_memo", memo)
        _module, starts, statements = memo
        span = node.span
        index = bisect.bisect_right(starts, span.start) - 1
        if index < 0:
            return None
        current = statements[index]
        if not (current.span.start <= span.start and span.end <= current.span.end):
            return None
        chain: list = [current]
        in_class = False
        lazy = False
        first_generator = False
        while True:
            entered = None
            for field_name, index, child in current._child_edges():
                if child.span.start <= span.start and span.end <= child.span.end:
                    entered = (field_name, index, child)
                    break
            if entered is None:
                break
            field_name, index, child = entered
            if field_name == "body" and isinstance(
                current, (FunctionDef, AsyncFunctionDef, Lambda)
            ):
                return None
            if field_name == "body" and isinstance(current, ClassDef):
                in_class = True
            if isinstance(current, GeneratorExp):
                first_generator = field_name == "generators" and index == 0
                lazy = lazy or not first_generator
            elif first_generator:
                # Only the first iterable is evaluated where the generator
                # expression stands.
                lazy = lazy or field_name != "iter"
                first_generator = False
            if isinstance(child, Statement) and not in_class:
                chain.append(child)
            current = child
        return ModuleExecutionSiteV1(self, tuple(chain), lazy)

    def module_bindings_at(self, site, names) -> dict:
        """The module's binding of each of ``names`` where ``site`` runs
        (``module_execution_site``), or with no site (a reader running after
        the module body, called from outside its execution) the module's
        final binding.

        Each answer is the reference to the evaluation that binds the name
        there (``_module_reference_state``), None where that binding is no
        evaluation (the name is read by name, as it always was), or
        ``UNDECIDED_MODULE_BINDING`` where the module body does not decide
        it.  It does not decide it

        - for a site in a generator's lazily evaluated part;
        - for a name a walrus in the site's own statements binds (it may
          run before or after the read);
        - for a name the innermost recorded statement binds when that
          statement is not the site's own (a statement the threading did
          not record runs somewhere inside it), or when the site's own
          statement is a ``while`` whose test holds the read (the test runs
          again after the body);
        - for a name whose binding differs between two threadings of the
          site's statement (an unrolled loop's iterations, a ``finally``'s
          two exit paths);
        - for a name bound to a comprehension member's coordinate, which is
          bound only inside its comprehension;
        - for every name, read while the module body is being threaded by a
          reader with no site (the final binding is not threaded yet), or
          at a site the threading has not reached.
        """
        _MODULE_THREADING.get()
        states = self.module_binding_states()
        if site is None:
            if states.final is None:
                return {name: UNDECIDED_MODULE_BINDING for name in names}
            return {
                name: _module_reference_state(states.final.get(name)) for name in names
            }
        chain = site.chain
        recorded = None
        depth = len(chain) - 1
        while depth >= 0:
            recorded = states.at.get(_source_position(chain[depth]))
            if recorded:
                break
            depth -= 1
        if site.lazy or not recorded:
            return {name: UNDECIDED_MODULE_BINDING for name in names}
        undecided: set = set()
        for statement in chain:
            undecided |= _walrus_targets(statement)
        anchor = chain[depth]
        if anchor is not chain[-1] or isinstance(anchor, While):
            undecided |= anchor.names_bound_within()
        answers = {}
        for name in names:
            if name in undecided:
                answers[name] = UNDECIDED_MODULE_BINDING
                continue
            bound = {id(unwrap_binding_state(scope.get(name))) for scope in recorded}
            if len(bound) > 1:
                answers[name] = UNDECIDED_MODULE_BINDING
                continue
            answers[name] = _module_reference_state(recorded[0].get(name))
        return answers

    def language_callee_at(self, name: str, span) -> Optional["LanguageCallee"]:
        """The language-fixed callee a bare name read at ``span`` is bound to.

        The import reference table first (``from typing import cast``), then
        the builtin namespace (``getattr`` nothing rebinds).  ``None`` for any
        other binding, whatever the name is spelled.
        """
        target = self.import_reference_target(
            (span.start_line, span.start_col, span.end_line, span.end_col)
        )
        if target is None:
            target = self.builtin_reference_at(name, span)
        return LanguageCallee.of(target)

    def language_callee_of(self, node) -> Optional["LanguageCallee"]:
        """The language-fixed binding the expression ``node`` reads.

        The one dispatch for a callee, a decorator and a class base alike: a
        bare name asks how it is bound at its own coordinate (an import
        reference, or the builtin namespace nothing rebinds); a dotted chain
        asks the one import reference table for the whole chain
        (``abc.ABC`` under ``import abc``).  Any other expression, and any
        binding that is not one of ``LanguageCallee``'s, answers ``None``.
        """
        if isinstance(node, Name):
            return self.language_callee_at(node.id, node.line_col_span())
        if isinstance(node, Attribute):
            return LanguageCallee.of(self.import_reference_of(node))
        return None

    def import_value_use_receipt(
        self, span: Tuple[int, int, int, int]
    ) -> object | None:
        """The value-use receipt at ``span``: a seated resolution first, else
        the lexical pass's own receipt for that value read (#7837).

        Every import-bound value read gets its receipt from the one lexical
        pass, not only the reads a manager path seats.
        """
        seated = self.import_value_use_resolution(span)
        if seated is not None:
            return seated
        if self.deferred_unresolved_import_value_use(span) is not None:
            # A manager seat already decided this read is unresolved; its
            # dormant marker owns the coordinate.
            return None
        receipts = self._lexical_value_use_receipts
        if receipts is None:
            module = self.typed_module
            if module is None:
                return None
            from sugar_lift_py_tests.import_binding import (
                authenticated_import_value_use_receipts,
            )

            root, path = self._lexical_import_seat()
            minted, _ = authenticated_import_value_use_receipts(
                root,
                path,
                self.source,
                self.source_cid,
                module_identities={},
                module=module,
            )
            receipts = {}
            for receipt in minted:
                site = receipt.use["useSite"]
                receipts[
                    (site["startLine"], site["startCol"], site["endLine"], site["endCol"])
                ] = receipt
            object.__setattr__(self, "_lexical_value_use_receipts", receipts)
        return receipts.get(span)

    def seat_import_value_use_resolution(
        self,
        span: Tuple[int, int, int, int],
        resolved: object,
        *,
        source_cid: str,
    ) -> None:
        """Seat one final-checked import value-use receipt on this unit only.

        One authenticated value-use receipt per occurrence.  No dependency
        source refines it: an imported name is answered only by its target
        symbol and the imported proofs (step 3).
        """
        from sugar_source_tree.panic import BackendDefect

        if source_cid != self.source_cid:
            raise BackendDefect(
                blame=span,
                owner="SourceUnit.seat_import_value_use_resolution",
                observed=f"source_cid={source_cid!r}",
                requested=f"source_cid={self.source_cid!r} (this unit only)",
                fix="seat only authenticated value-use receipts of this unit's source",
            )
        if (
            not isinstance(span, tuple)
            or len(span) != 4
            or not all(
                isinstance(part, int) and not isinstance(part, bool) for part in span
            )
        ):
            raise BackendDefect(
                blame=span,
                owner="SourceUnit.seat_import_value_use_resolution",
                observed=repr(span),
                requested="(start_line, start_col, end_line, end_col) ints",
                fix="mint seating keys from authenticated useSite coordinates only",
            )
        start_line, start_col, end_line, end_col = span
        # Validate coordinates against this unit's LineTable (no foreign offsets).
        # LineTable.offset raises BackendDefect on out-of-range — no broad catch.
        start_off = self.line_table.offset(start_line, start_col)
        end_off = self.line_table.offset(end_line, end_col)
        if end_off < start_off:
            raise BackendDefect(
                blame=span,
                owner="SourceUnit.seat_import_value_use_resolution",
                observed=f"inverted span {span!r}",
                requested="start <= end in unit source",
                fix="repair authenticated useSite coordinates",
            )
        from sugar_lift_py_tests.import_binding import AuthenticatedImportUseV1

        if type(resolved) is not AuthenticatedImportUseV1:
            raise BackendDefect(
                blame=span,
                owner="SourceUnit.seat_import_value_use_resolution",
                observed=type(resolved).__name__,
                requested="exact AuthenticatedImportUseV1",
                fix="seat only the closed import value-use producer product",
            )
        table = self._import_value_use_resolutions
        if table is None:
            table = {}
            object.__setattr__(self, "_import_value_use_resolutions", table)
        existing = table.get(span)
        resolved.revalidate()
        use = resolved.use
        demand = resolved.demand
        site = use.get("useSite") or {}
        receipt_span = (
            site.get("startLine"),
            site.get("startCol"),
            site.get("endLine"),
            site.get("endCol"),
        )
        exported = use.get("exportedMemberPath")
        if (
            resolved.source_cid != self.source_cid
            or site.get("sourceCid") != self.source_cid
            or demand.get("sourceCid") != self.source_cid
            or receipt_span != span
            or demand.get("kind") != "import-value-use-demand"
            or use.get("role") != "value-use"
            or demand.get("role") != "value-use"
            or use.get("importBindingCid") != resolved.import_binding.cid
            or demand.get("importBindingCid") != resolved.import_binding.cid
            or not isinstance(exported, list)
            or demand.get("exportedMemberPath") != exported
        ):
            raise BackendDefect(
                blame=span,
                owner="SourceUnit.seat_import_value_use_resolution",
                observed="receipt testimony does not match exact value-use seat",
                requested="same-source value-use role, binding, member path, and span",
                fix="seat the producer-minted receipt only at its own occurrence",
            )
        if existing is resolved:
            return
        if existing is not None:
            raise BackendDefect(
                blame=span,
                owner="SourceUnit.seat_import_value_use_resolution",
                observed="receipt conflicts with occupied value-use occurrence",
                requested="one exact receipt identity per occurrence",
                fix="preserve the producer-owned per-occurrence state transition",
            )
        table[span] = resolved

    def import_value_use_resolution(
        self, span: Tuple[int, int, int, int]
    ) -> object | None:
        """Seated import value-use resolution at exact ``span``, or None.

        Frames consume only exact seated coordinates — no scanning, no spelling.
        """
        table = self._import_value_use_resolutions
        if not table:
            return None
        return table.get(span)

    def defer_unresolved_import_value_use(
        self,
        span: Tuple[int, int, int, int],
        marker: object,
        *,
        source_cid: str,
    ) -> None:
        """Record a reachability-scoped unresolved value-use at ``span``.

        Seated by manager receipt seating in place of an eager
        ``ImportValueUseResolutionGap`` raise: the marker stays dormant until a
        value-use consumer reaches the coordinate and mints the countable
        terminal.  A span that later RESOLVES (seated in
        ``_import_value_use_resolutions``) takes precedence at read time.
        """
        from sugar_source_tree.panic import (
            BackendDefect,
            UnresolvedImportValueUseV1,
        )

        if source_cid != self.source_cid:
            raise BackendDefect(
                blame=span,
                owner="SourceUnit.defer_unresolved_import_value_use",
                observed=f"source_cid={source_cid!r}",
                requested=f"source_cid={self.source_cid!r} (this unit only)",
                fix="defer only value-use coordinates of this unit's source",
            )
        if type(marker) is not UnresolvedImportValueUseV1:
            raise BackendDefect(
                blame=span,
                owner="SourceUnit.defer_unresolved_import_value_use",
                observed=type(marker).__name__,
                requested="UnresolvedImportValueUseV1",
                fix="defer only the closed unresolved value-use marker",
            )
        table = self._deferred_unresolved_value_uses
        if table is None:
            table = {}
            object.__setattr__(self, "_deferred_unresolved_value_uses", table)
        existing = table.get(span)
        if existing is not None and existing != marker:
            raise BackendDefect(
                blame=span,
                owner="SourceUnit.defer_unresolved_import_value_use",
                observed="conflicting deferred markers at one value-use seat",
                requested="one unresolved-target testimony per exact coordinate",
                fix="defer the producer-owned unresolved marker only once",
            )
        table[span] = marker

    def deferred_unresolved_import_value_use(
        self, span: Tuple[int, int, int, int]
    ) -> object | None:
        """The deferred unresolved-target marker at ``span``, or None.

        A resolved seating always wins: a span present in
        ``_import_value_use_resolutions`` is not reported as deferred.
        """
        resolved = self._import_value_use_resolutions
        if resolved and span in resolved:
            return None
        table = self._deferred_unresolved_value_uses
        if not table:
            return None
        return table.get(span)

    def bind_typed_module(
        self,
        module: "Module",
        *,
        constructed_nodes: Tuple[object, ...] | None = None,
        function_nodes: Tuple[object, ...] | None = None,
    ) -> None:
        """Attach the already-materialized Module root (SourceFile only)."""
        object.__setattr__(self, "typed_module", module)
        bindings = {}
        for statement in module.body:
            for name in self._module_statement_bound_names(statement):
                bindings.setdefault(name, []).append(statement)
        object.__setattr__(
            self,
            "module_direct_bindings",
            {name: tuple(items) for name, items in bindings.items()},
        )
        if constructed_nodes is None or function_nodes is None:
            raise BackendDefect(
                blame=module.fragment,
                owner="SourceUnit.bind_typed_module",
                observed="module producer roster absent",
                requested="the node and function rosters from Backend.materialize_module",
                fix="route SourceFile through the sole backend module producer",
            )
        object.__setattr__(self, "function_nodes", function_nodes)
        patterns = {}
        patterns_by_target = {}
        enrollments = []
        constructed_count = 0
        for consumer in constructed_nodes:
            # ONE decision, published.  The walk and every consumer of the
            # applicability question call the same function; nobody re-derives
            # enrollment from node kinds or from an empty relation read.
            enrollment = self.target_pattern_enrollment(consumer)
            # Published from the walk that made it, positive and negative alike
            # (#7374).  Attendance testimony reads this roster; it never walks
            # the tree a second time to ask who should have been enrolled.
            enrollments.append((consumer, enrollment))
            if not isinstance(enrollment, TargetPatternEnrolledV1):
                continue
            owned = tuple(
                self._construct_target_pattern(consumer, target, prefix)
                for target, prefix in enrollment._projection_sites
            )
            # Keyed by SourceOccurrenceIdentityV1, never by the producer's Node
            # shell (#7346-A).  ``shadow.rewrite`` borrows the origin's span and
            # keeps its kind and unit, so a rewritten consumer denotes the SAME
            # occurrence and joins this row by construction -- for every enrolled
            # consumer at once, with no per-consumer retention to remember.
            #
            # Both writes REFUSE a duplicate key rather than overwriting it.
            # Ref-keying made a collision structurally impossible: two shells
            # over one occurrence were two keys.  Occurrence-keying collapses
            # them into one, so an overwrite becomes expressible -- and a
            # silently dropped relation row is the exact defect class this
            # repair exists to end.  The invariant is believed, not proven, so
            # it is stated executably here instead of in a comment.
            #
            # The two writes are INDEPENDENTLY reachable and neither is the
            # other's shadow, which is why both are guarded and both have a
            # tooth.  A blanket collapse of every occurrence only ever reaches
            # the consumer write -- it raises before the target loop runs -- so
            # the target write needs its own lever: collapse ONE grammar kind
            # (``Tuple``) and the two consumers stay distinct while their
            # targets claim one key.  Both levers are exercised, and each guard
            # dies alone under mutation (see
            # test_the_two_duplicate_key_guards_are_independently_reachable).
            consumer_key = SourceOccurrenceIdentityV1.of(consumer)
            if consumer_key in patterns:
                raise TargetPatternConstructionGapV1(
                    "duplicate-target-pattern-consumer-occurrence",
                    consumer_occurrence=consumer,
                    target_occurrence=None,
                    target_pattern=(consumer_key, patterns[consumer_key], owned),
                )
            patterns[consumer_key] = owned
            for pattern in owned:
                target_key = SourceOccurrenceIdentityV1.of(pattern.target_occurrence)
                if target_key in patterns_by_target:
                    raise TargetPatternConstructionGapV1(
                        "duplicate-target-pattern-target-occurrence",
                        consumer_occurrence=consumer,
                        target_occurrence=pattern.target_occurrence,
                        target_pattern=(
                            target_key,
                            patterns_by_target[target_key],
                            pattern,
                        ),
                    )
                patterns_by_target[target_key] = pattern
            constructed_count += len(owned)
        object.__setattr__(self, "_target_pattern_enrollments", tuple(enrollments))
        object.__setattr__(self, "_target_patterns_by_consumer", patterns)
        object.__setattr__(self, "_target_patterns_by_target", patterns_by_target)
        object.__setattr__(self, "target_pattern_construction_count", constructed_count)
        # Identity keys include spans against the bound module; drop stale rows.
        object.__setattr__(self, "_exception_type_identity_cache", {})

    @staticmethod
    def _is_binding_target_pattern(target) -> bool:
        """True only when every leaf is a lexical binding occurrence."""
        if isinstance(target, Name):
            return True
        if isinstance(target, Starred):
            return SourceUnit._is_binding_target_pattern(target.value)
        if isinstance(target, (Tuple_, List)):
            return all(
                SourceUnit._is_binding_target_pattern(child) for child in target.elts
            )
        return False

    @staticmethod
    def _owns_binding_leaf(target) -> bool:
        """True when this target introduces at least one lexical binding leaf.

        ``_construct_target_pattern`` mints a product exactly when this holds.
        One predicate serves both the producer walk and the published
        enrollment outcome, so there is no second answer to enrollment.
        """
        if isinstance(target, Name):
            return True
        if isinstance(target, Starred):
            return SourceUnit._owns_binding_leaf(target.value)
        if isinstance(target, (Tuple_, List)):
            return any(
                SourceUnit._owns_binding_leaf(child) for child in target.elts
            )
        return False

    def target_pattern_enrollment(self, consumer) -> TargetPatternEnrollmentV1:
        """The producer's ONE closed applicability decision for a consumer.

        Total and lookup-free: it answers "is this shape enrolled?" without
        touching the relation table, so it cannot be confused with "did my
        lookup find the row?".  ``bind_typed_module`` calls this same function
        while walking, which is what makes it authoritative rather than a
        reconstruction.
        """
        sites = ()
        if isinstance(consumer, Assign):
            sites = tuple(
                (target, ("targets", target_index))
                for target_index, target in enumerate(consumer.targets)
                if isinstance(target, (Tuple_, List))
                and self._is_binding_target_pattern(target)
            )
        elif isinstance(consumer, For):
            sites = ((consumer.target, ("target",)),)
        elif isinstance(consumer, With):
            # ``with M() as (a, b):`` -- the as-clause is an assignment whose
            # binding occurrence is this statement.  ``_bind_store_target``
            # lowers it to ``<target> = enter_result``; that store borrows this
            # span but is not a source occurrence, so the pattern it reads is
            # the one minted here, for the With that owns the target.
            sites = tuple(
                (item.optional_vars, ("items", item_index, "optional_vars"))
                for item_index, item in enumerate(consumer.items)
                if isinstance(item.optional_vars, (Tuple_, List))
                and self._is_binding_target_pattern(item.optional_vars)
            )
        elif isinstance(consumer, (ListComp, SetComp, DictComp, GeneratorExp)):
            sites = tuple(
                (generator.target, ("generators", index, "target"))
                for index, generator in enumerate(consumer.generators)
            )
        if not sites:
            return TargetPatternNotEnrolledV1(
                consumer_occurrence=consumer,
                reason="consumer-shape-not-enrolled",
                _authority=_TARGET_PATTERN_ENROLLMENT_AUTHORITY,
            )
        binding_sites = tuple(
            (target, prefix)
            for target, prefix in sites
            if self._owns_binding_leaf(target)
        )
        if not binding_sites:
            return TargetPatternNotEnrolledV1(
                consumer_occurrence=consumer,
                reason="no-binding-leaf-target",
                _authority=_TARGET_PATTERN_ENROLLMENT_AUTHORITY,
            )
        return TargetPatternEnrolledV1(
            consumer_occurrence=consumer,
            projection_sites=binding_sites,
            _authority=_TARGET_PATTERN_ENROLLMENT_AUTHORITY,
        )

    def _construct_target_pattern(
        self, consumer, target, prefix
    ) -> TargetPatternV1 | None:
        from .binding_state import mint_binding_coordinate_v1

        ordered = []

        def visit(node, path):
            if isinstance(node, Name):
                ordered.append((node, path))
                return
            if isinstance(node, Starred):
                visit(node.value, (*path, "star"))
                return
            if isinstance(node, (Tuple_, List)):
                for index, child in enumerate(node.elts):
                    visit(child, (*path, index))
                return
            if isinstance(node, (Attribute, Subscript)):
                # Store leaves carry runtime store obligations; they do not
                # introduce lexical bindings and therefore own no binding
                # coordinate in this pattern.
                return
            raise TargetPatternConstructionGapV1(
                "unsupported-target-leaf",
                consumer_occurrence=consumer,
                target_occurrence=target,
            )

        visit(target, prefix)
        if not ordered:
            # Unreachable: the producer only mints for sites the published
            # enrollment decision named.  Loud rather than ``None`` so the two
            # can never silently diverge.
            raise TargetPatternConstructionGapV1(
                "enrolled-target-without-binding-leaf",
                consumer_occurrence=consumer,
                target_occurrence=target,
            )
        owner_cid = (
            consumer.owned_loop_target.target_cid
            if isinstance(consumer, For) and consumer.owned_loop_target is not None
            else consumer.fragment.seal().cid
        )
        leaves = tuple(leaf for leaf, _ in ordered)
        coordinates = tuple(
            mint_binding_coordinate_v1(
                scope_owner_cid=owner_cid,
                binding_site=leaf.fragment,
                projection_path=path,
            )
            for leaf, path in ordered
        )
        return _mint_target_pattern(
            source_unit=self,
            consumer_occurrence=consumer,
            target_occurrence=target,
            leaves=leaves,
            coordinates=coordinates,
        )

    def _seated_target_patterns(self, consumer):
        """Raw relation read.  ``None`` means exactly one thing: lookup missed.

        Callers never see this; every public reader turns a miss into a typed
        refusal.  Non-enrollment is not expressible here -- that question is
        answered by ``target_pattern_enrollment`` and by nothing else.
        """
        patterns = self._target_patterns_by_consumer
        if patterns is None:
            raise TargetPatternConstructionGapV1(
                "target-pattern-table-not-built",
                consumer_occurrence=consumer,
                target_occurrence=None,
            )
        return patterns.get(SourceOccurrenceIdentityV1.of(consumer))

    def require_target_patterns(
        self, consumer: "Node"
    ) -> tuple[TargetPatternV1, ...]:
        """Strict read of an ENROLLED consumer's producer-owned products.

        Three facts that used to collapse into one empty tuple now have three
        distinct representations:

        * table never built  -> ``target-pattern-table-not-built`` refusal;
        * lawfully not enrolled -> ``TargetPatternNotEnrolledV1`` (a value,
          obtained from ``target_pattern_enrollment``, never from here);
        * enrolled but stranded -> ``foreign-target-occurrence`` refusal.
        """
        enrollment = self.target_pattern_enrollment(consumer)
        if not isinstance(enrollment, TargetPatternEnrolledV1):
            raise TargetPatternConstructionGapV1(
                "not-an-enrolled-target-pattern-consumer",
                consumer_occurrence=consumer,
                target_occurrence=None,
            )
        owned = self._seated_target_patterns(consumer)
        if not owned:
            raise TargetPatternConstructionGapV1(
                "foreign-target-occurrence",
                consumer_occurrence=consumer,
                target_occurrence=None,
            )
        return owned

    def relation_membership_roster(self) -> dict:
        """Attendance for the source relations this unit's ONE walk observed.

        A width sealed over a corpus must say WHO it saw, not merely how many
        rows it emitted.  Two sealed ``frontierWidth=477`` receipts described
        their run exactly and carried zero lexical-call testimony (#7351), so
        the denominator was unknowable and no seal failed.  This is the
        positive statement that makes that state impossible to reach quietly.

        For each relation:

        * ``expected`` is the producer's own ENROLLMENT ROSTER -- the closed
          applicability decision the structural walk ALREADY published for
          every occurrence it classified.
        * ``observed`` is the RELATION TABLE population verbatim, at full
          multiplicity.

        Nothing is re-derived: both sides are publications the one walk
        already made, and neither is computed from the other.  They are
        separate objects with separate lifetimes, so every way they can come
        apart has its own name at the seal -- an enrolled occurrence the table
        never seated is ``missing``, a seated row nobody enrolled is
        ``extra``, and a row seated twice is ``duplicate``.  A lawfully
        not-enrolled occurrence enters neither side: absence never wears the
        costume of a failed join.

        Refuses when the walk never ran at all, because "nothing was enrolled"
        and "nobody looked" are different facts.
        """
        enrollments = self._target_pattern_enrollments
        if enrollments is None:
            raise BackendDefect(
                blame=self.filename,
                owner="SourceUnit.relation_membership_roster",
                observed="target-pattern enrollment roster was never published",
                requested="the roster bind_typed_module publishes from its walk",
                fix="bind the typed module before asking who the walk saw",
            )
        patterns_by_consumer = self._target_patterns_by_consumer
        if patterns_by_consumer is None:
            raise BackendDefect(
                blame=self.filename,
                owner="SourceUnit.relation_membership_roster",
                observed="the target-pattern relation table was never built",
                requested="a built relation table to read attendance from",
                fix="bind the typed module before asking who the walk seated",
            )
        module = self.constructed_module

        return {
            "lexical-call": {
                "expected": tuple(
                    occurrence
                    for occurrence, decision in module.lexical_call_enrollments
                    if isinstance(decision, LexicalCallEnrolledV1)
                ),
                "observed": tuple(
                    SourceOccurrenceIdentityV1.of(row.call_occurrence)
                    for row in module.lexical_call_rows
                ),
            },
            "target-pattern": {
                "expected": tuple(
                    SourceOccurrenceIdentityV1.of(consumer)
                    for consumer, enrollment in enrollments
                    if isinstance(enrollment, TargetPatternEnrolledV1)
                ),
                "observed": tuple(patterns_by_consumer),
            },
        }

    def require_target_pattern(self, consumer, target) -> TargetPatternV1:
        enrollment = self.target_pattern_enrollment(consumer)
        target_occurrence = SourceOccurrenceIdentityV1.of(target)
        if isinstance(enrollment, TargetPatternEnrolledV1):
            for pattern in self._seated_target_patterns(consumer) or ():
                if (
                    SourceOccurrenceIdentityV1.of(pattern.target_occurrence)
                    == target_occurrence
                ):
                    return pattern
        # Not-enrolled and lookup-missed are both refusals HERE by design: this
        # door promises one exact enrolled pair or nothing.
        raise TargetPatternConstructionGapV1(
            "foreign-target-occurrence",
            consumer_occurrence=consumer,
            target_occurrence=target,
        )

    def require_target_pattern_for_target(self, target) -> TargetPatternV1:
        patterns = self._target_patterns_by_target
        pattern = (
            None
            if patterns is None
            else patterns.get(SourceOccurrenceIdentityV1.of(target))
        )
        if pattern is None:
            raise TargetPatternConstructionGapV1(
                "foreign-target-occurrence",
                consumer_occurrence=target,
                target_occurrence=target,
            )
        return pattern

    def require_target_pattern_coordinates(self, pattern, coordinates) -> None:
        if type(pattern) is not TargetPatternV1 or pattern.source_unit is not self:
            raise TargetPatternConstructionGapV1(
                "foreign-target-pattern",
                consumer_occurrence=pattern.consumer_occurrence,
                target_occurrence=pattern.target_occurrence,
                target_pattern=pattern,
            )
        if type(coordinates) is not tuple or len(coordinates) != len(
            pattern.coordinates
        ):
            raise TargetPatternConstructionGapV1(
                "target-coordinate-arity-mismatch",
                consumer_occurrence=pattern.consumer_occurrence,
                target_occurrence=pattern.target_occurrence,
                target_pattern=pattern,
                expected_coordinates=pattern.coordinates,
                actual_coordinates=coordinates,
            )
        from .binding_provenance import BindingCoordinateV1

        for observed, expected in zip(coordinates, pattern.coordinates, strict=True):
            if observed is not expected and any(
                observed is owned for owned in pattern.coordinates
            ):
                reason = "target-coordinate-order-mismatch"
            elif (
                type(observed) is not BindingCoordinateV1
                or BindingCoordinateV1.decode(observed.wire()) != observed
                or observed.binding_site != expected.binding_site
            ):
                reason = "foreign-target-coordinate"
            elif observed.scope_owner_cid != expected.scope_owner_cid:
                reason = "foreign-target-scope"
            elif (
                observed.projection_path != expected.projection_path
                or observed is not expected
            ):
                reason = "target-coordinate-order-mismatch"
            else:
                continue
            raise TargetPatternConstructionGapV1(
                reason,
                consumer_occurrence=pattern.consumer_occurrence,
                target_occurrence=pattern.target_occurrence,
                target_pattern=pattern,
                expected_coordinates=pattern.coordinates,
                actual_coordinates=coordinates,
            )

    def loop_target_coordinate_for_loop(self, owner: "Node"):
        from sugar_lift_py_tests.context_manager_resolution import (
            SourceFragmentCoordinateV1,
        )
        from sugar_lift_py_tests.loop_construction import mint_loop_target_coordinate_v1

        if owner.kind not in ("For", "AsyncFor", "While"):
            raise ValueError("loop target owner must be a loop node")
        span = owner.line_col_span()
        return mint_loop_target_coordinate_v1(
            owner.kind,
            SourceFragmentCoordinateV1(
                self.source_cid,
                span.start_line,
                span.start_col,
                span.end_line,
                span.end_col,
            ),
        )

    def _require_typed_module(self, owner: str, *, blame: object) -> "Module":
        module = self.typed_module
        if module is None:
            raise SourceTreePanic(
                blame=blame,
                owner=owner,
                observed="typed Module is not bound on this SourceUnit",
                requested=(
                    "the SourceFile-materialized Module as structural authority"
                ),
                fix=(
                    "construct through SourceFile so the typed tree is bound "
                    "before module-level identity queries"
                ),
            )
        return module  # type: ignore[return-value]

    def function_symtable(self, name: str, lineno: int):
        index = self._function_symtable_index
        if index is None:
            # One walk of the CPython symtable tree, which is fixed for the
            # life of the unit; every call used to repeat it.
            index = {}

            def visit(table) -> None:
                for child in table.get_children():
                    if child.get_type() == "function":
                        index.setdefault(
                            (child.get_name(), child.get_lineno()), []
                        ).append(child)
                    visit(child)

            visit(self.module_symtable)
            object.__setattr__(self, "_function_symtable_index", index)
        matches = index.get((name, lineno), ())
        if len(matches) != 1:
            raise SourceTreePanic(
                blame=f"{self.filename}:{lineno}:0",
                owner="SourceUnit.function_symtable",
                observed=(
                    f"{len(matches)} function symtables for {name!r} at line {lineno}"
                ),
                requested="one CPython function symtable selected by type, name, and line",
                fix="preserve the source function's exact CPython symtable identity",
            )
        return matches[0]

    def is_module_level_function(self, name: str, lineno: int) -> bool:
        """Whether this exact definition occupies an importable module slot.

        Authority is the already-materialized typed Module body (direct
        ``FunctionDef`` / ``AsyncFunctionDef`` children only) — never a second
        parse of the source text as semantic authority.
        """
        module = self._require_typed_module(
            "SourceUnit.is_module_level_function",
            blame=f"{self.filename}:{lineno}:0",
        )
        for statement in module.body:
            if statement.kind not in ("FunctionDef", "AsyncFunctionDef"):
                continue
            if (
                statement.name == name
                and statement.line_col_span().start_line == lineno
            ):
                return True
        return False

    def source_allocation_definition_for_call(self, call: "Call") -> "ClassDef | None":
        """Resolve one source allocation definition at an exact call use-site.

        Spelling is only the lexical lookup key.  Authority is the unique typed
        module binding plus the use-site's CPython scope classification. A
        local/free/nonlocal shadow or competing module binding keeps the
        allocation definition unauthenticated. Behavior is checked separately;
        it never participates in identity admission.
        """
        if not isinstance(call.func, Name):
            return None
        # A directly materialized Call/Assign still owns its ordinary sugar.
        # Absence of the SourceFile-bound module means only that class identity
        # cannot be authenticated here; it must not revoke the existing call
        # construction path.
        module = self.typed_module
        if module is None:
            return None
        span = call.line_col_span()
        owner = self.innermost_function_containing(span)
        if owner is not None:
            table = self.function_symtable(owner.name, owner.line_col_span().start_line)
            try:
                symbol = table.lookup(call.func.id)
            except KeyError:
                symbol = None
            if symbol is not None and (
                symbol.is_parameter()
                or symbol.is_local()
                or symbol.is_free()
                or symbol.is_nonlocal()
            ):
                return None

            # Do NOT resolve "nested" names from function_nodes here.
            # function_nodes is FunctionDef/AsyncFunctionDef only — never ClassDef.
            # Returning a FunctionDef as an allocation definition made
            # source_class_has_authenticated_default_attribute_behavior call
            # ClassDef._authenticated_new_constructor_shape on a FunctionDef
            # (recursive Name-calls: def f: f(...) — the enclosing FunctionDef
            # matched as a "prior nested" same-name definition). That AttributeError
            # blinded recensus (instrument-defect) and factory_walk auditor-errors
            # on real pandas (e.g. io/json/_normalize.py recursive normalize).
            # Nested ClassDef allocation is not enrolled via function_nodes; module
            # ClassDef bindings below remain the sole allocation door.

        bindings = (self.module_direct_bindings or {}).get(call.func.id, ())
        if len(bindings) != 1 or not isinstance(bindings[0], ClassDef):
            return None
        definition = bindings[0]
        # Constructing the allocation definition requires constructing its
        # methods. A call occurrence inside that same definition therefore
        # cannot use the definition as already-constructed testimony without a
        # cycle; it remains an opaque occurrence until recursive allocation has
        # its own construction rule.
        definition_span = definition.line_col_span()
        if (
            (definition_span.start_line, definition_span.start_col)
            <= (span.start_line, span.start_col)
            <= (definition_span.end_line, definition_span.end_col)
        ):
            return None
        return definition

    def source_function_definition_for_call(
        self, call: "Call"
    ) -> "FunctionDef | AsyncFunctionDef | None":
        """Resolve one ordinary source function at an exact lexical call site.

        The name is only a lookup key. Authority is the unique typed module
        binding plus CPython's scope classification at this occurrence. A
        parameter, local, free, nonlocal, ambiguous, or recursive binding is
        not silently treated as this module definition.
        """
        # Ask the producer's applicability question FIRST; read the relation
        # only for an enrolled occurrence.  A stranded enrolled row now refuses
        # instead of entering the fallback and answering with a different
        # module-level definition (#7348 caller 2).
        enrollment = self.lexical_call_enrollment(call)
        if isinstance(enrollment, LexicalCallNotEnrolledV1):
            if enrollment.reason in ("non-name-callee", "no-typed-module"):
                return None
            # module-scope-call / no-lexical-binding-in-scope /
            # binding-not-a-function-definition: the lawful symtable-classified
            # path below is this outcome's ONE named continuation.
            lexical_rows = ()
        else:
            lexical_rows = self.require_lexical_call_rows(call)
        if lexical_rows:
            row = lexical_rows[0]
            definition = row.definition_occurrence
            if row.source_cid != self.source_cid or not isinstance(
                definition, (FunctionDef, AsyncFunctionDef)
            ):
                from .panic import backend_defect

                backend_defect(
                    blame=call.fragment,
                    owner="SourceUnit.source_function_definition_for_call",
                    observed="foreign or malformed lexical call row",
                    requested="this SourceUnit's exact typed function definition",
                    fix="repair Backend.materialize_module lexical call testimony",
                )
            return definition

        span = call.line_col_span()
        owner = self.innermost_function_containing(span)
        if owner is not None:
            table = self.function_symtable(owner.name, owner.line_col_span().start_line)
            try:
                symbol = table.lookup(call.func.id)
            except KeyError:
                symbol = None
            if symbol is not None and (
                symbol.is_parameter()
                or symbol.is_local()
                or symbol.is_free()
                or symbol.is_nonlocal()
            ):
                return None

        bindings = (self.module_direct_bindings or {}).get(call.func.id, ())
        if len(bindings) != 1 or not isinstance(
            bindings[0], (FunctionDef, AsyncFunctionDef)
        ):
            return None
        definition = bindings[0]
        definition_span = definition.line_col_span()
        if (
            (definition_span.start_line, definition_span.start_col)
            <= (span.start_line, span.start_col)
            <= (definition_span.end_line, definition_span.end_col)
        ):
            return None
        return definition

    @staticmethod
    def source_class_has_authenticated_default_attribute_behavior(
        definition: "ClassDef",
    ) -> bool:
        """Whether ordinary attribute storage/lookup is source-constructed."""
        # Defense in depth: allocation definition must be ClassDef. A FunctionDef
        # here is not "no default attributes" — it is not an allocation at all.
        if not isinstance(definition, ClassDef):
            return False
        if definition._authenticated_new_constructor_shape() is not None:
            return True
        forbidden_methods = {
            "__new__",
            "__getattr__",
            "__getattribute__",
            "__setattr__",
            "__delattr__",
            "__getitem__",
            "__setitem__",
            "__delitem__",
        }
        return not (
            definition.bases
            or definition.keywords
            or definition.decorators
            or definition.type_params
            or any(
                not isinstance(member, (Pass, FunctionDef))
                for member in definition.body
            )
            or any(
                isinstance(member, FunctionDef)
                and (
                    member.name in forbidden_methods
                    or (
                        member.decorators
                        and definition._method_descriptor_kind(member) is None
                    )
                )
                for member in definition.body
            )
        )

    @staticmethod
    def _is_simple_class_field_statement(member: "Node") -> bool:
        """A class-body name assignment, not a hook or a computed target."""
        if isinstance(member, Assign):
            return all(isinstance(target, Name) for target in member.targets)
        if isinstance(member, AnnAssign):
            return isinstance(member.target, Name)
        return False

    @staticmethod
    def source_class_has_plain_source_body(
        definition: "ClassDef",
        *,
        _seen: frozenset[int] | None = None,
    ) -> bool:
        """Methods and simple class-body fields only, including local bases.

        Constructor hooks, decorators, keywords, type parameters, and
        unauthenticated or computed bases stay outside this door.
        """
        if not isinstance(definition, ClassDef):
            return False
        if definition._authenticated_new_constructor_shape() is not None:
            return True
        if definition.keywords or definition.decorators or definition.type_params:
            return False
        forbidden_methods = {
            "__new__",
            "__getattr__",
            "__getattribute__",
            "__setattr__",
            "__delattr__",
            "__getitem__",
            "__setitem__",
            "__delitem__",
        }
        for member in definition.body:
            if isinstance(member, Pass):
                continue
            if isinstance(member, FunctionDef):
                if member.name in forbidden_methods or (
                    member.decorators
                    and definition._method_descriptor_kind(member) is None
                ):
                    return False
                continue
            if SourceUnit._is_simple_class_field_statement(member):
                continue
            return False
        seen = set() if _seen is None else set(_seen)
        if id(definition) in seen:
            return False
        seen.add(id(definition))
        for base in definition.bases:
            name = None
            if isinstance(base, Name):
                name = base.id
            elif isinstance(base, Subscript) and isinstance(base.value, Name):
                name = base.value.id
            else:
                return False
            bindings = (definition.unit.module_direct_bindings or {}).get(name, ())
            if len(bindings) != 1 or not isinstance(bindings[0], ClassDef):
                return False
            if not SourceUnit.source_class_has_plain_source_body(
                bindings[0], _seen=frozenset(seen)
            ):
                return False
        return True

    @staticmethod
    def source_class_admits_source_constructor_frame(
        definition: "ClassDef",
    ) -> bool:
        """Whether this class call may carry its source constructor frame.

        Ordinary classes already pass through default-attribute behavior.
        A class whose body is only methods and simple name assignments, and
        whose bases are the same kind of authenticated local class, may also
        carry the frame so instance reads can see those class fields.
        Unauthenticated or computed bases stay outside this door.
        """
        return SourceUnit.source_class_has_authenticated_default_attribute_behavior(
            definition
        ) or SourceUnit.source_class_has_plain_source_body(definition)

    def construction_generation(self, node: "Node") -> int:
        """The source-authenticated generation of this exact occurrence.

        The byte offset is stable across shadow rewrites of the same occurrence
        and differs for distinct occurrences. It comes from the oracle-sealed
        construction fragment, never a binding owner or process counter.
        """
        if not isinstance(node, Call):
            raise SourceTreePanic(
                blame=node.fragment,
                owner="SourceUnit.construction_generation",
                observed=type(node).__name__,
                requested="one exact Call construction occurrence",
                fix="mint object identity only at the sole Call boundary",
            )
        return node.fragment.seal().start

    @staticmethod
    def _module_statement_bound_names(statement: "Node") -> set[str]:
        if isinstance(statement, (FunctionDef, AsyncFunctionDef, ClassDef)):
            return {statement.name}
        if isinstance(statement, (Assign, AnnAssign, AugAssign)):
            targets = (
                statement.targets
                if isinstance(statement, Assign)
                else (statement.target,)
            )
            names: set[str] = set()
            for target in targets:
                names |= SourceUnit._assignment_target_bound_names(target, statement)
            return names
        if statement.kind in ("Import", "ImportFrom"):
            return {
                alias.asname or alias.name.split(".", 1)[0] for alias in statement.names
            }
        return set()

    @staticmethod
    def _assignment_target_bound_names(
        target: "Node", statement: "Node"
    ) -> set[str]:
        """The names an assignment TARGET binds -- a closed grammar decision.

        ``X.attr = v`` and ``X[k] = v`` MUTATE the object ``X`` already denotes.
        Neither BINDS the name ``X``.  The former reading collected every
        ``Name`` in the whole target subtree, so ``get_option.__module__ =
        "pandas"`` at ``_config/config.py:950`` published a second module-scope
        binding of ``get_option`` -- and the by-name authority that must refuse
        an ambiguous name then refused a name that is not ambiguous.  Two
        different facts, "assigns to an attribute OF this name" and "binds this
        name", were sharing one table (#7394).

        A name-binding table must never be widened to make a lookup succeed, so
        this is a decision over the target grammar rather than a filter: Python
        admits exactly Name, Tuple, List, Starred, Attribute and Subscript in an
        assignment target.  Anything else is a producer defect and PANICS naming
        the construct, the coordinate and the shape -- it is not bucketed as
        "binds nothing", because a silently empty answer here is indistinguish-
        able from a legitimately non-binding target.
        """
        if isinstance(target, Name):
            return {target.id}
        if isinstance(target, (Tuple_, List)):
            names: set[str] = set()
            for element in target.elts:
                names |= SourceUnit._assignment_target_bound_names(element, statement)
            return names
        if isinstance(target, Starred):
            return SourceUnit._assignment_target_bound_names(target.value, statement)
        if isinstance(target, (Attribute, Subscript)):
            # Mutates an existing object; binds no module-scope name.
            return set()
        raise BackendDefect(
            blame=getattr(target, "fragment", None) or statement.fragment,
            owner="SourceUnit._assignment_target_bound_names",
            observed=(
                f"assignment target is not an assignable construct: {target.kind}"
            ),
            requested="Name, Tuple, List, Starred, Attribute or Subscript",
            fix="produce assignment targets from the Python assignment grammar",
        )

    def exception_type_identity(self, node: "Name"):
        """Return the authenticated exception-class coordinate reaching ``node``.

        This is deliberately lexical and closed: the Python builtin vocabulary,
        an exact ``from builtins import ...`` binding, or one source class
        definition.  Ambiguous, reassigned, parameter, and computed bindings
        have no identity coordinate and therefore stay loud at the consumer.

        Structural authority is the already-materialized typed Module plus the
        unit's CPython ``symtable`` (function scope flags). No second parse.

        Uses the bind-time ``function_nodes`` / ``module_direct_bindings``
        indexes (same door as ``source_allocation_definition_for_call``) and
        memoizes by name+span — a full ``module.walk()`` per Raise was ~12ms
        on pandas asserters and dominated Body.If → Raise exclusive heat.
        """
        from sugar_lift_py_tests.ir import ctor, str_const
        from sugar_lift_py_tests.temporal.builtin_name_bindings import (
            BUILTIN_EXCEPTION_NAMES,
        )

        self._require_typed_module(
            "SourceUnit.exception_type_identity", blame=node.fragment
        )
        span = node.line_col_span()
        cache_key = (
            node.id,
            span.start_line,
            span.start_col,
            span.end_line,
            span.end_col,
        )
        cache = self._exception_type_identity_cache
        if cache_key in cache:
            return cache[cache_key]

        result = self._compute_exception_type_identity(
            node, span, BUILTIN_EXCEPTION_NAMES, ctor, str_const
        )
        cache[cache_key] = result
        return result

    def imported_exception_type_identity(self, node: "Expression"):
        """Return the closed coordinate of an import-bound dotted type operand.

        The context-manager contract authenticates the operand's role as an
        exception type.  This method authenticates only its source identity:
        the whole reference, head and static Attribute links, must have its
        row in the one import reference table (#7837, #7851).  A shadowed,
        computed, or ambiguous head has no row and stays loud.

        The table records optional-provider bindings with their gate fact
        (``name = pytest.importorskip("mod")``; ``try: import mod`` /
        ``except ImportError:`` that leaves ``mod`` unbound on the handler
        path).  An exception-type identity is read only where the name is
        bound, so this reader admits the try-import gate.

        Language-owned builtins keep their builtin identity even through an
        import alias: qualification does not create a new exception class.
        Other coordinates name the import target path, without inventing MRO
        or ClassValue ancestry when defining source is absent from the seat.
        """
        link = node
        while isinstance(link, Attribute):
            link = link.value
        if not isinstance(link, Name):
            return None
        # The target symbol is the table's; it is never rebuilt here.
        target = self.import_reference_of(node, admit_provider_gate=True)
        if target is None:
            return None
        return exception_type_identity_of_import_target(target)

    def _compute_exception_type_identity(
        self, node: "Name", span, builtin_names, ctor, str_const
    ):
        owner = self.innermost_function_containing(span)
        if owner is not None:
            table = self.function_symtable(owner.name, owner.line_col_span().start_line)
            try:
                symbol = table.lookup(node.id)
            except KeyError:
                symbol = None
            if symbol is not None and (
                symbol.is_parameter()
                or symbol.is_local()
                or symbol.is_free()
                or symbol.is_nonlocal()
            ):
                return None

        bindings = []
        for statement in (self.module_direct_bindings or {}).get(node.id, ()):
            kind = statement.kind
            if kind == "ImportFrom":
                for alias in statement.names:
                    if (alias.asname or alias.name) == node.id:
                        bindings.append(("import", statement.module, alias.name))
            elif kind == "ClassDef":
                bindings.append(("class", statement))
            else:
                # FunctionDef / AsyncFunctionDef / Assign / AnnAssign / AugAssign /
                # Import — any non-closed exception-class binding.
                bindings.append(("other",))

        from sugar_lift_py_tests.temporal.builtin_name_bindings import (
            canonical_builtin_exception_name,
        )

        if not bindings and node.id in builtin_names:
            return ctor(
                "python:exception_type_identity",
                [
                    str_const("builtins"),
                    str_const(canonical_builtin_exception_name(node.id)),
                ],
            )
        if len(bindings) != 1:
            return None
        binding = bindings[0]
        if (
            binding[0] == "import"
            and binding[1] == "builtins"
            and binding[2] in builtin_names
        ):
            return ctor(
                "python:exception_type_identity",
                [
                    str_const("builtins"),
                    str_const(canonical_builtin_exception_name(binding[2])),
                ],
            )
        if binding[0] == "class":
            definition = binding[1]
            lc = definition.line_col_span()
            coordinate = (
                f"{self.source_cid}:{lc.start_line}:{lc.start_col}:"
                f"{lc.end_line}:{lc.end_col}"
            )
            return ctor(
                "python:exception_type_identity",
                [str_const("source-class"), str_const(coordinate)],
            )
        return None

    def _builtin_exception_ancestry(self, identity):
        """Python's own ancestry for a ``builtins`` exception identity.

        ``None`` when the identity is not a builtin one — a source class owns
        its own base graph and is resolved lexically below. The previous
        behaviour returned the singleton ``(identity,)`` for every non-local
        class, which is not "ancestry unknown" but the positive claim that the
        class has no ancestors, and it silently made ``except Exception`` fail
        to match ``raise ValueError``.
        """
        from sugar_lift_py_tests.ir import ctor, str_const
        from sugar_lift_py_tests.temporal.builtin_name_bindings import (
            BUILTIN_EXCEPTION_BASES,
        )

        args = getattr(identity, "args", ())
        if len(args) != 2 or getattr(args[0], "value", None) != "builtins":
            return None
        root = getattr(args[1], "value", None)
        if root not in BUILTIN_EXCEPTION_BASES:
            return None
        ancestry = []
        pending = [root]
        while pending:
            name = pending.pop(0)
            coordinate = ctor(
                "python:exception_type_identity",
                [str_const("builtins"), str_const(name)],
            )
            if coordinate in ancestry:
                continue
            ancestry.append(coordinate)
            pending.extend(BUILTIN_EXCEPTION_BASES[name])
        return tuple(ancestry)

    def exception_type_mro(self, node: "Name"):
        """Return the source-authenticated ancestry known for ``node``.

        Builtin identities carry Python's OWN hierarchy, transported from
        ``BUILTIN_EXCEPTION_BASES`` — the language states that ``ValueError``
        is an ``Exception``, so the ancestry is cited, never assumed. Source
        class identities carry every lexically resolved base coordinate. A
        computed base or cycle leaves the testimony unavailable, never guessed.
        """
        identity = self.exception_type_identity(node)
        if identity is None:
            return None
        builtin_ancestry = self._builtin_exception_ancestry(identity)
        if builtin_ancestry is not None:
            return builtin_ancestry
        module = self._require_typed_module(
            "SourceUnit.exception_type_mro", blame=node.fragment
        )
        definitions = [
            statement
            for statement in module.body
            if statement.kind == "ClassDef" and statement.name == node.id
        ]
        if len(definitions) != 1:
            # No unique lexical definition: the ancestry is UNKNOWN. The old
            # ``(identity,)`` was the positive claim "no ancestors", which the
            # matcher read as a decided miss against every handler but the
            # class itself.
            return None

        result = [identity]
        visiting: set[str] = set()

        def append_definition(definition) -> bool:
            # The ancestry is testimony only when it is CLOSED: every base is
            # either a builtin exception (whose own ancestry the language
            # table states) or a unique module-level source class walked in
            # turn. Anything else -- a dotted or imported base, a computed
            # base, a base without a unique definition, a cycle -- leaves the
            # whole ancestry unavailable, never a truncated prefix that a
            # membership test would read as a decided miss.
            if definition.name in visiting:
                return False
            visiting.add(definition.name)
            for base in definition.bases:
                if not isinstance(base, Name):
                    return False
                base_identity = self.exception_type_identity(base)
                if base_identity is None:
                    return False
                builtin_ancestry = self._builtin_exception_ancestry(base_identity)
                if builtin_ancestry is not None:
                    for ancestor in builtin_ancestry:
                        if ancestor not in result:
                            result.append(ancestor)
                    continue
                if base_identity not in result:
                    result.append(base_identity)
                base_definitions = [
                    candidate
                    for candidate in module.body
                    if candidate.kind == "ClassDef" and candidate.name == base.id
                ]
                if len(base_definitions) != 1 or not append_definition(
                    base_definitions[0]
                ):
                    return False
            visiting.remove(definition.name)
            return True

        return tuple(result) if append_definition(definitions[0]) else None

    def exception_class_ancestry(self):
        """The exception classes this module defines, with their ancestry (#7757).

        Returns ``((statement, name, symbol, identity, ancestors), ...)``: one
        entry per module-level exception class, in source order, then one per
        name a package re-exports:

        - ``statement`` is the ``class`` (or the re-exporting ``from ...
          import``) that binds ``name`` at module level;
        - ``symbol`` is the name's target symbol, ``python:<module>.<name>``
          (``module_member_target_symbol``: the one speller the function join
          reads too);
        - ``identity`` is the coordinate a consumer's import door mints for
          that symbol (``exception_type_identity_of_symbol``);
        - ``ancestors`` are the coordinates of the classes it is a subclass
          of, each testified by this source.

        The module's proof states ``adt.is_python_type(identity, ancestor)``
        for each ancestor. A consumer's ``except`` against the imported class
        retains exactly ``adt.is_python_type(identity, handler)``; prove joins
        that open question to these facts by the symbol, and closes it across
        the staged proofs: an ancestor that is itself an import coordinate is
        followed into the facts its own proof states (step 9).

        What testifies to an ancestor:

        - a builtin exception base, and the ancestry the language states for
          it;
        - a sibling exception class of this module, by its own symbol
          coordinate, and that class's ancestry in turn;
        - an import-bound base, by the coordinate the import door mints for
          it from the one import table. Its own ancestry is its defining
          proof's to state; the join follows it there.

        A package ``__init__`` that binds a name by ``from <m> import <name>``
        re-exports it: a consumer's ``from <package> import <name>`` names
        ``<package>.<name>``, while the defining module's rows name the
        import's target. The package states the one edge between them,
        ``adt.is_python_type(<package>.<name>, <target>)`` (the same class,
        so true), and the join follows the target's own facts.

        A base nothing testifies to (computed, subscripted, a call, a cycle)
        states nothing. Every fact stated is true, and what is not stated
        stays open at the consumer. A decorated class, or one with class
        keywords (a metaclass), states nothing: its decorator or metaclass
        decides what the name is bound to, not its header. A class whose
        ancestry reaches neither a builtin exception nor an imported class is
        not known here to be an exception class, and states nothing.
        """
        module = self._require_typed_module(
            "SourceUnit.exception_class_ancestry", blame=self.filename
        )
        bindings = self.module_direct_bindings or {}

        def own_class(name):
            bound = bindings.get(name, ())
            if len(bound) != 1 or bound[0].kind != "ClassDef":
                return None
            definition = bound[0]
            if definition.decorators or definition.keywords:
                return None
            return definition

        memo: dict = {}

        def ancestry(definition, visiting: frozenset):
            """``(ancestors, exceptional)`` of ``definition``: ``exceptional``
            when its ancestry reaches a builtin exception or an imported class
            (whose own ancestry its defining proof states)."""
            if definition.name in memo:
                return memo[definition.name]
            if definition.name in visiting:
                return (), False
            visiting = visiting | {definition.name}
            ancestors: list = []
            exceptional = False

            def add(identity) -> None:
                if identity not in ancestors:
                    ancestors.append(identity)

            for base in definition.bases:
                identity = None
                if isinstance(base, Name):
                    identity = self.exception_type_identity(base)
                    if identity is None:
                        identity = self.imported_exception_type_identity(base)
                elif isinstance(base, Attribute):
                    identity = self.imported_exception_type_identity(base)
                if identity is None:
                    continue
                kind = getattr(identity.args[0], "value", None)
                if kind == "builtins":
                    builtin_ancestry = self._builtin_exception_ancestry(identity)
                    for ancestor in builtin_ancestry or (identity,):
                        add(ancestor)
                    exceptional = True
                elif kind == "source-class":
                    sibling = own_class(base.id) if isinstance(base, Name) else None
                    if sibling is None:
                        continue
                    sibling_ancestors, sibling_exceptional = ancestry(sibling, visiting)
                    if not sibling_exceptional:
                        continue
                    sibling_symbol = self.module_member_target_symbol(sibling.name)
                    if sibling_symbol is None:
                        continue
                    add(exception_type_identity_of_symbol(sibling_symbol))
                    for ancestor in sibling_ancestors:
                        add(ancestor)
                    exceptional = True
                elif kind == "import":
                    # ``is(E, Base)`` holds whatever Base is; Base's own
                    # ancestry is its defining proof's, and the join follows
                    # it there (step 9).
                    add(identity)
                    exceptional = True
            result = (tuple(ancestors), exceptional)
            memo[definition.name] = result
            return result

        stated = []
        for statement in module.body:
            if statement.kind != "ClassDef":
                continue
            definition = own_class(statement.name)
            if definition is None:
                continue
            own = definition.line_col_span()
            here = statement.line_col_span()
            if (own.start_line, own.start_col) != (here.start_line, here.start_col):
                continue
            ancestors, exceptional = ancestry(definition, frozenset())
            if not exceptional or not ancestors:
                continue
            symbol = self.module_member_target_symbol(definition.name)
            if symbol is None:
                continue
            stated.append(
                (
                    definition,
                    definition.name,
                    symbol,
                    exception_type_identity_of_symbol(symbol),
                    ancestors,
                )
            )

        _root, path = self._lexical_import_seat()
        runner = self._lexical_import_pass() if path.name == "__init__.py" else None
        for statement in module.body if runner is not None else ():
            if statement.kind != "ImportFrom":
                continue
            for alias in statement.names:
                name = alias.asname or alias.name
                bound = bindings.get(name, ())
                if alias.name == "*" or len(bound) != 1 or bound[0] is not statement:
                    continue
                # The name's target is the one import table's, never rebuilt.
                target = runner.module_import_target(name)
                symbol = self.module_member_target_symbol(name)
                if target is None or symbol is None or target == symbol:
                    continue
                reached = exception_type_identity_of_import_target(target)
                if reached is None:
                    continue
                stated.append(
                    (
                        statement,
                        name,
                        symbol,
                        exception_type_identity_of_symbol(symbol),
                        (reached,),
                    )
                )
        return tuple(stated)

    def exception_class_value(self, node: "Name"):
        """Project one source-authenticated exception identity into one class graph."""
        from sugar_lift_py_tests.floor import BlockValue
        from sugar_lift_py_tests.floor.local_exception_class_value import (
            LocalExceptionClassValue,
        )
        from sugar_lift_py_tests.ir import ctor, str_const
        from sugar_lift_py_tests.temporal.builtin_name_bindings import (
            BUILTIN_EXCEPTION_NAMES,
            builtin_name_temporal,
        )

        identity = self.exception_type_identity(node)
        mro = self.exception_type_mro(node)
        if identity is None or mro is None:
            raise SugarNotWritten(
                blame=node.fragment,
                owner="SourceUnit.exception_class_value",
                observed="exception class lacks a closed authenticated base graph",
                requested="source-authenticated ClassValue ancestry",
                fix="keep computed, cyclic, or opaque exception ancestry loud",
            )
        cache = self.exception_class_values
        cached = cache.get(identity)
        if cached is not None:
            return cached

        for builtin_name in BUILTIN_EXCEPTION_NAMES:
            builtin_identity = ctor(
                "python:exception_type_identity",
                [str_const("builtins"), str_const(builtin_name)],
            )
            if identity == builtin_identity:
                value = builtin_name_temporal().value_for(builtin_name)
                cache[identity] = value
                return value

        module = self._require_typed_module(
            "SourceUnit.exception_class_value", blame=node.fragment
        )
        definitions = [
            statement
            for statement in module.body
            if statement.kind == "ClassDef" and statement.name == node.id
        ]
        if len(definitions) != 1:
            raise SugarNotWritten(
                blame=node.fragment,
                owner="SourceUnit.exception_class_value",
                observed="authenticated identity has no unique source class",
                requested="one lexical exception class definition",
                fix="keep ambiguous exception ancestry loud",
            )
        definition = definitions[0]
        bases = tuple(self.exception_class_value(base) for base in definition.bases)
        value = LocalExceptionClassValue(
            name=definition.name, bases=bases, record=BlockValue(())
        )
        cache[identity] = value
        return value

    def is_builtin_exception_group(self, node: "Name") -> bool:
        """Authenticate exception-group constructors by runtime identity."""
        from sugar_lift_py_tests.ir import ctor, str_const

        identity = self.exception_type_identity(node)
        if identity is None:
            return False
        return any(
            identity
            == ctor(
                "python:exception_type_identity",
                [str_const("builtins"), str_const(name)],
            )
            for name in ("BaseExceptionGroup", "ExceptionGroup")
        )


class Typeable:
    """The interface: you may ask me for my node type.

    ``resolve_type`` has two arms: a concrete ``Node`` subclass,
    or ``SourceTreePanic``. There is no third arm.
    """

    def resolve_type(self) -> type["Node"]:
        raise NotImplementedError


class Typed(Typeable):
    """The abstract class: I HAVE a resolved type; resolution already happened.

    For nodes the resolved type is the concrete class itself; the
    construction event was the resolution.
    """

    def resolve_type(self) -> type["Node"]:
        tp = type(self)
        if tp in _ABSTRACT or not issubclass(tp, Node):
            # Neither of the two panics fits: this is not a backend-facing
            # question at all (no BackendHandle, no adapter, no vocabulary
            # gap) and not a structural-defect-in-backend-output question
            # either. It is an internal invariant on OUR OWN construction
            # code: only concrete classes are ever instantiated (construct.py
            # resolves through resolve_kind, which already excludes
            # _ABSTRACT). Reaching here means our own code, not a backend,
            # built an abstract instance. Raised as the common base directly
            # — deliberately, not a guess at which subclass fits.
            raise SourceTreePanic(
                blame=tp,
                owner="nodes.Typed.resolve_type",
                observed=f"instance of abstract node class {tp.__name__}",
                requested="a concrete grammar class",
                fix="abstract node classes are never instantiated",
            )
        return tp


KIND_REGISTRY: dict[str, type["Node"]] = {}
_ABSTRACT: set[type] = set()


def _abstract(cls: type) -> type:
    _ABSTRACT.add(cls)
    KIND_REGISTRY.pop(cls.__name__, None)
    return cls


def _as_evaluation_of(node, sugar):
    """``node``'s sugar, stamped with the iterations ``node`` stands for.

    A shallow copy (same type and fields), so a sugar the construction shares
    with an untagged node is never mutated; the reducer enters the stamped
    segments while it desugars this copy (``Sugar.desugar``).
    """
    from .shadow import occurrence_tags_of

    tags = occurrence_tags_of(node)
    if not tags or sugar is None:
        return sugar
    import copy

    try:
        stamped = copy.copy(sugar)
        object.__setattr__(stamped, "_occurrence_tags", tags)
    except (AttributeError, TypeError):
        return sugar
    return stamped


def _iteration_copies(loop, index: int, statements) -> tuple:
    """Iteration ``index`` of ``loop``: one occurrence copy per node.

    The dissolved body shares node objects (and therefore spans and sugars)
    across iterations; a copy per iteration is what lets each evaluation of a
    site key its own opaque atoms (``shadow.OccurrenceShadowNode``).
    """
    from .shadow import as_occurrence, iteration_segment

    segment = iteration_segment(loop, index)
    return tuple(as_occurrence(statement, segment) for statement in statements)


def _iteration_scope(loop, index: int, bindings, outer):
    """The scope for substituting iteration ``index`` of ``loop``'s body:
    ``bindings``, with that iteration's segment ahead of the segments
    ``outer`` (the scope the loop itself was substituted in) already stood
    for -- an inner loop's iteration inside this one."""
    from .shadow import iteration_segment

    return {
        **bindings,
        _EVALUATION_OCCURRENCE: (
            iteration_segment(loop, index),
            *outer.get(_EVALUATION_OCCURRENCE, ()),
        ),
    }


def _exit_path_scope(clause_owner, path: str, bindings):
    """The scope for substituting ``clause_owner``'s ``finally`` for one exit
    path (``"completion"`` or ``"halt"``): ``bindings``, with that path's
    segment ahead of the exit paths ``bindings`` already stood for -- a
    ``finally`` nested inside another one's copy."""
    span = clause_owner.span
    return {
        **bindings,
        _EVALUATION_EXIT_PATH: (
            f"finally[{span.start},{span.end})@{path}",
            *bindings.get(_EVALUATION_EXIT_PATH, ()),
        ),
    }


def _holds_evaluation(statements) -> bool:
    """Whether a substituted suite holds a statement (or walrus) keyed as its
    own evaluation (``Statement._evaluation_key``: ``x += e``, ``a, b = f()``,
    ``y = e``, ``y: T = e``, ``(x := e)``)."""
    return any(
        isinstance(node, (AugAssign, Assign, AnnAssign, NamedExpr))
        and isinstance(getattr(node, "evaluation", None), str)
        for statement in statements
        for node in statement.walk()
    )


def _arm_walruses(arm):
    """The keyed walruses (plain name target, ``evaluation`` minted) a
    conditional expression's arm runs when it runs: every one under ``arm``
    except those in a lambda or a generator expression, which run later if
    at all."""
    found = []
    stack = [arm]
    while stack:
        node = stack.pop()
        if node.kind in ("Lambda", "GeneratorExp"):
            continue
        if (
            node.kind == "NamedExpr"
            and isinstance(node.target, Name)
            and isinstance(getattr(node, "evaluation", None), str)
        ):
            found.append(node)
        stack.extend(child for _field, _index, child in reversed(node.children()))
    return found


def _evaluation_ref(
    owner,
    span,
    evaluation: str,
    name: str,
    *,
    member=False,
    walrus: bool = False,
    cell: bool = False,
    deferred: bool = False,
    of: "Optional[Node]" = None,
) -> "Node":
    """``EvaluationRef(evaluation, name)`` at ``span``: a read of ``name``
    rewritten to a reference to the evaluation bound under ``evaluation``
    (temporal choice 1, #7661).  The one constructor of that node: an
    ``x += e`` statement's evaluation, an ``(x := e)`` walrus's, a
    comprehension generator's binding of one member, an assignment's target
    (``Assign.target_evaluations``), and the re-span of any of them to the
    read's own site (``Name.substitute``).

    ``member`` marks a comprehension member's reference: the comprehension
    binds every member under ``evaluation`` before any read of it, so the
    reference reads that coordinate only, never the name.  ``walrus`` marks a
    walrus's reference: it resolves through the key only
    (``EvaluationRefSugar``), never the name and never the walrus's value
    evaluated again.  ``cell`` marks a member reference to a comprehension's
    final member (``final_member_coordinate``) in the body of a lambda the
    comprehension stores: the lambda carries that binding in its closure
    (``Lambda._construct_sugar``, ``LambdaSugar``).  ``deferred`` marks a
    walrus in a generator expression's element or conditions: it writes when
    the generator is consumed, not where the generator is made, so where its
    key is unbound the read is undecided by name.

    ``of`` is the right-hand side an assignment's target was given: which
    object the name denotes, never its value.  The value is the key's; the
    object is what a store on it reaches (``container_mutation._identity``:
    ``r = []; a = r; r.append(1)`` changes what ``a`` names too) and which
    lambda a call through the name applies (``Call._construct_sugar``).  It
    is a leaf, not a child: nothing walks into it and its sugar is never
    built from it.  Where ``of`` is ground, substitution asks the reference
    for that value to decide a shape (``EvaluationRef.ground_value``), and
    for nothing else."""
    from .backend import Leaf, materialize
    from .shadow import ShadowNode

    slots = (("evaluation", Leaf(evaluation)), ("name", Leaf(name)))
    if member:
        slots = (*slots, ("member", Leaf(True)))
    if walrus:
        slots = (*slots, ("walrus", Leaf(True)))
    if cell:
        slots = (*slots, ("cell", Leaf(True)))
    if deferred:
        slots = (*slots, ("deferred", Leaf(True)))
    if of is not None:
        slots = (*slots, ("of", Leaf(of)))
    return materialize(
        owner.unit,
        ShadowNode("EvaluationRef", span, slots),
        owner.reporter,
    )


def _ground_value(node) -> "Optional[Node]":
    """The ground literal ``node`` denotes, or None.

    The one way substitution asks for a value to decide a shape: how many
    times a loop unrolls (``For._concrete_elements``, ``For._concrete_int``),
    which suite a ground condition selects (``While._ground_truth``), which
    member a starred unpack gives each name (``Assign._ground_members``).
    The answer decides the shape only.  It never stands in for a read: a read
    of an assigned name is still the reference to its key, and the statement
    that reads it still reads the key at reduce.

    Ground is: a ``Constant``; ``-``/``+`` over a ground operand; int
    arithmetic over ground ints that ``For._concrete_int`` decides; a
    ``List``/``Tuple`` display whose every member is ground (no ``*``
    member); a subscript of a ground display by a ground int in range (its
    member); and a key reference (``EvaluationRef``) whose ``of`` is ground,
    the value that key holds.  A reference is the binding the scope holds
    where it is read, so after a rebind it is the rebind's key: ``n = 3; n =
    4`` reads 4, and ``n = 3; n += 1`` reads ``x += e``'s key, which carries
    no ``of`` and is not ground."""
    if not isinstance(node, Node):
        return None
    kind = node.kind
    if kind == "EvaluationRef":
        of = getattr(node, "of", None)
        return _ground_value(of) if isinstance(of, Node) else None
    if kind == "Constant":
        return node
    if kind == "UnaryOp":
        if node.op.kind not in ("USub", "UAdd"):
            return None
        return node if _ground_value(node.operand) is not None else None
    if kind == "BinOp":
        return node if For._concrete_int(node, node) is not None else None
    if kind in ("List", "Tuple"):
        if all(
            element.kind != "Starred" and _ground_value(element) is not None
            for element in node.elts
        ):
            return node
        return None
    if kind == "Subscript":
        display = _ground_value(node.value)
        if display is None or display.kind not in ("List", "Tuple"):
            return None
        index = For._concrete_int(node, node.slice_)
        if index is None or not -len(display.elts) <= index < len(display.elts):
            return None
        return _ground_value(display.elts[index])
    return None


def _object_read_in(reference, reads, scope) -> bool:
    """Whether ``reads`` read a name that may reach the object ``reference``
    denotes: the reference's own name, or any name ``scope`` binds to that
    object or to an object it was taken from (``container_mutation._identity``,
    through each subscript receiver).  A loop over a list unrolls through the
    list's key only when its body cannot reach the list: Python iterates the
    live list, so a body that appends to it changes how many items there
    are."""
    from .binding_state import unwrap_binding_state
    from .container_mutation import _identity

    identities = []
    names = set()
    node = reference
    while isinstance(node, Node):
        if node.kind == "EvaluationRef":
            names.add(node.name)
        identity = _identity(node)
        identities.append(identity)
        taken_from = getattr(identity, "kind", None) == "Subscript"
        node = identity.value if taken_from else None
    for name, state in scope.items():
        if not isinstance(name, str):
            continue
        bound = _identity(unwrap_binding_state(state))
        if any(bound is identity for identity in identities):
            names.add(name)
    return any(
        node.kind == "Name" and node.id in names
        for root in reads
        for node in root.walk()
    )


def final_member_coordinate(member_coordinate: str) -> str:
    """The coordinate an eager comprehension binds its final member under:
    what the comprehension's cell for ``member_coordinate`` holds once the
    comprehension is done (the last member iterated, filtered or not).

    A closure stored in what the comprehension produces is called after the
    comprehension (``fs = [lambda: x for x in xs]; fs[0]()``), and Python
    reads the cell at call time, so its read of the member is a member
    reference to this coordinate (``_closure_cell_scope``), bound by
    ``ComprehensionSugar`` before the element is reduced."""
    from sugar_lift_python_source.canonical import cid_of_json

    return cid_of_json(
        {
            "kind": "comprehension-final-member",
            "schemaVersion": "1",
            "memberCoordinate": member_coordinate,
        }
    )


def _source_position(node: "Node") -> tuple:
    """The source occurrence a node is recognised by across substitution (a
    rewrite borrows its origin's span): a stored lambda, a module statement
    the module threading recorded."""
    return (node.kind, node.span.start, node.span.end)


def _stored_closures(roots) -> frozenset:
    """The lambdas an eager comprehension stores unevaluated in what it
    produces: an element (a dict comprehension's key or value) that is a
    lambda, a lambda inside a list, tuple, set or dict display there, or a
    lambda an eager comprehension there stores in its own result
    (``[[lambda: x for _ in ys] for x in xs]``): that result is stored in
    this one, so the lambda escapes both.

    Nothing calls such a lambda before the comprehension is done, so it reads
    the comprehension's final member.  A lambda anywhere else (called in
    place, handed to a call, read by a condition, produced by a lazy
    generator expression) may be called while the comprehension runs, when
    the cell holds the current member, and is not one of these."""
    found = set()
    pending = list(roots)
    while pending:
        node = pending.pop()
        if isinstance(node, Lambda):
            found.add(_source_position(node))
        elif isinstance(node, (List, Tuple_, Set)):
            pending.extend(node.elts)
        elif isinstance(node, Dict):
            for item in node.items:
                if item.key is not None:
                    pending.append(item.key)
                pending.append(item.value)
        elif isinstance(node, (ListComp, SetComp)):
            pending.append(node.elt)
        elif isinstance(node, DictComp):
            pending.extend((node.key, node.value))
    return frozenset(found)


def _closure_cell_scope(scope, roots, cells) -> "BindingMap":
    """``scope`` for substituting ``roots`` (an eager comprehension's element,
    or a dict comprehension's key and value) with ``cells``: each name the
    comprehension's targets bind, to what the comprehension's cell for it
    holds once the comprehension is done -- the last member's projection
    when the comprehension dissolves, a member reference to the final member
    coordinate (``final_member_coordinate``) when it does not.

    The cells are one layer on the layers of the comprehensions enclosing
    this one: a lambda reads, for each comprehension it escapes, that
    comprehension's cells (``Lambda.substitute``).  ``Lambda.substitute``
    reads them in the body of a lambda the comprehension stores
    (``_stored_closures``), the way a lambda's body reads every other
    enclosing binding: by substitution.  ``scope`` unchanged when no lambda
    is stored or no name has a cell."""
    if not cells:
        return scope
    stored = _stored_closures(roots)
    if not stored:
        return scope
    return {
        **scope,
        _CLOSURE_CELLS: (*scope.get(_CLOSURE_CELLS, ()), (stored, dict(cells))),
    }


def _mask_closure_cells(scope, names) -> "BindingMap":
    """``scope`` with ``names`` -- the names a comprehension's targets bind --
    removed from the cells of every enclosing comprehension: inside it those
    names are its own, never an enclosing comprehension's cell."""
    layers = scope.get(_CLOSURE_CELLS)
    if not layers or not names:
        return scope
    return {
        **scope,
        _CLOSURE_CELLS: tuple(
            (stored, {k: v for k, v in cells.items() if k not in names})
            for stored, cells in layers
        ),
    }


def _member_closure_scope(owner, inner, roots) -> "BindingMap":
    """``inner`` (the scope an eager comprehension ``owner`` that does not
    dissolve substitutes ``roots`` in) with the comprehension's cells: each
    target name, to a member reference to its final member coordinate
    (``_final_member_cells``)."""
    if not _stored_closures(roots):
        return inner
    return _closure_cell_scope(
        inner, roots, _final_member_cells(owner, owner.generators, inner)
    )


def _final_member_cells(owner, generators, inner) -> dict:
    """Each name ``generators`` bind whose read in ``inner`` is a member
    reference (``ListComp._target_references``), to a member reference to
    that member's final coordinate (``final_member_coordinate``), marked
    ``cell``: the lambda that reads it carries the binding in its closure."""
    names = set()
    for gen in generators:
        names |= owner._bound_names_in(gen.target)
    cells = {}
    for name in names:
        reference = unwrap_binding_state(inner.get(name))
        if (
            isinstance(reference, EvaluationRef)
            and getattr(reference, "member", False) is True
        ):
            cells[name] = _evaluation_ref(
                owner,
                reference.span,
                final_member_coordinate(reference.evaluation),
                reference.name,
                member=True,
                cell=True,
            )
    return cells


def _loop_header_evaluation_key(loop, name: str, scope) -> str:
    """The coordinate of a live loop header's evaluation of ``name``: the
    value ``name`` holds when an item of ``loop``'s body begins (the pre-loop
    value at the first item, the previous item's last write after it).

    A live loop is constructed once and reduced once per item, so this key
    names the header for every item; ``LoopRecurrenceSugar`` binds each item's
    value under it qualified by that item (``evaluation_here``), as
    ``Statement._evaluation_key`` is for a statement in the body.  The key is a
    function of the loop's source occurrence, the name, the iterations the
    loop is substituted for and the exit path of the clause copy it sits in,
    so ``For.substitute`` (which rewrites the reads)
    and ``construct_live_loop_recurrence`` (which hands the key to the
    recurrence) name the same header without carrying it on the node.
    """
    from sugar_lift_python_source.canonical import cid_of_json
    from sugar_lift_py_tests.temporal.temporal_context import EVALUATION_PREFIX

    from .shadow import occurrence_tags_of

    return EVALUATION_PREFIX + cid_of_json(
        {
            "kind": "python-loop-header-evaluation-v1",
            "loopFragmentCid": loop.fragment.seal().cid,
            "name": name,
            "occurrence": [
                *scope.get(_EVALUATION_OCCURRENCE, ()),
                *occurrence_tags_of(loop),
            ],
            "exitPath": list(scope.get(_EVALUATION_EXIT_PATH, ())),
        }
    )


def _loop_header_bindings(loop, names, scope) -> dict:
    """The body scope's binding of each name ``loop`` carries into its body
    (and, for a live ``for``, into its ``else`` suite): a reference to the
    loop header's evaluation of it (temporal choice 1, #7661), never the bare
    name looked up by spelling.

    A carried name is one the body rebinds that is bound before the loop
    (a ``BindingEntryV1`` in ``scope``: the same test
    ``construct_live_loop_recurrence`` uses for the names it carries).  A name
    bound only inside the body has no value at the header and stays masked, so
    its read before the body binds it stays the name read.  Each binding keeps
    the pre-loop binding's coordinate: it is the same variable, read at the
    header.  Where nothing binds the header key at reduce (a loop reduced as
    its recurrence, not per item), the reference reads the name, as before.
    """
    headers = {}
    for name in sorted(names):
        entry = scope.get(name)
        if not isinstance(entry, BindingEntryV1):
            continue
        evaluation = _loop_header_evaluation_key(loop, name, scope)
        reference = _evaluation_ref(loop, loop.span, evaluation, name)
        headers[name] = replace(entry, state=reference, sealed_state=None)
    return headers


@dataclass(frozen=True)
class ModuleBindingStatesV1:
    """The module body threaded once (``SourceUnit.module_binding_states``).

    ``at`` maps the source position (``_source_position``) of every
    statement the threading ran, at any depth, to the binding scope
    standing when it began, once per time it was threaded (an unrolled
    loop's iterations, a ``finally``'s exit paths); ``final`` is the scope
    after the last statement: what a function called after the module body
    reads a global as.  While the body is still being threaded ``at`` holds
    the statements threaded so far and ``final`` is None.
    """

    at: dict
    final: Optional[dict]


class _ModuleStatementRecord:
    """The table ``SourceUnit.module_binding_states`` threads a module body
    with (``_MODULE_STATEMENT_STATES``): ``at`` as ``ModuleBindingStatesV1``
    holds it, open while that threading runs."""

    __slots__ = ("at", "open")

    def __init__(self) -> None:
        self.at: dict = {}
        self.open = True


class ModuleExecutionSiteV1:
    """Where a node runs while the module body runs at import
    (``SourceUnit.module_execution_site``): the statements it runs in,
    outermost first, and whether it sits in a generator's lazily evaluated
    part.  Two sites are equal when they name the same statements of the
    same unit: a remembered frame built at one is served at the other."""

    __slots__ = ("unit", "chain", "lazy", "_key")

    def __init__(self, unit, chain: tuple, lazy: bool) -> None:
        self.unit = unit
        self.chain = chain
        self.lazy = lazy
        self._key = (tuple(_source_position(statement) for statement in chain), lazy)

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, ModuleExecutionSiteV1)
            and self.unit is other.unit
            and self._key == other._key
        )

    def __ne__(self, other: object) -> bool:
        return not self.__eq__(other)

    __hash__ = None  # type: ignore[assignment]


# Where the call being constructed runs while its module body runs at import
# (``ModuleExecutionSiteV1``), set by the call (``Call._construct_sugar``) and
# inherited by every construction it reaches: the callee's frame, the frames
# that frame's calls reach.  None: the construction runs after the module
# body, called from outside its execution.
_MODULE_EXECUTION_SITE: AmbientVar = AmbientVar(
    "sugar_module_execution_site", default=None
)
# A new token for each statement ``SourceUnit.module_binding_states`` records
# while it threads a module body; None when no module body is being threaded.
# Every reader of module bindings reads it, so an answer read from a partly
# threaded body is served again only at that same point of that threading.
_MODULE_THREADING: AmbientVar = AmbientVar("sugar_module_threading", default=None)


def current_module_execution_site():
    """The module execution site the construction running now is under
    (``_MODULE_EXECUTION_SITE``), not recorded as a read.  A source call
    frame carries it (``SourceVisibleCallFrameV1.module_execution_site``),
    so the frame read again at reduce is read at the site its call was
    constructed at.  A frame whose body does not depend on the site reads
    the same at any site."""
    return _MODULE_EXECUTION_SITE.now(None)


def construct_at_module_execution_site(site, construct):
    """``construct()`` under the module execution ``site``: a call the
    module body runs (``Call._construct_sugar``), or a frame read again at
    reduce at the site it was constructed at."""
    if site == _MODULE_EXECUTION_SITE.now(None):
        return construct()
    token = _MODULE_EXECUTION_SITE.set(site)
    try:
        return construct()
    finally:
        _MODULE_EXECUTION_SITE.reset(token)


def _walrus_targets(statement) -> frozenset:
    """The names a walrus in ``statement``'s own expressions binds in the
    enclosing scope: not in a statement it nests, nor in a ``lambda``,
    ``def`` or ``class`` body (a walrus in a comprehension binds the
    enclosing scope's name, and is one of these)."""
    names: set = set()
    pending = [
        child
        for _field, _index, child in statement._child_edges()
        if not isinstance(child, Statement)
    ]
    while pending:
        node = pending.pop()
        if isinstance(node, NamedExpr) and isinstance(node.target, Name):
            names.add(node.target.id)
        for field_name, _index, child in node._child_edges():
            if isinstance(child, Statement) or (
                field_name == "body" and isinstance(node, Lambda)
            ):
                continue
            pending.append(child)
    return frozenset(names)


def _module_reference_state(state):
    """A module binding state as a reader outside the module block takes it:
    a reference to the evaluation of the module body's write of the name
    (``EvaluationRef``: ``x += e``, an unpack's projection, a walrus), or
    the phi the module block built over such references where the write
    sits in an arm of an ``if``.  A comprehension member's coordinate is
    bound only inside its comprehension, so a binding to one is
    ``UNDECIDED_MODULE_BINDING`` wherever a reader outside it reads the
    name.  Any other state (an assignment's value, an unbound name) is no
    evaluation: None, and the reader reads the name as before."""
    state = unwrap_binding_state(state)
    if not isinstance(state, Node):
        return None
    kind = _evaluation_reference_kind(state)
    if kind is None:
        return None
    if kind == "member":
        return UNDECIDED_MODULE_BINDING
    return state


def _evaluation_reference_kind(node) -> Optional[str]:
    """``"evaluation"`` for a reference to a statement's or a walrus's
    evaluation (or a phi whose arms are such references or constants),
    ``"member"`` where a comprehension member's coordinate is among them,
    None for anything else."""
    if isinstance(node, EvaluationRef):
        return "member" if getattr(node, "member", False) else "evaluation"
    if not (isinstance(node, IfExp) and isinstance(node.test, BranchResultRef)):
        return None
    kinds = [
        _evaluation_reference_kind(arm)
        for arm in (node.body, node.orelse)
        if not isinstance(arm, Constant)
    ]
    if not kinds or None in kinds:
        return None
    return "member" if "member" in kinds else "evaluation"


def _bound_module_references(reader, bindings: dict, *, owner: str) -> dict:
    """``bindings`` (``SourceUnit.module_bindings_at``) as the scope a
    reader of module names substitutes its body in: each name bound to the
    reference to the evaluation that binds it where the reader runs.  A name
    whose binding is no evaluation is left out (it is read by name).  A
    name the module body does not decide there is cited ``undecided`` by
    name; it is never read by name in its place."""
    references = {}
    for name in sorted(bindings):
        binding = bindings[name]
        if binding is UNDECIDED_MODULE_BINDING:
            raise SugarNotWritten(
                owner=owner,
                blame=reader.fragment,
                observed=(
                    f"undecided module binding of `{name}` where "
                    f"`{reader.name}` reads it"
                ),
                requested=(
                    "the module binding the module body decides where this "
                    "read runs"
                ),
                fix=(
                    "decide the binding at the read's point of the module "
                    "body; never read the name in its place"
                ),
            )
        if binding is not None:
            references[name] = binding
    return references


class _Splice:
    """A substitute result that EXPANDS one statement into several. Returned by
    ``For.substitute`` when a concrete loop unrolls: the loop dissolves into its
    body statements, and ``_substitute_body`` splices them into the enclosing
    block so the loop's carried accumulator is just ordinary block-threading.
    Not a Node -- only ``_substitute_body`` handles it, and a `for` is always a
    statement in a block, so it is never substituted anywhere else."""

    __slots__ = ("statements", "bindings")

    def __init__(self, statements: tuple, bindings: BindingMap | None = None) -> None:
        self.statements = statements
        self.bindings = bindings or {}



_FRAMES_UNDER_CONSTRUCTION: AmbientSet = AmbientSet("frames_under_construction")


def _frame_is_under_construction(definition_cid: str) -> bool:
    """THE ONE READ of ``_FRAMES_UNDER_CONSTRUCTION``.

    Is that definition's frame still open?  The set is ambient state: each
    ask is recorded on the memo row in flight, so every row (a frame, a
    sugar answer, a substitution) is served only where the frames it asked
    about are open or closed as they were (``construction_cache.serve``).
    """
    return definition_cid in _FRAMES_UNDER_CONSTRUCTION


class SourceCallFrameCycle(Exception):
    """Re-entry into a source-visible frame still under construction.

    Raised by ``FunctionDef.source_visible_call_frame`` and caught only at the
    inline call sites in ``Call._construct_sugar``, where the call becomes a
    recursion seat (definition known, ``call-graph-cycle`` resolution gap).
    """

    def __init__(self, definition) -> None:
        super().__init__(definition.name)
        self.definition = definition


@_abstract
@dataclass(frozen=True, eq=False, repr=False, kw_only=True)
class Node(Typed):
    """Abstract base of every node. The hierarchy is the grammar.

    Shell over memoized field *data* on the unit ConstructionCache. Accessors
    resolve each backend slot at most once per construction coordinate into
    that shared row; re-reads hit the row. Control stacks enter the coordinate
    only for Break/Continue/Raise (nearest binding); other kinds share one row
    across every enclosing loop/handler. Shells are free to construct.
    Shadow rewrite uses the same door with a shadow backend ref.
    """

    unit: SourceUnit
    ref: object  # the BackendNode reference; duck-typed to avoid a cycle
    # The roll call. REQUIRED -- no default -- so a node cannot be constructed
    # off the roll: this is what makes construction complete BY CONSTRUCTION,
    # not by a call someone remembers to make. The constructor registers the
    # node (``__post_init__``); every child this node resolves is constructed
    # with the same reporter, so registration flows through the whole tree.
    reporter: AuditReporter
    control_context: ControlConstructionContextV1 = field(
        default_factory=ControlConstructionContextV1,
        compare=False,
        repr=False,
    )
    owned_loop_target: object | None = field(
        init=False, default=None, compare=False, repr=False
    )

    # Ordered names of fields holding child nodes (Node, optional
    # Node, or tuple of Node). Leaf values (str/int/...)
    # and operators are NOT children. Declared per class, in grammar order.
    # ClassVar on purpose: never a dataclass field, never instance state.
    _child_fields: ClassVar[Tuple[str, ...]] = ()

    def __post_init__(self) -> None:
        # THE construction event IS the registration. Registering here, in the
        # constructor, means calling ``cls(...)`` at all is showing up on the
        # roll -- there is no way to new a node without it. (register only
        # records the reference; field *data* is memoized on the unit cache.)
        testify(self.reporter, "register", self)
        if isinstance(self, (For, AsyncFor, While)):
            object.__setattr__(
                self,
                "owned_loop_target",
                self.unit.loop_target_coordinate_for_loop(self),
            )

    def _child_control_context(self, field_name: str) -> ControlConstructionContextV1:
        if isinstance(self, (For, AsyncFor, While)) and field_name == "body":
            if self.owned_loop_target is None:
                from sugar_lift_py_tests.loop_construction import LoopWireError

                raise LoopWireError("loop node has no owned target coordinate")
            return self.control_context.enter_loop(self.owned_loop_target)
        if isinstance(self, ExceptHandler) and field_name == "body":
            return self.control_context.enter_exception(self._effect_slot_id())
        if (
            isinstance(self, (FunctionDef, AsyncFunctionDef, ClassDef, Lambda))
            and field_name == "body"
        ):
            return ControlConstructionContextV1()
        return self.control_context

    def __init_subclass__(cls, **kw: object) -> None:
        super().__init_subclass__(**kw)
        KIND_REGISTRY[cls.__name__] = cls

    def _construction_cache(self) -> "ConstructionCache":
        """The unit's one work memo. Node shells are VIEWS -- many shells wrap
        one ref -- so every memo hangs off the unit, keyed by the construction
        coordinate, never off the transient shell."""
        from .construction_cache import ConstructionCache

        cache = self.unit.construction_cache
        if cache is None:
            cache = ConstructionCache()
            object.__setattr__(self.unit, "construction_cache", cache)
        return cache

    def _coordinate(self) -> "tuple[ConstructionCache, tuple, dict]":
        """``(cache, key, field row)`` for this shell's construction coordinate.

        The coordinate is a function of the shell's ref, reporter and control
        context, the unit's construction context and the node class.  A shell
        asks for it on every field read, every child-edge read and every
        sugar read, and each ask used to recompute the key and re-pin it.

        The shell holds the answer beside the participants that can be
        rebound under it -- the unit's cache, the unit's construction context
        and the reporter -- and asks ``cache.key`` again only when one of
        them is a different object.  The ref and the control context are
        frozen for the life of the shell.  The held row is the row in
        ``cache.fields``: rows are never dropped from a live cache, so the
        memo stays on the unit and every shell of one coordinate still reads
        one row.
        """
        state = self.__dict__
        unit = state["unit"]
        reporter = state["reporter"]
        cache = unit.construction_cache
        context = unit.construction_context
        held = state.get("_held_coordinate")
        if (
            held is not None
            and held[0] is cache
            and held[1] is context
            and held[2] is reporter
        ):
            return held[3]  # type: ignore[no-any-return]
        if cache is None:
            cache = self._construction_cache()
        key = cache.key(
            state["ref"],
            reporter,
            state["control_context"],
            context,
            kind=type(self).__name__,
        )
        answer = (cache, key, cache.fields.setdefault(key, {}))
        state["_held_coordinate"] = (cache, context, reporter, answer)
        return answer

    @property
    def target_pattern_enrollment(self) -> TargetPatternEnrollmentV1:
        """Is this shape an enrolled target-pattern consumer? (closed answer)"""
        return self.unit.target_pattern_enrollment(self)

    def require_target_patterns(self) -> tuple[TargetPatternV1, ...]:
        """The eager occurrence-owned target products for an ENROLLED consumer.

        Refuses rather than returning an empty tuple: absence of enrollment is
        ``target_pattern_enrollment``, not a smaller product.
        """
        return self.unit.require_target_patterns(self)

    def __getattr__(self, name: str):
        # Field data is memoized on the unit once per site; this shell exposes it.
        if name.startswith("_"):
            raise AttributeError(name)
        row = self._coordinate()[2]
        if name in row:
            return row[name]
        for slot_name, slot in self.ref.describe().slots:
            if slot_name == name:
                value = slot.resolve(
                    self.unit,
                    self.reporter,
                    self._child_control_context(slot_name),
                )
                row[name] = value
                return value
        if name in _declared_fields(type(self)):
            vocabulary_missing(
                blame=self.ref,
                owner="nodes.Node.__getattr__",
                observed=(
                    f"backend answer for {type(self).__name__} has no slot "
                    f"for declared accessor {name!r}"
                ),
                requested="the backend satisfies every accessor the class declares",
                fix="teach the adapter to answer this accessor; never guess",
            )
        raise AttributeError(name)

    @property
    def span(self) -> Span:
        desc = self.ref.describe()
        if desc.raw_span is not None:
            return desc.raw_span
        spans = list(desc.anchors) + [child.span for _, _, child in self.children()]
        if not spans:
            # Our own adapter's anchor-rule vocabulary is incomplete for a
            # kind it has not seen positioned before: a MISSING, not a defect.
            vocabulary_missing(
                blame=self.ref,
                owner="nodes.Node.span",
                observed=(
                    f"{self.kind} with neither a backend position nor any spanned child"
                ),
                requested="every node has a source extent",
                fix="give the adapter an anchor rule for this kind; never invent a span",
            )
        span = spans[0]
        for s in spans[1:]:
            span = span.envelope(s)
        return span

    @property
    def kind(self) -> str:
        """Frozen wire word for serialization. Never a dispatch mechanism."""
        override = getattr(type(self), "_kind", None)
        return override if isinstance(override, str) else type(self).__name__

    def substitute(self, scope: "dict[str, Node]") -> "Node":
        """This node's substitution — the temporal rewrite that binds a hole to
        its shape. Every concrete class writes it deliberately: a leaf returns
        itself, a compound recurses (``_substitute_children``), a scope-owner
        masks its bound names before recursing, a ``Name`` binds. There is NO
        permissive recurse-by-default — a silent default would let a binding
        node capture (rewrite an outer name into a body that rebinds it) and
        never say so. So the abstract throws: writing the override IS writing
        the substitution, coverage visible in the hierarchy, the capture hazard
        loud rather than silent.
        """
        where = f"{self.unit.filename}"
        try:
            lc = self.line_col_span()
            where = f"{self.unit.filename}:{lc.start_line}:{lc.start_col}"
        except SourceTreePanic:
            pass
        raise SubstituteNotWritten(
            blame=self.fragment,
            owner=f"{type(self).__name__}.substitute",
            observed=f"{self.kind} at {where} has no substitution written",
            requested="a deliberate substitution (recurse, mask, bind, or inert)",
            fix=(
                f"write substitute() on {type(self).__name__}: a leaf returns "
                "self, a compound returns self._substitute_children(scope), a "
                "scope-owner masks its bound names first; never a silent default"
            ),
        )

    def _substituted_child(self, child: "Node", scope: BindingMap) -> "Node":
        """``child.substitute(scope)``, asked ONCE per (child, scope) pair.

        Substitution already shares on the way down -- ``Name.substitute``
        returns the BOUND NODE ITSELF -- so a threaded term is a DAG of shared
        objects, not a copied tree. What was not shared is the *asking*: every
        path that reaches a shared term descends it again, so a binding read
        ``u`` times down a chain of ``N`` costs ``u^N`` visits over a term of
        size ``O(N)``. That is #7411, and it is a redundant question, not a
        redundant term.

        So the sharing added here is a memo on the FUNCTION, keyed by its two
        arguments: the child's construction coordinate and the scope OBJECT it
        is asked against. It is not a judgement that two terms are equal, and
        it never merges two answers -- it returns the one answer this exact
        call already produced.

        WHERE IT DECLINES TO SHARE, which is the whole safety argument: a
        different scope object is a different key, full stop. Every scope in
        this file is either threaded through unchanged or built FRESH
        (``{**scope, **binding}`` per statement in ``_substitute_body_tracked``,
        ``dict(scope)`` in ``With``/live-loop, a masked comprehension of
        ``scope`` in ``FunctionDef``/``Comprehension``); none is mutated after
        it has been substituted against. So a name rebound mid-block, a
        mutation between two reads, and a masking scope-owner each present a
        scope the memo has never seen, and the child substitutes again.
        """
        cache = child._construction_cache()
        # No reporter in the key: the row's testimony is replayed to it.
        key = (id(child.ref), id(scope))
        row = serve(cache.substitutions, key, child.reporter)
        if row is not None:
            return row.value
        computation = open_row()
        try:
            result = child.substitute(scope)
        except BaseException:
            abandon_row(computation)
            raise
        # Pin both identity-bearing participants for the row's lifetime: a
        # transient shadow ref or a dropped scope dict must not have its
        # address recycled into a live key (the hazard construction_cache
        # already closes for field rows).
        cache._pinned[key] = (child.ref, scope)
        close_row(cache.substitutions, key, computation, child.reporter, value=result)
        return result

    def _substitute_field(self, value, scope):
        """Substitute ONE field value (a child Node, None, or a tuple of
        them) against a scope. Returns ``(new_value, changed)``. A scope-owner
        uses this per field so it can hand different fields different scopes
        (its signature the outer scope, its body the masked one)."""
        if value is None:
            return value, False
        if isinstance(value, Node):
            new = self._substituted_child(value, scope)
            if isinstance(new, _Splice):
                raise TypeError(
                    "_Splice escaped into a generic child field: a statement "
                    f"tuple holding a {value.kind} must go through "
                    "_substitute_body (a block), never _substitute_children -- "
                    "give the containing node a block-aware substitute"
                )
            if new is not value:
                value.discharge_by_substitution()
            return new, new is not value
        items = tuple(value)
        new_items = tuple(
            self._substituted_child(item, scope) if isinstance(item, Node) else item
            for item in items
        )
        changed = any(new is not old for new, old in zip(new_items, items))
        if changed:
            for new, old in zip(new_items, items):
                if new is not old and isinstance(old, Node):
                    old.discharge_by_substitution()
        return (new_items if changed else value), changed

    def discharge_by_substitution(self) -> None:
        """Answer the roll call for a node the rewrite replaced.

        Substitution IS this node's discharge: it constructs nothing of its own,
        so it answers ``present_inert`` -- showed up, nothing built -- and the
        node that replaced it answers separately for what it constructs. Without
        this the replaced node stays registered with no answer at all, which the
        minority report reads (correctly) as a silent unaccounted construction.
        """
        testify(self.reporter, "present_inert", self)

    def _substitute_children(self, scope: BindingMap) -> "Node":
        """The structural recurse a NON-binding compound opts into: substitute
        every child against the SAME scope; if any changed, rebuild me around
        them (a shadow node borrowing my span); if none changed, return myself.
        A node calls this DELIBERATELY — it is never the silent default, because
        a scope-owner must mask its bound names before it can use it safely."""
        from .shadow import rewrite

        changed: dict[str, object] = {}
        for name in type(self)._child_fields:
            new, diff = self._substitute_field(getattr(self, name), scope)
            if diff:
                changed[name] = new
        if not changed:
            return self
        return rewrite(self, **changed)

    def substitution_binding(self, scope: BindingMap) -> "Optional[BindingMap]":
        """The binding this STATEMENT introduces for the rest of its block, or
        None. An assignment returns ``{name: its substituted rhs}``; an augmented
        assignment reads the OLD value from ``scope`` to build ``x OP e``;
        everything else binds nothing. Read AFTER this statement was substituted,
        so its value is already rewritten against the scope that stood before it."""
        return None

    def refine_binding_entries(
        self, binding: BindingMap, scope: BindingMap
    ) -> BindingMap:
        """Refine freshly minted entries without creating another binding map."""
        del scope
        return binding

    def post_binding_statement(self, binding: BindingMap) -> "Node":
        """Project a store's post-version into its substituted target."""
        del binding
        return self

    def post_binding_scope(self, scope: BindingMap) -> BindingMap:
        """Apply statement-owned invalidations to the one temporal map."""
        if not any(
            isinstance(entry, BindingEntryV1)
            and isinstance(entry.state, ObjectPlaceStateV1)
            for entry in scope.values()
        ):
            return scope
        from .container_mutation import runs_operand_code

        # Only a call that may run code holding the object can change it: a
        # cited pure builtin over builtin-typed operands leaves it as it was.
        exposed = {
            state.object_identity_cid
            for call in self.walk()
            if isinstance(call, Call) and runs_operand_code(call, scope)
            for state in call.exposed_object_places()
        }
        # ``f'{c}'`` runs ``c.__format__`` (and ``!s``/``!r`` its
        # ``__str__``/``__repr__``): user code unless ``c`` is builtin-typed.
        from .container_mutation import builtin_typed

        exposed |= {
            node.object_identity_cid
            for formatted in self.walk()
            if isinstance(formatted, FormattedValue)
            and not builtin_typed(formatted.value, scope)
            for node in formatted.value.walk()
            if isinstance(node, ObjectPlaceStateV1)
        }
        if not exposed:
            return scope
        replacements = {}
        for name, entry in scope.items():
            if (
                isinstance(name, str)
                and isinstance(entry, BindingEntryV1)
                and isinstance(entry.state, ObjectPlaceStateV1)
                and entry.state.object_identity_cid in exposed
            ):
                replacements[name] = replace(
                    entry, state=entry.state.invalidate(self.fragment)
                )
        return {**scope, **replacements}

    def _make_binop(self, left: "Node", op, right: "Node") -> "Node":
        """Construct a fresh BinOp node ``<left> <op> <right>`` as a shadow that
        borrows this node's span (so it still addresses this source site). Used
        by an augmented assignment to synthesize its ``x OP e`` rebind."""
        from .backend import Child, OpLeaf, materialize
        from .panic import backend_defect
        from .shadow import ShadowNode, _handle_of

        if not isinstance(left, Node) or not isinstance(right, Node):
            backend_defect(
                blame=self.fragment,
                owner="nodes.Node._make_binop",
                observed=(
                    "a synthesized binary operation received non-Node "
                    f"operands {type(left).__name__}, {type(right).__name__}"
                ),
                requested=(
                    "both binary-operation operands projected into constructed "
                    "tree Nodes before shadow enrollment"
                ),
                fix=(
                    "project BindingState through binding_state_read_node at "
                    "the read site; never put state-only testimony in Child"
                ),
            )

        slots = (
            ("left", Child(_handle_of(left))),
            ("op", OpLeaf(op)),
            ("right", Child(_handle_of(right))),
        )
        return materialize(
            self.unit, ShadowNode("BinOp", self.span, slots), self.reporter
        )

    def _make_call(self, func: "Node", args: tuple = ()) -> "Node":
        """Construct a fresh Call ``<func>(<args...>)`` as a shadow borrowing
        this node's span."""
        from .backend import Child, Children, materialize
        from .shadow import ShadowNode, _handle_of

        slots = (
            ("func", Child(_handle_of(func))),
            ("args", Children(tuple(_handle_of(a) for a in args))),
            ("keywords", Children(())),
        )
        return materialize(
            self.unit, ShadowNode("Call", self.span, slots), self.reporter
        )

    def _make_assign(self, target: "Node", value: "Node") -> "Node":
        """Construct ``<target> = <value>`` as a shadow borrowing this span.

        The one door for synthesizing a store: callers hand over a real target
        node and a real value node, and ``Assign`` supplies target totality.
        Nobody synthesizing a binding needs to learn target shapes.
        """
        from .backend import Child, Children, materialize
        from .shadow import ShadowNode, _handle_of

        slots = (
            ("targets", Children((_handle_of(target),))),
            ("value", Child(_handle_of(value))),
        )
        return materialize(
            self.unit, ShadowNode("Assign", self.span, slots), self.reporter
        )

    def _make_attribute(self, value: "Node", attr: str) -> "Node":
        """Construct ``<value>.<attr>`` as a shadow borrowing this node's span."""
        from .backend import Child, Leaf, materialize
        from .shadow import ShadowNode, _handle_of

        slots = (
            ("value", Child(_handle_of(value))),
            ("attr", Leaf(attr)),
        )
        return materialize(
            self.unit, ShadowNode("Attribute", self.span, slots), self.reporter
        )

    def _make_none_constant(self) -> "Node":
        """Synthesize ``None`` literal at this node's span."""
        from .backend import Leaf, materialize
        from .shadow import ShadowNode

        slots = (
            ("value", Leaf(None)),
            ("literal_kind", Leaf(None)),
        )
        return materialize(
            self.unit, ShadowNode("Constant", self.span, slots), self.reporter
        )

    def _effect_slot_id(self) -> str:
        """Content-addressed slot identity from this binding occurrence.

        The preimage pins the source, fragment, and occurrence span. Re-resolving
        the same source occurrence is byte-identical; equal text at another
        occurrence cannot collide. No process identity fallback exists.
        """
        try:
            lc = self.line_col_span()
        except SourceTreePanic as exc:
            raise SugarNotWritten(
                blame=exc.blame,
                owner=f"{type(self).__name__}._effect_slot_id",
                observed=f"{self.kind} has no stable source span for an effect slot",
                requested="a deterministic file:line:col extent for the binding site",
                fix="ensure the adapter anchors this node; never invent a process-local identity",
            ) from exc
        from sugar_lift_python_source.canonical import cid_of_json

        memento = self.fragment.seal()
        return cid_of_json(
            {
                "kind": "python-effect-slot-v1",
                "sourceCid": memento.source_cid,
                "fragmentCid": memento.cid,
                "span": {
                    "startLine": lc.start_line,
                    "startCol": lc.start_col,
                    "endLine": lc.end_line,
                    "endCol": lc.end_col,
                },
            }
        )

    def _make_effect_ref(self, slot_id: str) -> "Node":
        """Synthesize EffectRef(slot) — tree coordinate, not a floor object."""
        from .backend import Leaf, materialize
        from .shadow import ShadowNode

        slots = (("slot_id", Leaf(slot_id)),)
        return materialize(
            self.unit, ShadowNode("EffectRef", self.span, slots), self.reporter
        )

    def _make_observation_ref(self, slot_id: str, projection: str) -> "Node":
        """Synthesize ObservationRef(slot, projection) for with-as bindings."""
        from .backend import Leaf, materialize
        from .shadow import ShadowNode

        slots = (
            ("slot_id", Leaf(slot_id)),
            ("projection", Leaf(projection)),
        )
        return materialize(
            self.unit,
            ShadowNode("ObservationRef", self.span, slots),
            self.reporter,
        )

    def _substitute_body(self, statements: tuple, scope: BindingMap):
        new_items, changed, _net = self._substitute_body_tracked(statements, scope)
        return new_items, changed

    def _binding_entries(
        self, binding: BindingMap | None, scope: BindingMap
    ) -> BindingMap | None:
        if not binding:
            return binding
        builder = scope.get(_SUBSTITUTION_TRACE_BUILDER)
        if not isinstance(builder, SubstitutionTraceBuilderV1):
            return binding
        wrapped: BindingMap = {}
        for local_index, (name, state) in enumerate(binding.items()):
            if not isinstance(name, str):
                wrapped[name] = state
                continue
            if isinstance(state, BindingEntryV1):
                wrapped[name] = state
                continue
            site, path = self._binding_site_and_path(name, local_index)
            wrapped[name] = builder.mint_entry(
                binding_site=site,
                local_projection_path=path,
                state=state,
            )
        return wrapped

    def _binding_site_and_path(self, name: str, ordinal: int):
        """Locate a bound name's site and a **structural** local projection path.

        Paths are derived from grammar structure (``targets/i/tuple/j``,
        ``target/list/0``, …) — never from ``enumerate(walk())`` position.
        Walk order is a traversal policy (and default ``walk`` is unique-by-id);
        a coordinate must not depend on that policy. Orange audit of the
        DAG seen-set: path-position indices would under-count if a target
        DAG ever shared a Name across two edges.
        """
        candidates: list[tuple[object, tuple]] = []

        def collect(node: Node, path: tuple) -> None:
            if isinstance(node, Name):
                if node.id == name:
                    candidates.append((node.fragment, path))
                return
            if isinstance(node, Starred):
                collect(node.value, (*path, "starred"))
                return
            if isinstance(node, (Tuple_, List)):
                kind = "tuple" if isinstance(node, Tuple_) else "list"
                for index, child in enumerate(node.elts):
                    collect(child, (*path, kind, index))

        targets = getattr(self, "targets", None)
        if isinstance(targets, tuple):
            for target_index, target in enumerate(targets):
                collect(target, ("targets", target_index))
        target = getattr(self, "target", None)
        if isinstance(target, Node):
            collect(target, ("target",))
        if ordinal < len(candidates):
            return candidates[ordinal]
        return self.fragment, ("constructed-projection", ordinal)

    def _substitute_body_tracked(
        self, statements: tuple, scope: BindingMap, *, edge_states: list | None = None
    ):
        """Substitute a statement sequence, THREADING each statement's binding:
        an assignment binds its name to its substituted rhs for the rest of the
        block. This is the temporal that used to live in ``ctx.temporal`` -- now
        it is the tree rewriting itself, statement by statement, in single-
        assignment form (each binding a fresh entry; a rebind shadows the old
        for the tail). A walrus (``NamedExpr``) nested anywhere in the statement
        also leaks its binding to the rest of the block. Returns
        ``(new_statements, changed)``.

        ``edge_states`` is an out-parameter: pass a list and this loop appends
        ``(statement, state_in_effect_when_that_statement_begins)`` for every
        statement it threads. That is not a second mechanism and not a
        snapshot of the block -- it is the SAME threading, reported at each
        occurrence instead of only at the block's end. An exit that leaves the
        block *at* a statement (a raise, or an opaque step that may halt)
        carries exactly the state recorded for that statement, which is what
        exception routing must begin the selected handler from.

        Threading a module body for its readers
        (``SourceUnit.module_binding_states``), the scope carries the table
        ``_MODULE_STATEMENT_STATES``: the same state is recorded there for
        every statement, at any depth, by its source position."""
        from sugar_lift_py_tests.engine_log import reduction_span

        initial = dict(scope)
        scope = dict(scope)
        new_items = []
        changed = False
        for stmt in statements:
            pre_statement_scope = dict(scope)
            if edge_states is not None:
                edge_states.append((stmt, pre_statement_scope))
            record = scope.get(_MODULE_STATEMENT_STATES)
            if record is not None and record.open:
                record.at.setdefault(_source_position(stmt), []).append(
                    pre_statement_scope
                )
                _MODULE_THREADING.set(object())
            lc = stmt.line_col_span()
            with reduction_span(
                sugar="SubstituteStatement",
                role="temporal",
                site=f"{stmt.unit.filename}:{lc.start_line} {stmt.kind}",
            ):
                new_stmt = stmt.substitute(scope)
                live_loop_bindings = None
                if isinstance(new_stmt, (For, While)):
                    from .live_loop_construction import (
                        construct_live_loop_recurrence,
                    )

                    live_loop = construct_live_loop_recurrence(new_stmt, scope)
                    new_stmt = live_loop.statement
                    live_loop_bindings = live_loop.bindings
            if new_stmt is not stmt:
                changed = True
            # A statement may EXPAND into several: a `for` over a concrete
            # iterable dissolves into its unrolled body statements, spliced right
            # here so the block threads each one -- the loop's carried accumulator
            # is just ordinary block-threading over the unrolled sequence. The
            # expanded statements are already substituted; thread their bindings.
            produced = (
                new_stmt.statements if isinstance(new_stmt, _Splice) else (new_stmt,)
            )
            for produced_stmt in produced:
                pre_produced_scope = scope
                new_items.append(produced_stmt)
                binding = (
                    live_loop_bindings
                    if live_loop_bindings is not None
                    else produced_stmt.substitution_binding(scope)
                )
                if binding:
                    binding = produced_stmt._binding_entries(binding, scope)
                    binding = produced_stmt.refine_binding_entries(binding, scope)
                    post_binding = produced_stmt.post_binding_statement(binding)
                    if post_binding is not produced_stmt:
                        produced_stmt = post_binding
                        new_items[-1] = produced_stmt
                        changed = True
                    scope = {**scope, **binding}
                # walrus bindings nested in the statement's expressions leak out
                # to the enclosing block (their scope is the containing function).
                for node in produced_stmt.walk():
                    if node.kind == "NamedExpr":
                        if (
                            live_loop_bindings is not None
                            and node.target.kind == "Name"
                            and node.target.id in live_loop_bindings
                        ):
                            # A walrus in a live loop's body writes once per
                            # item, under that item's key: after the loop
                            # its name is the loop's carried value (the last
                            # item's write, latched as ``x += e``'s is), not
                            # a reference to a key no item bound unqualified.
                            continue
                        wb = node.substitution_binding(scope)
                        if wb:
                            wb = node._binding_entries(wb, scope)
                            scope = {**scope, **wb}
                scope = produced_stmt.post_binding_scope(scope)
                from .container_mutation import havoc_after

                scope = havoc_after(produced_stmt, pre_produced_scope, scope)
            if isinstance(new_stmt, _Splice) and new_stmt.bindings:
                projected = stmt._binding_entries(new_stmt.bindings, scope)
                scope = {**scope, **projected}
            trace = scope.get(_SUBSTITUTION_TRACE_BUILDER)
            if isinstance(trace, SubstitutionTraceBuilderV1):
                trace.record(stmt, pre_statement_scope, scope)
        net = {k: v for k, v in scope.items() if initial.get(k) is not v}
        return (tuple(new_items) if changed else statements), changed, net

    def _bound_names_in(self, target: "Node") -> set:
        """The names an assignment/for/with/lambda target binds. A Name binds;
        a Tuple/List/Starred target nests them. Walking for Names is
        conservative on attribute/subscript targets (over-masking a load
        under-substitutes rather than captures -- safe)."""
        return {n.id for n in target.walk() if n.kind == "Name"}

    def _substitute_generators(self, generators, scope):
        """Substitute comprehension generators, threading each target as a
        binding for its own ifs, the FOLLOWING generators and the result
        expression. Returns (new_generators, result_scope, changed) --
        result_scope has every generator target masked from ``scope``.

        A name a target binds is bound to a reference to the coordinate the
        comprehension binds it under for each member (temporal choice 1,
        #7661; ``ListComp._target_references``): a read in the element or a
        condition is an ``EvaluationRef``, never the name looked up by
        spelling. A target shape the comprehension has no sugar for binds no
        reference; its names stay masked."""
        bound = set()
        inner = scope
        carried = {}
        new_gens = []
        changed = False
        for index, gen in enumerate(generators):
            references = ListComp._target_references(self, index, gen)
            new_gen = gen._substitute_clause(inner, references)
            if new_gen is not gen:
                changed = True
            new_gens.append(new_gen)
            gen_bound = self._bound_names_in(gen.target)
            bound |= gen_bound
            # A later target rebinding a name ends the earlier reference.
            carried = {k: v for k, v in carried.items() if k not in gen_bound}
            carried.update(references)
            inner = {
                **{k: v for k, v in scope.items() if k not in bound},
                **carried,
            }
        # A name a target binds is this comprehension's own: never an
        # enclosing comprehension's cell (``_mask_closure_cells``).
        inner = _mask_closure_cells(inner, bound)
        return (tuple(new_gens) if changed else generators), inner, changed

    def _pattern_bound_names(self, pattern) -> set:
        """The names a match pattern captures -- MatchAs/MatchStar `name` and a
        MatchMapping `rest`. Captures are str fields, not Name references, so
        the patterns themselves substitute structurally; the MatchCase masks
        these for its guard and body."""
        names = set()
        for n in pattern.walk():
            if n.kind in ("MatchAs", "MatchStar"):
                nm = getattr(n, "name", None)
                if isinstance(nm, str):
                    names.add(nm)
            elif n.kind == "MatchMapping":
                r = getattr(n, "rest", None)
                if isinstance(r, str):
                    names.add(r)
        return names

    def sugar(self) -> object:
        """The roll-call DISCHARGE. A node registered on the roll when it was
        constructed (``__post_init__``); desugaring is how it answers. This
        template constructs the node's sugar (``_construct_sugar``, which each
        concrete class overrides) and records the PRESENT answer through the
        reporter the node already carries -- no parameter is threaded, because
        the node holds its own roll call. The ABSENT answer is recorded inside
        the abstract ``_construct_sugar`` before it throws. So every node either
        answers present here or is reported absent there: no node discharges
        silently.

        The answer is given ONCE PER CONSTRUCTION COORDINATE, not once per DAG
        path. Substitution shares node objects, so a bound value is one node
        reached by many paths; the roll asks each coordinate, and a coordinate
        that answered keeps its answer. Absent is memoized exactly as loudly as
        present: the panic is remembered and re-raised, so a gap stays a gap on
        every call and the reporter still fingers the site.
        """
        from sugar_lift_py_tests.engine_log import reduction_span
        from sugar_lift_py_tests.gap.panic import ConstructionPanic

        # THE construction coordinate -- the same (ref, reporter, control
        # context) the field row uses. Substitution shares node OBJECTS, so the
        # constructed graph is a DAG traversed as a tree; without this memo a
        # shared site re-answers the roll once per incoming path. T's ruling:
        # each distinct construction coordinate appears ONCE. Keyed by the
        # coordinate, never by the transient shell: shells are views, and a
        # rewritten shadow carries a DIFFERENT ref, so it can never collide
        # with the node it replaced. ``cache.key`` pins the ref, which is what
        # keeps a dead shadow's recycled address from serving stale work.
        #
        # One door (#7838): a row is served only where every ambient value its
        # construction read is still equal, and a reporter that did not hear
        # the row hears its testimony replayed (``construction_cache.serve``).
        cache, key, _ = self._coordinate()
        memo = cache.memo_key(key)
        row = serve(cache.sugar_rows, memo, self.reporter)
        if row is not None:
            if row.panic is not None:
                # A gap stays a gap, every time. Same panic, re-raised loudly.
                raise row.panic
            return row.value

        where = f"{self.unit.filename}"
        try:
            lc = self.line_col_span()
            where = f"{self.unit.filename}:{lc.start_line}:{lc.start_col}"
        except SourceTreePanic:
            pass
        with reduction_span(
            sugar=f"{self.kind}.sugar", role="construction", site=where
        ):
            computation = open_row()
            try:
                result = _as_evaluation_of(self, self._construct_sugar())
                # A constructed value whose testimony cannot be content-addressed
                # raises ConstructedValueTestimonyNotWritten here, so the
                # coordinate records the ABSENT answer (memoized panic, gap
                # already testified through the reporter) instead of a present
                # answer whose testimony silently failed to exist.
                testify(self.reporter, "present_construction", self, result)
            except (SourceTreePanic, ConstructionPanic) as panic:
                # The two sanctioned construction gaps. Remember the panic so
                # this coordinate keeps throwing it -- memoization must never
                # turn an absent answer into a present one.
                close_row(
                    cache.sugar_rows, memo, computation, self.reporter, panic=panic
                )
                raise
            except BaseException:
                # Anything else is a property of this traversal, never
                # remembered.
                abandon_row(computation)
                raise
            testify(self.reporter, "present_fact", self)
            close_row(cache.sugar_rows, memo, computation, self.reporter, value=result)
            return result

    def _require_construction_context(self, *, owner: str) -> object:
        """THE ONE DOOR to the construction context on a construction path.

        The enrollment in ``R_bare_construction_door`` is not a roster. It is
        THIS CALL SITE. A node kind that consults the context reaches here and
        is therefore covered; a kind that does not consult it (``Constant`` --
        a literal, no ``with`` to paint and no call frame to resolve) never
        reaches here and is therefore structurally silent. A kind added
        tomorrow that consults the context is covered the moment it reads,
        because reading IS the enrollment. Nothing to remember to update, so
        nothing to rot.

        Absence and lookup-failure never share a representation here. Every
        raw read this replaced had the shape::

            context = self.unit.construction_context
            if not isinstance(context, TreeConstructionContextV1):
                return None       # <- "no context" and "no entry" as ONE None

        A caller that gets ``None`` back from that cannot tell a tree opened
        through the bare door from a contexted tree with nothing at this
        coordinate. The first is an instrument defect and the second is a fact
        about the source. This door refuses the first LOUDLY and hands back a
        real context for the second, so the ``None`` that survives downstream
        means exactly one thing: looked up, genuinely absent.
        """
        context = self.unit.construction_context
        if context is None:
            from .panic import BareConstructionDoor

            raise BareConstructionDoor(
                owner=owner, blame=self.fragment, kind=type(self).__name__
            )
        return context

    def source_occurrence(self):
        """WHERE this node is. A pure function of the source, minted always.

        ``(unit.source_cid, line_col_span())`` and nothing else. It takes no
        construction context as input, so there is no state of the context under
        which the answer is unavailable -- a node occupies a span of a
        content-addressed source whether or not anything is enrolled at that
        coordinate, whether or not a table has a row for it, and whether or not
        the tree was opened through the production door.

        It was previously minted only under
        ``isinstance(context, TreeConstructionContextV1)``, at two sites that
        computed it identically, and downstream code then read
        ``coordinate is not None`` as "there is a context". One field carrying
        two answers::

            None == "this call occupies no span of any source"   (never true)
            None == "no context of the expected type was seated" (the real one)

        That is #7394's conflation inside the node whose job is to report
        occurrences, and ``_require_construction_context`` admits it: it refuses
        ``None`` and returns ``object``, so a context of another type is within
        the door's contract and silently produced a call with no occurrence.

        Minting it unconditionally is safe only because that door now bites. The
        condition was never about whether the occurrence was KNOWABLE -- it was
        the context witness wearing the occurrence's clothes. The witness is now
        the context itself.
        """
        from sugar_lift_py_tests.context_manager_resolution import (
            SourceFragmentCoordinateV1,
        )

        span = self.line_col_span()
        return SourceFragmentCoordinateV1(
            self.unit.source_cid,
            span.start_line,
            span.start_col,
            span.end_line,
            span.end_col,
        )

    def _authenticated_new_constructor_shape(self):
        """Source-owned ``__new__`` allocation shape, or None.

        Only ``ClassDef`` implements a real shape. Every other node answers
        None so callers never AttributeError when an allocation door is
        mis-routed to a non-class definition (L0a / construct-or-panic).
        """
        return None

    def _construct_sugar(self) -> object:
        """This node's sugar, constructed by the node itself.

        The tree recognizes and CONSTRUCTS; sugar carries the meaning
        (desugar, witnesses, universe coordinates). Every concrete class
        either overrides this and constructs its sugar, or inherits this
        throw. Two arms enforced by inheritance: no factory, no catalog,
        no registry — the absence of an override IS the loud MISSING.

        Overrides narrow the return type to their sugar class.
        """
        where = f"{self.unit.filename}"
        try:
            lc = self.line_col_span()
            where = f"{self.unit.filename}:{lc.start_line}:{lc.start_col}"
        except SourceTreePanic:
            pass  # an unpositioned kind still panics usefully, by file
        panic = SugarNotWritten(
            blame=self.fragment,
            owner=f"{type(self).__name__}.sugar",
            observed=f"{self.kind} at {where} has no sugar written",
            requested="a constructed sugar object",
            fix=(
                f"override sugar() on {type(self).__name__} and construct "
                "its sugar deliberately; never a fallback, never None"
            ),
        )
        # Testify the gap through the audit channel BEFORE throwing. An audit
        # walk's CollectingReporter records it (the frontier row); the report
        # never suppresses the throw. Every gap carries its own .fragment, so
        # the census -> wire memento is one hop: node.fragment.seal().
        testify(self.reporter, "report_gap", self, panic)
        raise panic

    def segment(self) -> str:
        return self.span.slice(self.unit.source)

    @property
    def fragment(self) -> "SourceFragment":
        """This node as a SourceFragment: its slice of the same oracle-pinned
        text the whole file answers. One accessor, one typed answer — never
        assembled by the caller from span + segment + cid."""
        from .fragment import SourceFragment

        return SourceFragment(unit=self.unit, span=self.span, node=self)

    def line_col_span(self) -> LineColSpan:
        return self.unit.line_table.project(self.span)

    # Stable source-location projections for consumers migrating off backend
    # AST objects.  These are computed from our span currency; they never read
    # or retain a backend-native node.
    @property
    def lineno(self) -> int:
        return self.line_col_span().start_line

    @property
    def col_offset(self) -> int:
        return self.line_col_span().start_col

    @property
    def end_lineno(self) -> int:
        return self.line_col_span().end_line

    @property
    def end_col_offset(self) -> int:
        return self.line_col_span().end_col

    def _child_edges(self) -> tuple[tuple[str, Optional[int], "Node"], ...]:
        """Resolved child edges once per construction-cache key.

        ``children()`` and ``walk()`` used to each re-getattr every ``_child_fields``
        entry.  The tree is immutable after materialize; re-deriving the edge list
        is pure recompute.  Memoize on the unit construction cache (same key as
        field data) so the second consumer of a node pays zero field getattr.
        """
        row = self._coordinate()[2]
        cached = row.get("__child_edges__")
        if cached is not None:
            return cached  # type: ignore[no-any-return]
        edges: list[tuple[str, Optional[int], Node]] = []
        for name in type(self)._child_fields:
            value = getattr(self, name)
            if value is None:
                continue
            if isinstance(value, Node):
                edges.append((name, None, value))
            else:
                for i, item in enumerate(value):
                    if item is not None:
                        edges.append((name, i, item))
        frozen = tuple(edges)
        row["__child_edges__"] = frozen
        return frozen

    def children(self) -> Iterator[tuple[str, Optional[int], "Node"]]:
        """Yield (field_name, index-or-None, child) in declared grammar order."""
        yield from self._child_edges()

    def walk(self, *, unique: bool = True) -> Iterator["Node"]:
        """Pre-order walk over the constructed graph. Iterative — never recursive.

        Expands each node via ``_child_edges()`` so a walk that follows a
        ``children()`` consumer (or a second walk) does not re-getattr fields.

        Default ``unique=True`` visits each node object **once** (DAG walk by
        identity). The graph is a DAG by design — e.g. successive
        ``self.attr = …`` stores share prior ``ReceiverFieldStoreState`` —
        so walking it as a tree is exponential in sharing depth and is the
        setup_method/nanops combinatorial blowup. Callers that need one
        yield per *path* (rare) pass ``unique=False``.

        Do **not** mint coordinates from ``enumerate(walk())`` — a walk index
        is a traversal policy, not a structural locus. Binding projection
        paths use grammar structure (``_binding_site_and_path``), which is
        independent of whether ``walk`` is unique-by-id or path-complete.
        """
        stack: list[Node] = [self]
        seen: set[int] | None = set() if unique else None
        while stack:
            node = stack.pop()
            if seen is not None:
                nid = id(node)
                if nid in seen:
                    continue
                seen.add(nid)
            yield node
            children = [child for _name, _index, child in node._child_edges()]
            stack.extend(reversed(children))

    # Fields holding a name this node binds (a str, or a tuple of str), and
    # fields holding the target expression(s) it binds through.  Declared per
    # binding class; every other node binds nothing.
    _bound_name_fields: ClassVar[Tuple[str, ...]] = ()
    _bound_target_fields: ClassVar[Tuple[str, ...]] = ()

    def names_bound_here(self) -> Tuple[str, ...]:
        """The names this node itself binds in its own scope (#7757 item 6).

        A binding site answers for itself: a definition, formal, ``except ...
        as``, ``match`` capture or type parameter its name; a ``global`` /
        ``nonlocal`` declaration the names it declares; an import alias the
        name it binds (``"*"`` for a star import, which may bind any name);
        an assignment, ``for``, ``with ... as``, walrus, comprehension or
        ``del`` the names its target binds.  Every other node binds nothing.
        """
        names: list[str] = []
        for field_name in type(self)._bound_name_fields:
            value = getattr(self, field_name)
            if isinstance(value, str):
                names.append(value)
            elif value:
                names.extend(value)
        for field_name in type(self)._bound_target_fields:
            value = getattr(self, field_name)
            for target in value if isinstance(value, tuple) else (value,):
                names.extend(_target_bound_names(target))
        return tuple(names)

    def names_bound_within(self) -> frozenset:
        """Every name this node or any node under it binds, in any scope."""
        return frozenset(
            name for node in self.walk() for name in node.names_bound_here()
        )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<{self.kind} [{self.span.start},{self.span.end})>"


@_abstract
class Statement(Node):
    def _evaluation_exit_path(self, scope) -> tuple:
        """The exit paths this evaluation is keyed under: the ones the scope
        substitutes for (``_exit_path_scope``), or, substituted again outside
        any duplicated clause, the ones its key was minted under."""
        path = tuple(scope.get(_EVALUATION_EXIT_PATH, ()))
        if path:
            return path
        minted = getattr(self, "evaluation_exit_path", None)
        return minted if isinstance(minted, tuple) else ()

    def _evaluation_key(self, scope) -> str:
        """The coordinate of this statement's one evaluation (temporal choice
        1, #7661): its source occurrence, the loop iterations it is
        substituted for, and the exit path whose copy of a duplicated clause
        it sits in (a ``finally`` on completion or on a halt).  The
        statement's sugar binds what it completed with under this key
        (``x += e``: the inplace result; ``a, b = f()``: each target's
        member, under its projection of the key); every later read
        substitution rewrites is an ``EvaluationRef`` to it.  A ``with ...
        as`` / ``try`` statement qualifies the effect slots its ``as`` names
        read with it (``_evaluation_slot``).  A re-substitution on the exit
        path its key was minted under keeps that key; a copy of it onto
        another exit path is another evaluation and gets its own.
        """
        from sugar_lift_python_source.canonical import cid_of_json
        from sugar_lift_py_tests.temporal.temporal_context import EVALUATION_PREFIX

        exit_path = self._evaluation_exit_path(scope)
        existing = getattr(self, "evaluation", None)
        if isinstance(existing, str):
            minted = getattr(self, "evaluation_exit_path", None)
            if exit_path == (minted if isinstance(minted, tuple) else ()):
                return existing
            return EVALUATION_PREFIX + cid_of_json(
                {
                    "kind": "python-statement-evaluation-exit-path-v1",
                    "evaluation": existing,
                    "exitPath": list(exit_path),
                }
            )
        from .shadow import occurrence_tags_of

        coordinate = {
            "kind": "python-statement-evaluation-v1",
            "statementFragmentCid": self.fragment.seal().cid,
            "occurrence": [
                *scope.get(_EVALUATION_OCCURRENCE, ()),
                *occurrence_tags_of(self),
            ],
        }
        if exit_path:
            coordinate["exitPath"] = list(exit_path)
        return EVALUATION_PREFIX + cid_of_json(coordinate)

    def _duplicated_evaluation_key(self, scope) -> "Optional[str]":
        """This statement's evaluation key when it is one of several
        evaluations of its source -- a loop iteration's copy or a duplicated
        clause's exit-path copy -- or was keyed as one already; else None.
        A statement evaluated once keeps the source occurrence's slots."""
        from .shadow import occurrence_tags_of

        if not (
            isinstance(getattr(self, "evaluation", None), str)
            or scope.get(_EVALUATION_OCCURRENCE)
            or scope.get(_EVALUATION_EXIT_PATH)
            or occurrence_tags_of(self)
        ):
            return None
        return self._evaluation_key(scope)

    def _keyed_evaluation(self, rewritten: "Node", scope) -> "Node":
        """``rewritten`` (this statement substituted) carrying its evaluation
        key, when it is one of several evaluations of its source
        (``_duplicated_evaluation_key``); else ``rewritten`` unchanged."""
        evaluation = self._duplicated_evaluation_key(scope)
        if evaluation is None:
            return rewritten
        from .shadow import rewrite_with_leaves

        return rewrite_with_leaves(
            rewritten,
            {
                "evaluation": evaluation,
                "evaluation_exit_path": self._evaluation_exit_path(scope),
            },
        )

    def _evaluation_slot(self, slot: str) -> str:
        """``slot`` (a source occurrence's effect slot) for the evaluation
        this statement is keyed as: each evaluation of a duplicated statement
        observes its own effect, so the name it binds reads that evaluation
        and never a sibling's.  Unchanged for a statement evaluated once."""
        evaluation = getattr(self, "evaluation", None)
        if not isinstance(evaluation, str):
            return slot
        from sugar_lift_python_source.canonical import cid_of_json

        return cid_of_json(
            {
                "kind": "python-effect-slot-evaluation-v1",
                "slot": slot,
                "evaluation": evaluation,
            }
        )


@_abstract
class Expression(Node):
    def dotted_expr_name(self) -> Optional[str]:
        """The dotted PLACE this expression names, or ``None`` if it names none.

        `x` -> "x", `a.b.c` -> "a.b.c", and everything else (a call, a subscript,
        a literal, an operator) -> ``None``, because it is not a place a later
        equality can refine a binding for. Structural only: it reads the tree it
        is on and consults no table of names.

        Only ``Name`` and ``Attribute`` override; the base answers ``None`` so
        every expression can be ASKED. `EqualityOpSugar` used to reach the same
        answer through a `site.compare_left()` method no real node implemented
        (only a test double did), which is why every real `==` refinement site
        raised `AttributeError: 'SourceFragment' has no attribute
        'compare_left'`.
        """
        return None


@_abstract
class Pattern(Node):
    """A structural pattern inside ``match``."""


@_abstract
class TypeParam(Node):
    """A PEP 695 type parameter."""

    _bound_name_fields = ("name",)


# --------------------------------------------------------------------------
# Helper nodes (grammar constituents that are not statements or expressions)
# --------------------------------------------------------------------------


class Param(Node):
    """One formal parameter. ``param_kind`` is one of: positional_only,
    positional_or_keyword, vararg, keyword_only, kwarg."""

    name: str
    annotation: Optional[Expression]
    default: Optional[Expression]
    param_kind: str
    _child_fields = ("annotation", "default")
    _bound_name_fields = ("name",)

    @property
    def arg(self) -> str:
        """The formal's identifier, projected from the typed binding site."""
        return self.name

    def substitute(self, scope):
        """A parameter's NAME is a binding site (a str, not a reference), so it
        is never captured; its annotation and default are ordinary expressions
        in the enclosing scope. So this just recurses into them -- the masking
        of the name itself is the enclosing FunctionDef's job, for the body."""
        return self._substitute_children(scope)

    def _construct_sugar(self):
        """A formal stands as its symbolic universe variable. A default is
        folded in through the same door the source-visible call frame uses
        (``default.sugar()``), so the two can never disagree; an annotation is
        a type witness, not a value, and never refuses the formal."""
        from sugar_lift_py_tests.sugar.param_sugar import ParamSugar

        return ParamSugar(
            name=self.name,
            site=self.fragment,
            default=self.default.sugar() if self.default is not None else None,
        )


@dataclass(frozen=True)
class ArgumentsProjection:
    """Read-only signature projection derived from typed ``Param`` nodes."""

    posonlyargs: Tuple[Param, ...]
    args: Tuple[Param, ...]
    vararg: Optional[Param]
    kwonlyargs: Tuple[Param, ...]
    kw_defaults: Tuple[Optional[Expression], ...]
    kwarg: Optional[Param]
    defaults: Tuple[Expression, ...]


def _arguments_projection(params: Tuple[Param, ...]) -> ArgumentsProjection:
    positional_only = tuple(p for p in params if p.param_kind == "positional_only")
    positional = tuple(p for p in params if p.param_kind == "positional_or_keyword")
    vararg = next((p for p in params if p.param_kind == "vararg"), None)
    keyword_only = tuple(p for p in params if p.param_kind == "keyword_only")
    kwarg = next((p for p in params if p.param_kind == "kwarg"), None)
    positional_defaults = tuple(
        p.default for p in (*positional_only, *positional) if p.default is not None
    )
    return ArgumentsProjection(
        posonlyargs=positional_only,
        args=positional,
        vararg=vararg,
        kwonlyargs=keyword_only,
        kw_defaults=tuple(p.default for p in keyword_only),
        kwarg=kwarg,
        defaults=positional_defaults,
    )


def _target_bound_names(target) -> Tuple[str, ...]:
    """The names a binding target binds: a Name its id, a Tuple/List/Starred
    its elements' names.  An attribute or subscript target mutates an object
    and binds no name."""
    if isinstance(target, Name):
        return (target.id,)
    if isinstance(target, (Tuple_, List)):
        return tuple(
            name for element in target.elts for name in _target_bound_names(element)
        )
    if isinstance(target, Starred):
        return _target_bound_names(target.value)
    return ()


class Keyword(Node):
    """A keyword argument at a call site. ``arg is None`` means ``**expr``
    (double-star spread) — a structural absence, not a gap."""

    arg: Optional[str]
    value: Expression
    _child_fields = ("value",)

    def substitute(self, scope):
        """Binds nothing: recurse into children and reassemble."""
        return self._substitute_children(scope)


class DictItem(Node):
    """One ``key: value`` entry of a Dict display. ``key is None`` means
    ``**expr`` (double-star spread) — a structural absence, not a gap."""

    key: Optional[Expression]
    value: Expression
    _child_fields = ("key", "value")

    def substitute(self, scope):
        """Binds nothing: recurse into children and reassemble."""
        return self._substitute_children(scope)


class Comprehension(Node):
    """One ``for target in iter [if ...]*`` clause."""

    target: Expression
    iter: Expression
    ifs: Tuple[Expression, ...]
    is_async: bool
    _child_fields = ("target", "iter", "ifs")
    _bound_target_fields = ("target",)

    def substitute(self, scope):
        """One `for <target> in <iter> [if ...]` clause: iter in the given
        scope; the target binds for its own ifs. Threading across clauses is the
        enclosing comprehension's job (_substitute_generators)."""
        return self._substitute_clause(scope, {})

    def _substitute_clause(self, scope, references):
        """This clause with ``iter`` substituted in ``scope`` and its ifs in
        ``scope`` with the target's names masked, then bound to
        ``references``: the enclosing comprehension's reference for each name
        this target binds (``ListComp._target_references``)."""
        from .shadow import rewrite

        new_iter, di = self._substitute_field(self.iter, scope)
        bound = set(self.unit.require_target_pattern_for_target(self.target).names)
        ifs_scope = (
            {k: v for k, v in scope.items() if k not in bound} if bound else scope
        )
        if references:
            ifs_scope = {**ifs_scope, **references}
        new_ifs, df = self._substitute_field(self.ifs, ifs_scope)
        changed = {}
        if di:
            changed["iter"] = new_iter
        if df:
            changed["ifs"] = new_ifs
        return self if not changed else rewrite(self, **changed)


class ExceptHandler(Node):
    _bound_name_fields = ("name",)
    type_: Optional[Expression]
    name: Optional[str]
    body: Tuple[Statement, ...]
    _child_fields = ("type_", "body")

    @property
    def type(self) -> Optional[Expression]:
        return self.type_

    def _effect_slot_id(self) -> str:
        """The source occurrence's slot, for the evaluation of the ``try``
        this handler was keyed under (``Try.substitute``): the ``as`` name's
        ``EffectRef``, the arm's routing and a bare re-raise in its body all
        read this one slot, one per evaluation (temporal choice 1, #7661)."""
        return Statement._evaluation_slot(self, super()._effect_slot_id())

    def substitute(self, scope):
        """except <type> as <name>: rewrite name → EffectRef(slot) in the body.

        Syntax creates the coordinate; routing authenticates it. The name is
        NOT exported after the handler (Python clears the exception target).
        Never E() — EffectRef is not an exception object.
        """
        from .shadow import rewrite

        changed = {}
        new_type, d = self._substitute_field(self.type_, scope)
        if d:
            changed["type_"] = new_type
        if self.name:
            slot_id = self._effect_slot_id()
            ref = self._make_effect_ref(slot_id)
            body_scope = {**scope, self.name: ref}
        else:
            body_scope = scope
        new_body, d = self._substitute_body(self.body, body_scope)
        if d:
            changed["body"] = new_body
        return self if not changed else rewrite(self, **changed)


class WithItem(Node):
    _bound_target_fields = ("optional_vars",)
    context_expr: Expression
    optional_vars: Optional[Expression]
    _child_fields = ("context_expr", "optional_vars")

    def substitute(self, scope):
        """Substitute the manager while retaining its enrolled source locus.

        A formal/temporal projection borrows the definition's span.  Contract
        resolution is keyed by this With occurrence, so that rewritten span
        must never replace the original manager use-site coordinate.
        """
        from .backend import Leaf, materialize
        from .shadow import ShadowNode, rewrite

        new_ctx, d = self._substitute_field(self.context_expr, scope)
        rewritten = self if not d else rewrite(self, context_expr=new_ctx)
        if hasattr(self, "manager_use_site_start_line"):
            return rewritten
        span = self.context_expr.line_col_span()
        desc = rewritten.ref.describe()
        return materialize(
            self.unit,
            ShadowNode(
                desc.kind,
                desc.raw_span or self.span,
                (
                    *desc.slots,
                    ("manager_use_site_start_line", Leaf(span.start_line)),
                    ("manager_use_site_start_col", Leaf(span.start_col)),
                    ("manager_use_site_end_line", Leaf(span.end_line)),
                    ("manager_use_site_end_col", Leaf(span.end_col)),
                ),
            ),
            self.reporter,
        )

    def _with_selected_manager_call(self, call):
        """This item over one arm's manager call, used at that call's own site.

        The arm's contract was derived at the call's coordinate (the call is
        where Python constructs the manager), not at the ``with ctx`` name.
        """
        from .backend import Leaf, materialize
        from .shadow import ShadowNode, rewrite

        span = (
            call.base if call.kind == "OpaqueObjectStateV1" else call
        ).line_col_span()
        desc = rewrite(self, context_expr=call).ref.describe()
        owner_start_line, owner_start_col, owner_end_line, owner_end_col = (
            self._manager_use_site_span()
        )
        use_site = {
            "manager_use_site_start_line": span.start_line,
            "manager_use_site_start_col": span.start_col,
            "manager_use_site_end_line": span.end_line,
            "manager_use_site_end_col": span.end_col,
            # The With item this arm belongs to: its one selected ref.
            "selected_arm_of_start_line": owner_start_line,
            "selected_arm_of_start_col": owner_start_col,
            "selected_arm_of_end_line": owner_end_line,
            "selected_arm_of_end_col": owner_end_col,
        }
        return materialize(
            self.unit,
            ShadowNode(
                desc.kind,
                desc.raw_span or self.span,
                (
                    *(slot for slot in desc.slots if slot[0] not in use_site),
                    *((name, Leaf(value)) for name, value in use_site.items()),
                ),
            ),
            self.reporter,
        )

    def _manager_use_site_span(self):
        """The immutable source occurrence used by preconstruction enrollment."""
        if hasattr(self, "manager_use_site_start_line"):
            return (
                self.manager_use_site_start_line,
                self.manager_use_site_start_col,
                self.manager_use_site_end_line,
                self.manager_use_site_end_col,
            )
        span = self.context_expr.line_col_span()
        return span.start_line, span.start_col, span.end_line, span.end_col

    def _manager_slot_id(self) -> str:
        """Once-eval manager identity for this with-item, one per evaluation.

        A ``with`` evaluated more than once (a loop iteration's copy, a
        duplicated ``finally``'s exit-path copy) keys its item with its own
        evaluation (``With.substitute``), so the manager, its enter result
        (``as x``, the lowered ``as (a, b)`` store) and its observation are
        that evaluation's slots, never a sibling copy's (temporal choice 1,
        #7661).  An item evaluated once keeps the source occurrence's slot.
        """
        return Statement._evaluation_slot(self, self._effect_slot_id())

    def _make_manager_ref(self) -> "Node":
        """``ManagerRef(M)`` — single manager coordinate for enter and exit."""
        from .backend import Leaf, materialize
        from .shadow import ShadowNode

        slots = (("slot_id", Leaf(self._manager_slot_id())),)
        return materialize(
            self.unit, ShadowNode("ManagerRef", self.span, slots), self.reporter
        )

    def _make_enter_call(self) -> "Node":
        """Tree coordinate ``ManagerRef(M).__enter__()`` — not ``context_expr`` twice."""
        enter_attr = self._make_attribute(self._make_manager_ref(), "__enter__")
        return self._make_call(enter_attr, ())

    def _source_exit_face_id(self) -> str:
        """The source occurrence's exit face: the one the manager summary
        derivation states the derived protocol's ``__exit__`` over
        (``manager_summary_derivation._direct_with_call_uses``), once per
        use site, before any evaluation exists."""
        return f"{self._effect_slot_id()}#exit_face"

    def _exit_face_id(self) -> str:
        """Exit-face coordinate X for parametric exit-arg refs, one per
        evaluation.

        Keyed off the item's evaluation the way ``_manager_slot_id`` is: a
        ``with`` evaluated more than once (a loop iteration's copy, a
        duplicated ``finally``'s exit-path copy) exits over its own face,
        never a sibling copy's.  The protocol that describes ``__exit__`` is
        re-keyed onto this face where the sugar is built
        (``With._protocol_at_exit_face``), so the sugar's face facts and the
        protocol's exit coordinates name the same face.  An item evaluated
        once keeps the source occurrence's face."""
        return Statement._evaluation_slot(self, self._source_exit_face_id())

    def _make_exit_type_ref(self) -> "Node":
        from .backend import Leaf, materialize
        from .shadow import ShadowNode

        slots = (("face_id", Leaf(self._exit_face_id())),)
        return materialize(
            self.unit, ShadowNode("ExitTypeRef", self.span, slots), self.reporter
        )

    def _make_exit_value_ref(self) -> "Node":
        from .backend import Leaf, materialize
        from .shadow import ShadowNode

        slots = (("face_id", Leaf(self._exit_face_id())),)
        return materialize(
            self.unit, ShadowNode("ExitValueRef", self.span, slots), self.reporter
        )

    def _make_exit_traceback_ref(self) -> "Node":
        from .backend import Leaf, materialize
        from .shadow import ShadowNode

        slots = (("face_id", Leaf(self._exit_face_id())),)
        return materialize(
            self.unit,
            ShadowNode("ExitTracebackRef", self.span, slots),
            self.reporter,
        )

    def _make_exit_call(self, typ: "Node", val: "Node", tb: "Node") -> "Node":
        """Tree coordinate ``ManagerRef(M).__exit__(typ, val, tb)``."""
        exit_attr = self._make_attribute(self._make_manager_ref(), "__exit__")
        return self._make_call(exit_attr, (typ, val, tb))

    def _make_parametric_exit_call(self) -> "Node":
        """One exit call: ``M.__exit__(ExitTypeRef(X), ExitValueRef(X), ExitTracebackRef(X))``.

        Face-specific values are ExitFaceBinding testimony under guards —
        not alternate MethodCall sugars built at desugar time.
        """
        return self._make_exit_call(
            self._make_exit_type_ref(),
            self._make_exit_value_ref(),
            self._make_exit_traceback_ref(),
        )


class ImportAlias(Node):
    name: str
    asname: Optional[str]

    def names_bound_here(self) -> Tuple[str, ...]:
        """``import a.b`` binds ``a``; ``as n`` binds ``n``; ``*`` may bind
        any name, so it answers ``"*"``."""
        if self.name == "*":
            return ("*",)
        return (self.asname or self.name.split(".", 1)[0],)

    def substitute(self, scope):
        """Binds nothing, no hole: substitutes to itself."""
        return self


class MatchCase(Node):
    pattern: Pattern
    guard: Optional[Expression]
    body: Tuple[Statement, ...]
    _child_fields = ("pattern", "guard", "body")

    def substitute(self, scope, extra_bindings=None):
        """`case <pattern> [if <guard>]: <body>` -- the pattern captures bind for
        the guard and body. Pattern value-exprs evaluate in the enclosing scope;
        guard and body are masked by the captures, then any ``extra_bindings``
        (a capture bound to the match SUBJECT, threaded by ``Match.substitute``)
        are re-applied so a `case x:` body sees x = subject, not a free name."""
        from .shadow import rewrite

        bound = self._pattern_bound_names(self.pattern)
        inner = {k: v for k, v in scope.items() if k not in bound} if bound else scope
        if extra_bindings:
            inner = {**inner, **extra_bindings}
        changed = {}
        new_pat, d = self._substitute_field(self.pattern, scope)
        if d:
            changed["pattern"] = new_pat
        new_guard, d = self._substitute_field(self.guard, inner)
        if d:
            changed["guard"] = new_guard
        new_body, d = self._substitute_body(self.body, inner)
        if d:
            changed["body"] = new_body
        return self if not changed else rewrite(self, **changed)


# --------------------------------------------------------------------------
# Module and statements
# --------------------------------------------------------------------------


class Module(Node):
    body: Tuple[Statement, ...]
    _child_fields = ("body",)

    def substitute(self, scope):
        """The module is the top block: it threads its statements (a module-
        level assignment binds its name for the rest) but masks nothing -- there
        is no enclosing scope above it."""
        from .shadow import rewrite

        new_body, changed = self._substitute_body(self.body, scope)
        if not changed:
            return self
        return rewrite(self, body=new_body)

    def _construct_sugar(self):
        """Construct the module block after its one temporal scope fold.

        ``Module`` owns only source order and module-level binding scope.  Each
        statement owns its own meaning and constructs through ``Statement.sugar``
        exactly once.  A child construction gap therefore propagates with the
        child's owner; the module neither skips it nor invents completion.
        """
        from sugar_lift_py_tests.engine_log import reduction_span
        from sugar_lift_py_tests.sugar.module_block_sugar import ModuleBlockSugar

        lc = self.line_col_span()
        where = f"{self.unit.filename}:{lc.start_line} Module"
        with reduction_span(sugar="ModuleBlock", role="construction", site=where):
            with reduction_span(sugar="Substitute", role="temporal", site=where):
                substituted = self.substitute({})
            with reduction_span(sugar="Construct", role="construction", site=where):
                return ModuleBlockSugar(
                    statements=tuple(
                        statement.sugar() for statement in substituted.body
                    ),
                    site=self.fragment,
                )



def generator_for_module_cid(statement):
    """Authenticate module identity separately from content/span CID."""
    from sugar_lift_python_source.canonical import cid_of_json

    return cid_of_json(
        {
            "kind": "generator-for-module",
            "schemaVersion": "1",
            "filename": statement.unit.filename,
            "sourceCid": statement.unit.source_cid,
        }
    )


def generator_for_target_coordinates(statement):
    """Mint one authenticated coordinate per lexical target leaf."""
    from .binding_state import mint_binding_coordinate_v1

    scope_owner_cid = generator_for_module_cid(statement)

    def collect(target, path):
        if isinstance(target, Name):
            return (
                mint_binding_coordinate_v1(
                    scope_owner_cid=scope_owner_cid,
                    binding_site=target.fragment,
                    projection_path=("target", *path),
                ),
            )
        if isinstance(target, (Tuple_, List)):
            coordinates = []
            for index, child in enumerate(target.elts):
                nested = collect(child, (*path, index))
                if nested is None:
                    return None
                coordinates.extend(nested)
            return tuple(coordinates) if coordinates else None
        return None

    return collect(statement.target, ())


class FunctionDef(Statement):
    _bound_name_fields = ("name",)
    name: str
    params: Tuple[Param, ...]
    body: Tuple[Statement, ...]
    decorators: Tuple[Expression, ...]
    returns: Optional[Expression]
    type_params: Tuple[TypeParam, ...]
    _child_fields = ("decorators", "type_params", "params", "returns", "body")

    def substitution_binding(self, scope):
        return _local_definition_binding(self, scope)

    @property
    def args(self):
        return _arguments_projection(self.params)

    def source_visible_call_frame(self):
        """Construct this callable body through the ordinary node/Sugar door.

        RECURSION IS A SEAT, NOT AN UNFOLDING. A same-module callee's frame is
        constructed inline at its call; along a recursive call graph
        (``ensure_key_mapped`` <-> ``_ensure_key_mapped_multiindex`` in pandas
        core/sorting.py) that re-enters this door for a definition whose frame
        is still under construction and unfolds until RecursionError (6 files
        on the 2026-09-05 board). The fixpoint reference is the definition
        itself: re-entry raises ``SourceCallFrameCycle``, and the call that
        asked carries the definition with a ``call-graph-cycle`` seat -- never
        a second body.
        """
        definition_cid = self.fragment.seal().cid
        if _frame_is_under_construction(definition_cid):
            raise SourceCallFrameCycle(self)

        # ONE FRAME PER CONSTRUCTION COORDINATE, not one per call site.  The
        # frame is a function of this definition's coordinate -- the same key
        # ``sugar()`` answers the roll by -- and of which frames were open
        # above it, because an open frame turns a call into a recursion seat.
        # Without this row every call site rebuilt its callee's whole frame,
        # and every call inside that frame rebuilt its callee's: the cost of
        # one call was the size of the call graph below it, paid once per
        # path (pandas/_testing/asserters.py: 92% of an 87 s run, unfinished).
        #
        # A remembered frame answers only a traversal that would have asked
        # the same questions and heard the same answers: every definition the
        # first construction asked about is open or closed now as it was
        # then, and so is every other ambient value it read -- the one rule
        # every memo row keeps (``construction_cache.serve``).  Any other
        # traversal constructs its own variant.  So a recursion seat never
        # leaks into a traversal where that definition is not open, and a
        # full body never replaces a seat.
        from sugar_lift_py_tests.gap.panic import ConstructionPanic

        cache, key, _ = self._coordinate()
        memo = cache.memo_key(key)
        row = serve(cache.call_frames, memo, self.reporter)
        if row is not None:
            if row.panic is not None:
                # A gap stays a gap, every time. Same panic, re-raised loudly.
                raise row.panic
            frame = row.value
            if frame.owner is not self:
                # Shells are views; the frame is owned by the shell that asks.
                frame = replace(frame, owner=self)
            return frame

        computation = open_row()
        # Opening its own frame is this construction's act, so whether it is
        # open is never ambient to it: its own recursion is decided inside,
        # never by the traversal above (the door refused above if it were
        # open).
        _FRAMES_UNDER_CONSTRUCTION.add(definition_cid)
        try:
            try:
                frame = FunctionDef._source_visible_call_frame_unguarded(self)
            finally:
                _FRAMES_UNDER_CONSTRUCTION.discard(definition_cid)
        except (SourceTreePanic, ConstructionPanic) as panic:
            # The two sanctioned construction gaps, remembered as loudly as a
            # frame.
            close_row(cache.call_frames, memo, computation, self.reporter, panic=panic)
            raise
        except BaseException:
            # Anything else (a cycle passing through, an interrupt) is a
            # property of this traversal and is never remembered.
            abandon_row(computation)
            raise
        if frame is None:
            # No frame is not an answer to remember.
            abandon_row(computation)
            return frame
        close_row(cache.call_frames, memo, computation, self.reporter, value=frame)
        return frame

    def bound_classmethod_call_frame(self, class_def: "ClassDef"):
        """This ``@classmethod`` as ``Class.method``: ``cls`` already bound.

        ``classmethod.__get__(None, Class)`` (Objects/funcobject.c
        ``cm_descr_get``) returns a method whose ``__self__`` is ``Class``;
        calling it supplies ``Class`` as the first formal.  The frame drops
        that formal and the body reads ``Class`` by its module-level name
        wherever it read ``cls``; the caller binds the remaining formals,
        so a caller that also spells ``cls=`` is an unconsumed keyword, as
        CPython's "multiple values" TypeError.  The caller has checked that
        the module binds ``Class`` once, by this class statement.
        """
        from sugar_lift_py_tests.source_call_frame import SourceCallBindingGap

        if (
            self.unit.lexical_class_owner_for(self) is not class_def
            or class_def._method_descriptor_kind(self) != "classmethod"
            or not self.params
            or self.params[0].param_kind
            not in {"positional_only", "positional_or_keyword"}
            or self.params[0].default is not None
        ):
            raise SourceCallBindingGap("bound classmethod frame needs its class owner")
        definition_cid = self.fragment.seal().cid
        if _frame_is_under_construction(definition_cid):
            raise SourceCallFrameCycle(self)
        _FRAMES_UNDER_CONSTRUCTION.add(definition_cid)
        try:
            return FunctionDef._source_visible_call_frame_unguarded(
                self, bound_receiver=class_def
            )
        finally:
            _FRAMES_UNDER_CONSTRUCTION.discard(definition_cid)

    def _source_visible_call_frame_unguarded(self, bound_receiver=None):
        """Construct this callable body through the ordinary node/Sugar door.

        Parameterized frames require the shared BindingCoordinateV1 owner.  The
        coordinate-free zero-parameter arm can already carry its exact body;
        it is built from the same substituted statement nodes as `_construct_sugar`.
        """
        from sugar_lift_py_tests.context_manager_resolution import (
            SourceFragmentCoordinateV1,
        )
        from sugar_lift_py_tests.source_call_frame import SourceVisibleCallFrameV1
        from sugar_source_tree.binding_provenance import BindingCoordinateV1

        span = self.line_col_span()
        site = SourceFragmentCoordinateV1(
            self.unit.source_cid,
            span.start_line,
            span.start_col,
            span.end_line,
            span.end_col,
        )
        params = self.params if bound_receiver is None else self.params[1:]
        offset = len(self.params) - len(params)
        parameters = tuple(param.name for param in params)
        owner_cid = self.fragment.seal().cid
        coordinates = tuple(
            BindingCoordinateV1.mint(
                owner_cid, param.fragment, ("formal", index + offset)
            )
            for index, param in enumerate(params)
        )
        captured_names, captured_coordinates = self._captured_bindings()
        formal_scope = {
            **self._captured_scope(),
            **{
                param.name: self._make_coordinate_ref(param, coordinate)
                for param, coordinate in zip(params, coordinates, strict=True)
            },
        }
        if bound_receiver is not None:
            formal_scope[self.params[0].name] = For._make_name(
                self, bound_receiver.name
            )
        from sugar_lift_py_tests.sugar.source_visible_function_body_sugar import (
            SourceVisibleFunctionBodySugar,
        )

        lexical_rows = self.unit.constructed_module.lexical_call_rows
        filtered_body = tuple(
            statement
            for statement in self.body
            if all(statement is not row.definition_occurrence for row in lexical_rows)
        )
        substituted_body, _ = self._substitute_body(filtered_body, formal_scope)
        generator_steps = self._source_visible_generator_steps_from(substituted_body)
        body = SourceVisibleFunctionBodySugar(
            (
                ()
                if generator_steps is not None
                else tuple(
                    self._sugar_body_statement(statement)
                    for statement in substituted_body
                )
            ),
            self.fragment,
        )
        return SourceVisibleCallFrameV1(
            source_identity_cid=self.unit.source_cid,
            definition_site=site,
            definition_fragment_cid=self.fragment.seal().cid,
            parameters=parameters,
            formal_coordinates=coordinates,
            formal_declaration_sites=tuple(
                param.fragment.seal().to_dict() for param in params
            ),
            formal_projection_paths=tuple(
                ("formal", index + offset) for index, _ in enumerate(params)
            ),
            parameter_kinds=tuple(param.param_kind for param in params),
            default_sugars=tuple(
                param.default.sugar() if param.default is not None else None
                for param in params
            ),
            default_nodes=tuple(param.default for param in params),
            default_fragments=tuple(
                param.default.fragment if param.default is not None else None
                for param in params
            ),
            default_fragment_cids=tuple(
                param.default.fragment.seal().cid if param.default is not None else None
                for param in params
            ),
            body=body,
            owner=self,
            bound_receiver_class=bound_receiver,
            generator_steps=generator_steps,
            generator_step_fragment_cids=(
                ()
                if generator_steps is None
                else tuple(
                    statement.fragment.seal().cid for statement in substituted_body
                )
            ),
            captured_names=captured_names,
            captured_coordinates=captured_coordinates,
        )

    def _captured_bindings(self) -> tuple:
        """``(names, coordinates)``: each enclosing function's local this body
        reads (CPython's free variables, ``nonlocal`` ones excepted), and the
        coordinate the frame reads it through.

        Python reads such a name from the enclosing frame's cell when the
        function is called: the binding the enclosing scope holds at the
        call, never the one it held where the ``def`` stood.  So the body
        reads it as a captured coordinate, like a formal, and the call binds
        it: a call in the enclosing body carries the binding its own scope
        holds for the name (``Call._closure_cells``) and binds its value under
        the coordinate (``CallSiteSugar._captured_values``).  The name itself
        is never read.  ``__class__`` (the cell a class body gives a method
        that uses ``super()``) is the class's, not an enclosing function's
        local, and is not captured here."""
        table = self.unit.function_symtable(self.name, self.line_col_span().start_line)
        names = tuple(
            sorted(
                symbol.get_name()
                for symbol in table.get_symbols()
                if symbol.is_free()
                and not symbol.is_nonlocal()
                and symbol.get_name() != "__class__"
            )
        )
        if not names:
            return (), ()
        from sugar_source_tree.binding_provenance import BindingCoordinateV1

        owner_cid = self.fragment.seal().cid
        return names, tuple(
            BindingCoordinateV1.mint(owner_cid, self.fragment, ("captured", name))
            for name in names
        )

    def _captured_scope(self) -> dict:
        """Each captured name (``_captured_bindings``) to its coordinate ref."""
        names, coordinates = self._captured_bindings()
        return {
            name: self._make_coordinate_ref(self, coordinate)
            for name, coordinate in zip(names, coordinates, strict=True)
        }

    def lacks_captured_binding_testimony(self, covered=frozenset()) -> bool:
        """Whether CPython classifies a closure binding we cannot seat: a
        ``nonlocal`` name (the body writes the enclosing cell), or a free
        name the call does not bind (``covered``: the captured names a call
        in the enclosing body carries, ``Call._closure_cells``)."""
        table = self.unit.function_symtable(self.name, self.line_col_span().start_line)
        return any(
            symbol.is_nonlocal()
            or (symbol.is_free() and symbol.get_name() not in covered)
            for symbol in table.get_symbols()
        )

    def _source_visible_body(self, scope):
        from sugar_lift_py_tests.sugar.source_visible_function_body_sugar import (
            SourceVisibleFunctionBodySugar,
        )

        scope = {**self._captured_scope(), **scope}
        substituted_body, _ = self._substitute_body(self.body, scope)
        if self._source_visible_generator_steps_from(substituted_body) is not None:
            return SourceVisibleFunctionBodySugar((), self.fragment)
        return SourceVisibleFunctionBodySugar(
            tuple(
                self._sugar_body_statement(statement) for statement in substituted_body
            ),
            self.fragment,
        )

    def _source_visible_generator_steps(self, scope):
        substituted_body, _ = self._substitute_body(self.body, scope)
        return self._source_visible_generator_steps_from(substituted_body)

    def _source_visible_generator_steps_from(self, body):
        if not self._owns_yield(body):
            return None
        from sugar_lift_py_tests.generator_construction import (
            AssignStepV1,
            AttributeAssignStepV1,
            AssertStepV1,
            ImportFromStepV1,
            ImportStepV1,
            WhileStepV1,
            FinallyStepV1,
            ForStepV1,
            IfStepV1,
            InertStepV1,
            OpaqueStepV1,
            RaiseStepV1,
            ReturnStepV1,
            TermStepV1,
            YieldFromStepV1,
            YieldStepV1,
        )
        from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar

        steps = []

        absent_step = _GeneratorStepAbsentV1()
        absent_cleanup = _GeneratorCleanupAbsentV1()

        def name_statement(statement):
            """One nameable step, or None when the vocabulary cannot perform it.

            None is not a skip: the caller either keeps a containing `If`
            opaque or appends an honest `OpaqueStepV1`. Unhandled kinds stay
            loud SUGAR NOT WRITTEN at transition — never silently advanced.

            Recurses into suspension-owning ``If`` and nested ``try/finally``
            so real/renamed generator managers advance through source-visible
            control to their first yield without consumer reconstruction.
            """
            if isinstance(statement, Expr) and isinstance(statement.value, Yield):
                value = statement.value.value
                return _GeneratorNamedStepV1(
                    YieldStepV1(None if value is None else value.sugar())
                )
            if isinstance(statement, Expr) and isinstance(statement.value, YieldFrom):
                occurrence = statement.value.fragment
                return _GeneratorNamedStepV1(
                    YieldFromStepV1(
                        statement.value.value.sugar(),
                        occurrence,
                        occurrence.seal().cid,
                    )
                )
            if isinstance(statement, Return):
                return _GeneratorNamedStepV1(
                    ReturnStepV1(
                        None if statement.value is None else statement.value.sugar()
                    )
                )
            if isinstance(statement, Raise) and not self._owns_yield((statement,)):
                # Validation arms (``if bad: raise …``) and cleanup raises —
                # RaiseSugar rides the step; transition halts with the effect.
                return _GeneratorNamedStepV1(
                    RaiseStepV1(
                        statement.sugar(),
                        statement.fragment.seal().cid,
                    )
                )
            if (
                isinstance(statement, Expr)
                and isinstance(statement.value, Constant)
                and not self._owns_yield((statement,))
            ):
                # EVALUATED AND DISCARDED IS NOTHING. A bare `Constant`
                # expression -- the docstring case -- owes no effect, no
                # binding and no suspension, so calling it opaque made the
                # machine refuse at a statement that asks for nothing and name
                # the WRONG blocker. It is stepped, not performed.
                return _GeneratorNamedStepV1(InertStepV1(statement.kind))
            if isinstance(statement, Pass) and not self._owns_yield((statement,)):
                return _GeneratorNamedStepV1(InertStepV1(statement.kind))
            if (
                isinstance(statement, Expr)
                and not self._owns_yield((statement,))
                and not isinstance(statement.value, (Yield, YieldFrom))
            ):
                # Bare expression statements (cleanup / setup calls): admit the
                # *value* as ConstructedTermSugar — never ExprStatementSugar.
                value_sugar = statement.value.sugar()
                if isinstance(value_sugar, ConstructedTermSugar):
                    return _GeneratorNamedStepV1(
                        TermStepV1(value_sugar, statement.fragment.seal().cid)
                    )
                return absent_step
            if (
                isinstance(statement, Assign)
                and not self._owns_yield((statement,))
                and len(statement.targets) == 1
                and isinstance(statement.targets[0], Name)
            ):
                return _GeneratorNamedStepV1(
                    AssignStepV1(
                        statement.targets[0].id,
                        statement.value.sugar(),
                        statement.fragment.seal().cid,
                    )
                )
            if (
                isinstance(statement, Assign)
                and not self._owns_yield((statement,))
                and len(statement.targets) == 1
                and isinstance(statement.targets[0], Attribute)
            ):
                target = statement.targets[0]
                return _GeneratorNamedStepV1(
                    AttributeAssignStepV1(
                        receiver=target.value.sugar(),
                        attr=target.attr,
                        value=statement.value.sugar(),
                        fragment_cid=statement.fragment.seal().cid,
                        target_cid=target.fragment.seal().cid,
                        occurrence=target.fragment,
                    )
                )
            if (
                isinstance(statement, AnnAssign)
                and not self._owns_yield((statement,))
                and isinstance(statement.target, Name)
                and statement.value is not None
            ):
                return _GeneratorNamedStepV1(
                    AssignStepV1(
                        statement.target.id,
                        statement.value.sugar(),
                        statement.fragment.seal().cid,
                    )
                )
            if isinstance(statement, Assert) and not self._owns_yield((statement,)):
                from sugar_lift_py_tests.context_manager_resolution import (
                    SourceFragmentCoordinateV1,
                )

                span = statement.line_col_span()
                return _GeneratorNamedStepV1(
                    AssertStepV1(
                        assert_sugar=statement.sugar(),
                        assert_cid=statement.fragment.seal().cid,
                        assert_coordinate=SourceFragmentCoordinateV1(
                            statement.unit.source_cid,
                            span.start_line,
                            span.start_col,
                            span.end_line,
                            span.end_col,
                        ),
                        occurrence=statement.fragment,
                    )
                )
            if isinstance(statement, ImportFrom) and not self._owns_yield((statement,)):
                from sugar_lift_py_tests.context_manager_resolution import (
                    SourceFragmentCoordinateV1,
                )

                span = statement.line_col_span()
                return _GeneratorNamedStepV1(
                    ImportFromStepV1(
                        import_sugar=statement.sugar(),
                        coordinate=SourceFragmentCoordinateV1(
                            statement.unit.source_cid,
                            span.start_line,
                            span.start_col,
                            span.end_line,
                            span.end_col,
                        ),
                        occurrence=statement.fragment,
                    )
                )
            if isinstance(statement, Import) and not self._owns_yield((statement,)):
                from sugar_lift_py_tests.context_manager_resolution import (
                    SourceFragmentCoordinateV1,
                )

                span = statement.line_col_span()
                return _GeneratorNamedStepV1(
                    ImportStepV1(
                        import_sugar=statement.sugar(),
                        coordinate=SourceFragmentCoordinateV1(
                            statement.unit.source_cid,
                            span.start_line,
                            span.start_col,
                            span.end_line,
                            span.end_col,
                        ),
                        occurrence=statement.fragment,
                    )
                )
            if isinstance(statement, While) and not statement.orelse:
                from sugar_lift_py_tests.context_manager_resolution import (
                    SourceFragmentCoordinateV1,
                )

                body_steps = branch_steps(statement.body)
                guard = statement.test.sugar()
                if body_steps is None or not isinstance(guard, ConstructedTermSugar):
                    return absent_step
                span = statement.line_col_span()
                return _GeneratorNamedStepV1(
                    WhileStepV1(
                        guard=guard,
                        body_steps=body_steps,
                        fragment_cid=statement.fragment.seal().cid,
                        coordinate=SourceFragmentCoordinateV1(
                            statement.unit.source_cid,
                            span.start_line,
                            span.start_col,
                            span.end_line,
                            span.end_col,
                        ),
                        occurrence=statement.fragment,
                    )
                )
            if isinstance(statement, If):
                # Suspension-owning and pre-yield guarded If: both sides fully
                # constructed (recursive), guard + If occurrence CID. Partial
                # branches refuse the whole If as Opaque (never skip inside).
                then_body = branch_steps(statement.body)
                else_body = branch_steps(statement.orelse)
                if then_body is None or else_body is None:
                    return absent_step
                return _GeneratorNamedStepV1(
                    IfStepV1(
                        statement.test.sugar(),
                        then_body,
                        else_body,
                        statement.fragment.seal().cid,
                    )
                )
            if (
                isinstance(statement, For)
                and not statement.orelse
                and not self._owns_yield((statement,))
            ):
                body_steps = branch_steps(statement.body)
                target_coordinates = generator_for_target_coordinates(statement)
                iterable = statement.iter.sugar()
                if (
                    body_steps is None
                    or target_coordinates is None
                    or not isinstance(iterable, ConstructedTermSugar)
                ):
                    return absent_step
                return _GeneratorNamedStepV1(
                    ForStepV1(
                        iterable=iterable,
                        target_coordinates=target_coordinates,
                        body_steps=body_steps,
                        module_cid=generator_for_module_cid(statement),
                        fragment_cid=statement.fragment.seal().cid,
                        occurrence=statement.fragment,
                    )
                )
            if (
                isinstance(statement, Try)
                and statement.handlers
                and not statement.orelse
                and not statement.finalbody
                and len(statement.body) == 1
                and isinstance(statement.body[0], Expr)
                and isinstance(statement.body[0].value, Yield)
                and (
                    statement.body[0].value.value is None
                    or isinstance(statement.body[0].value.value, (Name, Constant))
                )
                and all(
                    not self._owns_yield(handler.body)
                    and all(
                        isinstance(item, (Pass, Raise, Return))
                        or (
                            isinstance(item, Expr)
                            and not isinstance(item.value, (Yield, YieldFrom))
                        )
                        for item in handler.body
                    )
                    for handler in statement.handlers
                )
            ):
                # ``try: yield v`` / ``except ...``: the arms a generator
                # manager suppresses with. Arms that bind nothing keep the
                # frame's binding state exact after an arm completes.
                from sugar_lift_py_tests.generator_construction import (
                    YieldExceptStepV1,
                )

                try:
                    handlers = statement._authenticated_handler_specs()
                except SugarNotWritten:
                    return absent_step
                if handlers is None:
                    return absent_step
                value = statement.body[0].value.value
                return _GeneratorNamedStepV1(
                    YieldExceptStepV1(
                        YieldStepV1(None if value is None else value.sugar()),
                        handlers,
                        statement.fragment.seal().cid,
                        statement.fragment,
                    )
                )
            if (
                isinstance(statement, Try)
                and not statement.handlers
                and not statement.orelse
                and statement.finalbody
            ):
                # try/finally without handlers: fully nameable body+cleanup is
                # one atomic producer unit; partial nameability expands body
                # statement-by-statement so a yield is never swallowed by a
                # single Opaque Try when only a peer loop is unnameable.
                body_steps = branch_steps(statement.body)
                cleanup = cleanup_terms(statement.finalbody)
                if body_steps is not None and isinstance(
                    cleanup, _GeneratorCleanupTermsV1
                ):
                    cleanup_step = FinallyStepV1(cleanup.terms)
                    return _GeneratorTryFinallyStepsV1(
                        compose_finally(body_steps, cleanup_step)
                    )
                cleanup_steps = branch_steps(statement.finalbody)
                if body_steps is not None and cleanup_steps is not None:
                    return _GeneratorTryFinallyStepsV1(
                        compose_finally(
                            body_steps,
                            FinallyStepV1((), cleanup_steps=cleanup_steps),
                        )
                    )
                if body_steps is None and self._owns_yield(statement.body):
                    return _GeneratorTryFinallyExpansionV1(statement, cleanup)
                return absent_step
            return absent_step

        def branch_steps(body):
            """Steps for one branch/suite, or None if any shape is unnameable.

            None keeps the containing If/try opaque. A partially-nameable
            branch is not provable: never skip unsupported shapes inside.
            """
            collected = []
            for nested in body:
                produced = name_statement(nested)
                if isinstance(produced, _GeneratorStepAbsentV1):
                    return None
                if isinstance(produced, _GeneratorTryFinallyStepsV1):
                    collected.extend(produced.steps)
                    continue
                if isinstance(produced, _GeneratorNamedStepV1):
                    collected.append(produced.step)
                    continue
                return None
            return tuple(collected)

        def compose_finally(body_steps, cleanup_step):
            """Seat cleanup before every terminal face and on fall-through."""
            composed = []
            for step in body_steps:
                if isinstance(step, IfStepV1):
                    step = IfStepV1(
                        step.guard,
                        compose_finally_exits(step.then_steps, cleanup_step),
                        compose_finally_exits(step.else_steps, cleanup_step),
                        step.fragment_cid,
                    )
                if isinstance(step, (ReturnStepV1, RaiseStepV1)):
                    composed.append(cleanup_step)
                composed.append(step)
            composed.append(cleanup_step)
            return tuple(composed)

        def compose_finally_exits(branch, cleanup_step):
            """Compose only exits in a branch; branch fall-through stays in try."""
            composed = []
            for step in branch:
                if isinstance(step, IfStepV1):
                    step = IfStepV1(
                        step.guard,
                        compose_finally_exits(step.then_steps, cleanup_step),
                        compose_finally_exits(step.else_steps, cleanup_step),
                        step.fragment_cid,
                    )
                if isinstance(step, (ReturnStepV1, RaiseStepV1)):
                    composed.append(cleanup_step)
                composed.append(step)
            return tuple(composed)

        def cleanup_terms(finalbody):
            """Finally payloads: ConstructedTermSugar only (no ExprStatementSugar)."""
            terms = []
            for item in finalbody:
                if isinstance(item, Pass):
                    continue
                if isinstance(item, For):
                    # A structured cleanup step is not a term. Let the typed
                    # step path below own it without probing ``For.sugar``.
                    return absent_cleanup
                if isinstance(item, Expr) and not self._owns_yield((item,)):
                    value_sugar = item.value.sugar()
                    if isinstance(value_sugar, ConstructedTermSugar):
                        terms.append(value_sugar)
                        continue
                    return absent_cleanup
                if isinstance(item, Raise) and not self._owns_yield((item,)):
                    # Raise is a step, not a Finally term; refuse pure-term suite.
                    return absent_cleanup
                try:
                    sugar = item.sugar()
                except SugarNotWritten:
                    return absent_cleanup
                if isinstance(sugar, ConstructedTermSugar):
                    terms.append(sugar)
                    continue
                return absent_cleanup
            return _GeneratorCleanupTermsV1(tuple(terms))

        def append_statement(statement):
            produced = name_statement(statement)
            if isinstance(produced, _GeneratorTryFinallyStepsV1):
                steps.extend(produced.steps)
                return
            if isinstance(produced, _GeneratorTryFinallyExpansionV1):
                for nested in produced.statement.body:
                    append_statement(nested)
                if isinstance(produced.cleanup, _GeneratorCleanupTermsV1):
                    steps.append(FinallyStepV1(produced.cleanup.terms))
                else:
                    steps.append(
                        OpaqueStepV1(
                            "Finally",
                            carries_suspension=False,
                        )
                    )
                return
            if isinstance(produced, _GeneratorNamedStepV1):
                steps.append(produced.step)
                return
            if isinstance(statement, If):
                # Branch held an unnameable shape. Keep the whole If opaque,
                # never skip unsupported shapes inside the arms.
                steps.append(
                    OpaqueStepV1(
                        statement.kind,
                        carries_suspension=self._owns_yield((statement,)),
                    )
                )
                return
            steps.append(
                OpaqueStepV1(
                    statement.kind,
                    carries_suspension=self._owns_yield((statement,)),
                )
            )

        for statement in body:
            append_statement(statement)
        if not steps or not isinstance(steps[-1], ReturnStepV1):
            steps.append(ReturnStepV1())
        return tuple(steps)

    @staticmethod
    def _owns_yield(body) -> bool:
        """Does this body own a suspension boundary of its own?

        `Yield` and `YieldFrom` are the two constructors of that boundary, so
        ownership tests BOTH. Recognizing only `Yield` made a `yield from`-only
        function construct an ordinary eager call frame: the call completed as
        a plain `CallSiteValue` instead of allocating a generator, and the
        boundary's refusal only surfaced later if the body happened to be
        forced. One constructor recognized and the other not is what let a
        suspension escape as an ordinary value.

        The constructed graph is a DAG (see ``walk``): a substituted body
        shares subgraphs across statements. Each node object is asked once.
        Walking the DAG as a tree re-asked every shared subgraph once per
        path, which is exponential in sharing depth.
        """
        seen: set[int] = set()
        stack: list = list(reversed(tuple(body)))
        while stack:
            node = stack.pop()
            if isinstance(node, (Yield, YieldFrom)):
                return True
            if not isinstance(node, Node):
                continue
            # A nested callable owns its own boundary; it is not this body's.
            if isinstance(node, (FunctionDef, AsyncFunctionDef, Lambda)):
                continue
            nid = id(node)
            if nid in seen:
                continue
            seen.add(nid)
            stack.extend(child for _name, _index, child in node._child_edges())
        return False

    def _make_coordinate_ref(self, param: "Param", coordinate) -> "Node":
        from .backend import Leaf, materialize
        from .shadow import ShadowNode

        return materialize(
            self.unit,
            ShadowNode(
                "BindingCoordinateRef",
                param.span,
                (("coordinate", Leaf(coordinate)),),
            ),
            self.reporter,
        )

    def substitute(self, scope):
        """The first MASKING node: a function opens a scope. Its parameters
        (and any PEP 695 type parameters) bind their names, and ONLY THE BODY
        sees them -- so only the body's scope has those names held out. The
        signature (decorators, type params, parameter annotations/defaults, the
        return annotation) is evaluated in the ENCLOSING scope, unmasked. This
        is why the abstract panics rather than recursing blindly: a blind
        recurse would substitute an outer `x` into a body whose parameter is
        `x`, capturing it. Masking is that capture, left as a gap.
        """
        from .shadow import rewrite

        table = self.unit.function_symtable(self.name, self.line_col_span().start_line)
        parameters = frozenset(table.get_parameters())
        locals_ = frozenset(table.get_locals()) - parameters
        bound = {p.name for p in self.params}
        for tp in self.type_params:
            name = getattr(tp, "name", None)
            if isinstance(name, str):
                bound.add(name)
        body_scope = (
            {k: v for k, v in scope.items() if k not in bound} if bound else scope
        )
        inherited_bound = scope.get(_LEXICALLY_BOUND_NAMES, frozenset())
        formal_refs = {
            parameter.name: self._make_parameter_entry(parameter, ordinal, scope)
            for ordinal, parameter in enumerate(self.params)
        }
        body_scope = {
            **body_scope,
            **formal_refs,
            **{
                name: UnboundBinding(name=name, cause=self.fragment) for name in locals_
            },
            _LEXICALLY_BOUND_NAMES: frozenset(inherited_bound) | bound | locals_,
        }

        changed: dict[str, object] = {}
        # signature: the enclosing scope, unmasked (evaluated before the body).
        for field in ("decorators", "type_params", "params", "returns"):
            new, diff = self._substitute_field(getattr(self, field), scope)
            if diff:
                changed[field] = new
        # body: the enclosing scope with the bound names held out, THREADED --
        # each assignment binds its name for the statements after it.  A door
        # threading the module for what it does at import does not run the
        # body: the def statement binds the function, and the caller's frame
        # substitutes the body when (if) it calls it.
        if scope.get(DEFER_DEFINITION_BODY_REFUSAL):
            new_body, body_diff = self.body, False
        else:
            new_body, body_diff = self._substitute_body(self.body, body_scope)
        if body_diff:
            changed["body"] = new_body

        if not changed:
            return self
        return rewrite(self, **changed)

    def _substitute_body(self, statements: tuple, scope: BindingMap):
        """Every door that substitutes this function's body (its own sugar,
        its call frame, a constructor's initializer, a generator's steps)
        substitutes it here, so each one reads a module global the same way:
        as the module binds it where the function is called
        (``_module_global_references``), not as the name."""
        references = self._module_global_references()
        if references:
            scope = {**scope, **references}
        return Node._substitute_body(self, statements, scope)

    def _module_global_references(self) -> dict:
        """The module's binding of each global this body reads, where the
        function is called, when that binding is the evaluation of a module
        write of it (temporal choice 1, #7661).

        A function reads a global when it runs.  Called from outside the
        module's execution (after import), it reads the module's last
        write: ``x = 1; x += 1; x += 1`` binds a read of ``x`` to the second
        ``x += 1``'s evaluation, wherever the ``def`` stands.  Called while
        the module body runs (a call in the module body or in a class body,
        or a call reached from one: ``_MODULE_EXECUTION_SITE``), it reads
        the binding standing at that call: ``x = 1; x += 1; y = f(); x += 1``
        binds the read to the first ``x += 1``'s evaluation.  A write in an
        arm of a module-level ``if`` is read through the phi the module
        block builds over it; a walrus's write through its evaluation.

        The global is the one CPython names (``symtable``: implicit or
        declared ``global``, read in this body); a local, a formal or a name
        an enclosing function binds is not one.  A global whose binding
        there is no evaluation (``x = 1``) is read by name, as before.  One
        the module body does not decide there is cited ``undecided`` by
        name (``SourceUnit.module_bindings_at``).
        """
        unit = self.unit
        if unit.typed_module is None:
            return {}
        candidates = unit.module_evaluation_bound_names()
        if not candidates:
            return {}
        table = unit.function_symtable(self.name, self.line_col_span().start_line)
        reads = {
            symbol.get_name()
            for symbol in table.get_symbols()
            if symbol.is_global() and symbol.is_referenced()
        } & candidates
        if not reads:
            return {}
        site = _MODULE_EXECUTION_SITE.get()
        if site is not None and site.unit is not unit:
            # Another module's body calls this one's function after this
            # module was imported: it reads this module's final binding.
            site = None
        return _bound_module_references(
            self,
            unit.module_bindings_at(site, reads),
            owner="FunctionDef._module_global_references",
        )

    def _make_parameter_entry(self, parameter: Param, ordinal: int, scope):
        owner = self._active_initializer_owner()
        if owner is not None and ordinal == 0:
            coordinate = self._constructed_receiver_coordinate(owner, parameter)
            ref = owner._make_constructed_receiver_ref(coordinate.cid)
        else:
            ref = self._make_parameter_ref(parameter, ordinal)
        factory = scope.get(_BINDING_ENTRY_FACTORY)
        if not isinstance(factory, RuntimeBindingEntryFactoryV1):
            return ref
        return factory.mint_entry(
            binding_site=parameter.fragment,
            projection_path=("formal", ordinal),
            state=ref,
        )

    def _active_initializer_owner(self) -> "ClassDef | None":
        """The exact class whose active ``__init__`` this occurrence is.

        Class ownership is projected from the backend's parent relation.  The
        last same-name initializer is Python's live class binding; overwritten
        definitions and genuinely free functions keep the ordinary formal
        entrance.

        Active membership is decided on the SOURCE OCCURRENCE (#7346-B), not on
        the shell.  ``owner.body`` holds the producer's shells; a reconstructed
        ``__init__`` is a different shell denoting the same occurrence, and the
        shell comparison silently reclassified the live initializer as
        overwritten -- degrading its receiver entrance to an ordinary formal.
        A genuinely overwritten initializer denotes a DIFFERENT occurrence and
        stays inactive.
        """
        if self.name != "__init__":
            return None
        owner = self.unit.lexical_class_owner_for(self)
        if owner is None:
            return None
        active = next(
            (
                item
                for item in reversed(owner.body)
                if isinstance(item, FunctionDef) and item.name == "__init__"
            ),
            None,
        )
        if active is None:
            return None
        occurrence = SourceOccurrenceIdentityV1.of(self)
        return owner if SourceOccurrenceIdentityV1.of(active) == occurrence else None

    def _constructed_receiver_coordinate(self, owner: "ClassDef", parameter: Param):
        """Mint the same receiver coordinate as the class-construction door."""
        from sugar_source_tree.binding_provenance import BindingCoordinateV1

        return BindingCoordinateV1.mint(
            owner.fragment.seal().cid,
            parameter.fragment,
            ("receiver", 0),
        )

    def _formal_coordinate(self, parameter: Param, ordinal: int):
        """Mint the exact FormalParameterCoordinateV1 for one formal. The single
        source of truth: both the body FormalRef (via _make_parameter_ref) and
        the universe's own formal declarations (via formal_coordinates) mint
        through here, so a demand keyed to a body formal coordinate and the
        owned contract's declaration carry byte-identical coordinate CIDs."""
        from sugar_lift_py_tests.context_manager_resolution import (
            SourceFragmentCoordinateV1,
        )
        from sugar_lift_py_tests.formal_parameter import FormalParameterCoordinateV1
        from sugar_lift_py_tests.ir import PrimitiveSort

        kind = {
            "positional_only": "positional-only",
            "positional_or_keyword": "positional-or-keyword",
            "vararg": "variadic-positional",
            "keyword_only": "keyword-only",
            "kwarg": "variadic-keyword",
        }.get(parameter.param_kind)
        if kind is None:
            from .panic import BackendDefect

            raise BackendDefect(
                blame=parameter.fragment,
                owner="FunctionDef._formal_coordinate",
                observed=parameter.param_kind,
                requested="one canonical Python parameter kind",
                fix="repair the backend parameter-kind projection",
            )

        def coordinate(node: Node) -> SourceFragmentCoordinateV1:
            span = node.line_col_span()
            return SourceFragmentCoordinateV1(
                node.unit.source_cid,
                span.start_line,
                span.start_col,
                span.end_line,
                span.end_col,
            )

        return FormalParameterCoordinateV1.mint(
            owner_source_identity_cid=self.unit.source_cid,
            owner_definition_locus=coordinate(self),
            declaration_locus=coordinate(parameter),
            ordinal=ordinal,
            parameter_kind=kind,
            declared_name=parameter.name,
            sort=PrimitiveSort("Value"),
        )

    def formal_coordinates(self) -> tuple:
        """The ordered formal coordinates for every parameter -- the universe's
        own structural formals, threaded into UniverseValue so
        link_unit_projection can assemble the owned contract WITHOUT post()."""
        return tuple(
            self._formal_coordinate(parameter, ordinal)
            for ordinal, parameter in enumerate(self.params)
        )

    def _make_parameter_ref(self, parameter: Param, ordinal: int) -> "Node":
        from .backend import Leaf, materialize
        from .shadow import ShadowNode

        formal = self._formal_coordinate(parameter, ordinal)
        # The FormalRef stands in the Param's place for the whole body, so the
        # Param's discharge is this substitution -- otherwise it registers and
        # never answers.
        parameter.discharge_by_substitution()
        return materialize(
            self.unit,
            ShadowNode("FormalRef", parameter.span, (("coordinate", Leaf(formal)),)),
            self.reporter,
        )

    def _sugar_body_statement(self, stmt: "Node") -> object:
        """Sugar one body statement under a Construct-body kind span."""
        from sugar_lift_py_tests.engine_log import reduction_span

        lc = stmt.line_col_span()
        site = f"{stmt.unit.filename}:{lc.start_line} {stmt.kind}"
        with reduction_span(sugar=f"Body.{stmt.kind}", role="construction", site=site):
            return stmt.sugar()

    def _construct_sugar(self):
        """`def <name>(<formals>): <body>` constructs FunctionUniverseSugar WITH
        each body statement's own sugar — the recursion, child-before-parent.

        The body is SUBSTITUTED first: every temporal binding (a local
        assignment, a conditional phi) is rewritten into the tree before any
        sugar runs, so by the time a statement is sugared its names are already
        resolved — a `Name` that survives is only ever a free formal (the
        parameters are masked by ``substitute``, so they stand as symbolic
        Vars). This is why the meaning layer holds NO temporal: substitute did
        it. A body statement whose sugar is not written yet raises
        SugarNotWritten from its own `.sugar()`, which propagates out here.
        """
        from sugar_lift_py_tests.engine_log import reduction_span
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            FunctionUniverseSugar,
        )

        # CONSTRUCTION IS THE INSTRUMENTED BOUNDARY: the span names this
        # function while it substitutes+constructs, so the engine log's
        # heartbeat testifies exactly which function a slow lift is inside --
        # the bisection instrument (macro says nothing; the active frame says
        # where to cut next). The factory had this on SugarBody.reduce; the
        # tree construction path re-enters it here.
        lc = self.line_col_span()
        where = f"{self.unit.filename}:{lc.start_line} {self.name}"
        # Same seat law as source_visible_call_frame: a callee's universe asked
        # for while that callee's own universe is under construction is the
        # recursion seat, not a second unfolding.
        definition_cid = self.fragment.seal().cid
        if _frame_is_under_construction(definition_cid):
            raise SourceCallFrameCycle(self)
        _FRAMES_UNDER_CONSTRUCTION.add(definition_cid)
        try:
            with reduction_span(sugar="FunctionUniverse", role="construction", site=where):
                # Phase spans: the bisection instrument. A slow function names its
                # slow PHASE here; the per-statement spans inside _substitute_body
                # then name the statement. We measure; we do not guess.
                with reduction_span(sugar="Substitute", role="temporal", site=where):
                    # Substitute the body against an empty scope: formals are masked
                    # (stay free -> symbolic), locals thread/inline, phis -> IfExps.
                    from sugar_lift_python_source.canonical import cid_of_json

                    scope_owner_cid = cid_of_json(
                        {
                            "kind": "binding-scope-owner",
                            "schemaVersion": "1",
                            "source": self.fragment.seal().to_dict(),
                        }
                    )
                    trace_builder = SubstitutionTraceBuilderV1(scope_owner_cid)
                    loop_trace_required = any(
                        isinstance(node, (For, AsyncFor, While))
                        for statement in self.body
                        for node in statement.walk()
                    )
                    substituted = self.substitute(
                        {
                            _SCOPE_OWNER_CID: scope_owner_cid,
                            _SUBSTITUTION_TRACE_BUILDER: trace_builder,
                            _BINDING_ENTRY_FACTORY: RuntimeBindingEntryFactoryV1(
                                scope_owner_cid
                            ),
                        }
                    )
                with reduction_span(sugar="Construct", role="construction", site=where):
                    from .backend import materialize
                    from .binding_state import ConstructionTestimonyReporterV1

                    if loop_trace_required:
                        with reduction_span(
                            sugar="Construct.rematerialize",
                            role="construction",
                            site=where,
                        ):
                            testimony_reporter = ConstructionTestimonyReporterV1(
                                self.reporter, trace_builder
                            )
                            construction_root = materialize(
                                substituted.unit, substituted.ref, testimony_reporter
                            )
                        body_stmts = construction_root.body
                        with reduction_span(
                            sugar="Construct.body", role="construction", site=where
                        ):
                            statements = tuple(
                                self._sugar_body_statement(stmt) for stmt in body_stmts
                            )
                        with reduction_span(
                            sugar="Construct.freeze_trace",
                            role="construction",
                            site=where,
                        ):
                            substitution_trace = trace_builder.freeze(testimony_reporter)
                    else:
                        # Every statement still has an immutable runtime snapshot.
                        # Only a loop consumer demands the sealed state projection;
                        # ordinary functions retain the runtime trace without
                        # sealing/hashing every binding (see freeze()).
                        with reduction_span(
                            sugar="Construct.body", role="construction", site=where
                        ):
                            statements = tuple(
                                self._sugar_body_statement(stmt)
                                for stmt in substituted.body
                            )
                        with reduction_span(
                            sugar="Construct.freeze_trace",
                            role="construction",
                            site=where,
                        ):
                            substitution_trace = trace_builder.freeze()
                    bridge_source_symbol = None
                    context = self._require_construction_context(
                        owner="FunctionDef._construct_sugar"
                    )
                    workspace_root = getattr(context, "workspace_root", None)
                    if workspace_root is not None and self.unit.is_module_level_function(
                        self.name, self.line_col_span().start_line
                    ):
                        from pathlib import Path

                        # The construction door already mints the locus
                        # workspace-relative (`workspace_path_source`). Re-deriving
                        # it here would be a second answer to a question already
                        # resolved; an absolute filename means the unit did NOT come
                        # through that door, and that stays LOUD.
                        relative = Path(self.unit.filename)
                        if relative.is_absolute():
                            raise SugarNotWritten(
                                blame=self.fragment,
                                owner="FunctionDef.bridge_source_symbol",
                                observed=f"absolute source locus `{self.unit.filename}`",
                                requested="workspace-relative source locus",
                                fix=(
                                    "route the source through the workspace-relative "
                                    "lift door (`workspace_path_source`)"
                                ),
                            )
                        # The one speller of a module's own definition
                        # symbol: the class ancestry rows read it too.
                        bridge_source_symbol = self.unit.module_member_target_symbol(
                            self.name
                        )
                    return FunctionUniverseSugar(
                        name=self.name,
                        formals=tuple(p.name for p in self.params),
                        statements=statements,
                        site=self.fragment,
                        bridge_source_symbol=bridge_source_symbol,
                        substitution_trace=substitution_trace,
                        formal_coordinates=self.formal_coordinates(),
                    )
        finally:
            _FRAMES_UNDER_CONSTRUCTION.discard(definition_cid)

class AsyncFunctionDef(Statement):
    """`async def` — same FunctionUniverse body door as FunctionDef (L1a).

    Fields match FunctionDef. Construction does not invent a second path:
    substitute, formals, and body statements all share FunctionDef's door so
    every async function walks child-before-parent via ``_sugar_body_statement``.
    """

    _bound_name_fields = ("name",)
    name: str
    params: Tuple[Param, ...]
    body: Tuple[Statement, ...]
    decorators: Tuple[Expression, ...]
    returns: Optional[Expression]
    type_params: Tuple[TypeParam, ...]
    _child_fields = ("decorators", "type_params", "params", "returns", "body")

    def substitution_binding(self, scope):
        return _local_definition_binding(self, scope)

    @property
    def args(self):
        return _arguments_projection(self.params)

    def substitute(self, scope):
        """Same scope shape as FunctionDef (identical fields)."""
        return FunctionDef.substitute(self, scope)

    def _substitute_body(self, statements, scope):
        """Same body door as FunctionDef: a global reads the module's binding
        of it where the function is called."""
        return FunctionDef._substitute_body(self, statements, scope)

    def _module_global_references(self) -> dict:
        return FunctionDef._module_global_references(self)

    def _make_parameter_entry(self, parameter: Param, ordinal: int, scope):
        return FunctionDef._make_parameter_entry(self, parameter, ordinal, scope)

    def _active_initializer_owner(self) -> "ClassDef | None":
        return FunctionDef._active_initializer_owner(self)

    def _constructed_receiver_coordinate(self, owner: "ClassDef", parameter: Param):
        return FunctionDef._constructed_receiver_coordinate(self, owner, parameter)

    def _formal_coordinate(self, parameter: Param, ordinal: int):
        return FunctionDef._formal_coordinate(self, parameter, ordinal)

    def formal_coordinates(self) -> tuple:
        return FunctionDef.formal_coordinates(self)

    def _make_parameter_ref(self, parameter: Param, ordinal: int) -> "Node":
        return FunctionDef._make_parameter_ref(self, parameter, ordinal)

    def _sugar_body_statement(self, stmt: "Node") -> object:
        """One body door: statement constructs through its children."""
        return FunctionDef._sugar_body_statement(self, stmt)

    def source_visible_call_frame(self):
        """Same frame door as FunctionDef (same formals/body shape); the
        guard and the recursion seat live there."""
        return FunctionDef.source_visible_call_frame(self)

    # Frame-door helper shared with FunctionDef (a staticmethod there).
    _owns_yield = staticmethod(FunctionDef._owns_yield)

    def _make_coordinate_ref(self, *args, **kwargs):
        """Frame-door helper shared with FunctionDef (see source_visible_call_frame)."""
        return FunctionDef._make_coordinate_ref(self, *args, **kwargs)

    def _source_visible_generator_steps_from(self, *args, **kwargs):
        """Frame-door helper shared with FunctionDef (see source_visible_call_frame)."""
        return FunctionDef._source_visible_generator_steps_from(self, *args, **kwargs)

    def _source_visible_generator_steps(self, *args, **kwargs):
        """Frame-door helper shared with FunctionDef (see source_visible_call_frame)."""
        return FunctionDef._source_visible_generator_steps(self, *args, **kwargs)

    def lacks_captured_binding_testimony(self, covered=frozenset()) -> bool:
        """Frame-door helper shared with FunctionDef (see source_visible_call_frame)."""
        return FunctionDef.lacks_captured_binding_testimony(self, covered)

    def _captured_bindings(self) -> tuple:
        """Frame-door helper shared with FunctionDef (see source_visible_call_frame)."""
        return FunctionDef._captured_bindings(self)

    def _captured_scope(self) -> dict:
        """Frame-door helper shared with FunctionDef (see source_visible_call_frame)."""
        return FunctionDef._captured_scope(self)

    def _construct_sugar(self):
        """L1a: FunctionUniverse body construction — same door as FunctionDef."""
        return FunctionDef._construct_sugar(self)


class ClassDef(Statement):
    _bound_name_fields = ("name",)
    name: str
    binding_target: Name
    bases: Tuple[Expression, ...]
    keywords: Tuple[Keyword, ...]
    body: Tuple[Statement, ...]
    decorators: Tuple[Expression, ...]
    type_params: Tuple[TypeParam, ...]
    _child_fields = (
        "binding_target",
        "decorators",
        "type_params",
        "bases",
        "keywords",
        "body",
    )

    def substitution_binding(self, scope):
        return _local_definition_binding(self, scope)

    def __post_init__(self):
        # A NODE OFF THE ROLL. `Node.__post_init__` is where registration
        # happens, and its own docstring is the law: "calling ``cls(...)`` at
        # all is showing up on the roll -- there is no way to new a node
        # without it." This override silently was that way: every ClassDef in
        # the corpus was constructed unregistered, so the identity guard's
        # `definition-ref-not-materialized` was unsatisfiable for every
        # allocation callee no matter what the guard admitted.
        #
        # The binding-target check below is this class's OWN extra demand and
        # keeps running; it is not a reason to skip the roll.
        super().__post_init__()
        if (
            not isinstance(self.binding_target, Name)
            or self.binding_target.id != self.name
        ):
            from sugar_source_tree.panic import BackendDefect

            raise BackendDefect(
                blame=self.fragment,
                owner="ClassDef",
                observed="class binding target does not match its definition name",
                requested="the exact identifier child bound by this ClassDef",
                fix="carry the parser-owned ClassDef name occurrence as binding_target",
            )

    def _method_descriptor_kind(
        self, method: "FunctionDef | AsyncFunctionDef"
    ) -> Optional[str]:
        """Authenticate one language descriptor decorator by its binding.

        The decorator resolves through ``SourceUnit.language_callee_of``: a
        name that falls through to the builtin namespace (or an import of
        ``builtins``) reaches the descriptor constructor; any rebinding
        reaches nothing and never grants property or class/static method
        semantics.
        """
        if len(method.decorators) != 1:
            return None
        return _METHOD_DESCRIPTOR_KINDS.get(
            self.unit.language_callee_of(method.decorators[0])
        )

    def _authenticated_new_constructor_shape(self):
        """One source-owned ``__new__`` allocation followed by field stores."""
        constructors = tuple(
            item
            for item in self.body
            if isinstance(item, FunctionDef) and item.name == "__new__"
        )
        if len(constructors) != 1 or any(
            isinstance(item, FunctionDef) and item.name == "__init__"
            for item in self.body
        ):
            return None
        constructor = constructors[0]
        if len(constructor.params) < 2 or len(constructor.body) < 3:
            return None
        allocation = constructor.body[0]
        returned = constructor.body[-1]
        if (
            not isinstance(allocation, Assign)
            or len(allocation.targets) != 1
            or not isinstance(allocation.targets[0], Name)
            or not isinstance(returned, Return)
            or not isinstance(returned.value, Name)
            or returned.value.id != allocation.targets[0].id
            or not isinstance(allocation.value, Call)
            or allocation.value.keywords
            or len(allocation.value.args) < 1
            or not isinstance(allocation.value.func, Attribute)
            or allocation.value.func.attr != "__new__"
            or not isinstance(allocation.value.func.value, Call)
        ):
            return None
        super_call = allocation.value.func.value
        class_param = constructor.params[0]
        if (
            # The builtin ``super`` by its binding: a module or function that
            # binds its own ``super`` reaches no language callee.
            super_call.language_callee() is not LanguageCallee.BUILTIN_SUPER
            or super_call.keywords
            or len(super_call.args) != 2
            or not isinstance(super_call.args[0], Name)
            or super_call.args[0].id != self.name
            or not isinstance(super_call.args[1], Name)
            or super_call.args[1].id != class_param.name
            or not isinstance(allocation.value.args[0], Name)
            or allocation.value.args[0].id != class_param.name
        ):
            return None
        # Admission is decided on the SOURCE OCCURRENCE (#7346-C).  The name is
        # bound exactly once at module level AND that one binding must be THIS
        # occurrence -- a reconstructed shell of the same class is admitted, a
        # foreign or shadowed class is not.
        bindings = (self.unit.module_direct_bindings or {}).get(self.name, ())
        if len(bindings) != 1 or not isinstance(bindings[0], Node):
            return None
        if SourceOccurrenceIdentityV1.of(bindings[0]) != (
            SourceOccurrenceIdentityV1.of(self)
        ):
            return None
        field_body = constructor.body[1:-1]
        receiver_name = allocation.targets[0].id
        formal_names = {param.name for param in constructor.params[1:]}
        field_names = []
        for statement in field_body:
            if (
                not isinstance(statement, Assign)
                or len(statement.targets) != 1
                or not isinstance(statement.targets[0], Attribute)
                or not isinstance(statement.targets[0].value, Name)
                or statement.targets[0].value.id != receiver_name
                or not isinstance(statement.value, Name)
                or statement.value.id not in formal_names
                or statement.targets[0].attr != statement.value.id
            ):
                return None
            field_names.append(statement.targets[0].attr)
        if len(field_names) != len(set(field_names)):
            return None
        return constructor, allocation.targets[0], field_body

    def substitute(self, scope):
        """A class: decorators and type params evaluate in the enclosing scope;
        the type params then bind for the bases, keywords, and body. The body is
        threaded (a class body reads the enclosing scope; it opens no closure)."""
        from .shadow import rewrite

        tnames = {
            n
            for tp in self.type_params
            for n in [getattr(tp, "name", None)]
            if isinstance(n, str)
        }
        inner = {k: v for k, v in scope.items() if k not in tnames} if tnames else scope
        changed = {}
        for fld in ("decorators", "type_params"):
            new, d = self._substitute_field(getattr(self, fld), scope)
            if d:
                changed[fld] = new
        for fld in ("bases", "keywords"):
            new, d = self._substitute_field(getattr(self, fld), inner)
            if d:
                changed[fld] = new
        new_body, d = self._substitute_body(self.body, inner)
        if d:
            changed["body"] = new_body
        return self if not changed else rewrite(self, **changed)

    def _construct_class_method_member(self, method):
        """Enroll one method through the FunctionDef construction door only.

        ClassDef owns member *membership* and field construction (L1b). Method
        bodies are FunctionDef / AsyncFunctionDef construction — not reimplemented
        here. AsyncFunctionDef shares the FunctionDef door (same formals/body shape).
        """
        from sugar_lift_py_tests.floor import ConstructedClassMethodV1

        if isinstance(method, (FunctionDef, AsyncFunctionDef)):
            # White FunctionDef door -- ClassDef does not reimplement method
            # bodies. AsyncFunctionDef shares it (same formals/body shape); its
            # universe is a coroutine factory, which the SYNC manager protocol
            # never enters. Refusing the whole class over an async member is
            # why contextlib.nullcontext (async def __aenter__) stopped at
            # force-floor the moment contextlib was enrolled (plan Cut 1).
            from sugar_lift_py_tests.floor.class_definition_value import (
                DeferredClassMethodV1,
            )
            from sugar_source_tree.panic import SugarNotWritten

            try:
                body = method.sugar()
                frame = method.source_visible_call_frame()
            except (SugarNotWritten, TypeError):
                # The class body binds the method; the method body runs only
                # when called.  Its refusal is deferred to that caller.
                return DeferredClassMethodV1(
                    method.name,
                    method.fragment.seal().cid,
                    method,
                    self._method_descriptor_kind(method),
                )
        else:
            from sugar_source_tree.panic import SugarNotWritten

            raise SugarNotWritten(
                blame=method.fragment,
                owner="ClassDef._construct_class_method_member",
                observed=f"class method species {type(method).__name__}",
                requested="FunctionDef or AsyncFunctionDef",
                fix="route method bodies through the FunctionDef construction door",
            )
        return ConstructedClassMethodV1(
            method.name,
            method.fragment.seal().cid,
            body,
            frame,
            self._method_descriptor_kind(method),
        )


    def _sugar_source_class_base(self, base):
        """Sugar a base, unwrapping a local ``Base`` or ``Base[T]`` to that class.

        Subscription supplies type arguments; it does not change which class
        owns inherited runtime methods. The module-level ClassDef binding is
        the same door ``module_direct_bindings`` already uses for allocation.
        Computed and attributed bases stay ordinary expressions.
        """
        name = None
        if isinstance(base, Name):
            name = base.id
        elif isinstance(base, Subscript) and isinstance(base.value, Name):
            name = base.value.id
        if name is not None:
            bindings = (self.unit.module_direct_bindings or {}).get(name, ())
            if len(bindings) == 1 and isinstance(bindings[0], ClassDef):
                return bindings[0].sugar()
        return base.sugar()

    def _module_name_references(self) -> dict:
        """The module's binding of each module name this class body reads,
        where that binding is the evaluation of a module write of it
        (temporal choice 1, #7661).

        A class statement the module body runs (at any depth: in an ``if``,
        a loop, another class body) runs at import, in source order: its
        body reads a module name as the module holds it when the statement
        runs (``SourceUnit.module_bindings_at``), whoever calls the class
        later and in whatever context (the class-call door, #7794).  So
        ``x = 1; x += 1; class C: y = x; x += 1`` reads ``y`` as the first
        ``x += 1``'s evaluation.  A name the class body binds itself is not
        read from the module; a binding that is no evaluation is read by
        name, as before; one the module body does not decide there is cited
        ``undecided`` by name.  A class in a function body reads its
        enclosing function's bindings and is not answered here.
        """
        unit = self.unit
        if unit.typed_module is None:
            return {}
        candidates = unit.module_evaluation_bound_names()
        if not candidates:
            return {}
        bound_here: set[str] = set()
        reads: set[str] = set()
        for statement in self.body:
            if isinstance(statement, (FunctionDef, AsyncFunctionDef, ClassDef)):
                bound_here.add(statement.name)
                continue
            bound_here |= statement.names_bound_within()
            reads.update(
                node.id for node in statement.walk() if isinstance(node, Name)
            )
        reads = (reads & candidates) - bound_here
        if not reads:
            return {}
        site = unit.module_execution_site(self)
        if site is None:
            return {}
        return _bound_module_references(
            self,
            unit.module_bindings_at(site, reads),
            owner="ClassDef._module_name_references",
        )

    def _construct_sugar(self):
        """Construct source-visible class structure through body members.

        L1b (this door): fields, nested ClassDef, conditional fields.
        Methods (FunctionDef / AsyncFunctionDef) enroll through the FunctionDef
        construction door — ClassDef does not reimplement method bodies.
        """
        if (
            not isinstance(self.binding_target, Name)
            or self.binding_target.id != self.name
        ):
            from sugar_source_tree.panic import BackendDefect

            raise BackendDefect(
                blame=self.fragment,
                owner="ClassDef._construct_sugar",
                observed="class binding target does not match its definition name",
                requested="the exact identifier child bound by this ClassDef",
                fix="carry the parser-owned ClassDef name occurrence as binding_target",
            )
        methods = tuple(
            item
            for item in self.body
            if isinstance(item, (FunctionDef, AsyncFunctionDef))
        )
        docstring_cid = None
        if self.body:
            first = self.body[0]
            if (
                isinstance(first, Expr)
                and isinstance(first.value, Constant)
                and isinstance(first.value.value, str)
            ):
                docstring_cid = first.fragment.seal().cid
        # Simple Name = <expr> fields (constants and constructed values). The
        # residual ClassDef mass is non-constant body assigns; Constant-only
        # was an over-narrow partition that left honest source-visible fields
        # as unsupported-member gaps.
        annotated_assignments = tuple(
            item
            for item in self.body
            if isinstance(item, AnnAssign) and isinstance(item.target, Name)
        )
        unsupported = tuple(
            item
            for index, item in enumerate(self.body)
            if not isinstance(item, (FunctionDef, AsyncFunctionDef, ClassDef, If, Pass))
            and not (
                index == 0
                and isinstance(item, Expr)
                and isinstance(item.value, Constant)
                and isinstance(item.value.value, str)
            )
            and not (
                isinstance(item, Assign)
                and item.targets
                and all(isinstance(target, Name) for target in item.targets)
            )
            and not (isinstance(item, AnnAssign) and isinstance(item.target, Name))
        )
        if unsupported:
            from sugar_source_tree.panic import SugarNotWritten

            raise SugarNotWritten(
                blame=unsupported[0].fragment,
                owner="ClassDef._construct_sugar",
                observed=f"unsupported class member {unsupported[0].kind}",
                requested="a total source-visible class member construction arm",
                fix="add the member's ordinary node Sugar arm or keep the class loud",
            )
        from sugar_lift_py_tests.floor import (
            ConstructedClassFieldV1,
            ConstructedClassMethodV1,
        )
        from sugar_lift_py_tests.context_manager_resolution import (
            SourceFragmentCoordinateV1,
        )
        from sugar_lift_py_tests.sugar.class_definition_sugar import (
            ClassDefinitionSugar,
            ConstructedClassConditionalFieldsV1,
        )

        references = self._module_name_references()

        def body_read(expression):
            # A module name this body reads is the module's binding of it
            # when the class statement ran (``_module_name_references``).
            if references and any(
                isinstance(node, Name) and node.id in references
                for node in expression.walk()
            ):
                expression = expression.substitute(references)
            return expression.sugar()

        def conditional_fields(statements):
            def binding_occurrence(target):
                span = target.line_col_span()
                return SourceFragmentCoordinateV1(
                    target.unit.source_cid,
                    span.start_line,
                    span.start_col,
                    span.end_line,
                    span.end_col,
                )

            fields = []
            for item in statements:
                if (
                    isinstance(item, Assign)
                    and item.targets
                    and all(isinstance(target, Name) for target in item.targets)
                ):
                    value_sugar = body_read(item.value)
                    target_keys = dict(item.target_evaluations())
                    fields.extend(
                        ConstructedClassFieldV1(
                            target.id,
                            target.fragment.seal().cid,
                            value_sugar,
                            binding_occurrence(target),
                            item.fragment.seal().cid,
                            evaluation_key=target_keys.get(target.id),
                        )
                        for target in item.targets
                    )
                    continue
                if isinstance(item, AnnAssign) and isinstance(item.target, Name):
                    if item.value is not None:
                        fields.append(
                            ConstructedClassFieldV1(
                                item.target.id,
                                item.fragment.seal().cid,
                                body_read(item.value),
                                binding_occurrence(item.target),
                                evaluation_key=dict(item.target_evaluations()).get(
                                    item.target.id
                                ),
                            )
                        )
                    continue
                if isinstance(item, ClassDef):
                    fields.append(
                        ConstructedClassFieldV1(
                            item.name,
                            item.fragment.seal().cid,
                            item.sugar(),
                            binding_occurrence(item.binding_target),
                        )
                    )
                    continue
                if isinstance(item, If):
                    fields.append(
                        ConstructedClassConditionalFieldsV1(
                            condition_fragment_cid=item.test.fragment.seal().cid,
                            condition_sugar=body_read(item.test),
                            when_true=conditional_fields(item.body),
                            when_false=conditional_fields(item.orelse),
                        )
                    )
                    continue
                if isinstance(item, Pass):
                    continue
                from sugar_source_tree.panic import SugarNotWritten

                raise SugarNotWritten(
                    blame=item.fragment,
                    owner="ClassDef._construct_sugar",
                    observed=f"unsupported conditional class member {item.kind}",
                    requested="a constructed field assignment or pass",
                    fix="add the member's ordinary class-control arm or keep it loud",
                )
            return tuple(fields)

        constructed = tuple(
            self._construct_class_method_member(method) for method in methods
        )
        fields = conditional_fields(
            tuple(
                item
                for index, item in enumerate(self.body)
                if not isinstance(item, (FunctionDef, AsyncFunctionDef, Pass))
                and not (
                    index == 0
                    and isinstance(item, Expr)
                    and isinstance(item.value, Constant)
                    and isinstance(item.value.value, str)
                )
            )
        )
        base_sugars = ()
        if self.bases:
            context = self._require_construction_context(
                owner="ClassDef._construct_sugar"
            )
            table = getattr(context, "source_class_bases", None)
            enrolled = () if table is None else table.get(self.fragment.seal().cid, ())
            # A source-base table carries already-authenticated local class
            # definitions.  Otherwise unwrap a local ``Base`` / ``Base[T]``
            # through the module binding door, and retain any other base
            # expression as Sugar so desugaring evaluates it through the
            # temporal floor. Dropping an unenrolled builtin base here erased
            # ``dict`` from ``class _EnumDict(dict)`` and fabricated a
            # plain-object receiver. Dropping ``AbstractRaises[T]`` left
            # ``super()`` with zero direct bases.
            base_sugars = enrolled or tuple(
                self._sugar_source_class_base(base) for base in self.bases
            )
        return ClassDefinitionSugar(
            class_name=self.name,
            source_identity_cid=self.unit.source_cid,
            definition_fragment_cid=self.fragment.seal().cid,
            methods=constructed,
            fields=fields,
            docstring_cid=docstring_cid,
            annotation_cids=tuple(
                item.fragment.seal().cid for item in annotated_assignments
            ),
            decorator_cids=tuple(item.fragment.seal().cid for item in self.decorators),
            binding_target_occurrence=SourceFragmentCoordinateV1(
                self.binding_target.unit.source_cid,
                self.binding_target.line_col_span().start_line,
                self.binding_target.line_col_span().start_col,
                self.binding_target.line_col_span().end_line,
                self.binding_target.line_col_span().end_col,
            ),
            decorator_sugars=tuple(item.sugar() for item in self.decorators),
            decorator_occurrences=tuple(
                SourceFragmentCoordinateV1(
                    item.unit.source_cid,
                    item.line_col_span().start_line,
                    item.line_col_span().start_col,
                    item.line_col_span().end_line,
                    item.line_col_span().end_col,
                )
                for item in self.decorators
            ),
            base_sugars=base_sugars,
            base_fragment_cids=tuple(base.fragment.seal().cid for base in self.bases),
            site=self.fragment,
            class_definition=self,
        )


    def _source_initializer_class(self) -> "ClassDef | None":
        """The class that wrote the inherited or own source ``__init__``."""
        seen: set[int] = set()

        def owner_of(definition: "ClassDef") -> "ClassDef | None":
            if id(definition) in seen:
                return None
            seen.add(id(definition))
            own = next(
                (
                    item
                    for item in reversed(definition.body)
                    if isinstance(item, FunctionDef) and item.name == "__init__"
                ),
                None,
            )
            if own is not None:
                return definition
            for base in definition.bases:
                name = None
                if isinstance(base, Name):
                    name = base.id
                elif isinstance(base, Subscript) and isinstance(base.value, Name):
                    name = base.value.id
                else:
                    return None
                bindings = (definition.unit.module_direct_bindings or {}).get(name, ())
                if len(bindings) != 1 or not isinstance(bindings[0], ClassDef):
                    return None
                found = owner_of(bindings[0])
                if found is not None:
                    return found
            return None

        return owner_of(self)

    def _source_initializer(self) -> "FunctionDef | None":
        """This class's ``__init__``, or the first authenticated local base's.

        Ordinary classes with no source initializer still inherit
        ``object.__init__`` (zero formals). Unauthenticated, computed, or
        attributed bases are not a source initializer.
        """
        owner = self._source_initializer_class()
        if owner is None:
            return None
        return next(
            (
                item
                for item in reversed(owner.body)
                if isinstance(item, FunctionDef) and item.name == "__init__"
            ),
            None,
        )

    def _dataclass_generated_init_fields(self):
        """The ``__init__`` ``@dataclasses.dataclass`` writes, as its fields.

        Lib/dataclasses.py ``_process_class`` collects the class's own
        annotated assignments, in order, as fields; ``_init_fn`` writes
        ``__init__(self, f1, f2=<default>, ...)`` with one store
        ``self.f = f`` per field, and for ``field(default_factory=F)`` the
        store ``self.f = F() if f is <sentinel> else f`` (``_field_init``):
        the factory is called once per construction when the caller omits
        the argument.

        Returns ``((name, target, default, factory), ...)``, or ``None`` for
        anything this does not model exactly: a decorator other than the bare
        stdlib ``dataclasses.dataclass`` (any argument may change ``init``,
        ``kw_only``, ``frozen`` or slots), a source ``__init__`` or
        ``__post_init__``, a base other than ``typing.Generic[...]`` (base
        dataclasses contribute fields), ``ClassVar``/``InitVar``/``KW_ONLY``
        annotations, ``field(...)`` with anything but ``default_factory`` /
        ``default``, or a non-default field after a default one (which
        dataclasses itself rejects with ``TypeError``).
        """
        unit = self.unit
        if (
            len(self.decorators) != 1
            or unit.language_callee_of(self.decorators[0])
            is not LanguageCallee.DATACLASSES_DATACLASS
        ):
            return None
        for base in self.bases:
            if not (
                isinstance(base, Subscript)
                and unit.language_callee_of(base.value) is LanguageCallee.TYPING_GENERIC
            ):
                return None
        if getattr(self, "keywords", ()):
            return None

        def mentions_special(annotation) -> bool:
            for node in annotation.walk():
                if isinstance(node, Name) and node.id in {
                    "ClassVar",
                    "InitVar",
                    "KW_ONLY",
                }:
                    return True
                if isinstance(node, Attribute) and node.attr in {
                    "ClassVar",
                    "InitVar",
                    "KW_ONLY",
                }:
                    return True
                if isinstance(node, Constant) and isinstance(node.value, str):
                    return True  # a string annotation is not read here
            return False

        fields = []
        seen_default = False
        for item in self.body:
            if isinstance(item, (FunctionDef, AsyncFunctionDef)) and item.name in {
                "__init__",
                "__post_init__",
            }:
                return None
            if not isinstance(item, AnnAssign):
                continue
            if not isinstance(item.target, Name) or not item.simple:
                return None
            if mentions_special(item.annotation):
                return None
            default = None
            factory = None
            value = item.value
            if value is not None:
                if (
                    isinstance(value, Call)
                    and unit.language_callee_of(value.func)
                    is LanguageCallee.DATACLASSES_FIELD
                ):
                    if value.args or len(value.keywords) != 1:
                        return None
                    (keyword,) = value.keywords
                    if keyword.arg == "default_factory":
                        factory = keyword.value
                    elif keyword.arg == "default":
                        default = keyword.value
                    else:
                        return None
                else:
                    default = value
            # CPython evaluates a default (and the factory expression) once,
            # at class creation; the frame re-reads them per construction.
            # That is the same value only for a constant default and a bare
            # factory name, so nothing else is modelled.
            if default is not None and not isinstance(default, Constant):
                return None
            if factory is not None and not isinstance(factory, Name):
                return None
            has_default = default is not None or factory is not None
            if seen_default and not has_default:
                return None
            seen_default = seen_default or has_default
            fields.append((item.target.id, item.target, default, factory))
        if any(name == "__dataclass_self__" for name, *_ in fields):
            return None
        return tuple(fields)

    def _dataclass_constructor_frame(self, fields, *, site, owner_cid):
        """The frame of the dataclass-written ``__init__`` (see above)."""
        from sugar_lift_py_tests.source_call_frame import SourceVisibleCallFrameV1
        from sugar_source_tree.binding_provenance import BindingCoordinateV1

        coordinates = tuple(
            BindingCoordinateV1.mint(owner_cid, target.fragment, ("dataclass-field", index))
            for index, (_name, target, _default, _factory) in enumerate(fields)
        )
        defaults = tuple(
            default
            if default is not None
            else (None if factory is None else self._make_call(factory, ()))
            for _name, _target, default, factory in fields
        )
        default_sources = tuple(
            default if default is not None else factory
            for _name, _target, default, factory in fields
        )
        formal_scope = {
            name: self._make_field_coordinate_ref(target, coordinate)
            for (name, target, _default, _factory), coordinate in zip(
                fields, coordinates, strict=True
            )
        }
        return SourceVisibleCallFrameV1(
            source_identity_cid=self.unit.source_cid,
            definition_site=site,
            definition_fragment_cid=owner_cid,
            parameters=tuple(name for name, *_ in fields),
            formal_coordinates=coordinates,
            formal_declaration_sites=tuple(
                target.fragment.seal().to_dict() for _name, target, *_ in fields
            ),
            formal_projection_paths=tuple(
                ("dataclass-field", index) for index, _ in enumerate(fields)
            ),
            parameter_kinds=tuple("positional_or_keyword" for _ in fields),
            default_sugars=tuple(
                None if default is None else default.sugar() for default in defaults
            ),
            default_nodes=defaults,
            default_fragments=tuple(
                None if source is None else source.fragment for source in default_sources
            ),
            default_fragment_cids=tuple(
                None if source is None else source.fragment.seal().cid
                for source in default_sources
            ),
            body=self._source_visible_body(formal_scope, dataclass_fields=fields),
            owner=self,
            constructed_new_method=None,
        )

    def _make_field_coordinate_ref(self, target, coordinate) -> "Node":
        from .backend import Leaf, materialize
        from .shadow import ShadowNode

        return materialize(
            self.unit,
            ShadowNode(
                "BindingCoordinateRef",
                target.span,
                (("coordinate", Leaf(coordinate)),),
            ),
            self.reporter,
        )

    def source_visible_constructor_frame(self):
        """The class call projected through its already-constructed definition."""
        from sugar_lift_py_tests.context_manager_resolution import (
            SourceFragmentCoordinateV1,
        )
        from sugar_lift_py_tests.source_call_frame import SourceVisibleCallFrameV1
        from sugar_lift_py_tests.sugar.class_constructor_body_sugar import (
            ClassConstructorBodySugar,
        )
        from sugar_source_tree.binding_provenance import BindingCoordinateV1

        initializer = self._source_initializer()
        new_shape = self._authenticated_new_constructor_shape()
        constructor = (
            initializer
            if initializer is not None
            else (None if new_shape is None else new_shape[0])
        )
        constructed_new_method = None
        new_definitions = tuple(
            item
            for item in self.body
            if isinstance(item, FunctionDef) and item.name == "__new__"
        )
        if len(new_definitions) == 1:
            from sugar_lift_py_tests.floor import ConstructedClassMethodV1

            new_definition = new_definitions[0]
            constructed_new_method = ConstructedClassMethodV1(
                new_definition.name,
                new_definition.fragment.seal().cid,
                new_definition.sugar(),
                new_definition.source_visible_call_frame(),
                self._method_descriptor_kind(new_definition),
            )
        owner_cid = self.fragment.seal().cid
        span = self.line_col_span()
        site = SourceFragmentCoordinateV1(
            self.unit.source_cid,
            span.start_line,
            span.start_col,
            span.end_line,
            span.end_col,
        )
        # A source class without ``__init__`` that is an exception type inherits
        # BaseException's constructor law: ``(*args)``.  Ordinary new-style
        # classes inherit ``object.__init__`` (zero formals).  Installing the
        # empty frame at ``raise OptionError(msg)`` was minting
        # SourceCallBindingGap("unconsumed call actual") for every argumented
        # exception construction during module-wide frame resolution — and that
        # silence blocked authenticated generator managers whose helpers only
        # *mention* those raises.
        if initializer is None and new_shape is None and not new_definitions:
            dataclass_fields = self._dataclass_generated_init_fields()
            if dataclass_fields is not None:
                return self._dataclass_constructor_frame(
                    dataclass_fields, site=site, owner_cid=owner_cid
                )
        if initializer is None and self._inherits_default_exception_constructor():
            args_coordinate = BindingCoordinateV1.mint(
                owner_cid, self.fragment, ("inherited-exception-args", 0)
            )
            return SourceVisibleCallFrameV1(
                source_identity_cid=self.unit.source_cid,
                definition_site=site,
                definition_fragment_cid=owner_cid,
                parameters=("args",),
                formal_coordinates=(args_coordinate,),
                formal_declaration_sites=(self.fragment.seal().to_dict(),),
                formal_projection_paths=(("inherited-exception-args", 0),),
                parameter_kinds=("vararg",),
                default_sugars=(None,),
                default_nodes=(None,),
                default_fragments=(None,),
                default_fragment_cids=(None,),
                body=self._source_visible_body(
                    {}, constructed_new_method=constructed_new_method
                ),
                owner=self,
                constructed_new_method=constructed_new_method,
            )
        params = () if constructor is None else constructor.params[1:]
        coordinates = tuple(
            BindingCoordinateV1.mint(owner_cid, param.fragment, ("formal", index))
            for index, param in enumerate(params)
        )
        formal_scope = {
            param.name: self._make_constructor_coordinate_ref(param, coordinate)
            for param, coordinate in zip(params, coordinates, strict=True)
        }
        return SourceVisibleCallFrameV1(
            source_identity_cid=self.unit.source_cid,
            definition_site=site,
            definition_fragment_cid=owner_cid,
            parameters=tuple(param.name for param in params),
            formal_coordinates=coordinates,
            formal_declaration_sites=tuple(
                param.fragment.seal().to_dict() for param in params
            ),
            formal_projection_paths=tuple(
                ("formal", index) for index, _ in enumerate(params)
            ),
            parameter_kinds=tuple(param.param_kind for param in params),
            default_sugars=tuple(
                param.default.sugar() if param.default is not None else None
                for param in params
            ),
            default_nodes=tuple(param.default for param in params),
            default_fragments=tuple(
                param.default.fragment if param.default is not None else None
                for param in params
            ),
            default_fragment_cids=tuple(
                param.default.fragment.seal().cid if param.default is not None else None
                for param in params
            ),
            body=self._source_visible_body(
                formal_scope, constructed_new_method=constructed_new_method
            ),
            owner=self,
            constructed_new_method=constructed_new_method,
        )

    def _inherits_default_exception_constructor(self) -> bool:
        """Whether this class inherits BaseException's ``(*args)`` constructor.

        Identity is the authenticated base graph, never the class spelling:
        each base resolves through ``SourceUnit.exception_type_identity`` (its
        binding -- the builtin namespace nothing rebinds, ``from builtins
        import``, or the one module class statement binding it), and a source
        class is walked through its own bases in turn.  A non-exception class
        without ``__init__`` still takes zero arguments (object construction);
        only exception ancestry opens ``*args``.
        """
        unit = self.unit
        visiting: set[int] = set()

        def base_is_exception(base) -> bool:
            if not isinstance(base, Name):
                return False
            identity = unit.exception_type_identity(base)
            if identity is None:
                return False
            if unit._builtin_exception_ancestry(identity) is not None:
                return True
            bindings = (unit.module_direct_bindings or {}).get(base.id, ())
            if len(bindings) != 1 or not isinstance(bindings[0], ClassDef):
                return False
            (definition,) = bindings
            if id(definition) in visiting:
                return False
            visiting.add(id(definition))
            try:
                return any(base_is_exception(item) for item in definition.bases)
            finally:
                visiting.remove(id(definition))

        return any(base_is_exception(base) for base in self.bases)

    def _make_constructor_coordinate_ref(self, param: "Param", coordinate) -> "Node":
        from .backend import Leaf, materialize
        from .shadow import ShadowNode

        return materialize(
            self.unit,
            ShadowNode(
                "BindingCoordinateRef",
                param.span,
                (("coordinate", Leaf(coordinate)),),
            ),
            self.reporter,
        )

    def _source_visible_body(
        self, scope, *, constructed_new_method=None, dataclass_fields=None
    ):
        from sugar_lift_py_tests.sugar.class_constructor_body_sugar import (
            ClassConstructorBodySugar,
        )
        from sugar_source_tree.binding_provenance import BindingCoordinateV1
        from sugar_source_tree.binding_state import BindingEntryV1

        initializer = self._source_initializer()
        initializer_body = None
        receiver_coordinate_cid = None
        if dataclass_fields is not None:
            # ``_init_fn``: one ``__dataclass_self__.f = f`` per field, in
            # field order (the receiver name CPython uses, which no field
            # may spell -- checked when the fields were read).
            from sugar_lift_py_tests.sugar.source_visible_function_body_sugar import (
                SourceVisibleFunctionBodySugar,
            )

            coordinate = BindingCoordinateV1.mint(
                self.fragment.seal().cid, self.fragment, ("dataclass-receiver", 0)
            )
            receiver = self._make_constructed_receiver_ref(coordinate.cid)
            receiver_coordinate_cid = coordinate.cid
            receiver_name = "__dataclass_self__"
            stores = tuple(
                self._make_assign(
                    self._make_attribute(For._make_name(self, receiver_name), name),
                    For._make_name(self, name),
                )
                for name, *_ in dataclass_fields
            )
            constructor_scope = {
                receiver_name: BindingEntryV1(coordinate, receiver, None),
                **scope,
            }
            substituted_body, _ = self._substitute_body(stores, constructor_scope)
            initializer_body = SourceVisibleFunctionBodySugar(
                tuple(statement.sugar() for statement in substituted_body),
                self.fragment,
            )
        elif initializer is not None:
            receiver_param = initializer.params[0]
            coordinate = BindingCoordinateV1.mint(
                self.fragment.seal().cid,
                receiver_param.fragment,
                ("receiver", 0),
            )
            receiver = self._make_constructed_receiver_ref(coordinate.cid)
            receiver_coordinate_cid = coordinate.cid
            initializer_scope = {
                receiver_param.name: BindingEntryV1(
                    coordinate, receiver, None  # unsealed; seal when testified
                ),
                **scope,
            }
            initializer_body = initializer._source_visible_body(initializer_scope)
        else:
            new_shape = self._authenticated_new_constructor_shape()
            if new_shape is not None:
                from sugar_lift_py_tests.sugar.source_visible_function_body_sugar import (
                    SourceVisibleFunctionBodySugar,
                )

                constructor, receiver_target, field_body = new_shape
                coordinate = BindingCoordinateV1.mint(
                    self.fragment.seal().cid,
                    receiver_target.fragment,
                    ("receiver", 0),
                )
                receiver = self._make_constructed_receiver_ref(coordinate.cid)
                receiver_coordinate_cid = coordinate.cid
                constructor_scope = {
                    receiver_target.id: BindingEntryV1(coordinate, receiver, None),
                    **scope,
                }
                substituted_body, _ = constructor._substitute_body(
                    field_body, constructor_scope
                )
                initializer_body = SourceVisibleFunctionBodySugar(
                    tuple(statement.sugar() for statement in substituted_body),
                    constructor.fragment,
                )
        return ClassConstructorBodySugar(
            definition=self.sugar(),
            initializer_body=initializer_body,
            receiver_coordinate_cid=receiver_coordinate_cid,
            site=self.fragment,
            constructed_new_method=constructed_new_method,
        )

    def _make_constructed_receiver_ref(self, receiver_coordinate_cid):
        from .backend import Leaf, materialize
        from .shadow import ShadowNode

        return materialize(
            self.unit,
            ShadowNode(
                "ConstructedReceiverRef",
                self.span,
                (
                    ("class_name", Leaf(self.name)),
                    ("binding_coordinate_cid", Leaf(receiver_coordinate_cid)),
                ),
            ),
            self.reporter,
        )


class Return(Statement):
    value: Optional[Expression]
    _child_fields = ("value",)

    def substitute(self, scope):
        """`return <expr>` binds nothing: recurse into the returned expression."""
        return self._substitute_children(scope)

    def _construct_sugar(self):
        """Construct the function exit, including Python's real empty return."""
        from sugar_lift_py_tests.sugar.return_sugar import ReturnSugar

        return ReturnSugar(
            value=self.value.sugar() if self.value is not None else None,
            site=self.fragment,
        )


class Delete(Statement):
    _bound_target_fields = ("targets",)
    targets: Tuple[Expression, ...]
    _child_fields = ("targets",)

    def substitute(self, scope):
        """Lower supported targets to ordered delete operations."""
        if any(not isinstance(t, (Name, Attribute, Subscript)) for t in self.targets):
            return self._substitute_children(scope)

        if len(self.targets) == 1 and isinstance(self.targets[0], Subscript):
            from .container_mutation import mutation_statement

            target = self.targets[0]
            # ``del r[k]`` and ``del r[lo:hi:st]`` alike: the slice is the
            # key ``__delitem__`` receives.
            mutation = mutation_statement(
                self,
                scope,
                call_site=target,
                receiver=target.value.substitute(scope),
                method="__delitem__",
                args=(target.slice_.substitute(scope),),
            )
            if mutation is not None:
                return mutation

        current = dict(scope)
        operations = []
        for target in self.targets:
            if isinstance(target, Name):
                prior = _explicit_state(target.id, current)
                if prior is _MISSING:
                    prior = UnboundBinding(name=target.id, cause=target.fragment)
                operation = self._make_delete_name(target.id, prior, target.span)
                current[target.id] = UnboundBinding(
                    name=target.id, cause=target.fragment
                )
            elif isinstance(target, Attribute):
                operation = self._make_delete_attribute(
                    target.value.substitute(current), target.attr, target.span
                )
            else:
                operation = self._make_delete_subscript(
                    target.value.substitute(current),
                    target.slice_.substitute(current),
                    target.span,
                )
            operations.append(operation)
        return operations[0] if len(operations) == 1 else _Splice(tuple(operations))

    def _construct_sugar(self):
        """Construct the exact module-level subscript-delete statement."""
        if len(self.targets) == 1 and isinstance(self.targets[0], Subscript):
            target = self.targets[0]
            return self._make_delete_subscript(
                target.value, target.slice_, target.span
            ).sugar()
        from .panic import SugarNotWritten

        raise SugarNotWritten(
            blame=self.fragment,
            owner="Delete._construct_sugar",
            observed="delete statement is not one exact subscript target",
            requested="one source-authenticated subscript delete occurrence",
            fix="lower other delete targets through their typed construction owner",
        )

    def _make_delete_name(
        self, name: str, prior: BindingState, span: Span | None = None
    ) -> "Node":
        from .backend import Leaf, materialize
        from .shadow import ShadowNode

        return materialize(
            self.unit,
            ShadowNode(
                "DeleteName",
                span or self.span,
                (("name", Leaf(name)), ("prior", Leaf(prior))),
            ),
            self.reporter,
        )

    def _make_delete_attribute(self, receiver, attr: str, span: Span) -> "Node":
        from .backend import Child, Leaf, materialize
        from .shadow import ShadowNode, _handle_of

        return materialize(
            self.unit,
            ShadowNode(
                "DeleteAttribute",
                span,
                (("receiver", Child(_handle_of(receiver))), ("attr", Leaf(attr))),
            ),
            self.reporter,
        )

    def _make_delete_subscript(self, receiver, index, span: Span) -> "Node":
        from .backend import Child, materialize
        from .shadow import ShadowNode, _handle_of

        return materialize(
            self.unit,
            ShadowNode(
                "DeleteSubscript",
                span,
                (
                    ("receiver", Child(_handle_of(receiver))),
                    ("index", Child(_handle_of(index))),
                ),
            ),
            self.reporter,
        )


def _substituted_store_target(statement, target, scope):
    """Substitute the receiver (and subscript index) of a store target.

    The attribute/subscript NAME is a store selector, never a reference, but
    the RECEIVER is an ordinary expression: it is what carries an authenticated
    object place or a constructed receiver into the store. Returns the rewritten
    target, or ``None`` when nothing changed.
    """
    from .shadow import rewrite

    receiver, receiver_changed = statement._substitute_field(target.value, scope)
    changes = {"value": receiver} if receiver_changed else {}
    if isinstance(target, Subscript):
        index, index_changed = statement._substitute_field(target.slice_, scope)
        if index_changed:
            changes["slice_"] = index
        if isinstance(receiver, ObjectPlaceStateV1):
            projected = receiver.subscript_key_projection(index)
            if projected is not None:
                changes["slice_"] = projected
    return rewrite(target, **changes) if changes else None


def _substituted_unpack_store_leaves(statement, target, scope):
    """Thread load-side receivers/keys for store leaves inside a flat unpack.

    Name (and starred-Name) leaves are binding sites and stay untouched.
    Attribute/Subscript leaves load their receiver and index, so they take the
    same ``_substituted_store_target`` door as a standalone store. Nested
    unpack shapes are not rewritten here — they stay on the name-only or loud
    paths owned elsewhere.
    """
    from .shadow import rewrite

    if not isinstance(target, (Tuple_, List)):
        return None
    new_elts = []
    changed = False
    for leaf in target.elts:
        if isinstance(leaf, (Attribute, Subscript)):
            rewritten = _substituted_store_target(statement, leaf, scope)
            if rewritten is not None:
                new_elts.append(rewritten)
                changed = True
                continue
        new_elts.append(leaf)
    if not changed:
        return None
    return rewrite(target, elts=tuple(new_elts))


def _valued_store_target_sugar(target, value_sugar, site):
    """The ONE ladder for a valued attribute/subscript store target.

    ``o.x = v`` and ``o.x: T = v`` are the SAME runtime store — an annotation
    is never checked at runtime, so it states nothing and may not move the
    store to a different arm. Both spellings therefore construct through this
    one ladder: an authenticated object place is a place assign, a constructed
    receiver is a receiver field store, and any other receiver is the typed
    runtime store effect. Returns ``None`` for a target this ladder does not
    own, so the caller stays loud.
    """
    from sugar_lift_py_tests.sugar.place_assign_sugar import PlaceAssignSugar

    if isinstance(target, Attribute):
        if isinstance(target.value, ObjectPlaceStateV1):
            return PlaceAssignSugar(
                receiver=target.value.sugar(),
                selector_kind="attribute",
                selector=target.attr,
                value=value_sugar,
                site=site,
            )
        if isinstance(target.value, (BindingCoordinateRef, ConstructedReceiverRef)):
            from sugar_lift_py_tests.sugar.receiver_field_store_sugar import (
                ReceiverFieldStoreSugar,
            )

            return ReceiverFieldStoreSugar(
                receiver=target.value.sugar(),
                value=value_sugar,
                attr=target.attr,
                site=site,
            )
        from sugar_lift_py_tests.sugar.store_effect_sugar import (
            AttributeStoreEffectSugar,
        )

        return AttributeStoreEffectSugar(
            receiver=target.value.sugar(),
            value=value_sugar,
            attr=target.attr,
            site=site,
        )
    if isinstance(target, Subscript):
        if isinstance(target.value, ObjectPlaceStateV1):
            return PlaceAssignSugar(
                receiver=target.value.sugar(),
                selector_kind="subscript",
                selector=target.slice_.sugar(),
                value=value_sugar,
                site=site,
            )
        from sugar_lift_py_tests.sugar.store_effect_sugar import (
            SubscriptStoreEffectSugar,
        )

        return SubscriptStoreEffectSugar(
            receiver=target.value.sugar(),
            index=target.slice_.sugar(),
            value=value_sugar,
            site=site,
        )
    return None


def _store_target_binding(statement, target, scope):
    """Thread an authenticated object place forward across a store.

    ``o.x = v`` and ``o.x: T = v`` update the same place, so both report the
    same binding: every name bound to that exact object identity carries the
    stored field onward. A receiver that is not an authenticated place threads
    nothing — the store is an effect, not a lexical binding.
    """
    if not isinstance(target.value, ObjectPlaceStateV1):
        return None
    if isinstance(target, Attribute):
        updated = target.value.with_attribute_store(
            target.attr, statement.value, statement.fragment
        )
    else:
        updated = target.value.with_subscript_store(
            target.slice_, statement.value, statement.fragment
        )
    if updated is None:
        return None
    return {
        name: replace(entry, state=updated)
        for name, entry in scope.items()
        if isinstance(name, str)
        and isinstance(entry, BindingEntryV1)
        and isinstance(entry.state, ObjectPlaceStateV1)
        and entry.state.object_identity_cid == target.value.object_identity_cid
    }


def _receiver_field_projection_binding(statement, target, scope):
    if not isinstance(target, Attribute):
        return None
    receiver_coordinate_cid = _receiver_coordinate_cid(target.value)
    if receiver_coordinate_cid is None:
        return None
    prior = scope.get(_RECEIVER_FIELD_PROJECTIONS)
    projections = dict(prior) if isinstance(prior, dict) else {}
    key = (receiver_coordinate_cid, target.attr)
    projections[key] = _ReceiverFieldProjection(
        receiver_coordinate_cid=receiver_coordinate_cid,
        selector=target.attr,
        store_occurrence=statement.fragment,
        value=statement.value,
    )
    return {_RECEIVER_FIELD_PROJECTIONS: projections}


def _has_authenticated_source_method(receiver, name: str) -> bool:
    """Whether this exact constructed receiver carries a source override."""
    if not isinstance(receiver, ObjectPlaceStateV1):
        return False
    value = receiver.constructed_value
    return bool(getattr(value, "has_method", lambda _name: False)(name))


def _keyed_target_binding(statement, binding, keys: dict, targets) -> dict:
    """``binding`` (each target name to the value node substitution gave it)
    with every name in ``keys`` bound instead to a reference to its key, at
    its target leaf: the one way an assignment's target is read after it
    (``Assign``, ``AnnAssign``).  The value node rides on the reference as
    the object the name denotes (``_evaluation_ref``, ``of``)."""
    if not binding or not keys:
        return binding
    leaves = {}
    for target in targets:
        leaves.update(_unpack_target_names(target))
    return {
        name: (
            _evaluation_ref(
                statement,
                leaves[name].span if name in leaves else statement.span,
                keys[name],
                name,
                of=state if isinstance(state, Node) else None,
            )
            if name in keys
            else state
        )
        for name, state in binding.items()
    }


def _unpack_target_names(target) -> dict:
    """The Name leaves an unpacking target binds, by name: every Name under
    its Tuple/List/Starred structure, never the receiver or index of an
    Attribute/Subscript leaf.  A repeated name keeps its last leaf, the store
    that is live after the statement."""
    names: dict = {}

    def collect(node) -> None:
        if isinstance(node, Name):
            names.pop(node.id, None)
            names[node.id] = node
        elif isinstance(node, Starred):
            collect(node.value)
        elif isinstance(node, (Tuple_, List)):
            for child in node.elts:
                collect(child)

    collect(target)
    return names


class Assign(Statement):
    _bound_target_fields = ("targets",)
    targets: Tuple[Expression, ...]
    value: Expression
    _child_fields = ("targets", "value")

    def substitute(self, scope):
        """Substitute the RHS, and load-side store target coordinates.

        Plain Name targets are BINDING SITES -- never substituted (that would
        rewrite the name being bound). Attribute/Subscript store targets load
        their receiver (and subscript index) as ordinary expressions: those
        faces must substitute so a prior ``xs = [0]`` reaches ``xs[0] = v`` as
        a decided list. The same load law applies to store leaves inside a flat
        unpack (``x, xs[0] = p, q``): Name leaves stay binding sites; store
        leaves thread receivers and keys. The binding this statement introduces
        for the rest of the block is reported by substitution_binding().
        """
        from .shadow import rewrite, rewrite_with_leaves

        mutation = self._builtin_container_mutation(scope)
        if mutation is not None:
            return mutation
        mapping_pop = self._mapping_pop_assignment(scope)
        if mapping_pop is not None:
            return mapping_pop

        new_value, changed = self._substitute_field(self.value, scope)
        field_state = self._receiver_field_store_state(scope, new_value)
        if field_state is not None:
            return field_state
        changes = {"value": new_value} if changed else {}
        if len(self.targets) == 1 and isinstance(
            self.targets[0], (Attribute, Subscript)
        ):
            new_target = _substituted_store_target(self, self.targets[0], scope)
            if new_target is not None:
                changes["targets"] = (new_target,)
        elif len(self.targets) == 1 and isinstance(self.targets[0], (Tuple_, List)):
            new_target = _substituted_unpack_store_leaves(self, self.targets[0], scope)
            if new_target is not None:
                changes["targets"] = (new_target,)
        # No retention: the relation is keyed by SOURCE OCCURRENCE, and the
        # rewrite denotes the same occurrence, so its row joins by construction.
        rewritten = self if not changes else rewrite(self, **changes)
        if rewritten._dynamic_unpack_target() is None and not (
            rewritten._keyed_names()
        ):
            return rewritten
        # ``a, b = f()``: the statement's one evaluation is unpacked at
        # reduce.  ``y = e``, whatever ``e`` is: the statement evaluates ``e``
        # once, here.  Either way, carry the key so every later read of a
        # target is a reference to that target's projection of it (temporal
        # choice 1).
        leaves = {
            "evaluation": self._evaluation_key(scope),
            "evaluation_exit_path": self._evaluation_exit_path(scope),
        }
        return rewrite_with_leaves(rewritten, leaves)

    def _dynamic_unpack_target(self):
        """The Tuple/List target of an unpack whose right-hand side is not a
        display, or None.  Substitution cannot pair such a target with
        members; the statement's sugar unpacks its one evaluation at reduce
        (``DynamicUnpackAssignSugar``, ``NestedDynamicUnpackAssignSugar``,
        ``DynamicUnpackStoreAssignSugar``)."""
        if len(self.targets) != 1:
            return None
        target = self.targets[0]
        if not isinstance(target, (Tuple_, List)) or not target.elts:
            return None
        if isinstance(self.value, (Tuple_, List)):
            return None
        return target

    def _unpack_projection_binding(self):
        """``a, b = f()`` binds each Name target to a reference to its
        projection of the statement's one evaluation (temporal choice 1,
        #7661): the unpack sugar binds each member under that projection at
        reduce.  Before, it bound nothing, and a later read fell to the
        name's prior state (the seeded unbound state: a false NameError).
        A statement that was never substituted carries no key and binds
        nothing.

        Where the right-hand side's key holds a ground display (``xs = [1, 2,
        3]; a, *b = xs``), each reference carries the member that display
        gives its name as the object it denotes (``_ground_members``): ``b``
        denotes the new list ``[2, 3]``.  The reads still read the
        projections; the members only decide later shapes (``for y in
        b``)."""
        evaluation = getattr(self, "evaluation", None)
        target = self._dynamic_unpack_target()
        if not isinstance(evaluation, str) or target is None:
            return None
        from sugar_lift_py_tests.temporal.temporal_context import projection_key

        members = self._ground_members(target)
        bindings = {
            name: _evaluation_ref(
                self,
                leaf.span,
                projection_key(evaluation, name),
                name,
                of=members.get(name),
            )
            for name, leaf in _unpack_target_names(target).items()
        }
        return bindings or None

    def _ground_members(self, target) -> dict:
        """Each Name leaf of ``target`` to the member of the right-hand side's
        ground display it is given (``_ground_value``,
        ``TargetPatternV1.bindings_for``; a starred leaf the new list of the
        members it takes), or nothing where the value is not a ground display,
        the target is no binding pattern, or the arity does not match."""
        ground = _ground_value(self.value)
        if ground is None or ground.kind not in ("List", "Tuple"):
            return {}
        enrollment = self.unit.target_pattern_enrollment(self)
        if not isinstance(
            enrollment, TargetPatternEnrolledV1
        ) or not enrollment.covers(target):
            return {}
        owner = self.unit.require_target_pattern_for_target(target).consumer_occurrence
        members = self.unit.require_target_pattern(owner, target).bindings_for(ground)
        return members or {}

    def _name_values(self) -> dict:
        """The value node substitution binds each Name target to: the
        right-hand side for ``y = e`` and ``a = b = e`` (Attribute/Subscript
        targets among them bind no name), each display member for ``a, b =
        p, q`` (a Name leaf beside store leaves included).  A non-display
        unpack binds its targets to its projections instead and has none."""
        if len(self.targets) == 1:
            target = self.targets[0]
            if isinstance(target, Name):
                return {target.id: self.value}
            if (
                not isinstance(target, (Tuple_, List))
                or self._dynamic_unpack_target() is not None
            ):
                return {}
            name_only = self._destructured_binding()
            if name_only is not None:
                return dict(name_only)
            pairs = self._flat_store_unpack_pairs()
            if pairs is None:
                return {}
            return self._name_bindings_from_store_unpack(pairs)
        if all(isinstance(t, (Name, Attribute, Subscript)) for t in self.targets):
            return {t.id: self.value for t in self.targets if isinstance(t, Name)}
        return {}

    def _keyed_names(self) -> tuple:
        """Every Name target this statement binds by value
        (``_name_values``): ``y = e`` whatever ``e`` is, each Name of a chain
        (``y = z = e``), each Name leaf of a display unpack (``a, b = p,
        q``).  Each is bound to its own projection of this statement's
        evaluation (``target_evaluations``), never to the right-hand side: a
        read of ``y`` that inlined ``e`` evaluated ``e`` again where ``y`` was
        read, against whatever had been rebound since (``x += 1; y = x + 0;
        x += 1; return y``)."""
        return tuple(self._name_values())

    def target_evaluations(self) -> tuple:
        """``(name, key)`` for each keyed Name target (``_keyed_names``):
        ``key`` is the target's projection of this statement's evaluation
        (``Statement._evaluation_key``, ``projection_key``).  The statement's
        sugar binds the value its right-hand side completed with under that
        key at reduce, and every later read of the name is a reference to it.
        A statement that was never substituted carries no key and has none."""
        evaluation = getattr(self, "evaluation", None)
        if not isinstance(evaluation, str) or self._dynamic_unpack_target() is not None:
            return ()
        from sugar_lift_py_tests.temporal.temporal_context import projection_key

        return tuple(
            (name, projection_key(evaluation, name)) for name in self._keyed_names()
        )

    def _keyed_binding(self, binding):
        """``binding`` with each keyed Name target bound to a reference to its
        projection of this statement's evaluation, carrying the right-hand
        side it was given as the object it denotes (``_evaluation_ref``,
        ``of``)."""
        return _keyed_target_binding(
            self, binding, dict(self.target_evaluations()), self.targets
        )

    def _receiver_field_store_state(self, scope, new_value):
        """Thread ``name.attr = value`` into later reads of that exact name."""
        if len(self.targets) != 1 or not isinstance(self.targets[0], Attribute):
            return None
        target = self.targets[0]
        if not isinstance(target.value, Name) or target.value.id not in scope:
            return None
        receiver = target.value.substitute(scope)
        if not isinstance(receiver, Node):
            return None
        # An ordinary formal is not a constructed receiver.  Active class
        # initializers have already projected their first parameter through the
        # backend-authenticated class-owner relation, so they reach this point
        # as ConstructedReceiverRef instead.  Only the genuinely formal arm
        # falls through to AttributeStoreEffectSugar below.
        if isinstance(receiver, (FormalRef, BindingCoordinateRef)):
            return None
        from .backend import Child, Leaf, materialize
        from .shadow import ShadowNode, _handle_of

        post_state = materialize(
            self.unit,
            ShadowNode(
                "ReceiverFieldStoreState",
                self.span,
                (
                    ("receiver", Child(_handle_of(receiver))),
                    ("value", Child(_handle_of(new_value))),
                    ("attr", Leaf(target.attr)),
                ),
            ),
            self.reporter,
        )
        return materialize(
            self.unit,
            ShadowNode(
                "ReceiverFieldStoreStatement",
                self.span,
                (
                    ("receiver_name", Leaf(target.value.id)),
                    ("post_state", Child(_handle_of(post_state))),
                ),
            ),
            self.reporter,
        )

    def _builtin_container_mutation(self, scope):
        """``x = r.<mutator>(...)`` or ``r[k] = v`` on a decided list/dict/set."""
        if len(self.targets) != 1:
            return None
        from .container_mutation import mutation_statement

        target = self.targets[0]
        if isinstance(target, Subscript):
            # ``r[k] = v`` and ``r[lo:hi:st] = it`` alike: the slice is the key
            # ``__setitem__`` receives.
            return mutation_statement(
                self,
                scope,
                call_site=target,
                receiver=target.value.substitute(scope),
                method="__setitem__",
                args=(target.slice_.substitute(scope), self.value.substitute(scope)),
                value_first=True,
            )
        call = self.value
        if (
            not isinstance(target, Name)
            or not isinstance(call, Call)
            or call.keywords
            or not isinstance(call.func, Attribute)
            or any(isinstance(arg, Starred) for arg in call.args)
        ):
            return None
        mutation = mutation_statement(
            self,
            scope,
            call_site=call,
            receiver=call.func.value.substitute(scope),
            method=call.func.attr,
            args=tuple(arg.substitute(scope) for arg in call.args),
            target_name=target.id,
        )
        if mutation is not None:
            return mutation
        from .container_mutation import path_mutation_statement

        return path_mutation_statement(
            self, scope, call=call.substitute(scope), target_name=target.id
        )

    def _mapping_pop_assignment(self, scope):
        """Split ``result = mapping.pop(key, default)`` into two SSA bindings.

        Python's operation has two products: the expression result and the
        receiver's post-mutation state.  Both are derived from the same source
        occurrence and threaded by the shadow tree; neither is reconstructed
        from a later spelling of the receiver.
        """
        if not (
            len(self.targets) == 1
            and isinstance(self.targets[0], Name)
            and isinstance(self.value, Call)
            and not self.value.keywords
            and len(self.value.args) == 2
            and isinstance(self.value.func, Attribute)
            and self.value.func.attr == "pop"
            and isinstance(self.value.func.value, Name)
        ):
            return None
        receiver_name = self.value.func.value.id
        receiver = self.value.func.value.substitute(scope)
        if _has_authenticated_source_method(receiver, "pop"):
            return None

        from .backend import Child, Leaf, materialize
        from .shadow import ShadowNode, _handle_of

        key = self.value.args[0].substitute(scope)
        default = self.value.args[1].substitute(scope)

        def projection(kind):
            return materialize(
                self.unit,
                ShadowNode(
                    kind,
                    self.span,
                    (
                        ("receiver", Child(_handle_of(receiver))),
                        ("key", Child(_handle_of(key))),
                        ("default", Child(_handle_of(default))),
                    ),
                ),
                self.reporter,
            )

        return materialize(
            self.unit,
            ShadowNode(
                "MappingPopAssignStatement",
                self.span,
                (
                    ("target_name", Leaf(self.targets[0].id)),
                    ("receiver_name", Leaf(receiver_name)),
                    ("result", Child(_handle_of(projection("MappingPopResult")))),
                    ("post_state", Child(_handle_of(projection("MappingPopState")))),
                ),
            ),
            self.reporter,
        )

    def _destructured_binding(self):
        # Destructure only an already-constructed Tuple/List display.  This is
        # structural projection, not an iterator guess: a symbolic/opaque RHS
        # has no authenticated cardinality and therefore stays loud.
        #
        # Lexical binding patterns only. Attribute/Subscript (and mixed) unpack
        # targets are intentionally NOT enrolled as binding patterns (see
        # ``_is_binding_target_pattern`` and
        # ``test_attribute_only_unpack_is_not_minted_as_a_binding_pattern``).
        # Calling ``require_target_pattern`` when none was minted is a hierarchy
        # lie — it dresses a non-binding unpack as ``foreign-target-occurrence``
        # and aborts the file. Return None so mixed/store unpack falls through
        # to ``_flat_store_unpack_pairs`` / store construction.
        target = self.targets[0]
        if not isinstance(target, (Tuple_, List)):
            return None
        enrollment = self.unit.target_pattern_enrollment(self)
        if not isinstance(
            enrollment, TargetPatternEnrolledV1
        ) or not enrollment.covers(target):
            # Lawful fall-through: mixed / pure-store unpack owns no binding
            # pattern.  This arm is now reached ONLY for authentic
            # non-enrollment; a stranded enrolled row goes loud below.
            return None
        # The pattern is read through the consumer that OWNS the target
        # occurrence: this Assign for a source assignment, or the With whose
        # as-clause this store lowers (``With._bind_store_target``).  The
        # lowered store borrows the With's span but is no source occurrence of
        # its own, so reading under ``self`` would always miss.  The owner's
        # row is still read strictly: a stranded owner refuses.
        owner = self.unit.require_target_pattern_for_target(target).consumer_occurrence
        pattern = self.unit.require_target_pattern(owner, target)
        return pattern.bindings_for(self.value)

    def _display_unpack_pairs(self, target, value):
        """Zip one Tuple/List target against a matching display RHS.

        Supports at most one starred element. Returns ``None`` when arity or
        structure cannot be authenticated from a concrete display.
        """
        if not isinstance(target, (Tuple_, List)) or not isinstance(
            value, (Tuple_, List)
        ):
            return None
        starred = [
            index
            for index, element in enumerate(target.elts)
            if isinstance(element, Starred)
        ]
        if len(starred) > 1:
            return None
        if not starred:
            if len(target.elts) != len(value.elts):
                return None
            return list(zip(target.elts, value.elts))
        star_index = starred[0]
        suffix = len(target.elts) - star_index - 1
        if len(value.elts) < len(target.elts) - 1:
            return None
        pairs = list(zip(target.elts[:star_index], value.elts[:star_index]))
        rest_end = len(value.elts) - suffix if suffix else len(value.elts)
        rest = self._make_unpack_rest_list(value.elts[star_index:rest_end])
        pairs.append((target.elts[star_index].value, rest))
        if suffix:
            pairs.extend(zip(target.elts[-suffix:], value.elts[-suffix:]))
        return pairs

    def _flat_starred_name_parts(self, target):
        """Parse a flat ``Name | *Name`` target into (prefix, star_name, suffix).

        Used for non-display RHS dynamic unpack. Nested stars, non-Name leaves,
        or more than one star stay unadmitted (``None``).
        """
        if not isinstance(target, (Tuple_, List)):
            return None
        star_indices = [
            index
            for index, element in enumerate(target.elts)
            if isinstance(element, Starred)
        ]
        if len(star_indices) != 1:
            return None
        star_index = star_indices[0]
        star = target.elts[star_index]
        if not isinstance(star.value, Name):
            return None
        prefix: list[str] = []
        suffix: list[str] = []
        for index, element in enumerate(target.elts):
            if index == star_index:
                continue
            if not isinstance(element, Name):
                return None
            if index < star_index:
                prefix.append(element.id)
            else:
                suffix.append(element.id)
        return (tuple(prefix), star.value.id, tuple(suffix))

    def _name_only_nested_unpack_pattern(self, target):
        """Name-only nested Tuple/List tree for non-display dynamic unpack.

        Flat all-Name targets stay with ``DynamicUnpackAssignSugar``. This
        admits only trees that nest at least one Tuple/List of Names (no
        Attribute/Subscript/Starred). Returns a pattern tuple for
        ``NestedDynamicUnpackAssignSugar``, or ``None``.
        """
        if not isinstance(target, (Tuple_, List)):
            return None

        def build(node):
            if isinstance(node, Name):
                return node.id
            if isinstance(node, (Tuple_, List)):
                if not node.elts:
                    return None
                parts = []
                for element in node.elts:
                    part = build(element)
                    if part is None:
                        return None
                    parts.append(part)
                return tuple(parts)
            return None

        pattern = build(target)
        if not isinstance(pattern, tuple):
            return None
        # Flat all-str is owned by DynamicUnpackAssignSugar — not nested.
        if all(isinstance(part, str) for part in pattern):
            return None
        # Every leaf must be a name (build already refused other shapes).
        return pattern

    def _flat_mixed_unpack_targets(self, target, evaluation=None):
        """Parse flat Name|Attribute|Subscript|*Name into typed unpack targets.

        At most one ``*Name``. Nested / ``*attr`` stay unadmitted. Pure Name
        leaves return ``None`` (DynamicUnpackAssignSugar owns that path).
        A Name leaf binds its member under its projection of ``evaluation``
        (the statement's one evaluation) too.
        """
        if not isinstance(target, (Tuple_, List)):
            return None
        star_indices = [
            index
            for index, element in enumerate(target.elts)
            if isinstance(element, Starred)
        ]
        if len(star_indices) > 1:
            return None
        from sugar_lift_py_tests.sugar.unpack_projection_targets import (
            AttributeUnpackTarget,
            NameUnpackTarget,
            StarUnpackTarget,
            SubscriptUnpackTarget,
        )

        targets: list[object] = []
        has_store = False
        for element in target.elts:
            if isinstance(element, Name):
                targets.append(NameUnpackTarget(element.id, evaluation=evaluation))
                continue
            if isinstance(element, Starred):
                if not isinstance(element.value, Name):
                    return None
                targets.append(
                    StarUnpackTarget(element.value.id, evaluation=evaluation)
                )
                continue
            if isinstance(element, Attribute):
                has_store = True
                targets.append(
                    AttributeUnpackTarget(
                        receiver=element.value.sugar(),
                        attr=element.attr,
                        site=element.fragment,
                    )
                )
                continue
            if isinstance(element, Subscript):
                has_store = True
                targets.append(
                    SubscriptUnpackTarget(
                        receiver=element.value.sugar(),
                        index=element.slice_.sugar(),
                        site=element.fragment,
                    )
                )
                continue
            return None
        if not has_store:
            return None
        return tuple(targets)

    def _flat_store_unpack_pairs(self):
        """Flat Name|Attribute|Subscript leaves against a display RHS.

        Nested unpack patterns stay on the name-only destructure path (or
        loud). This is the mass residual: ``o.x, o.y = p, q`` and mixed
        ``x, o.a = p, q`` / ``x, obj[key] = p, q``.

        A leaf is admitted ONLY when the constructed store retains the exact
        receiver term AND the exact RHS member it is paired with -- positional
        correspondence is the whole claim of an unpack, so a store that cannot
        carry its own value is not allowed to stand in for one. Attribute
        leaves qualify (``AttributeStoreEffectSugar`` carries receiver, attr
        and value). Subscript leaves qualify the same way after #6599:
        ``SubscriptStoreEffectSugar`` carries receiver, index, and value, so
        ``a[i], b[j] = p, q`` and ``a[i], b[j] = q, p`` construct *differently*
        and the pairing is retained. Object-place subscripts still prefer
        ``PlaceAssignSugar`` at construction. Undecided receivers stay loud
        at *desugar* time through the store law — never by refusing the leaf
        at admission.
        """
        if len(self.targets) != 1:
            return None
        target = self.targets[0]
        if not isinstance(target, (Tuple_, List)):
            return None
        if not isinstance(self.value, (Tuple_, List)):
            return None
        pairs = self._display_unpack_pairs(target, self.value)
        if pairs is None:
            return None
        for leaf, _value in pairs:
            if not isinstance(leaf, (Name, Attribute, Subscript)):
                return None
        # Only useful when at least one leaf is a store (Attribute/Subscript);
        # pure-Name flat unpack is MultiAssignSugar via _destructured_binding.
        if not any(isinstance(leaf, (Attribute, Subscript)) for leaf, _ in pairs):
            return None
        return pairs

    def _name_bindings_from_store_unpack(self, pairs):
        """Lexical Name leaves only — stores are not temporal bindings."""
        bindings = {}
        for leaf, value in pairs:
            if isinstance(leaf, Name):
                bindings[leaf.id] = value
            elif isinstance(leaf, Starred) and isinstance(leaf.value, Name):
                bindings[leaf.value.id] = value
        return bindings

    def _make_unpack_rest_list(self, elements):
        """The starred target's real CPython list result, from real RHS children."""
        from .backend import Children, materialize
        from .shadow import ShadowNode, _handle_of

        return materialize(
            self.unit,
            ShadowNode(
                "List",
                self.span,
                (
                    (
                        "elts",
                        Children(tuple(_handle_of(element) for element in elements)),
                    ),
                ),
            ),
            self.reporter,
        )

    def _binding_site_and_path(self, name: str, ordinal: int):
        del ordinal
        matches = []

        def collect(target, path):
            if isinstance(target, Name):
                if target.id == name:
                    matches.append((target.fragment, path))
                return
            if isinstance(target, Starred):
                collect(target.value, (*path, "starred"))
                return
            if isinstance(target, (Tuple_, List)):
                kind = "tuple" if isinstance(target, Tuple_) else "list"
                for index, child in enumerate(target.elts):
                    collect(child, (*path, kind, index))

        for target_index, target in enumerate(self.targets):
            collect(target, ("targets", target_index))
        if matches:
            # Repeated targets are legal; the final store is the live binding.
            return matches[-1]
        return super()._binding_site_and_path(name, 0)

    def substitution_binding(self, scope):
        # Every Name target binds to its own projection of this statement's
        # evaluation, never to the right-hand side (``_keyed_names``).
        return self._keyed_binding(self._value_binding(scope))

    def _value_binding(self, scope):
        # A single Name target binds its name to the already-substituted rhs.
        # A single Tuple/List target of plain Names destructures against a
        # matching display rhs (see _destructured_binding). A chain of plain
        # Name targets (`x = y = e`) binds each name to the same rhs.
        # A Tuple/List target against a non-display rhs binds each Name
        # target to a reference to its projection of the statement's one
        # evaluation.  Attribute / subscript targets and display arity
        # mismatches thread nothing -- their references stay honest gaps
        # rather than a wrong binding.
        if len(self.targets) == 1:
            target = self.targets[0]
            if isinstance(target, Name):
                return {target.id: self.value}
            if isinstance(target, (Attribute, Subscript)):
                threaded = _store_target_binding(self, target, scope)
                if threaded is not None:
                    return threaded
                if isinstance(target.value, ObjectPlaceStateV1):
                    return None
                projected = _receiver_field_projection_binding(self, target, scope)
                if projected is not None:
                    return projected
            # Name-only nested/flat display unpack.
            name_only = self._destructured_binding()
            if name_only is not None:
                return name_only
            # Mixed Name + Attribute/Subscript leaves against a display: bind
            # only the Name leaves; stores are construction effects, not
            # temporal bindings.
            store_pairs = self._flat_store_unpack_pairs()
            if store_pairs is not None:
                names = self._name_bindings_from_store_unpack(store_pairs)
                return names if names else None
            # A non-display right-hand side: each Name target reads its
            # projection of the statement's one evaluation.
            return self._unpack_projection_binding()
        if all(isinstance(t, (Name, Attribute, Subscript)) for t in self.targets):
            # Store targets do not bind lexical names, but they also do not
            # erase the Name targets in the same left-to-right assignment.
            return {t.id: self.value for t in self.targets if isinstance(t, Name)}
        return None

    def refine_binding_entries(self, binding, scope):
        del scope
        if len(self.targets) != 1 or not isinstance(self.targets[0], Name):
            return binding
        entry = binding.get(self.targets[0].id)
        if not isinstance(entry, BindingEntryV1):
            return binding
        if isinstance(entry.state, ObjectPlaceStateV1):
            return {
                **binding,
                self.targets[0].id: replace(
                    entry.with_testimony(entry.state.construction_testimony),
                    state=entry.state,
                ),
            }
        if isinstance(entry.state, OpaqueObjectStateV1):
            return binding
        state = self._object_place_state(entry)
        if state is None:
            return binding
        if isinstance(state, OpaqueObjectStateV1):
            return {**binding, self.targets[0].id: replace(entry, state=state)}
        return {
            **binding,
            self.targets[0].id: replace(
                entry.with_testimony(state.construction_testimony), state=state
            ),
        }

    def _object_place_state(self, entry: BindingEntryV1):
        del entry
        if not isinstance(self.value, Call):
            return None
        definition = self.unit.source_allocation_definition_for_call(self.value)
        if definition is None:
            from .backend import Child, Leaf, materialize
            from .object_identity import OpaqueObjectCoordinateV1
            from .shadow import ShadowNode, _handle_of

            coordinate = OpaqueObjectCoordinateV1.mint(
                call_occurrence=self.value.fragment,
                construction_generation=self.unit.construction_generation(self.value),
                source_cid=self.unit.source_cid,
                artifact_cid=self.unit.source_cid,
            )
            return materialize(
                self.unit,
                ShadowNode(
                    "OpaqueObjectStateV1",
                    self.targets[0].span,
                    (
                        ("object_coordinate", Leaf(coordinate)),
                        ("base", Child(_handle_of(self.value))),
                    ),
                ),
                self.reporter,
            )
        if not self.unit.source_class_has_authenticated_default_attribute_behavior(
            definition
        ):
            return None
        constructed = self._constructed_floor_value(self.value)
        if constructed is None:
            return None
        floor_value, testimony = constructed
        from sugar_lift_py_tests.floor import ObjectValue

        if not isinstance(floor_value, ObjectValue):
            return None
        # The class statement's content address is a fact of its sugar; the
        # statement is not reduced to read it.
        class_definition_cid = definition.sugar().class_definition_cid
        from .object_identity import SourceObjectCoordinateV1

        object_coordinate = SourceObjectCoordinateV1.mint(
            allocation_definition=definition.fragment,
            call_occurrence=self.value.fragment,
            construction_generation=self.unit.construction_generation(self.value),
            source_cid=self.unit.source_cid,
            artifact_cid=self.unit.source_cid,
        )
        from .backend import Child, Children, Leaf, materialize
        from .shadow import ShadowNode, _handle_of

        return materialize(
            self.unit,
            ShadowNode(
                "ObjectPlaceStateV1",
                self.targets[0].span,
                (
                    ("object_coordinate", Leaf(object_coordinate)),
                    ("class_definition_cid", Leaf(class_definition_cid)),
                    ("construction_testimony", Leaf(testimony)),
                    ("constructed_value", Leaf(floor_value)),
                    ("object_identity_cid", Leaf(object_coordinate.cid)),
                    ("base", Child(_handle_of(self.value))),
                    ("selectors", Leaf(())),
                    ("values", Children(())),
                    ("value_testimonies", Leaf(())),
                    ("version_cids", Leaf(())),
                    ("version_records", Leaf(())),
                    ("prior_version_cids", Leaf(())),
                    ("store_occurrence_cids", Leaf(())),
                    ("invalidated_by_opaque_call", Leaf(False)),
                ),
            ),
            self.reporter,
        )

    @staticmethod
    def _constructed_floor_value(value):
        from sugar_lift_py_tests.floor import CallSiteValue
        from sugar_lift_py_tests.ir import _term_content_cid
        from sugar_lift_py_tests.outcome import outcome_to_exitset
        from .binding_provenance import ConstructedValueTestimonyV1

        outcome = outcome_to_exitset(value.sugar().desugar())
        constructed = outcome.completed_value()
        # A construction testimony has no arm to carry an owed item on: an
        # owing value is not constructed here.
        if constructed is None or outcome.owed_items():
            return None
        if isinstance(constructed, CallSiteValue):
            constructed = constructed.force_floor(
                None,
                owner="Assign._constructed_floor_value",
                project_callsite=False,
            )
        term = constructed.to_term(owner="Assign._constructed_floor_value")
        testimony = ConstructedValueTestimonyV1.mint(
            value.fragment, _term_content_cid(term)
        )
        return constructed, testimony

    def post_binding_statement(self, binding):
        if len(self.targets) == 1 and isinstance(self.targets[0], Name):
            entry = binding.get(self.targets[0].id)
            if isinstance(entry, BindingEntryV1) and isinstance(
                entry.state, ObjectPlaceStateV1
            ):
                from .shadow import rewrite

                return rewrite(self, value=entry.state)
        if len(self.targets) != 1 or not isinstance(
            self.targets[0], (Attribute, Subscript)
        ):
            return self
        prior = self.targets[0].value
        if not isinstance(prior, ObjectPlaceStateV1):
            return self
        updated = next(
            (
                entry.state
                for entry in binding.values()
                if isinstance(entry, BindingEntryV1)
                and isinstance(entry.state, ObjectPlaceStateV1)
                and entry.state.object_identity_cid == prior.object_identity_cid
            ),
            None,
        )
        if updated is None:
            return self
        from .shadow import rewrite

        target = self.targets[0]
        projected = (
            updated.attribute_field(target.attr)
            if isinstance(target, Attribute)
            else updated.subscript_field(target.slice_)
        )
        if projected is None:
            return self
        return rewrite(
            self,
            targets=(rewrite(target, value=updated),),
            value=projected,
        )

    def _construct_sugar(self):
        """`<name> = <rhs>` constructs AssignSugar WITH the rhs's sugar (held as
        the deferred source). A destructured tuple/list target or a chained
        `x = y = e` whose binding threaded constructs MultiAssignSugar -- both
        are inert once substitute has done its work, exactly like the single
        Name case. Any shape whose binding did NOT thread (attribute/subscript
        targets, starred/nested tuples, arity mismatches) stays a loud gap --
        never a partial binding rendered inert."""
        if len(self.targets) == 1 and isinstance(self.targets[0], Name):
            from sugar_lift_py_tests.sugar.assign_sugar import AssignSugar

            return AssignSugar(
                name=self.targets[0].id,
                value=self.value.sugar(),
                site=self.fragment,
                evaluations=self.target_evaluations(),
            )

        if len(self.targets) == 1 and isinstance(self.targets[0], (Tuple_, List)):
            bindings = self._destructured_binding()
            if bindings is not None:
                from sugar_lift_py_tests.sugar.assign_sugar import MultiAssignSugar

                return MultiAssignSugar(
                    bindings=tuple(
                        (name, val.sugar()) for name, val in bindings.items()
                    ),
                    site=self.fragment,
                    evaluations=self.target_evaluations(),
                )
            # Flat Name|Attribute|Subscript leaves against a display RHS —
            # historical factory mass (dual-subscript / multi-attribute unpack).
            store_pairs = self._flat_store_unpack_pairs()
            if store_pairs is not None:
                from sugar_lift_py_tests.sugar.assign_sugar import (
                    UnpackStoreAssignSugar,
                )
                from sugar_lift_py_tests.sugar.store_effect_sugar import (
                    AttributeStoreEffectSugar,
                )

                name_bindings = []
                stores = []
                for leaf, val in store_pairs:
                    if isinstance(leaf, Name):
                        name_bindings.append((leaf.id, val.sugar()))
                        continue
                    if isinstance(leaf, Attribute):
                        if isinstance(leaf.value, ObjectPlaceStateV1):
                            from sugar_lift_py_tests.sugar.place_assign_sugar import (
                                PlaceAssignSugar,
                            )

                            stores.append(
                                PlaceAssignSugar(
                                    receiver=leaf.value.sugar(),
                                    selector_kind="attribute",
                                    selector=leaf.attr,
                                    value=val.sugar(),
                                    site=leaf.fragment,
                                )
                            )
                        else:
                            stores.append(
                                AttributeStoreEffectSugar(
                                    receiver=leaf.value.sugar(),
                                    value=val.sugar(),
                                    attr=leaf.attr,
                                    site=leaf.fragment,
                                )
                            )
                        continue
                    if isinstance(leaf, Subscript):
                        # Object places keep PlaceAssignSugar; every other
                        # source-visible subscript reuses the #6599 store
                        # sugar (receiver + index + paired RHS member).
                        if isinstance(leaf.value, ObjectPlaceStateV1):
                            from sugar_lift_py_tests.sugar.place_assign_sugar import (
                                PlaceAssignSugar,
                            )

                            stores.append(
                                PlaceAssignSugar(
                                    receiver=leaf.value.sugar(),
                                    selector_kind="subscript",
                                    selector=leaf.slice_.sugar(),
                                    value=val.sugar(),
                                    site=leaf.fragment,
                                )
                            )
                        else:
                            from sugar_lift_py_tests.sugar.store_effect_sugar import (
                                SubscriptStoreEffectSugar,
                            )

                            stores.append(
                                SubscriptStoreEffectSugar(
                                    receiver=leaf.value.sugar(),
                                    index=leaf.slice_.sugar(),
                                    value=val.sugar(),
                                    site=leaf.fragment,
                                )
                            )
                        continue
                    return super()._construct_sugar()
                return UnpackStoreAssignSugar(
                    bindings=tuple(name_bindings),
                    stores=tuple(stores),
                    site=self.fragment,
                    evaluations=self.target_evaluations(),
                )
            target = self.targets[0]
            if not isinstance(self.value, (Tuple_, List)) and target.elts:
                from sugar_lift_py_tests.sugar.dynamic_unpack_assign_sugar import (
                    DynamicUnpackAssignSugar,
                )

                # The statement's one evaluation: each target's member is
                # bound under its projection of this key at reduce.
                evaluation = getattr(self, "evaluation", None)
                if not isinstance(evaluation, str):
                    evaluation = None
                # Exact-arity: every leaf is a plain Name (flat).
                if all(isinstance(item, Name) for item in target.elts):
                    return DynamicUnpackAssignSugar(
                        tuple(item.id for item in target.elts),
                        self.value.sugar(),
                        self.fragment,
                        evaluation=evaluation,
                    )
                # Nested Name-only tree: ``(a, b), (c, d) = formal``.
                # Construction already exists for flat dynamic unpack; this
                # only admits the nested case that used to fall through to
                # Assign.sugar SNW (not a missing call — missing arm).
                nested = self._name_only_nested_unpack_pattern(target)
                if nested is not None:
                    from sugar_lift_py_tests.sugar.nested_dynamic_unpack_assign_sugar import (
                        NestedDynamicUnpackAssignSugar,
                    )

                    return NestedDynamicUnpackAssignSugar(
                        pattern=nested,
                        value=self.value.sugar(),
                        site=self.fragment,
                        evaluation=evaluation,
                    )
                # Starred: at most one *Name among flat Name leaves. Opaque /
                # runtime-selected RHS keeps the typed unpack obligation via
                # SequenceProjectionOperation (never a fabricated completion).
                star_parts = self._flat_starred_name_parts(target)
                if star_parts is not None:
                    prefix, star_name, suffix = star_parts
                    return DynamicUnpackAssignSugar(
                        target_names=(*prefix, *suffix),
                        value=self.value.sugar(),
                        site=self.fragment,
                        star_name=star_name,
                        prefix_names=prefix,
                        suffix_names=suffix,
                        evaluation=evaluation,
                    )
                # Store leaves (+ optional *Name) against non-display RHS.
                mixed = self._flat_mixed_unpack_targets(target, evaluation)
                if mixed is not None:
                    from sugar_lift_py_tests.sugar.assign_sugar import (
                        DynamicUnpackStoreAssignSugar,
                    )

                    return DynamicUnpackStoreAssignSugar(
                        value=self.value.sugar(),
                        targets=mixed,
                        site=self.fragment,
                    )
            return super()._construct_sugar()

        if len(self.targets) > 1 and all(isinstance(t, Name) for t in self.targets):
            from sugar_lift_py_tests.sugar.assign_sugar import ChainedAssignSugar

            value_sugar = self.value.sugar()
            return ChainedAssignSugar(
                bindings=tuple((t.id, value_sugar) for t in self.targets),
                stores=(),
                value=value_sugar,
                site=self.fragment,
                evaluations=self.target_evaluations(),
            )

        if len(self.targets) > 1 and all(
            isinstance(t, (Name, Attribute, Subscript)) for t in self.targets
        ):
            from sugar_lift_py_tests.sugar.assign_sugar import ChainedAssignSugar

            value_sugar = self.value.sugar()
            stores = []
            for target in self.targets:
                if isinstance(target, Attribute):
                    from sugar_lift_py_tests.sugar.store_effect_sugar import (
                        AttributeStoreEffectSugar,
                    )

                    stores.append(
                        AttributeStoreEffectSugar(
                            receiver=target.value.sugar(),
                            value=value_sugar,
                            attr=target.attr,
                            site=target.fragment,
                        )
                    )
                elif isinstance(target, Subscript):
                    from sugar_lift_py_tests.sugar.store_effect_sugar import (
                        SubscriptStoreEffectSugar,
                    )

                    stores.append(
                        SubscriptStoreEffectSugar(
                            receiver=target.value.sugar(),
                            index=target.slice_.sugar(),
                            value=value_sugar,
                            site=target.fragment,
                        )
                    )
            return ChainedAssignSugar(
                bindings=tuple(
                    (target.id, value_sugar)
                    for target in self.targets
                    if isinstance(target, Name)
                ),
                stores=tuple(stores),
                value=value_sugar,
                site=self.fragment,
                evaluations=self.target_evaluations(),
            )

        if len(self.targets) == 1 and isinstance(
            self.targets[0], (Attribute, Subscript)
        ):
            store = _valued_store_target_sugar(
                self.targets[0], self.value.sugar(), self.fragment
            )
            if store is not None:
                return store

        return super()._construct_sugar()


class AugAssign(Statement):
    _bound_target_fields = ("target",)
    target: Expression
    op: BinaryOperator
    value: Expression
    _child_fields = ("target", "value")

    def substitute(self, scope):
        """`<target> OP= <value>` -- substitute the value and load-side targets.

        A plain Name target is a binding site: the prior load is carried as
        ``prior_read``; the rebind itself is evaluation-time ScopeRebind of
        authenticated project_inplace (not a substitute-time BinOp).

        Attribute and Subscript targets are runtime stores — receivers (and
        subscript indices) are load expressions and must substitute so formals
        become ``FormalRefSugar`` (same door as Assign).  The operator
        occurrence is minted from the **pre-substitute** target/value structure
        and carried as ``operator_site`` so formal declaration spans cannot
        steal it.
        """
        from .backend import Child, Leaf, materialize
        from .shadow import ShadowNode, _handle_of, rewrite

        # Structural operator site before any rewrite (Name/Attribute/Subscript).
        # Name rebind is evaluation-time ScopeRebind of project_inplace — not
        # substitute-time _make_binop (__add__).  operator_site is the iadd
        # occurrence for all three targets.
        pre_sub_operator_site = None
        if isinstance(self.target, (Name, Attribute, Subscript)):
            pre_sub_operator_site = getattr(self, "operator_site", None)
            if pre_sub_operator_site is None:
                pre_sub_operator_site = self._mint_operator_site_from_structure()

        if isinstance(self.target, Name):
            # ``r += x`` on a decided list/dict/set mutates the object in
            # place: every alias sees it (container_mutation.py).
            from .container_mutation import mutation_statement

            mutation = mutation_statement(
                self,
                scope,
                call_site=self,
                receiver=self.target.substitute(scope),
                method=f"__{self.op.inplace_operator}__",
                args=(self.value.substitute(scope),),
            )
            if mutation is not None:
                return mutation

        new_value, value_changed = self._substitute_field(self.value, scope)
        changes = {"value": new_value} if value_changed else {}
        if isinstance(self.target, (Attribute, Subscript)):
            new_target = _substituted_store_target(self, self.target, scope)
            if new_target is not None:
                changes["target"] = new_target
            rewritten = self if not changes else rewrite(self, **changes)
            # Always carry pre-sub operator_site through substitute.
            desc = rewritten.ref.describe()
            return materialize(
                self.unit,
                ShadowNode(
                    desc.kind,
                    desc.raw_span or rewritten.span,
                    (
                        *desc.slots,
                        ("operator_site", Leaf(pre_sub_operator_site)),
                    ),
                ),
                self.reporter,
            )
        rewritten = self if not changes else rewrite(self, **changes)
        if not isinstance(rewritten.target, Name):
            return rewritten
        # Prior binding as the load; RHS already substituted.  Do not mint a
        # BinOp rebind child — inplace owns the binding at desugar time.
        name = rewritten.target.id
        old_state = unwrap_binding_state(scope.get(name, rewritten.target))
        old_read = binding_state_read_node(
            old_state,
            make_read=rewritten.target._make_binding_read,
        )
        desc = rewritten.ref.describe()
        # A re-substitution replaces the key slots it was given: a node
        # answers its FIRST slot of a name, so an appended key would never
        # be read.
        return materialize(
            self.unit,
            ShadowNode(
                desc.kind,
                desc.raw_span or self.span,
                (
                    *(
                        slot
                        for slot in desc.slots
                        if slot[0] not in ("evaluation", "evaluation_exit_path")
                    ),
                    ("prior_read", Child(_handle_of(old_read))),
                    ("operator_site", Leaf(pre_sub_operator_site)),
                    ("evaluation", Leaf(self._evaluation_key(scope))),
                    (
                        "evaluation_exit_path",
                        Leaf(self._evaluation_exit_path(scope)),
                    ),
                ),
            ),
            self.reporter,
        )

    def _mint_operator_site_from_structure(self):
        """Authenticated operator occurrence: gap between target and RHS spans.

        Same law as ``Compare._comparison_leg_site``: the operator token lives
        in the non-empty source interval between adjacent structural children.
        ``self.op`` testifies which operator occupies the gap — no text scan
        that could match a same-spelling string literal in the target
        (``obj['+='] += rhs``).
        """
        from sugar_source_tree.panic import SugarNotWritten
        from .fragment import SourceFragment
        from .spans import Span

        target = self.target
        value = self.value

        def reject():
            raise SugarNotWritten(
                blame=self.fragment,
                owner="AugAssign._mint_operator_site_from_structure",
                observed=(target.span, value.span, self.span),
                requested=(
                    "the source-authenticated operator interval between the "
                    "AugAssign target and its RHS (pre-substitute structure)"
                ),
                fix=(
                    "mint operator_site from target/value spans before "
                    "substitute and carry it forward; never text-scan for +="
                ),
            )

        if not (
            self.span.start <= target.span.start < target.span.end
            and target.span.end < value.span.start
            and value.span.end <= self.span.end
        ):
            reject()
        gap = Span(target.span.end, value.span.start)
        if not gap.slice(self.unit.source).strip():
            reject()
        return SourceFragment(
            unit=self.unit,
            span=gap,
            node=self,
        )

    def substitution_binding(self, scope):
        # `x OP= e` binds `x` to a reference to this statement's one
        # evaluation (temporal choice 1, #7661): AugAssignSugar binds the
        # authenticated inplace result under the evaluation key, and every
        # later read is an EvaluationRef to it -- never a substitute-time
        # BinOp/__add__, never the name looked up by spelling.  Only a plain
        # Name target binds.  A statement that was never substituted carries
        # no key: it binds the Name itself, read from the temporal.
        del scope
        if not isinstance(self.target, Name):
            return None
        evaluation = getattr(self, "evaluation", None)
        if not isinstance(evaluation, str):
            return {self.target.id: self.target}
        return {
            self.target.id: _evaluation_ref(
                self, self.target.span, evaluation, self.target.id
            )
        }

    def _construct_sugar(self):
        """`<target> OP= <value>` — Name: project_inplace owns ScopeRebind.

        Attribute/subscript targets are runtime stores (get → inplace → set).
        Name targets evaluate left/right once through the same inplace edge
        and rebind the name to that result; halt skips the rebind.
        """
        if isinstance(self.target, Name):
            from sugar_lift_py_tests.sugar.augassign_sugar import AugAssignSugar

            prior = getattr(self, "prior_read", None)
            if not isinstance(prior, Node):
                # No substitute yet (e.g. direct sugar on raw node): fall back
                # to the target as the old read.
                prior = self.target
            op_site = getattr(self, "operator_site", None)
            if op_site is None:
                op_site = self._mint_operator_site_from_structure()
            evaluation = getattr(self, "evaluation", None)
            return AugAssignSugar(
                name=self.target.id,
                left=prior.sugar(),
                right=self.value.sugar(),
                operator=type(self.op).inplace_operator,
                operation=self.op.project_inplace,
                op_site=op_site,
                site=self.fragment,
                evaluation=evaluation if isinstance(evaluation, str) else None,
            )
        if isinstance(self.target, Attribute):
            from sugar_lift_py_tests.sugar.augassign_sugar import (
                AttributeAugAssignSugar,
            )

            op_site = getattr(self, "operator_site", None)
            if op_site is None:
                op_site = self._mint_operator_site_from_structure()
            # Same substrate as subscript: get → project_inplace → setattr.
            return AttributeAugAssignSugar(
                receiver=self.target.value.sugar(),
                attr=self.target.attr,
                rhs=self.value.sugar(),
                operator=type(self.op).inplace_operator,
                operation=self.op.project_inplace,
                get_site=self.target.fragment,
                op_site=op_site,
                set_site=self.fragment,
                site=self.fragment,
            )
        if isinstance(self.target, Subscript):
            from sugar_lift_py_tests.sugar.augassign_sugar import (
                SubscriptAugAssignSugar,
            )

            # op_site: carried pre-substitute structure, or mint now if no sub.
            op_site = getattr(self, "operator_site", None)
            if op_site is None:
                op_site = self._mint_operator_site_from_structure()
            # Operator-owned double dispatch — not a caller isinstance ladder.
            return SubscriptAugAssignSugar(
                receiver=self.target.value.sugar(),
                index=self.target.slice_.sugar(),
                rhs=self.value.sugar(),
                operator=type(self.op).inplace_operator,
                operation=self.op.project_inplace,
                get_site=self.target.fragment,
                op_site=op_site,
                set_site=self.fragment,
                site=self.fragment,
            )
        return super()._construct_sugar()


class AnnAssign(Statement):
    _bound_target_fields = ("target",)
    target: Expression
    annotation: Expression
    value: Optional[Expression]
    simple: bool
    _child_fields = ("target", "annotation", "value")

    def substitute(self, scope):
        """`<target>: <ann> = <value>` -- substitute the annotation and value.

        A plain Name target is a binding site and is never substituted. An
        attribute/subscript target is a STORE, exactly as a plain Assign's is:
        its receiver is an ordinary expression and is substituted, so an
        authenticated object place or a constructed receiver reaches the store
        the same way through either spelling.

        A Name target with a value is ``y = e``: the statement evaluates ``e``
        once, here, and carries its key, so every later read of ``y`` is a
        reference to ``y``'s projection of it (``target_evaluations``)."""
        from .shadow import rewrite, rewrite_with_leaves

        changed = {}
        for fld in ("annotation", "value"):
            new, d = self._substitute_field(getattr(self, fld), scope)
            if d:
                changed[fld] = new
        if isinstance(self.target, (Attribute, Subscript)):
            new_target = _substituted_store_target(self, self.target, scope)
            if new_target is not None:
                changed["target"] = new_target
        rewritten = self if not changed else rewrite(self, **changed)
        if self.value is None or not isinstance(self.target, Name):
            return rewritten
        return rewrite_with_leaves(
            rewritten,
            {
                "evaluation": self._evaluation_key(scope),
                "evaluation_exit_path": self._evaluation_exit_path(scope),
            },
        )

    def target_evaluations(self) -> tuple:
        """``((name, key),)`` for a Name target with a value, as
        ``Assign.target_evaluations``: ``key`` is the name's projection of this
        statement's evaluation.  A bare declaration, a store target, or a
        statement never substituted has none."""
        evaluation = getattr(self, "evaluation", None)
        if (
            self.value is None
            or not isinstance(self.target, Name)
            or not isinstance(evaluation, str)
        ):
            return ()
        from sugar_lift_py_tests.temporal.temporal_context import projection_key

        return ((self.target.id, projection_key(evaluation, self.target.id)),)

    def substitution_binding(self, scope):
        # Only an annotated assignment WITH a value binds; a bare `x: int` is a
        # declaration and binds nothing. A Name target binds to its own
        # projection of this statement's evaluation, as Assign's does; an
        # attribute/subscript target over an authenticated object place threads
        # that place forward, the same store Assign reports.
        if self.value is None:
            return None
        if isinstance(self.target, Name):
            return _keyed_target_binding(
                self,
                {self.target.id: self.value},
                dict(self.target_evaluations()),
                (self.target,),
            )
        if isinstance(self.target, (Attribute, Subscript)):
            threaded = _store_target_binding(self, self.target, scope)
            if threaded is not None:
                return threaded
            return _receiver_field_projection_binding(self, self.target, scope)
        return None

    def _construct_sugar(self):
        """`<target>: <annotation> [= <value>]` -- a plain Name target with a
        value is the assignment ``<target> = <value>``: ``AssignSugar``
        evaluates the value at this statement (its halts are the
        statement's) and binds it under the target's key
        (``target_evaluations``), which every later read references.
        If there is no value, it is a bare declaration: no bytecode runs, no
        binding is introduced, nothing happens at runtime at all.  A bare
        attribute annotation is different: CPython evaluates the receiver and
        discards it, without reading the attribute or performing a store.

        The annotation itself is NEVER a fact the meaning layer states either
        way: Python does not check it at runtime (no TypeError on mismatch),
        so an annotation asserts nothing -- it is documentation the tree
        passes through, never a stated post. A valued attribute/subscript target
        is the same runtime store owned by Assign.  A bare Attribute therefore
        reuses the ordinary expression-statement path for its receiver only.
        Other bare non-Name annotations stay loud."""
        if isinstance(self.target, Name) and self.value is not None:
            from sugar_lift_py_tests.sugar.assign_sugar import AssignSugar

            return AssignSugar(
                name=self.target.id,
                value=self.value.sugar(),
                site=self.fragment,
                evaluations=self.target_evaluations(),
            )
        if isinstance(self.target, Name):
            from sugar_lift_py_tests.sugar.inert_sugar import InertSugar

            return InertSugar(site=self.fragment)
        if self.value is None and isinstance(self.target, Attribute):
            from sugar_lift_py_tests.sugar.expr_statement_sugar import (
                ExprStatementSugar,
            )

            return ExprStatementSugar(
                value=self.target.value.sugar(),
                site=self.fragment,
            )
        if self.value is not None and isinstance(self.target, (Attribute, Subscript)):
            store = _valued_store_target_sugar(
                self.target, self.value.sugar(), self.fragment
            )
            if store is not None:
                return store
        return super()._construct_sugar()


class TypeAlias(Statement):
    _bound_target_fields = ("name",)
    name: Expression
    type_params: Tuple[TypeParam, ...]
    value: Expression
    _child_fields = ("name", "type_params", "value")

    def substitute(self, scope):
        """`type <name>[<params>] = <value>` -- the type params bind for the
        value; the name is a binding site."""
        from .shadow import rewrite

        tnames = {
            n
            for tp in self.type_params
            for n in [getattr(tp, "name", None)]
            if isinstance(n, str)
        }
        inner = {k: v for k, v in scope.items() if k not in tnames} if tnames else scope
        changed = {}
        new_tp, d = self._substitute_field(self.type_params, scope)
        if d:
            changed["type_params"] = new_tp
        new_val, d = self._substitute_field(self.value, inner)
        if d:
            changed["value"] = new_val
        return self if not changed else rewrite(self, **changed)


class For(Statement):
    _bound_target_fields = ("target",)
    target: Expression
    iter: Expression
    body: Tuple[Statement, ...]
    orelse: Tuple[Statement, ...]
    _child_fields = ("target", "iter", "body", "orelse")

    def substitute(self, scope):
        """`for <target> in <iter>: <body>` -- a loop is a FOLD, and over a
        CONCRETE iterable it DISSOLVES: the fold has known length, so it unrolls.
        The body is threaded once per element (the target rebound to that
        element, every loop-carried variable threaded forward exactly as a
        straight-line block threads its assignments -- `t = t + x` reads the
        previous iteration's t), and the unrolled statements are SPLICED into the
        enclosing block via ``_Splice``. The `for` node itself is gone; its
        carried accumulator is now just block-threading over the unrolled
        sequence, and there is no loop-sugar left to write.

        A SYMBOLIC iterable is the real fold (carried variables become fold terms,
        the body a universal `forall x in iter`); it is not lifted yet, so it
        keeps the `for` node (masking the target) and inherits the loud
        SugarNotWritten. `else` and a tuple target likewise stay loud."""
        from sugar_lift_py_tests.engine_log import reduction_span

        from .shadow import rewrite

        where = f"{self.unit.filename}"
        try:
            lc = self.line_col_span()
            where = f"{self.unit.filename}:{lc.start_line}:{lc.start_col}"
        except SourceTreePanic:
            pass

        with reduction_span(sugar="For.substitute", role="temporal", site=where):
            new_iter, iter_changed = self._substitute_field(self.iter, scope)
            subst_iter = new_iter if iter_changed else self.iter

            # `else` is unrollable too: the jump-guard means no `break` exists, and
            # with no break the else ALWAYS runs -- it is just more block, spliced
            # after the unrolled iterations.
            concrete = self.target.kind in ("Name", "Tuple", "List")
            with reduction_span(
                sugar="For.concrete_elements", role="temporal", site=where
            ):
                elements = (
                    self._concrete_elements(subst_iter, self.body, scope)
                    if concrete
                    else None
                )
            if elements is not None and len(elements) > self._UNROLL_FUEL:
                elements = None  # past the unroll budget: the fold/universal stands
            if elements is not None:
                with reduction_span(sugar="For.unroll", role="temporal", site=where):
                    target_pattern = self.unit.require_target_pattern(self, self.target)
                    bindings = [target_pattern.bindings_for(e) for e in elements]
                    unpacks, bindings = self._iteration_unpacks(
                        elements, bindings, scope
                    )
                    if all(b is not None for b in bindings):
                        if self._body_has_owned_loop_control():
                            controlled = self._unroll_concrete_controlled(
                                bindings, scope, unpacks
                            )
                            if controlled is not None:
                                statements, final_bindings = controlled
                                return _Splice(statements, final_bindings)
                            # A symbolic guard owns a jump.  It cannot be selected
                            # by concrete unrolling and must remain a real loop
                            # below.
                            elements = None
                    if elements is not None and all(b is not None for b in bindings):
                        target_names = set(target_pattern.names)
                        unrolled: list = []
                        carried = dict(
                            scope
                        )  # carries loop variables across iterations
                        final_target_bindings = None
                        for index, element_bindings in enumerate(bindings):
                            final_target_bindings = element_bindings
                            iter_scope = _iteration_scope(
                                self, index, {**carried, **element_bindings}, scope
                            )
                            new_body, _c = self._substitute_body(self.body, iter_scope)
                            if unpacks[index] is not None:
                                # The iteration's unpack of its item opens it.
                                new_body = (unpacks[index], *new_body)
                            # Each iteration is its own evaluation of the body.
                            new_body = _iteration_copies(self, index, new_body)
                            unrolled.extend(new_body)
                            # thread this iteration's bindings forward (the
                            # carried fold), never the loop target's own names
                            # (rebound next iteration).
                            for stmt in new_body:
                                b = stmt.substitution_binding(iter_scope)
                                if b:
                                    iter_scope = {**iter_scope, **b}
                            carried = {
                                k: v
                                for k, v in iter_scope.items()
                                if k not in target_names
                            }
                        if self.orelse:
                            else_scope = (
                                {**carried, **final_target_bindings}
                                if final_target_bindings is not None
                                else carried
                            )
                            # The else runs once, outside every iteration.
                            else_scope = {
                                **else_scope,
                                _EVALUATION_OCCURRENCE: scope.get(
                                    _EVALUATION_OCCURRENCE, ()
                                ),
                            }
                            else_body, _c = self._substitute_body(
                                self.orelse, else_scope
                            )
                            unrolled.extend(else_body)
                        return _Splice(tuple(unrolled), final_target_bindings)
                if elements is not None:
                    # A concrete iterable whose display element the target did
                    # not destructure -- an arity or nesting the display does
                    # not match -- is a runtime binding error, never a symbolic
                    # universal. It stays loud. (A non-display element is
                    # unpacked by its iteration's keyed unpack,
                    # ``_iteration_unpacks``; the symbolic-jump case set
                    # `elements = None` above and falls through.)
                    raise SugarNotWritten(
                        owner="For.substitute",
                        blame=self.target.fragment,
                        observed=(
                            f"concrete for-loop target {self.target.kind} does not "
                            "destructure its elements"
                        ),
                        requested="a target that binds every concrete element by name",
                        fix=(
                            "use a Name or a flat tuple/list of Names matching the "
                            "element arity; a starred, nested, or arity-mismatched "
                            "target stays loud until its destructuring is written"
                        ),
                    )

            # Symbolic (or unsupported) loop: keep the node, mask the target AND
            # every loop-carried variable (a name the body rebinds), recurse.
            # Masking the carried names keeps the update SYMBOLIC in the body
            # (`total = total + x` stays, not `total = 0 + x`) so
            # substitution_binding can read the fold; the pre-loop value seeds
            # it from the outer scope. A symbolic loop is not a dead unroll --
            # it is the universal / fold over the hole.
            #
            # In the body a carried name (bound before the loop, rebound in the
            # body) is not masked to the bare name: it reads the loop header's
            # evaluation of it, the value the item began with, bound per item
            # by the recurrence (``_loop_header_bindings``).  The loop target is
            # bound per item by the recurrence itself and stays masked.  The
            # ``else`` runs once, after every item: it reads every name the
            # loop carries through the same header, which the recurrence binds
            # once more, outside every item, to the value the last item handed
            # on.
            with reduction_span(sugar="For.symbolic", role="temporal", site=where):
                target_names = set(
                    self.unit.require_target_pattern(self, self.target).names
                )
                bound = target_names | For._stmts_bound_names(self.body)
                bs = (
                    {k: v for k, v in scope.items() if k not in bound}
                    if bound
                    else scope
                )
                body_scope = {
                    **bs,
                    **_loop_header_bindings(self, bound - target_names, scope),
                }
                else_scope = {
                    **bs,
                    **_loop_header_bindings(
                        self,
                        (bound | For._stmts_bound_names(self.orelse)) - target_names,
                        scope,
                    ),
                }
                changed = {}
                if iter_changed:
                    changed["iter"] = new_iter
                for f, field_scope in (("body", body_scope), ("orelse", else_scope)):
                    new, d = self._substitute_body(getattr(self, f), field_scope)
                    if d:
                        changed[f] = new
                if not changed:
                    return self
                rewritten = rewrite(self, **changed)
                return rewritten

    @staticmethod
    def _stmts_bound_names(statements) -> set:
        """The names any statement (at any depth) binds -- the structural twin
        of _stmts_bind, for the symbolic-loop carried-name mask."""
        names: set = set()

        def bind(target) -> None:
            # A destructuring target (``n, k = ...``, ``[a, *b] = ...``) binds
            # every name it nests, exactly as a plain Name target does.
            if target.kind == "Name":
                names.add(target.id)
            elif target.kind in ("Tuple", "List"):
                for element in target.elts:
                    bind(element)
            elif target.kind == "Starred":
                bind(target.value)

        for stmt in statements:
            for n in stmt.walk():
                if n.kind in ("Assign",):
                    for t in n.targets:
                        bind(t)
                elif n.kind in ("AugAssign", "AnnAssign", "NamedExpr"):
                    bind(n.target)
        return names

    @staticmethod
    def _stmts_bind(statements) -> bool:
        """True when any statement (at any depth) binds a name for a tail --
        Assign/AugAssign/AnnAssign or a walrus. STRUCTURAL, not a binding read:
        an If no longer reports its branch bindings (phis are spliced at
        substitute time), so classification walks the source shape instead of
        asking for bindings that are only materialized during substitution."""
        return any(
            n.kind in ("Assign", "AugAssign", "AnnAssign", "NamedExpr")
            for stmt in statements
            for n in stmt.walk()
        )

    def _carried_and_facts(self):
        """Split the body into carried assignments (statements that bind a name
        for the tail -- the fold's update) and fact statements (asserts, the rest
        -- the universal's body). A pure-fold loop is all carried; an assert-only
        loop is all facts; a loop with BOTH is the accumulator-referencing case
        (point 3), left loud."""
        carried, facts = [], []
        for stmt in self.body:
            (carried if For._stmts_bind((stmt,)) else facts).append(stmt)
        return carried, facts

    def substitution_binding(self, scope):
        """Never synthesize a symbolic loop post-value.

        The only lawful symbolic post-binding is projected from a decoded
        ``LoopConstructionV1`` by ``project_loop_post_binding`` after the loop
        has constructed its exact completed faces. Until block sequencing owns
        that projection, the source occurrence remains typed-loud and contributes
        no fabricated tail binding here.
        """
        del scope
        return None

    def _make_name(self, identifier: str) -> "Node":
        from .backend import Leaf, materialize
        from .shadow import ShadowNode

        return materialize(
            self.unit,
            ShadowNode("Name", self.span, (("id", Leaf(identifier)),)),
            self.reporter,
        )

    def _make_call(self, func: "Node", args: tuple) -> "Node":
        from .backend import Child, Children, materialize
        from .shadow import ShadowNode, _handle_of

        slots = (
            ("func", Child(_handle_of(func))),
            ("args", Children(tuple(_handle_of(a) for a in args))),
            ("keywords", Children(())),
        )
        return materialize(
            self.unit, ShadowNode("Call", self.span, slots), self.reporter
        )

    def _construct_sugar(self):
        """A residual symbolic loop is typed-loud until its recurrence graph is
        sealed; it is never weakened to a universal or an inert pseudo-fold."""
        return super()._construct_sugar()

    def _body_has_loop_control(self) -> bool:
        """True when any `break`/`continue` appears anywhere in the body. The
        plain unroll repeats the body verbatim, which would duplicate the jump
        and silently mis-thread the carried state -- a break is the last hole
        being filled, and the unroll must not fake past it. Conservative on
        purpose (a nested loop's own jumps also block): over-blocking falls to
        the symbolic branch (loud), never to a wrong unroll."""
        return any(
            ("break" in stmt.segment() or "continue" in stmt.segment())
            and any(n.kind in ("Break", "Continue") for n in stmt.walk())
            for stmt in self.body
        )

    def _body_has_owned_loop_control(self) -> bool:
        target_cid = self.owned_loop_target.target_cid
        return any(
            node.kind in ("Break", "Continue")
            and node.control_context.nearest_loop_target().target_cid == target_cid
            for statement in self.body
            for node in statement.walk()
        )

    def _iteration_unpacks(self, elements, bindings, scope):
        """``for y in [x]``, ``for a, b in [p, q]``: each iteration's binding
        of its item.

        Every iteration opens with ``<target> = <element>``, keyed as that
        iteration's own evaluation (``_iteration_scope``, as #7886 keys ``x
        += e``), and each target name binds to a reference to its projection
        of that evaluation (temporal choice 1, #7661;
        ``Assign.target_evaluations``) -- never the element inlined at each
        read of the name, which read ``x`` again wherever ``y`` was read,
        after the body had rebound it (``for y in [x]: x = 9; r = y``).  A
        display element is paired by the assignment's own display unpack
        (``MultiAssignSugar``); any other element (a name, a call, a constant)
        is evaluated once and unpacked (``DynamicUnpackAssignSugar``).  The
        assignment's sugar binds each target under its projection at reduce.

        The element is already substituted (the iterable was evaluated once,
        before the loop), so the store is keyed, not substituted again: a
        later iteration's rebinding never reaches an earlier element.

        Returns ``(unpacks, bindings)``: per iteration, the keyed store (or
        None) and the target bindings (None where a display did not
        destructure, which stays loud).
        """
        from .shadow import rewrite_with_leaves

        unpacks = []
        resolved = []
        destructures = self.target.kind in ("Tuple", "List")
        for index, (element, binding) in enumerate(
            zip(elements, bindings, strict=True)
        ):
            # A display that did not destructure stays loud; a ``*xs`` member
            # of the iterable display is no one item.
            if element.kind == "Starred" or (
                destructures
                and binding is None
                and element.kind in ("Tuple", "List")
            ):
                unpacks.append(None)
                resolved.append(binding)
                continue
            iteration = _iteration_scope(self, index, scope, scope)
            store = self._make_assign(self.target, element)
            store = rewrite_with_leaves(
                store,
                {
                    "evaluation": store._evaluation_key(iteration),
                    "evaluation_exit_path": store._evaluation_exit_path(iteration),
                },
            )
            unpacks.append(store)
            resolved.append(store.substitution_binding(iteration))
        return tuple(unpacks), resolved

    def _unroll_concrete_controlled(self, bindings, scope, unpacks=None):
        """Exact AST-local execution of bounded jump-bearing loop structure.

        Only literal-decidable branch guards are selected.  A symbolic guard
        returns ``None`` so the source loop remains typed and loud/opaque.
        ``unpacks`` (``_iteration_unpacks``) opens each iteration with its
        keyed binding of its item.
        """
        unrolled = []
        carried = dict(scope)
        final_target_bindings = None
        broke = False
        for index, element_bindings in enumerate(bindings):
            final_target_bindings = element_bindings
            iteration = _iteration_scope(
                self, index, {**carried, **element_bindings}, scope
            )
            reduced = self._substitute_controlled_suite(self.body, iteration)
            if reduced is None:
                return None
            statements, iteration, action = reduced
            if unpacks is not None and unpacks[index] is not None:
                statements = (unpacks[index], *statements)
            unrolled.extend(_iteration_copies(self, index, statements))
            target_names = set(
                self.unit.require_target_pattern(self, self.target).names
            )
            carried = {
                key: value
                for key, value in iteration.items()
                if key not in target_names
            }
            if action == "break":
                broke = True
                break
            # continue and fallthrough both advance to the next concrete item;
            # the controlled suite already omitted the skipped tail.
        if not broke and self.orelse:
            else_scope = (
                {**carried, **final_target_bindings}
                if final_target_bindings is not None
                else carried
            )
            # The else runs once, outside every iteration.
            else_scope = {
                **else_scope,
                _EVALUATION_OCCURRENCE: scope.get(_EVALUATION_OCCURRENCE, ()),
            }
            else_body, _changed = self._substitute_body(self.orelse, else_scope)
            unrolled.extend(else_body)
        return tuple(unrolled), final_target_bindings

    def _substitute_controlled_suite(self, statements, scope):
        produced = []
        current = dict(scope)
        for statement in statements:
            if (
                statement.kind == "Try"
                and not statement.handlers
                and not statement.orelse
                and statement.finalbody
                and len(statement.body) == 1
                and statement.body[0].kind in ("Break", "Continue")
                and statement.body[0].control_context.nearest_loop_target().target_cid
                == self.owned_loop_target.target_cid
            ):
                # A concrete loop dissolves before construction, so consume its
                # owned jump here only after routing the mandatory cleanup.  The
                # jump has no value to evaluate; ``finally`` therefore precedes
                # the selected loop edge.  A cleanup halt/return remains in the
                # produced block and supersedes that edge through ordinary
                # ExitSet reduction.  Wider Try shapes retain their live
                # TrySugar router below rather than being linearized here.
                incoming_action = statement.body[0].kind.lower()
                cleanup = For._substitute_controlled_suite(
                    self, statement.finalbody, current
                )
                if cleanup is None:
                    return None
                cleanup_statements, current, cleanup_action = cleanup
                produced.extend(cleanup_statements)
                return produced, current, cleanup_action or incoming_action
            if statement.kind == "Break":
                return produced, current, "break"
            if statement.kind == "Continue":
                return produced, current, "continue"
            if statement.kind == "If" and any(
                node.kind in ("Break", "Continue")
                and node.control_context.nearest_loop_target().target_cid
                == self.owned_loop_target.target_cid
                for node in statement.walk()
            ):
                test, _changed = statement._substitute_field(statement.test, current)
                verdict = While._ground_truth(self, test)
                if verdict is None:
                    return None
                branch = statement.body if verdict else statement.orelse
                nested = For._substitute_controlled_suite(self, branch, current)
                if nested is None:
                    return None
                branch_statements, current, action = nested
                produced.extend(branch_statements)
                if action is not None:
                    return produced, current, action
                continue
            substituted = statement.substitute(current)
            expanded = (
                substituted.statements
                if isinstance(substituted, _Splice)
                else (substituted,)
            )
            produced.extend(expanded)
            for item in expanded:
                binding = item.substitution_binding(current)
                if binding:
                    binding = item._binding_entries(binding, current)
                    current = {**current, **binding}
            if isinstance(substituted, _Splice) and substituted.bindings:
                projected = statement._binding_entries(substituted.bindings, current)
                current = {**current, **projected}
        return produced, current, None

    # The unroll budget. A concrete loop within it dissolves to its unroll; past
    # it, the SYMBOLIC form (universal / fold coordinate) stands -- not merely
    # cheaper: 1,100 iterations of a carried update is a fold, and unrolling it
    # grows a term chain quadratically. Small on purpose; proofs want small
    # unrolls.
    _UNROLL_FUEL = 128

    def _concrete_elements(
        self, iterable: "Expression", reads=(), scope=None
    ) -> "Optional[list]":
        """The element nodes to unroll over, or ``None`` if `iterable` is not
        concrete. A `List`/`Tuple_` literal is concrete by construction; a
        `range(...)` call is concrete only when every argument (after
        substitution) is a literal `int` -- a symbolic bound leaves the fold
        real, so it is not recognized here.

        A read of a name whose key holds a ground display (``xs = [1, 2];
        for x in xs``, ``_ground_value``) is concrete too: the display decides
        how many items there are, and each item is ``xs[i]``, a read of the
        key, never the display's member.  A list is unrolled this way only
        when ``reads`` (the loop body, the comprehension's element and
        conditions) cannot reach it (``_object_read_in``): Python iterates
        the live list."""
        if iterable.kind in ("EvaluationRef", "Subscript"):
            ground = _ground_value(iterable)
            if ground is None or ground.kind not in ("List", "Tuple"):
                return None
            if ground.kind == "List" and _object_read_in(
                iterable, reads, scope or {}
            ):
                return None
            return [
                For._item_of(self, iterable, index)
                for index in range(len(ground.elts))
            ]
        if iterable.kind in ("List", "Tuple"):
            elements = list(iterable.elts)
            if any(For._is_ground_zero_division(self, element) for element in elements):
                # A ground ZeroDivisionError is an effect, not a concrete
                # element -- the same refusal _concrete_int already makes for
                # a range bound. Unrolling would drop the raise when the
                # target is unused.
                return None
            return elements
        if (
            iterable.kind == "Call"
            and iterable.func.kind == "Name"
            and iterable.func.id == "range"
            and not iterable.keywords
        ):
            ints = []
            for arg in iterable.args:
                v = For._concrete_int(self, arg)
                if v is None:
                    return None
                ints.append(v)
            return [For._int_constant(self, i) for i in range(*ints)]
        return None

    def _concrete_int(self, arg: "Expression") -> "Optional[int]":
        """The literal int an arg denotes, or ``None`` if it is not one. A
        negative bound parses as `UnaryOp(USub, Constant(n))` (cpython does
        not fold the literal), so both shapes are recognized; `bool` is
        rejected even though it subclasses `int`.  A key reference (or a
        subscript of one) denotes the int its ground value is
        (``_ground_value``): ``n = 3; range(n)``."""
        if arg.kind in ("EvaluationRef", "Subscript"):
            ground = _ground_value(arg)
            if ground is None:
                return None
            arg = ground
        if (
            arg.kind == "Constant"
            and isinstance(arg.value, int)
            and not isinstance(arg.value, bool)
        ):
            return arg.value
        if arg.kind == "UnaryOp" and arg.op.kind == "USub":
            inner = For._concrete_int(self, arg.operand)
            return -inner if inner is not None else None
        if arg.kind == "BinOp":
            # A ground arithmetic composition denotes its int as surely as a
            # negative literal does: `0 + 1` reads 1. Structural reading of what
            # the literals compose to (int-closed operators only), never an
            # evaluation of anything symbolic -- a non-ground side reads None.
            left = For._concrete_int(self, arg.left)
            right = For._concrete_int(self, arg.right)
            if left is None or right is None:
                return None
            op = arg.op.kind
            if op == "FloorDiv" and right == 0:
                return None  # a ground ZeroDivisionError is an effect, not an int
            if op == "Mod" and right == 0:
                return None
            return {
                "Add": lambda: left + right,
                "Sub": lambda: left - right,
                "Mult": lambda: left * right,
                "FloorDiv": lambda: left // right,
                "Mod": lambda: left % right,
            }.get(op, lambda: None)()
        return None


    def _is_ground_zero_division(self, arg: "Expression") -> bool:
        """A ground ``/``, ``//``, or ``%`` by zero is an effect, not an element.

        ``_concrete_int`` already refuses ``//`` and ``%`` by zero as an int
        (range bounds). A list or tuple display whose element is that same
        ground ZeroDivisionError is not a concrete iterable.
        """
        if arg.kind != "BinOp" or arg.op.kind not in ("Div", "FloorDiv", "Mod"):
            return False
        right = For._concrete_int(self, arg.right)
        return right == 0

    def _int_constant(self, value: int) -> "Node":
        """Synthesize an int `Constant` node bound to `value`, borrowing this
        `for`'s span -- the unroll rebinds the loop target to a real node, and
        `range`'s elements have no source site of their own to borrow."""
        from .backend import Leaf, materialize
        from .shadow import ShadowNode

        slots = (
            ("value", Leaf(value)),
            ("literal_kind", Leaf(None)),
        )
        return materialize(
            self.unit, ShadowNode("Constant", self.span, slots), self.reporter
        )

    def _item_of(self, iterable: "Node", index: int) -> "Node":
        """``<iterable>[index]``, borrowing this node's span: one item of an
        iterable whose ground value decided how many items there are
        (``_concrete_elements``).  The item reads the iterable's key at
        reduce; the ground value is never put in its place."""
        from .backend import Child, materialize
        from .shadow import ShadowNode, _handle_of

        slots = (
            ("value", Child(_handle_of(iterable))),
            ("slice_", Child(_handle_of(For._int_constant(self, index)))),
        )
        return materialize(
            self.unit, ShadowNode("Subscript", self.span, slots), self.reporter
        )


class AsyncFor(Statement):
    _bound_target_fields = ("target",)
    target: Expression
    iter: Expression
    body: Tuple[Statement, ...]
    orelse: Tuple[Statement, ...]
    _child_fields = ("target", "iter", "body", "orelse")

    def substitute(self, scope):
        """Same as For: masks the loop target for body/orelse."""
        return For.substitute(self, scope)


class While(Statement):
    test: Expression
    body: Tuple[Statement, ...]
    orelse: Tuple[Statement, ...]
    _child_fields = ("test", "body", "orelse")

    # The unroll bound. A CONCRETE while whose state never satisfies exit within
    # this many iterations is treated as not-concrete (falls to the symbolic
    # branch, which is loud) -- `while True:` lands there honestly rather than
    # spinning substitute forever. Not a semantic limit: a real concrete loop
    # that long is beyond what an unroll should dissolve anyway.
    _FUEL = 128  # the shared unroll budget (see For._UNROLL_FUEL)

    def substitute(self, scope):
        """`while <test>: <body>` -- the unbounded loop, and over CONCRETE state
        it DISSOLVES exactly like a concrete `for`: each iteration is one more
        substitution. The condition, substituted against the carried state, is
        ground-decidable (constants only); while it decides True the body is
        threaded once more (its bindings carried forward), and the unrolled
        statements are SPLICED into the enclosing block. `i = 0; while i < 3:
        i = i + 1` unrolls to three rebinds of i; `return i` reads 3.

        A condition that is NOT ground-decidable against the carried state (a
        formal in the state, an effect) keeps the node -- the symbolic while is
        the recurrence-with-exit-condition, an unwritten segment that stays
        loud. `while True:` exhausts the fuel and lands there too: an infinite
        concrete loop is a non-termination the unroll must not fake."""
        from .shadow import rewrite

        unrolled = self._try_unroll(scope)
        if unrolled is not None:
            return _Splice(unrolled)

        # Symbolic (or unsupported) while: keep the node; mask the carried
        # names (any name the body rebinds) so the update stays symbolic.  In
        # the body a carried name reads the loop header's evaluation of it, as
        # in a live ``for`` (``_loop_header_bindings``); the test and the
        # ``else`` read names as before.
        bound = For._stmts_bound_names(self.body)
        bs = {k: v for k, v in scope.items() if k not in bound} if bound else scope
        body_scope = {**bs, **_loop_header_bindings(self, bound, scope)}
        changed = {}
        new_test, d = self._substitute_field(self.test, bs)
        if d:
            changed["test"] = new_test
        for f, field_scope in (("body", body_scope), ("orelse", bs)):
            new, d = self._substitute_body(getattr(self, f), field_scope)
            if d:
                changed[f] = new
        return self if not changed else rewrite(self, **changed)

    def _try_unroll(self, scope):
        """The unrolled statement tuple, or None if the loop is not concrete
        (condition undecidable against the carried state, or fuel exhausted)."""
        controlled = For._body_has_owned_loop_control(self)
        carried = dict(scope)
        unrolled: list = []
        for index in range(self._FUEL):
            test, _d = self._substitute_field(self.test, carried)
            verdict = self._ground_truth(test)
            if verdict is None:
                return None  # not decidable -- not a concrete loop
            if verdict is False:
                # Exit via the condition: with no break (jump-guard), the
                # `else` always runs -- spliced after the iterations.
                if self.orelse:
                    else_body, _c = self._substitute_body(self.orelse, carried)
                    unrolled.extend(else_body)
                return tuple(unrolled)
            if controlled:
                reduced = For._substitute_controlled_suite(
                    self, self.body, _iteration_scope(self, index, carried, scope)
                )
                if reduced is None:
                    return None
                new_body, carried, action = reduced
                unrolled.extend(_iteration_copies(self, index, new_body))
                if action == "break":
                    return tuple(unrolled)
                continue
            carried = _iteration_scope(self, index, carried, scope)
            new_body, _c = self._substitute_body(self.body, carried)
            new_body = _iteration_copies(self, index, new_body)
            unrolled.extend(new_body)
            for stmt in new_body:
                b = stmt.substitution_binding(carried)
                if b:
                    carried = {**carried, **b}
        return None  # fuel exhausted: an infinite/huge loop is not an unroll

    def _ground_truth(self, test):
        """Decide a GROUND condition structurally, or None. Constants only --
        this is the same structural reading as For._concrete_int (recognizing
        literals), never an evaluation of symbolic meaning: a bool Constant
        stands as itself; a single-op Compare over int literals decides by the
        operator. Anything else (a free name, a call) is not ground.  A key
        reference decides by the ground value its key holds
        (``_ground_value``): ``DEBUG = False; if DEBUG: break``."""
        if test.kind in ("EvaluationRef", "Subscript"):
            ground = _ground_value(test)
            if ground is not None:
                test = ground
        if test.kind == "Constant" and isinstance(test.value, bool):
            return test.value
        if test.kind == "Compare" and len(test.ops) == 1:
            left = For._concrete_int(self, test.left)
            right = For._concrete_int(self, test.comparators[0])
            if left is None or right is None:
                return None
            op = test.ops[0].kind
            return {
                "Lt": left < right,
                "LtE": left <= right,
                "Gt": left > right,
                "GtE": left >= right,
                "Eq": left == right,
                "NotEq": left != right,
            }.get(op)
        return None


class If(Statement):
    test: Expression
    body: Tuple[Statement, ...]
    orelse: Tuple[Statement, ...]
    _child_fields = ("test", "body", "orelse")

    def substitute(self, scope):
        """An if introduces no names into its own scope; each branch is a
        sub-block that threads its OWN assignments. The branch-carried bindings
        become the PHI, emitted HERE, ONCE, as explicit spliced SSA assignments
        after the if: `x = <then> if <test> else <else>`. Resolve at
        construction -- the reads downstream are O(1) Assign bindings, never a
        re-walk of the branches (the re-read was 2^nesting on real code).

        Branch-result slot identity is the SOURCE condition occurrence at the
        first mint (``branch_result_slot(self.test)`` before rewrite). A later
        substitute must REUSE that retained pair — not recompute a slot from
        the rewritten test. Name substitution can replace ``if hashable:`` with
        the bound RHS node (e.g. ``is_hashable(other)``) whose span is the
        assignment RHS, not the use site; recomputing the slot from that node
        invents a "foreign" address for the same condition (D-class hierarchy
        lie). Foreign means stored ≠ authenticated; rewritten test is not foreign.
        """
        from .shadow import rewrite

        stored_slot_id = getattr(self, "branch_result_slot_id", None)
        authenticated_slot_id = getattr(
            self, "authenticated_branch_result_slot_id", None
        )
        # Both ids are written together on first mint. Either alone is incomplete.
        retained_slot = stored_slot_id is not None and authenticated_slot_id is not None
        if retained_slot:
            if stored_slot_id != authenticated_slot_id:
                backend_defect(
                    blame=self.fragment,
                    owner="If.substitute",
                    observed=(
                        "If retained branch-result slot ids that disagree with "
                        "each other "
                        f"(stored={stored_slot_id!r}, "
                        f"authenticated={authenticated_slot_id!r})"
                    ),
                    requested=(
                        "one stored id equal to one authenticated id, both "
                        "minted once for this If.test occurrence"
                    ),
                    fix=(
                        "preserve the pair written by the first ordinary "
                        "substitution; do not recompute slot identity from a "
                        "rewritten test node"
                    ),
                )
            slot = BranchResultSlot(stored_slot_id)
        else:
            # First mint: address the SOURCE test occurrence before rewrite.
            slot = branch_result_slot(self.test)

        changed = {}
        new_test, d = self._substitute_field(self.test, scope)
        if d:
            changed["test"] = new_test
        new_body, d, then_net = self._substitute_body_tracked(self.body, scope)
        if d:
            changed["body"] = new_body
        new_orelse, d, else_net = self._substitute_body_tracked(self.orelse, scope)
        if d:
            changed["orelse"] = new_orelse
        if retained_slot:
            node = self if not changed else rewrite(self, **changed)
        else:
            node = self._rewrite_with_slot(changed, slot, authenticated_slot=slot)

        names = set(then_net) | set(else_net)
        phis = []
        availability: BindingMap = {}
        for name in _ordered_binding_keys(names):
            incoming = _explicit_state(name, scope)
            then_val = then_net.get(name, incoming)
            else_val = else_net.get(name, incoming)
            if then_val is _MISSING or else_val is _MISSING:
                continue
            joined = join_binding_state(
                slot=slot,
                when_true=then_val,
                when_false=else_val,
                make_ifexp=self._make_ifexp,
            )
            if isinstance(joined, Node):
                phis.append(self._make_assign(name, joined))
            else:
                availability[name] = joined
        if not phis and not availability:
            return node
        return _Splice((node, *phis), availability)

    def _rewrite_with_slot(self, changed, slot, *, authenticated_slot=None):
        from .backend import Leaf, materialize
        from .shadow import ShadowNode, rewrite

        try:
            self.branch_result_slot_id
        except AttributeError:
            pass
        else:
            backend_defect(
                blame=self.fragment,
                owner="If._rewrite_with_slot",
                observed="If attempted to mint a second branch-result slot",
                requested="the one slot authenticated for this exact If.test",
                fix="route the source If through ordinary substitution exactly once",
            )
        rewritten = rewrite(self, **changed)
        if authenticated_slot is None:
            authenticated_slot = branch_result_slot(rewritten.test)
        desc = rewritten.ref.describe()
        return materialize(
            self.unit,
            ShadowNode(
                desc.kind,
                desc.raw_span or self.span,
                (
                    *desc.slots,
                    ("branch_result_slot_id", Leaf(slot.slot_id)),
                    (
                        "authenticated_branch_result_slot_id",
                        Leaf(authenticated_slot.slot_id),
                    ),
                ),
            ),
            self.reporter,
            # Preserve the enclosing control context (loop targets AND exception
            # slots) across the branch-result rewrite -- as ``rewrite`` does.
            # Without it a slot-rewritten If inside an ``except`` lost the
            # in-flight exception slot, so a bare ``raise`` in one of its
            # branches (``if exc is not value: raise`` in contextlib
            # _GeneratorContextManager.__exit__) refused with 'no authenticated
            # in-flight exception slot'.
            self.control_context,
        )

    def _make_assign(self, name: str, value: "Node") -> "Node":
        """Synthesize `name = <value>` -- the phi as an explicit SSA assignment,
        borrowing this if's span."""
        from .backend import Child, Children, materialize
        from .shadow import ShadowNode, _handle_of

        target = For._make_name(self, name)
        slots = (
            ("targets", Children((_handle_of(target),))),
            ("value", Child(_handle_of(value))),
        )
        return materialize(
            self.unit, ShadowNode("Assign", self.span, slots), self.reporter
        )

    def _make_ifexp(
        self, slot: BranchResultSlot, body: "Node", orelse: "Node"
    ) -> "Node":
        """Synthesize ``<body> if <test> else <orelse>`` as a shadow IfExp that
        borrows this if's span (so the phi still addresses this source site)."""
        from .backend import Child, materialize
        from .shadow import ShadowNode, _handle_of

        test = self._make_branch_result_ref(slot)
        slots = (
            ("body", Child(_handle_of(body))),
            ("test", Child(_handle_of(test))),
            ("orelse", Child(_handle_of(orelse))),
        )
        return materialize(
            self.unit, ShadowNode("IfExp", self.span, slots), self.reporter
        )

    def _make_branch_result_ref(self, slot: BranchResultSlot) -> "Node":
        from .backend import Leaf, materialize
        from .shadow import ShadowNode

        return materialize(
            self.unit,
            ShadowNode(
                "BranchResultRef", self.span, (("slot_id", Leaf(slot.slot_id)),)
            ),
            self.reporter,
        )

    def _construct_sugar(self):
        """`if <test>: <body> [else: <orelse>]` constructs IfSugar -- the guard.
        The test recognizes itself; each branch's statements recognize themselves.
        The guard turns each branch's stated facts into implications; the binding
        phi is substitute's job, never this."""
        from sugar_lift_py_tests.engine_log import reduction_span
        from sugar_lift_py_tests.sugar.if_sugar import IfSugar

        try:
            slot = BranchResultSlot(self.branch_result_slot_id)
        except AttributeError:
            substituted = self.substitute({})
            if isinstance(substituted, _Splice):
                substituted = substituted.statements[0]
            return substituted.sugar()
        try:
            authenticated_slot = BranchResultSlot(
                self.authenticated_branch_result_slot_id
            )
        except AttributeError:
            backend_defect(
                blame=self.fragment,
                owner="If._construct_sugar",
                observed="If without condition-owned branch-result authentication",
                requested="the slot identity authenticated once by If.substitute",
                fix="carry the authenticated slot through If._rewrite_with_slot",
            )
        if slot != authenticated_slot:
            backend_defect(
                blame=self.fragment,
                owner="If._construct_sugar",
                observed="If stored a branch-result slot from a different condition",
                requested="the branch-result slot authenticated for this exact If.test",
                fix="carry branch_result_slot(If.test) through If.substitute unchanged",
            )
        where = f"{self.unit.filename}"
        try:
            lc = self.line_col_span()
            where = f"{self.unit.filename}:{lc.start_line}:{lc.start_col}"
        except SourceTreePanic:
            pass
        with reduction_span(sugar="If.test", role="construction", site=where):
            test = self.test.sugar()
        # Both suites are built here, every statement of them, ``with``
        # included: construction is step 5 and never waits on a reduction.
        with reduction_span(sugar="If.then", role="construction", site=where):
            then_body = tuple(s.sugar() for s in self.body)
        with reduction_span(sugar="If.else", role="construction", site=where):
            else_body = tuple(s.sugar() for s in self.orelse)
        return IfSugar(
            test=test,
            branch_slot=slot,
            then_body=then_body,
            else_body=else_body,
            site=self.fragment,
        )


import contextlib as _contextlib_for_projection

# True while population projects a frame only to collect its manager calls
# (#7732).  That projection runs BEFORE any reader has seated a contract, so a
# ``with ... as name`` in the projected frame has none yet: it exports no
# ``as`` binding instead of demanding the contract now.  The projection is
# read for its manager calls and then discarded; the With itself constructs
# later through the same require door, loudly, once every reader has run.
_IN_MANAGER_USE_PROJECTION: AmbientVar = AmbientVar(
    "sugar_in_manager_use_projection", default=False
)


@_contextlib_for_projection.contextmanager
def manager_use_projection():
    """Mark a substitution as population's manager-call projection."""
    token = _IN_MANAGER_USE_PROJECTION.set(True)
    try:
        yield
    finally:
        _IN_MANAGER_USE_PROJECTION.reset(token)


def selected_manager_calls(expr):
    """The arms' manager calls of a branch-selected ``with`` head, else None.

    After substitution, ``with ctx:`` whose ``ctx`` was bound by a call in
    each arm of an ``if`` has the head ``IfExp(BranchResultRef, call, call)``
    (nested for ``elif``).  Anything else in an arm is not this shape.
    """
    if expr.kind == "Call" or (
        expr.kind == "OpaqueObjectStateV1" and expr.base.kind == "Call"
    ):
        # An opaque call-result identity is transparent: it constructs as
        # its base call, at the base call's coordinate.
        return (expr,)
    if expr.kind != "IfExp" or not isinstance(expr.test, BranchResultRef):
        return None
    body = selected_manager_calls(expr.body)
    orelse = selected_manager_calls(expr.orelse)
    if body is None or orelse is None:
        return None
    return (*body, *orelse)


class With(Statement):
    items: Tuple[WithItem, ...]
    body: Tuple[Statement, ...]
    _child_fields = ("items", "body")

    def _manager_contract_populated(self, item: WithItem) -> bool:
        """Whether population has seated a row (ref, citation or gap) for ``item``."""
        from sugar_lift_py_tests.context_manager_resolution import (
            SourceFragmentCoordinateV1,
        )

        context = self.unit.construction_context
        refs = getattr(context, "source_derived_contract_refs", None)
        if refs is None:
            return True  # the door itself reports the missing context
        coordinate = SourceFragmentCoordinateV1(
            self.unit.source_cid, *item._manager_use_site_span()
        )
        return coordinate in refs

    def _prebound_manager_resolution(self, item: WithItem):
        """Read the sole preconstruction contract resolution for this occurrence."""
        context = self._require_construction_context(
            owner="With._prebound_manager_resolution"
        )
        from sugar_lift_py_tests.context_manager_resolution import (
            ContractRefProtocolError,
            SourceFragmentCoordinateV1,
            TreeConstructionContextV1,
        )

        if not isinstance(context, TreeConstructionContextV1):
            backend_defect(
                blame=self.fragment,
                owner="With._construct_sugar",
                observed="tree construction context is not TreeConstructionContextV1",
                requested="the immutable prereq-2 contract-ref table",
                fix="inject the decoded typed table before SourceFile construction",
            )
        start_line, start_col, end_line, end_col = item._manager_use_site_span()
        coordinate = SourceFragmentCoordinateV1(
            self.unit.source_cid,
            start_line,
            start_col,
            end_line,
            end_col,
        )
        derived = context.source_derived_contract_refs.get(coordinate)
        if derived is not None:
            return derived
        if hasattr(item, "selected_arm_of_start_line"):
            # One arm of a branch-selected head (``_selected_manager_sugar``):
            # its resolution rides inside the With item's selected ref.
            from sugar_lift_py_tests.context_manager_resolution import (
                SelectedContextManagerRefV1,
            )

            selected = context.source_derived_contract_refs.get(
                SourceFragmentCoordinateV1(
                    self.unit.source_cid,
                    item.selected_arm_of_start_line,
                    item.selected_arm_of_start_col,
                    item.selected_arm_of_end_line,
                    item.selected_arm_of_end_col,
                )
            )
            if isinstance(selected, SelectedContextManagerRefV1):
                arm = selected.arm(coordinate)
                if arm is not None:
                    return arm
        try:
            return context.contract_refs.require(coordinate)
        except ContractRefProtocolError:
            # Construct or panic: no contract ref means construction is unwritten.
            from .panic import ContextManagerResolutionConstructionGap

            panic = ContextManagerResolutionConstructionGap(
                blame=self.fragment,
                owner="With._construct_sugar",
                observed=(
                    "no context-manager derivation for source coordinate "
                    f"{coordinate}"
                ),
                requested="one resolved authenticated ContextManagerContractRefV1",
                fix=(
                    "publish or derive the exact typed CM contract before construction; "
                    "With constructs only through the require door"
                ),
                use_site=coordinate,
            )
            testify(self.reporter, "report_gap", self, panic)
            raise panic

    def _published_generator_resource_testimony(self, item: WithItem):
        """Return the producer's one closed generator-resource surface."""
        context = self._require_construction_context(
            owner="With._published_generator_resource_testimony"
        )
        from sugar_lift_py_tests.context_manager_resolution import (
            SourceDerivedGeneratorResourceRefV1,
            SourceFragmentCoordinateV1,
            TreeConstructionContextV1,
        )

        if not isinstance(context, TreeConstructionContextV1):
            return None
        start_line, start_col, end_line, end_col = item._manager_use_site_span()
        coordinate = SourceFragmentCoordinateV1(
            self.unit.source_cid,
            start_line,
            start_col,
            end_line,
            end_col,
        )
        published = context.source_derived_contract_refs.get(coordinate)
        if isinstance(published, SourceDerivedGeneratorResourceRefV1):
            return published
        return None

    def _published_non_manager_head(self, item: WithItem):
        """The producer's absence proof for a direct-call head, else None."""
        if not isinstance(item.context_expr, Call):
            return None
        context = self._require_construction_context(
            owner="With._published_non_manager_head"
        )
        from sugar_lift_py_tests.context_manager_resolution import (
            SourceFragmentCoordinateV1,
            TreeConstructionContextV1,
        )

        if not isinstance(context, TreeConstructionContextV1):
            return None
        start_line, start_col, end_line, end_col = item._manager_use_site_span()
        coordinate = SourceFragmentCoordinateV1(
            self.unit.source_cid, start_line, start_col, end_line, end_col
        )
        return context.source_non_manager_heads.get(coordinate)

    def _raise_resolution_gap(self, resolution) -> None:
        from .panic import ContextManagerResolutionConstructionGap

        # Construct or panic. Name the With door and the contract that was needed.
        detail = getattr(resolution, "detail", None)
        what = getattr(resolution, "kind", None)
        target = getattr(resolution, "target_symbol", None)
        observed = "authenticated preconstruction resolution has no contract ref"
        if what:
            observed = f"{observed}: {what}"
        if target:
            observed = f"{observed} for manager {target!r}"
        if detail:
            observed = f"{observed} [{detail}]"
        panic = ContextManagerResolutionConstructionGap(
            blame=resolution.use_site,
            owner="With._construct_sugar",
            observed=observed,
            requested="one resolved authenticated ContextManagerContractRefV1",
            fix=(
                "publish or resolve the exact typed CM contract before construction; "
                "With constructs only through the require door"
            ),
            use_site=getattr(resolution, "use_site", None),
            target_symbol=target if isinstance(target, str) else None,
            resolution_kind=what if isinstance(what, str) else None,
            demand_cid=getattr(resolution, "demand_cid", None),
        )
        testify(self.reporter, "report_gap", self, panic)
        raise panic

    def _provider_manager_call(self, item: WithItem):
        """The Call that authenticates this manager item, by binding not spelling.

        A direct Call head is already the provider.  A bare Name head reaches
        its provider only through the seat populate installed at the immutable
        manager-use coordinate when projecting ordinary assignment testimony.
        Same spelling elsewhere never authorizes a manager.
        """
        if isinstance(item.context_expr, Call):
            return item.context_expr
        context = self._require_construction_context(
            owner="With._provider_manager_call"
        )
        from sugar_lift_py_tests.context_manager_resolution import (
            SourceFragmentCoordinateV1,
            TreeConstructionContextV1,
        )

        if not isinstance(context, TreeConstructionContextV1):
            return None
        start_line, start_col, end_line, end_col = item._manager_use_site_span()
        coordinate = SourceFragmentCoordinateV1(
            self.unit.source_cid,
            start_line,
            start_col,
            end_line,
            end_col,
        )
        call = context.source_manager_provider_calls.get(coordinate)
        return call if isinstance(call, Call) else None

    def _generator_manager_frame(self, item: WithItem):
        call = self._provider_manager_call(item)
        if call is None:
            return None
        context = self._require_construction_context(
            owner="With._generator_manager_frame"
        )
        from sugar_lift_py_tests.context_manager_resolution import (
            SourceFragmentCoordinateV1,
            TreeConstructionContextV1,
        )

        if not isinstance(context, TreeConstructionContextV1):
            return None
        span = call.line_col_span()
        coordinate = SourceFragmentCoordinateV1(
            self.unit.source_cid,
            span.start_line,
            span.start_col,
            span.end_line,
            span.end_col,
        )
        frame = context.source_call_frames.get(coordinate)
        if frame is None or frame.generator_steps is None:
            return None
        return frame

    def _generator_manager_is_bare_generator_object(self, item: WithItem) -> bool:
        """True when the head calls an authenticated, undecorated generator function.

        The seated frame is the callee's own authenticated FunctionDef body.
        With no decorator between the definition and the binding, calling it
        returns the generator object itself -- never a wrapper -- so the head's
        value is decided: a generator, which has no ``__enter__``. A decorated
        callee is not decided here: its call returns whatever the decorator
        returned.
        """
        return self._bare_generator_object_kind(item) is not None

    def _bare_generator_object_kind(self, item: WithItem):
        """``"generator"`` / ``"async_generator"`` for an undecorated generator
        function head (``def`` / ``async def``), else None."""
        frame = self._generator_manager_frame(item)
        if frame is None:
            return None
        owner = getattr(frame, "owner", None)
        if getattr(owner, "decorators", None):
            return None
        if isinstance(owner, FunctionDef):
            return "generator"
        if isinstance(owner, AsyncFunctionDef):
            return "async_generator"
        return None

    def _generator_manager_sugar(self, item: WithItem):
        if self._generator_manager_frame(item) is None:
            return None
        call = self._provider_manager_call(item)
        if call is None:
            return None
        # Always sugar the provider Call (with its installed frame), never the
        # bare Name spelling at the With head.
        return call.sugar()

    def _require_narrow_cm_ref(self, item: WithItem):
        resolution = self._prebound_manager_resolution(item)
        if resolution is None:
            return None
        from sugar_lift_py_tests.context_manager_contract import (
            EffectBoundarySemanticsV1,
            ExpectsModeV1,
            SuppressesModeV1,
            RaiseEffectKindV1,
            WarningEffectKindV1,
            NeverSuppressesDispositionV1,
            ReturnTruthinessDispositionV1,
            ProtocolResourceSemanticsV1,
            SourceEnterFacesCompletionV1,
            SourceExitFacesCompletionV1,
            LanguageOwnedCCallFacesCompletionV1,
            TotalCompletionV1,
        )
        from sugar_lift_py_tests.context_manager_resolution import (
            ContextManagerContractRefV1,
            ContextManagerResolutionGapV1,
            FactoredSourceDerivedContextManagerRefV1,
            LanguageOwnedContextManagerRefV1,
            SourceDerivedContextManagerRefV1,
        )
        from sugar_lift_py_tests.floor.formal_selected_manager import (
            FormalSelectedManagerProtocol,
        )
        from sugar_lift_py_tests.ir import PrimitiveSort
        from sugar_lift_py_tests.outcome import Completed
        from .panic import UnsupportedContextManagerSemantics

        from sugar_lift_py_tests.context_manager_resolution import (
            OpaqueCitedContextManagerRefV1,
        )

        from sugar_lift_py_tests.context_manager_resolution import (
            PartitionedOpaqueCitedContextManagerRefV1,
        )

        if isinstance(resolution, ContextManagerResolutionGapV1):
            self._raise_resolution_gap(resolution)
        if isinstance(
            resolution,
            (OpaqueCitedContextManagerRefV1, PartitionedOpaqueCitedContextManagerRefV1),
        ):
            # A POSITIVE seated citation, not a rescued refusal. This arm never
            # catches a panic and never infers opacity from a missing contract:
            # the producer authenticated the callee and authenticated that its
            # enter/exit semantics are uncited. Semantics are deliberately
            # unreachable on this ref -- reading `.semantics` raises -- so the
            # admitted-semantics checks below cannot silently pass it through.
            return resolution
        if isinstance(resolution, FactoredSourceDerivedContextManagerRefV1):
            faces = getattr(resolution.boundary_faces, "exits", ())
            completed = tuple(face for face in faces if isinstance(face, Completed))
            if not completed or any(
                not (
                    isinstance(face.value, EffectBoundarySemanticsV1)
                    and face.value.schema_version == "1"
                    and isinstance(face.value.mode, (ExpectsModeV1, SuppressesModeV1))
                    and isinstance(
                        face.value.effect_kind,
                        (RaiseEffectKindV1, WarningEffectKindV1),
                    )
                )
                for face in completed
            ):
                panic = UnsupportedContextManagerSemantics(
                    blame=self.fragment,
                    demand_cid=resolution.protocol_construction_cid,
                    member_cid=resolution.protocol_construction_cid,
                    owner="With._construct_sugar",
                    observed=(
                        "factored source-derived CM carries unsupported message-pattern "
                        f"faces at {resolution.protocol_construction_cid}"
                    ),
                    requested=(
                        "ExitSet of typed Expects/Suppresses Raise/Warning "
                        "EffectBoundarySemanticsV1 faces"
                    ),
                    fix="leave unsupported factored faces loud; never recombine or drop them",
                )
                testify(self.reporter, "report_gap", self, panic)
                raise panic
            # Expected-type and binding authorize every face. Disagreeing faces
            # must refuse here — never let face zero speak for the rest.
            _ = resolution.shared_expected_type_operand
            _ = resolution.shared_binding
            return resolution
        from sugar_lift_py_tests.context_manager_resolution import (
            SourceDerivedGeneratorResourceRefV1,
        )

        if not isinstance(
            resolution,
            (
                ContextManagerContractRefV1,
                SourceDerivedContextManagerRefV1,
                SourceDerivedGeneratorResourceRefV1,
                LanguageOwnedContextManagerRefV1,
            ),
        ):
            backend_defect(
                blame=self.fragment,
                owner="With._construct_sugar",
                observed=f"unexpected resolution value {type(resolution).__name__}",
                requested="ContextManagerContractRefV1 or ContextManagerResolutionGapV1",
                fix="keep the injected table closed and typed",
            )
        semantics = resolution.semantics
        admitted_resource = (
            isinstance(semantics, ProtocolResourceSemanticsV1)
            and semantics.schema_version == "1"
            and (
                isinstance(semantics.enter.completion, TotalCompletionV1)
                or (
                    isinstance(semantics.enter.completion, SourceEnterFacesCompletionV1)
                    and isinstance(resolution, SourceDerivedContextManagerRefV1)
                )
                or (
                    isinstance(
                        semantics.enter.completion,
                        LanguageOwnedCCallFacesCompletionV1,
                    )
                    and isinstance(resolution, LanguageOwnedContextManagerRefV1)
                    and isinstance(resolution.protocol, FormalSelectedManagerProtocol)
                )
            )
            and semantics.enter.projection == "enter-result"
            and isinstance(semantics.enter.sort, PrimitiveSort)
            and semantics.enter.sort.name == "Value"
            and (
                isinstance(semantics.exit.completion, TotalCompletionV1)
                or (
                    isinstance(semantics.exit.completion, SourceExitFacesCompletionV1)
                    and isinstance(resolution, SourceDerivedContextManagerRefV1)
                )
                or (
                    isinstance(
                        semantics.exit.completion,
                        LanguageOwnedCCallFacesCompletionV1,
                    )
                    and isinstance(resolution, LanguageOwnedContextManagerRefV1)
                    and isinstance(resolution.protocol, FormalSelectedManagerProtocol)
                )
            )
            and isinstance(
                semantics.exit.disposition,
                (NeverSuppressesDispositionV1, ReturnTruthinessDispositionV1),
            )
        )
        admitted_boundary = (
            isinstance(semantics, EffectBoundarySemanticsV1)
            and semantics.schema_version == "1"
            and isinstance(semantics.mode, (ExpectsModeV1, SuppressesModeV1))
            and isinstance(
                semantics.effect_kind, (RaiseEffectKindV1, WarningEffectKindV1)
            )
        )
        if not (admitted_resource or admitted_boundary):
            panic = UnsupportedContextManagerSemantics(
                blame=self.fragment,
                demand_cid=resolution.demand_cid,
                member_cid=resolution.contract_cid,
                owner="With._construct_sugar",
                observed=(
                    "authenticated CM member carries unsupported enter/exit semantics "
                    f"at {resolution.contract_cid}"
                ),
                requested=(
                    "total Value resource with source-derived NeverSuppresses or "
                    "ReturnTruthiness disposition, or typed "
                    "Expects/Suppresses Raise/Warning boundary"
                ),
                fix="leave unsupported authenticated semantics loud; never upgrade testimony",
            )
            testify(self.reporter, "report_gap", self, panic)
            raise panic
        return resolution

    @staticmethod
    def _formal_head_with_operands(head_sugar, expr):
        """A formal-selected head that also evaluates its call's operands.

        Only the outermost call of the head may carry non-constant operands
        (``formal_manager_head``); constants evaluate without effect, so a
        head whose operands are all constants keeps its single opaque face.
        """
        from dataclasses import replace

        if expr.kind == "OpaqueObjectStateV1":
            expr = expr.base
        if expr.kind != "Call":
            return head_sugar
        operands = (
            *expr.args,
            *(keyword.value for keyword in expr.keywords),
        )
        if all(operand.kind == "Constant" for operand in operands):
            return head_sugar
        return replace(
            head_sugar, operands=tuple(operand.sugar() for operand in operands)
        )

    def _selected_manager_sugar(self, expr):
        """``with ctx:`` where the arms of an ``if`` each bound ``ctx = cm()``.

        Substitution projects the head to the phi of the arms' calls,
        ``IfExp(BranchResultRef(slot), cm_a(), cm_b())``.  Python evaluated
        exactly one of those calls -- in its arm, once -- and the ``with``
        enters the manager that call returned.  So the statement IS
        ``if <that same branch result>: with cm_a(): body`` ``else: with
        cm_b(): body``: the selection is guarded by the owning ``if``'s own
        branch result (the slot it already authenticates), and each arm is
        an ordinary single-manager ``with`` whose use coordinate is that
        arm's call, where its contract was derived.  Each arm is constructed
        here, with the statement, or refused by name.
        """
        from sugar_lift_py_tests.sugar.if_sugar import IfSugar

        if expr.kind != "IfExp":
            from .shadow import rewrite

            return rewrite(
                self,
                items=(self.items[0]._with_selected_manager_call(expr),),
                body=tuple(self.body),
            ).sugar()
        return IfSugar(
            test=expr.test.sugar(),
            branch_slot=BranchResultSlot(expr.test.slot_id),
            then_body=(self._selected_manager_sugar(expr.body),),
            else_body=(self._selected_manager_sugar(expr.orelse),),
            site=self.fragment,
        )

    def _nest_items(self) -> "With":
        """``with A, B: body`` IS ``with A: with B: body`` — Python's own law.

        Multi-manager composition is NOT a second control model. It is this
        same node, once per manager, so every routing law is inherited rather
        than reimplemented:

        - enter order is left-to-right (A is the outer node);
        - exit order is right-to-left (B is inner, its ``__exit__`` runs first);
        - **failure entering B still exits A**, because B's entire With — its
          enter-halt exit included — is the *body* of A, and the per-edge
          contract application runs over EVERY outgoing body edge.

        The rewrite is idempotent on a single-item With, and recursive: a
        three-item With nests one manager per level as its children construct.
        """
        if len(self.items) <= 1:
            return self
        from .shadow import rewrite

        inner = rewrite(self, items=tuple(self.items[1:]), body=tuple(self.body))
        return rewrite(self, items=(self.items[0],), body=(inner,))

    def _bind_store_target(self, item) -> "With":
        """``with M() as <store target>:`` IS ``<target> = enter_result`` first.

        Python's as-clause is an ASSIGNMENT, not a name declaration. A simple
        ``as <Name>`` is discharged by substitution (stated, no store effect,
        the stronger discharge) and is left alone. Every OTHER target -- an
        attribute, a subscript, a tuple, a nested or starred destructure -- is a
        real store, and ``Assign`` is already total over exactly that target
        set. So this node does not grow one arm per target shape: it rewrites
        into the form ``Assign`` already owns and inherits the totality.

        The store rides as the FIRST body statement, which is where Python runs
        it: after ``__enter__`` completed, inside the block, so a store that
        halts is a body edge and the contract's ``__exit__`` still runs over it.
        Nothing about exit routing is special-cased -- the store is simply the
        first thing the body does.

        Restricted to ProtocolResource semantics on purpose. The EffectBoundary
        contract refuses an as-binding outright (its projection is not
        authenticated), and that refusal stays total; injecting a store there
        would route a binding its contract has not admitted.

        Idempotent: the rewrite only fires on a target this node did not already
        rewrite, detected structurally by the injected store's own value being
        this item's enter-result ObservationRef.
        """
        from sugar_lift_py_tests.context_manager_contract import (
            ENTER_RESULT,
            ProtocolResourceSemanticsV1,
        )
        from sugar_lift_py_tests.context_manager_resolution import (
            ContextManagerContractRefV1,
            LanguageOwnedContextManagerRefV1,
            SourceDerivedContextManagerRefV1,
        )
        from .shadow import rewrite

        target = item.optional_vars
        if target is None or target.kind == "Name":
            return self
        # A generator-based manager binds its enter result (the first yield)
        # exactly as a class-based one does (``GeneratorWithSugar`` /
        # ``WithSourceResourceSugar`` both bind the enter slot), so its store
        # target is lowered the same way: ``a``/``b`` read their projections
        # of that store, never their prior state by spelling.  Its contract
        # is the generator frame, read before any resolution is required.
        if self._generator_manager_frame(item) is None:
            resolution = self._prebound_manager_resolution(item)
            if not isinstance(
                resolution,
                (
                    ContextManagerContractRefV1,
                    SourceDerivedContextManagerRefV1,
                    LanguageOwnedContextManagerRefV1,
                ),
            ) or not isinstance(resolution.semantics, ProtocolResourceSemanticsV1):
                return self

        enter_slot = f"{item._manager_slot_id()}#enter_result"
        if self._already_bound_store(enter_slot):
            return self
        store = self._make_assign(
            target, item._make_observation_ref(enter_slot, ENTER_RESULT)
        )
        return rewrite(self, body=(store, *self.body))

    def _already_bound_store(self, enter_slot: str) -> bool:
        """True when this With's body already opens with its own enter store."""
        if not self.body:
            return False
        head = self.body[0]
        if head.kind != "Assign":
            return False
        value = head.value
        return value.kind == "ObservationRef" and value.slot_id == enter_slot

    def _construct_sugar(self):
        """Build only from the pre-resolved authenticated CM contract ref.

        There is no consumer/vendor membrane fallback. Missing provider
        publication or resolution remains a typed construction gap. The narrow
        resource arm admits one synchronous manager and an optional simple-name
        binding to its real enter-result projection."""
        if len(self.items) != 1:
            return self._nest_items()._construct_sugar()
        item = self.items[0]
        if (
            item.optional_vars is None
            and item.context_expr.kind == "IfExp"
            and selected_manager_calls(item.context_expr) is not None
        ):
            return self._selected_manager_sugar(item.context_expr)
        # The as-clause is Python's own ASSIGNMENT, not a name declaration, so
        # this node does not enumerate target shapes at all:
        #
        # - a simple ``as <Name>`` is discharged by SUBSTITUTION -- `substitute`
        #   rewrote the body's loads to ObservationRef(slot). Stated, no store
        #   effect, and that is the stronger discharge, so it stays.
        # - any other target is a real store, and `_bind_store_target` already
        #   rewrote it into the body as `<target> = ObservationRef(slot)`, where
        #   `Assign` supplies attribute/subscript/tuple/nested/starred totality.
        #
        # Either way the enter-result slot must be BOUND whenever the site names
        # a target, which is what `binds_enter_result` (not `as_name`) decides.
        as_name = None
        binds_enter_result = item.optional_vars is not None
        if binds_enter_result and item.optional_vars.kind == "Name":
            as_name = item.optional_vars.id

        non_manager = self._published_non_manager_head(item)
        if non_manager is not None:
            from sugar_lift_py_tests.sugar.generator_with_sugar import (
                NonManagerObjectWithSugar,
            )

            # The head's class is proven, from its source MRO, to lack
            # ``__enter__`` (or ``__exit__``): evaluate the head once, then the
            # With raises the interpreter's own TypeError before enter and body.
            return NonManagerObjectWithSugar(
                manager=item.context_expr.sugar(),
                site=self.fragment,
                type_name=non_manager.type_name,
                has_enter=non_manager.has_enter,
                has_exit=non_manager.has_exit,
            )

        published_generator_resource = self._published_generator_resource_testimony(
            item
        )
        generator_manager = self._generator_manager_sugar(item)
        if generator_manager is not None and published_generator_resource is None:
            from sugar_lift_py_tests.sugar.generator_with_sugar import (
                GeneratorObjectWithSugar,
                GeneratorWithSugar,
            )

            object_kind = self._bare_generator_object_kind(item)
            if object_kind is not None:
                # An undecorated generator function returns a generator
                # object (an async generator object for ``async def``), which
                # is not a context manager: the With raises TypeError after
                # the call, before enter and body.
                return GeneratorObjectWithSugar(
                    manager=generator_manager,
                    site=self.fragment,
                    object_kind=object_kind,
                )

            enter_slot = (
                f"{item._manager_slot_id()}#enter_result"
                if binds_enter_result
                else None
            )
            return GeneratorWithSugar(
                manager=generator_manager,
                body=tuple(stmt.sugar() for stmt in self.body),
                enter_slot_id=enter_slot,
                site=self.fragment,
            )

        # SourceTreePanic from the door propagates — no Exception swallow.
        resolved_ref = self._require_narrow_cm_ref(item)
        if resolved_ref is not None:
            from sugar_lift_py_tests.context_manager_contract import (
                EffectBoundarySemanticsV1,
                ProtocolResourceSemanticsV1,
            )
            from sugar_lift_py_tests.kit_rpc import ContextManagerEdgeDtoV1
            from sugar_lift_py_tests.sugar.with_resource_sugar import WithResourceSugar

            from sugar_lift_py_tests.context_manager_resolution import (
                FactoredSourceDerivedContextManagerRefV1,
                LanguageOwnedContextManagerRefV1,
                SourceDerivedContextManagerRefV1,
            )

            from sugar_lift_py_tests.context_manager_resolution import (
                SourceDerivedGeneratorResourceRefV1,
            )

            from sugar_lift_py_tests.context_manager_resolution import (
                OpaqueCitedContextManagerRefV1,
                PartitionedOpaqueCitedContextManagerRefV1,
            )

            if isinstance(
                resolved_ref,
                (
                    OpaqueCitedContextManagerRefV1,
                    PartitionedOpaqueCitedContextManagerRefV1,
                ),
            ):
                from sugar_lift_py_tests.sugar.with_opaque_cited_manager_sugar import (
                    WithOpaqueCitedManagerSugar,
                )

                # An `as` target on a cited manager binds the OPEN enter-result
                # coordinate. A simple Name was already discharged by
                # substitution; any other target is a real store, and
                # `_bind_store_target` declines to rewrite this contract (it
                # admits only ProtocolResource semantics), so the binding would
                # otherwise be silently dropped. A dropped binding is the one
                # outcome no contract admits -- stay loud.
                if binds_enter_result and as_name is None:
                    from .panic import UnsupportedWithBindingTarget

                    panic = UnsupportedWithBindingTarget(
                        blame=item.optional_vars.fragment,
                        owner="With._construct_sugar",
                        observed=(
                            "cited-opaque manager as-binding to a "
                            f"{item.optional_vars.kind} store target"
                        ),
                        requested=(
                            "a cited-opaque manager bound to a simple Name, or "
                            "no target"
                        ),
                        fix=(
                            "authenticate a store projection for the open "
                            "enter-result coordinate, or keep the store target "
                            "loud -- never drop the binding"
                        ),
                    )
                    testify(self.reporter, "report_gap", self, panic)
                    raise panic
                enter_slot = (
                    f"{item._manager_slot_id()}#enter_result"
                    if binds_enter_result
                    else None
                )
                return WithOpaqueCitedManagerSugar(
                    manager=item.context_expr.sugar(),
                    body=tuple(stmt.sugar() for stmt in self.body),
                    contract_ref=resolved_ref,
                    enter_slot_id=enter_slot,
                    site=self.fragment,
                )

            generator_protocol = (
                resolved_ref.generator_protocol
                if isinstance(resolved_ref, SourceDerivedGeneratorResourceRefV1)
                else None
            )
            if isinstance(resolved_ref, LanguageOwnedContextManagerRefV1) and isinstance(
                resolved_ref.semantics, ProtocolResourceSemanticsV1
            ):
                from sugar_lift_py_tests.sugar.with_language_owned_resource_sugar import (
                    WithLanguageOwnedResourceSugar,
                )

                manager_slot = item._manager_slot_id()
                enter_slot = (
                    f"{manager_slot}#enter_result" if binds_enter_result else None
                )
                head_sugar = getattr(resolved_ref.protocol, "head_sugar", None)
                manager_head = (
                    head_sugar() if callable(head_sugar) else item.context_expr.sugar()
                )
                from sugar_lift_py_tests.floor.formal_selected_manager import (
                    FormalSelectedManagerProtocol,
                )

                if isinstance(resolved_ref.protocol, FormalSelectedManagerProtocol):
                    manager_head = self._formal_head_with_operands(
                        manager_head, item.context_expr
                    )
                return WithLanguageOwnedResourceSugar(
                    manager=manager_head,
                    protocol=resolved_ref.protocol,
                    summary=resolved_ref,
                    body=tuple(stmt.sugar() for stmt in self.body),
                    manager_slot_id=manager_slot,
                    enter_slot_id=enter_slot,
                    exit_face_id=item._exit_face_id(),
                    site=self.fragment,
                )

            if (
                isinstance(resolved_ref, SourceDerivedContextManagerRefV1)
                or generator_protocol is not None
            ) and isinstance(resolved_ref.semantics, ProtocolResourceSemanticsV1):
                from sugar_lift_py_tests.sugar.with_source_resource_sugar import (
                    WithSourceResourceSugar,
                )

                manager_slot = item._manager_slot_id()
                enter_slot = (
                    f"{manager_slot}#enter_result" if binds_enter_result else None
                )
                enter_definition, exit_definition = (
                    self._require_native_resource_definitions(resolved_ref)
                )
                if generator_protocol is not None:
                    from sugar_lift_py_tests.sugar.method_call_sugar import (
                        MethodCallSugar,
                    )
                    from sugar_lift_py_tests.sugar.resource_coord_sugar import (
                        ManagerRefSugar,
                    )

                    receiver = ManagerRefSugar(slot_id=manager_slot, site=self.fragment)
                    enter_sugar = MethodCallSugar(
                        receiver=receiver,
                        name="__enter__",
                        args=(),
                        native_definition_coordinate=enter_definition,
                        site=self.fragment,
                    )
                    exit_sugar = MethodCallSugar(
                        receiver=receiver,
                        name="__exit__",
                        args=(
                            item._make_exit_type_ref().sugar(),
                            item._make_exit_value_ref().sugar(),
                            item._make_exit_traceback_ref().sugar(),
                        ),
                        native_definition_coordinate=exit_definition,
                        site=self.fragment,
                    )
                else:
                    from dataclasses import replace

                    enter_sugar = replace(
                        item._make_enter_call().sugar(),
                        native_definition_coordinate=enter_definition,
                    )
                    exit_sugar = replace(
                        item._make_parametric_exit_call().sugar(),
                        native_definition_coordinate=exit_definition,
                    )
                manager_sugar = (
                    generator_manager
                    if generator_protocol is not None
                    else item.context_expr.sugar()
                )
                if (
                    generator_protocol is None
                    and resolved_ref.call_actual_sugars is not None
                ):
                    from sugar_lift_py_tests.context_manager_resolution import (
                        SourceFragmentCoordinateV1,
                    )

                    manager_sugar = resolved_ref.call_actual_sugars.bind(
                        manager_sugar,
                        use_site=SourceFragmentCoordinateV1(
                            self.unit.source_cid, *item._manager_use_site_span()
                        ),
                    )
                return WithSourceResourceSugar(
                    manager=manager_sugar,
                    enter=enter_sugar,
                    exit=exit_sugar,
                    protocol=self._protocol_at_exit_face(
                        generator_protocol
                        if generator_protocol is not None
                        else resolved_ref.protocol,
                        item,
                    ),
                    summary=resolved_ref,
                    body=tuple(stmt.sugar() for stmt in self.body),
                    manager_slot_id=manager_slot,
                    enter_slot_id=enter_slot,
                    exit_face_id=item._exit_face_id(),
                    enter_definition=enter_definition,
                    exit_definition=exit_definition,
                    site=self.fragment,
                )

            if isinstance(resolved_ref, FactoredSourceDerivedContextManagerRefV1):
                from sugar_lift_py_tests.sugar.with_effect_boundary_sugar import (
                    WithEffectBoundarySugar,
                )

                if binds_enter_result and as_name is None:
                    from .panic import UnsupportedWithBindingTarget

                    panic = UnsupportedWithBindingTarget(
                        blame=item.optional_vars.fragment,
                        owner="With._construct_sugar",
                        observed=(
                            "factored EffectBoundary as-binding to a "
                            f"{item.optional_vars.kind} store target"
                        ),
                        requested=(
                            "a factored EffectBoundary manager bound to a simple "
                            "Name, or no target"
                        ),
                        fix=(
                            "authenticate a store projection for this contract, or "
                            "keep the store target loud -- never drop the binding"
                        ),
                    )
                    testify(self.reporter, "report_gap", self, panic)
                    raise panic
                observation_slot = None
                if as_name is not None:
                    observation_slot = self._effect_boundary_observation_slot(
                        item, resolved_ref
                    )
                manager_sugar = item.context_expr.sugar()
                manager_sugar = self._authenticate_expected_exception_type(
                    item.context_expr, manager_sugar, resolved_ref
                )
                return WithEffectBoundarySugar(
                    manager=manager_sugar,
                    body=tuple(stmt.sugar() for stmt in self.body),
                    semantics=None,
                    contract_ref=resolved_ref,
                    context_manager_edge=None,
                    boundary_faces=resolved_ref.boundary_faces,
                    observation_slot_id=observation_slot,
                    site=self.fragment,
                )

            if isinstance(resolved_ref.semantics, EffectBoundarySemanticsV1):
                from sugar_lift_py_tests.sugar.with_effect_boundary_sugar import (
                    WithEffectBoundarySugar,
                )

                observation_slot = None
                if as_name is not None:
                    # The slot exists because the CONTRACT declares a binding,
                    # never because the source spelled `as`. A manager that
                    # binds nothing cannot acquire a slot by being written with
                    # a name next to it.
                    observation_slot = self._effect_boundary_observation_slot(
                        item, resolved_ref
                    )
                elif binds_enter_result:
                    # A STORE target on an EffectBoundary. #6391 authenticated an
                    # observation slot for a NAME; it did not authenticate a
                    # store, and `_bind_store_target` deliberately declines to
                    # rewrite this contract. Without this arm the binding would
                    # silently become `observation_slot = None` -- the site would
                    # construct while dropping the binding the source wrote.
                    # Stay loud instead; a dropped binding is the one outcome
                    # neither contract admits.
                    from .panic import UnsupportedWithBindingTarget

                    panic = UnsupportedWithBindingTarget(
                        blame=item.optional_vars.fragment,
                        owner="With._construct_sugar",
                        observed=(
                            "EffectBoundary as-binding to a "
                            f"{item.optional_vars.kind} store target"
                        ),
                        requested="an EffectBoundary manager bound to a simple Name, or no target",
                        fix=(
                            "authenticate a store projection for this contract, or "
                            "keep the store target loud -- never drop the binding"
                        ),
                    )
                    testify(self.reporter, "report_gap", self, panic)
                    raise panic
                manager_sugar = item.context_expr.sugar()
                manager_sugar = self._authenticate_expected_exception_type(
                    item.context_expr, manager_sugar, resolved_ref
                )
                return WithEffectBoundarySugar(
                    manager=manager_sugar,
                    body=tuple(stmt.sugar() for stmt in self.body),
                    semantics=resolved_ref.semantics,
                    contract_ref=resolved_ref,
                    context_manager_edge=(
                        None
                        if isinstance(resolved_ref, SourceDerivedContextManagerRefV1)
                        else ContextManagerEdgeDtoV1.from_resolved(
                            resolved_ref, resolved_ref.use_site
                        )
                    ),
                    observation_slot_id=observation_slot,
                    site=self.fragment,
                )

            if not isinstance(resolved_ref.semantics, ProtocolResourceSemanticsV1):
                backend_defect(
                    blame=self.fragment,
                    owner="With._construct_sugar",
                    observed="closed CM resolver returned an unknown semantics variant",
                    requested="ProtocolResourceSemanticsV1 or EffectBoundarySemanticsV1",
                    fix="keep the semantics union exhaustive",
                )

            manager_slot = item._manager_slot_id()
            enter_slot = f"{manager_slot}#enter_result" if binds_enter_result else None
            enter_definition, exit_definition = (
                self._require_native_resource_definitions(resolved_ref)
            )
            from dataclasses import replace

            enter_sugar = replace(
                item._make_enter_call().sugar(),
                native_definition_coordinate=enter_definition,
            )
            exit_sugar = replace(
                item._make_parametric_exit_call().sugar(),
                native_definition_coordinate=exit_definition,
            )
            return WithResourceSugar(
                manager=item.context_expr.sugar(),
                manager_slot_id=manager_slot,
                enter=enter_sugar,
                exit=exit_sugar,
                exit_face_id=item._exit_face_id(),
                body=tuple(stmt.sugar() for stmt in self.body),
                disposition=resolved_ref.semantics.exit.disposition,
                contract_ref=resolved_ref,
                context_manager_edge=ContextManagerEdgeDtoV1.from_resolved(
                    resolved_ref, resolved_ref.use_site
                ),
                enter_slot_id=enter_slot,
                enter_definition=enter_definition,
                exit_definition=exit_definition,
                site=self.fragment,
            )
        panic = RuntimeSelectedContextManager(
            blame=self.fragment,
            owner="With.sugar",
            observed="With manager has no injected authenticated preconstruction authority",
            requested="one resolved ContextManagerContractRefV1 at the exact use-site",
            fix="run authenticated contract resolution before tree construction",
        )
        testify(self.reporter, "report_gap", self, panic)
        raise panic

    @staticmethod
    def _protocol_at_exit_face(protocol, item):
        """The derived protocol describing ``__exit__`` over this evaluation's
        face.

        The summary derivation states the protocol over the source
        occurrence's face, once per use site.  A ``with`` evaluated more than
        once exits over its own face per evaluation (``_exit_face_id``), so
        the protocol is re-keyed onto that face here and the sugar's face
        facts and the protocol's exit coordinates stay together.  An item
        evaluated once keeps the derived protocol as published."""
        face = item._exit_face_id()
        if face == item._source_exit_face_id():
            return protocol
        return protocol.at_exit_face(face)

    def _require_native_resource_definitions(self, resolved_ref):
        """Require both protocol methods through the one authenticated door."""
        from sugar_lift_py_tests.context_manager_resolution import (
            NativeDefinitionCoordinateGapV1,
            NativeProtocolSlot,
        )
        from .panic import SugarNotWritten

        refs = self._require_construction_context(
            owner="With._require_native_resource_definitions"
        ).contract_refs
        receiver = resolved_ref.use_site
        enter = refs.require_native_definition(
            receiver, NativeProtocolSlot.CONTEXT_ENTER
        )
        exit_ = refs.require_native_definition(
            receiver, NativeProtocolSlot.CONTEXT_EXIT
        )
        for resolution in (enter, exit_):
            if isinstance(resolution, NativeDefinitionCoordinateGapV1):
                raise SugarNotWritten(
                    blame=self.fragment,
                    owner="With._require_native_resource_definitions",
                    observed=resolution.reason,
                    requested=(
                        "authenticated source definition coordinates for both "
                        "context-enter and context-exit"
                    ),
                    fix=(
                        "retain this native resource as undischarged until the "
                        "shared definition door resolves the missing slot"
                    ),
                )
        return enter, exit_

    def _authenticate_expected_exception_type(self, manager, manager_sugar, reference):
        """Attach the floor-owned identity to the selected real call operand."""
        from dataclasses import replace

        from sugar_lift_py_tests.context_manager_contract import (
            FormalArgumentProjectionV1,
            KeywordOnlyV1,
            PositionalOnlyV1,
            PositionalOrKeywordV1,
        )
        from sugar_lift_py_tests.sugar.authenticated_exception_type_sugar import (
            AuthenticatedExceptionTypeSugar,
        )
        from sugar_lift_py_tests.sugar.call_site_sugar import CallSiteSugar
        from sugar_lift_py_tests.sugar.method_call_sugar import MethodCallSugar

        semantics = getattr(reference, "semantics", None)
        if semantics is not None:
            selector = semantics.expected_type_operand
        else:
            selector = getattr(reference, "shared_expected_type_operand", None)
        if not isinstance(selector, FormalArgumentProjectionV1):
            return manager_sugar
        if not isinstance(manager, Call) or not isinstance(
            manager_sugar, (CallSiteSugar, MethodCallSugar)
        ):
            return manager_sugar
        positional = list(enumerate(manager.args))
        keywords = {
            keyword.arg: keyword.value for keyword in manager.keywords if keyword.arg
        }
        actual = None
        actual_location = None
        for index, parameter in enumerate(reference.import_signature.parameters):
            if positional and isinstance(
                parameter.passing, (PositionalOnlyV1, PositionalOrKeywordV1)
            ):
                position, value = positional.pop(0)
                location = ("arg", position)
            elif parameter.name in keywords and isinstance(
                parameter.passing, (PositionalOrKeywordV1, KeywordOnlyV1)
            ):
                value = keywords[parameter.name]
                location = ("keyword", parameter.name)
            else:
                continue
            if index == selector.parameter_index:
                actual, actual_location = value, location
                break

        def authenticate(node, sugar):
            # The selected formal is classinfo. Preserve tuple construction and
            # authenticate each member at its own source coordinate, rather
            # than trying to evaluate a dotted member on a symbolic module.
            from sugar_lift_py_tests.sugar.collection_sugar import TupleSugar

            if isinstance(node, Tuple_) and isinstance(sugar, TupleSugar):
                return replace(
                    sugar,
                    elements=tuple(
                        authenticate(element, child)
                        for element, child in zip(
                            node.elts, sugar.elements, strict=True
                        )
                    ),
                )
            if not isinstance(node, (Name, Attribute)):
                return sugar
            identity = (
                self.unit.exception_type_identity(node)
                if isinstance(node, Name)
                else self.unit.imported_exception_type_identity(node)
            )
            if identity is None:
                return sugar
            class_value = None
            if isinstance(node, Attribute):
                from sugar_lift_py_tests.floor.exception_class_value import (
                    ExceptionClassValue,
                )

                qualified = getattr(identity.args[1], "value", None)
                if isinstance(qualified, str) and qualified:
                    class_value = ExceptionClassValue(qualified)
            elif isinstance(node, Name):
                try:
                    class_value = self.unit.exception_class_value(node)
                except SugarNotWritten:
                    class_value = None
            return AuthenticatedExceptionTypeSugar(
                sugar, identity, site=node.fragment, class_value=class_value
            )

        if actual_location is None:
            return manager_sugar
        actual_sugar = (
            manager_sugar.args[actual_location[1]]
            if actual_location[0] == "arg"
            else next(
                sugar
                for name, sugar in manager_sugar.keywords
                if name == actual_location[1]
            )
        )
        wrapped = authenticate(actual, actual_sugar)
        if actual_location[0] == "arg":
            args = list(manager_sugar.args)
            args[actual_location[1]] = wrapped
            return replace(manager_sugar, args=tuple(args))
        keywords_sugar = list(manager_sugar.keywords)
        for position, (name, sugar) in enumerate(keywords_sugar):
            if name == actual_location[1]:
                keywords_sugar[position] = (name, wrapped)
                break
        return replace(manager_sugar, keywords=tuple(keywords_sugar))

    def substitute(self, scope):
        """Rewrite a simple as-name to the resolved resource enter projection."""
        from .shadow import rewrite
        from sugar_lift_py_tests.context_manager_contract import (
            ENTER_RESULT,
        )

        if len(self.items) > 1:
            # Nest FIRST, then substitute: an earlier manager's as-name must be
            # in scope for a later manager's expression, exactly as it is in the
            # nested spelling this rewrite produces.
            return self._nest_items().substitute(scope)

        changed = {}
        new_items, d = self._substitute_field(self.items, scope)
        if d:
            changed["items"] = new_items
        items = new_items if d else self.items

        body_scope = dict(scope)
        if self.unit.construction_context is not None:
            if len(items) != 1:
                return self if not changed else rewrite(self, **changed)
            item = items[0]
            # A with evaluated more than once (a loop iteration's copy, a
            # duplicated ``finally``'s exit-path copy) is one evaluation per
            # copy: its item is keyed with this evaluation BEFORE any slot is
            # read, so the manager, enter-result and observation slots (the
            # ``as x`` ObservationRef, the lowered ``as (a, b)`` store's
            # value) are this copy's, never a sibling's (``_manager_slot_id``).
            evaluation = self._duplicated_evaluation_key(scope)
            if (
                evaluation is not None
                and getattr(item, "evaluation", None) != evaluation
            ):
                from .shadow import rewrite_with_leaves

                item = rewrite_with_leaves(item, {"evaluation": evaluation})
                items = (item,)
                changed["items"] = items
            if item.optional_vars is not None and item.optional_vars.kind != "Name":
                # A store target is normalized into `<target> = enter_result` as
                # the first body statement BEFORE the body is substituted, so
                # the store threads its own bindings to the rest of the block
                # through the ordinary assignment seam. Substituting first and
                # injecting after would resolve the block's loads against the
                # OUTER scope and silently shadow the names this site binds.
                # Keyed first, so the re-substitution reads the same key.
                current = self._keyed_evaluation(
                    self if not changed else rewrite(self, **changed), scope
                )
                bound = current._bind_store_target(item)
                if bound is not current:
                    return bound.substitute(scope)
            if item.optional_vars is not None and item.optional_vars.kind == "Name":
                enter_slot = f"{item._manager_slot_id()}#enter_result"
                body_scope[item.optional_vars.id] = item._make_observation_ref(
                    enter_slot, ENTER_RESULT
                )
            new_body, d = self._substitute_body(self.body, body_scope)
            if d:
                changed["body"] = new_body
            # Keyed as the item is: the With's own sugar reads its slots off
            # the keyed item.
            return self._keyed_evaluation(
                self if not changed else rewrite(self, **changed), scope
            )
        for item in items:
            if item.optional_vars is not None:
                for name in self._bound_names_in(item.optional_vars):
                    body_scope.pop(name, None)

        new_body, d = self._substitute_body(self.body, body_scope)
        if d:
            changed["body"] = new_body
        return self if not changed else rewrite(self, **changed)

    def _effect_boundary_binding(self, item, resolved_ref):
        """(slot_id, projection) the CONTRACT declares for this ``as`` name.

        The projection is read off the authenticated semantics' ``binding``
        field -- exception-info or warning-observation -- so a manager name
        never selects it. ``NoBindingV1`` means the contract states this
        manager hands the body nothing, and a source that binds a name anyway
        is a real disagreement between contract and use site: it stays loud
        rather than acquiring a slot by syntax.
        """
        from sugar_lift_py_tests.context_manager_contract import (
            EXCEPTION_INFO,
            ExceptionInfoBindingV1,
            WARNING_OBSERVATION,
            WarningObservationBindingV1,
        )

        semantics = getattr(resolved_ref, "semantics", None)
        if semantics is not None:
            binding = semantics.binding
        else:
            binding = getattr(resolved_ref, "shared_binding", None)
        if isinstance(binding, ExceptionInfoBindingV1):
            projection = EXCEPTION_INFO
        elif isinstance(binding, WarningObservationBindingV1):
            projection = WARNING_OBSERVATION
        else:
            from .panic import UnsupportedWithBindingTarget

            panic = UnsupportedWithBindingTarget(
                blame=self.fragment,
                owner="With._construct_sugar",
                observed=(
                    "source binds an EffectBoundary result the authenticated "
                    f"contract declares no binding for ({type(binding).__name__})"
                ),
                requested="a contract carrying exception-info or warning-observation binding",
                fix="never grant an observation slot from the `as` spelling alone",
            )
            testify(self.reporter, "report_gap", self, panic)
            raise panic
        # One observation per evaluation of this with: the item carries the
        # with's evaluation key (``With.substitute``), so its manager slot is
        # already this evaluation's.  The ``as`` name's ObservationRef and the
        # boundary's deposit both read this slot, so a read of one
        # iteration's ``e`` is never the next iteration's effect.
        return f"{item._manager_slot_id()}#observation", projection

    def _effect_boundary_observation_slot(self, item, resolved_ref):
        return self._effect_boundary_binding(item, resolved_ref)[0]

    def _with_assignment_binding(self, item, value, scope):
        """Delegate a with-as binding to Python's ordinary Assign seam."""
        assignment = self._make_assign(item.optional_vars, value)
        return assignment.substitution_binding(scope)

    def substitution_binding(self, scope):
        """Export a contract projection through ordinary Assign binding."""
        from sugar_lift_py_tests.context_manager_contract import (
            ENTER_RESULT,
        )

        if self.unit.construction_context is not None:
            if len(self.items) != 1:
                return self._nest_items().substitution_binding(None)
            item = self.items[0]
            if item.optional_vars is None:
                return None
            if item.optional_vars.kind != "Name":
                # ``with M() as (a, b):`` lowered its store into the body
                # (``_bind_store_target``) and substitution keyed it as one
                # evaluation: after the with, each target is a reference to
                # its projection of that evaluation, as it is inside the body
                # -- never the name read by spelling.  A store target no
                # store was lowered for, and an attribute/subscript store
                # (no lexical name), binds nothing.
                if item.optional_vars.kind not in ("Tuple", "List"):
                    return None
                enter_slot = f"{item._manager_slot_id()}#enter_result"
                if not self._already_bound_store(enter_slot):
                    return None
                return self.body[0].substitution_binding(scope)
            # SourceTreePanic from the door propagates — no Exception swallow.
            resolved_ref = None
            if self._generator_manager_frame(item) is None:
                if (
                    _IN_MANAGER_USE_PROJECTION.get()
                    and not self._manager_contract_populated(item)
                ):
                    # No reader has run yet; constructed (or refused) later.
                    return None
                resolved_ref = self._require_narrow_cm_ref(item)
            from sugar_lift_py_tests.context_manager_contract import (
                EffectBoundarySemanticsV1,
            )
            from sugar_lift_py_tests.context_manager_resolution import (
                OpaqueCitedContextManagerRefV1,
            )

            if isinstance(resolved_ref, OpaqueCitedContextManagerRefV1):
                # A citation declares no contract, so it declares no
                # observation slot. `as` binds the OPEN enter-result
                # coordinate -- the same slot `_construct_sugar` binds.
                #
                # This arm is REQUIRED, not defensive tidiness. The
                # EffectBoundary test below reads `.semantics` through
                # `getattr(..., None)`, whose default only absorbs
                # AttributeError; the citation's typed refusal is not one, so
                # it would escape this frame-projection path as an INSTRUMENT
                # FAILURE rather than a countable row. Asking a citation for
                # semantics stays loud -- the answer is that this consumer
                # must not ask.
                enter_slot = f"{item._manager_slot_id()}#enter_result"
                return self._with_assignment_binding(
                    item,
                    item._make_observation_ref(enter_slot, ENTER_RESULT),
                    scope,
                )

            if resolved_ref is not None and isinstance(
                getattr(resolved_ref, "semantics", None), EffectBoundarySemanticsV1
            ):
                # An effect boundary hands the body its OBSERVATION slot, not
                # an enter result. Exporting enter-result here would have made
                # the body read a projection the contract never declared.
                slot, projection = self._effect_boundary_binding(item, resolved_ref)
                return self._with_assignment_binding(
                    item,
                    item._make_observation_ref(slot, projection),
                    scope,
                )
            enter_slot = f"{item._manager_slot_id()}#enter_result"
            return self._with_assignment_binding(
                item,
                item._make_observation_ref(enter_slot, ENTER_RESULT),
                scope,
            )
        return None


class AsyncWith(Statement):
    items: Tuple[WithItem, ...]
    body: Tuple[Statement, ...]
    _child_fields = ("items", "body")

    def substitute(self, scope):
        """Async context management stays loud before child construction."""
        del scope
        return self._raise_async_gap()

    def _raise_async_gap(self):
        from .panic import AsyncContextManagerUnsupported

        panic = AsyncContextManagerUnsupported(
            blame=self.fragment,
            owner="AsyncWith._construct_sugar",
            observed="async context manager is outside the narrow synchronous arm",
            requested="one synchronous pre-resolved NeverSuppresses manager",
            fix="keep async enter/exit semantics loud until separately specified",
        )
        testify(self.reporter, "report_gap", self, panic)
        raise panic

    def _construct_sugar(self):
        return self._raise_async_gap()


class Raise(Statement):
    exc: Optional[Expression]
    cause: Optional[Expression]
    _child_fields = ("exc", "cause")

    def substitute(self, scope):
        """Binds nothing: recurse into children and reassemble."""
        return self._substitute_children(scope)

    def _exception_name(self):
        """The raised exception's name, read structurally off ``exc`` (never
        desugared): ``raise E`` -> ``"E"``, ``raise E(...)`` -> ``"E"``,
        ``raise mod.E`` / ``raise mod.E(...)`` -> ``"mod.E"``. A bare ``raise``
        (re-raise, ``exc is None``) or an exotic raised expression we cannot read
        is ``None`` -- the halt is no less real, the name is only its label."""
        node = self.exc
        if node is None:
            return None
        if node.kind == "Call":  # raise E(...) -- the constructor
            node = node.func
        parts = []
        while node is not None and node.kind == "Attribute":  # mod.sub.E
            parts.append(node.attr)
            node = node.value
        if node is not None and node.kind == "Name":
            parts.append(node.id)
        elif node is not None and node.kind == "FormalRef":
            # After substitution a raised formal name is a FormalRef, not a
            # Name; its label is the formal's declared name (`raise exc` -> exc).
            parts.append(node.coordinate.declared_name)
        if not parts:
            return None
        return ".".join(reversed(parts))

    def _construct_sugar(self):
        """Build exception and explicit cause children for the halt effect."""
        from sugar_lift_py_tests.engine_log import reduction_span

        where = f"{self.unit.filename}"
        try:
            lc = self.line_col_span()
            where = f"{self.unit.filename}:{lc.start_line}:{lc.start_col}"
        except SourceTreePanic:
            pass

        if self.exc is None:
            from sugar_lift_py_tests.sugar.raise_sugar import RaiseSugar

            return RaiseSugar(
                exception=None,
                cause=None,
                exception_name=None,
                site=self.fragment,
                in_flight_slot=self.control_context.nearest_exception_slot(
                    blame=self.fragment
                ),
            )
        from sugar_lift_py_tests.sugar.raise_sugar import RaiseSugar
        from dataclasses import replace

        from sugar_lift_py_tests.sugar.authenticated_exception_type_sugar import (
            AuthenticatedExceptionTypeSugar,
        )
        from sugar_lift_py_tests.sugar.call_site_sugar import CallSiteSugar

        def group_call(node):
            return (
                isinstance(node, Call)
                and isinstance(node.func, Name)
                and self.unit.is_builtin_exception_group(node.func)
            )

        def leaf_sugar(node):
            leaf_identity = leaf_mro = leaf_name = None
            if isinstance(node, Call) and isinstance(node.func, Name):
                leaf_identity = self.unit.exception_type_identity(node.func)
                leaf_mro = self.unit.exception_type_mro(node.func)
                leaf_name = node.func.id
            elif isinstance(node, Name):
                leaf_identity = self.unit.exception_type_identity(node)
                leaf_mro = self.unit.exception_type_mro(node)
                leaf_name = node.id
            if leaf_identity is None:
                raise SugarNotWritten(
                    blame=node.fragment,
                    owner="Raise._construct_sugar",
                    observed="exception-group leaf lacks authenticated exception identity",
                    requested="a source-authenticated exception type",
                    fix="keep opaque/native group members loud",
                )
            value = node.sugar()
            if isinstance(value, CallSiteSugar):
                value = replace(
                    value,
                    exception_type_coordinate=leaf_identity,
                    exception_type_mro=leaf_mro,
                )
            value = AuthenticatedExceptionTypeSugar(
                value,
                leaf_identity,
                leaf_mro,
                node.fragment,
                class_value=self.unit.exception_class_value(
                    node.func if isinstance(node, Call) else node
                ),
            )
            return RaiseSugar(value, None, leaf_name, node.fragment)

        def grouped_sugar(call):
            if (
                len(call.args) != 2
                or call.keywords
                or not isinstance(call.args[1], (List, Tuple))
            ):
                raise SugarNotWritten(
                    blame=call.fragment,
                    owner="Raise._construct_sugar",
                    observed="unsupported native exception-group construction",
                    requested="ExceptionGroup(message, finite list-or-tuple members)",
                    fix="keep opaque/native group construction loud",
                )
            from sugar_lift_py_tests.sugar.grouped_raise_sugar import GroupedRaiseSugar

            return GroupedRaiseSugar(
                group_identity=call.fragment.seal().cid,
                message=call.args[0].sugar(),
                children=tuple(
                    grouped_sugar(member) if group_call(member) else leaf_sugar(member)
                    for member in call.args[1].elts
                ),
                site=call.fragment,
                exception_type_coordinate=self.unit.exception_type_identity(call.func),
                exception_type_mro=self.unit.exception_type_mro(call.func),
            )

        if group_call(self.exc):
            if self.cause is not None:
                raise SugarNotWritten(
                    blame=self.fragment,
                    owner="Raise._construct_sugar",
                    observed="exception-group raise with explicit cause",
                    requested="group cause regroup semantics",
                    fix="keep unsupported native behavior loud",
                )
            return grouped_sugar(self.exc)

        identity = None
        mro = None
        type_operand = None
        if isinstance(self.exc, Call) and isinstance(self.exc.func, Name):
            type_operand = self.exc.func
        elif isinstance(self.exc, Call) and isinstance(self.exc.func, Attribute):
            type_operand = self.exc.func
        elif isinstance(self.exc, Name):
            type_operand = self.exc
        elif isinstance(self.exc, Attribute):
            type_operand = self.exc
        if type_operand is not None:
            with reduction_span(
                sugar="Raise.exception_type_identity",
                role="construction",
                site=where,
            ):
                if isinstance(type_operand, Name):
                    identity = self.unit.exception_type_identity(type_operand)
                    if identity is None:
                        identity = self.unit.imported_exception_type_identity(
                            type_operand
                        )
                        mro = self.unit._builtin_exception_ancestry(identity)
                    else:
                        mro = self.unit.exception_type_mro(type_operand)
                else:
                    identity = self.unit.imported_exception_type_identity(type_operand)
                    mro = self.unit._builtin_exception_ancestry(identity)

        with reduction_span(sugar="Raise.exc.sugar", role="construction", site=where):
            exception_sugar = self.exc.sugar()
        from sugar_lift_py_tests.sugar.method_call_sugar import MethodCallSugar

        if identity is not None and isinstance(
            exception_sugar, (CallSiteSugar, MethodCallSugar)
        ):
            exception_sugar = replace(
                exception_sugar,
                exception_type_coordinate=identity,
                exception_type_mro=mro,
            )
        elif identity is not None:
            class_value = None
            if isinstance(type_operand, Attribute):
                from sugar_lift_py_tests.floor.exception_class_value import (
                    ExceptionClassValue,
                )

                qualified = getattr(identity.args[1], "value", None)
                if isinstance(qualified, str) and qualified:
                    class_value = ExceptionClassValue(qualified)
            exception_sugar = AuthenticatedExceptionTypeSugar(
                exception_sugar,
                identity,
                mro,
                self.exc.fragment,
                class_value=class_value,
            )

        return RaiseSugar(
            exception=exception_sugar,
            cause=self.cause.sugar() if self.cause is not None else None,
            exception_name=self._exception_name(),
            site=self.fragment,
            in_flight_slot=(
                self.control_context.exception_slots[-1]
                if self.control_context.exception_slots
                else None
            ),
        )


def _occurrence_keys_of(fragment):
    """The spellings a raise occurrence at ``fragment`` is keyed by: the
    fragment itself and its ``file:line:col`` locus (``RaiseSugar``)."""
    keys = {str(fragment)}
    filename = getattr(fragment, "filename", None)
    line = getattr(fragment, "line", None)
    col = getattr(fragment, "col", None)
    if filename is not None and line is not None and col is not None:
        keys.add(f"{filename}:{line}:{col}")
    return keys


class _HaltEdgeState(dict):
    """One body halt edge's state: a binding map that also knows which body
    statement (``edge``) it leaves from, so disagreeing edges are joined over
    that statement's ``try-edge`` slot instead of falling back to the pre-try
    state."""

    def __init__(self, entries, *, edge, join=None):
        super().__init__(entries)
        self.edge = edge
        self.join = join


class _HaltEdgeJoin:
    """Joins the states body halt edges carry into one handler/``finally``."""

    def __init__(self, try_node, scope, site_id):
        self.try_node = try_node
        self.scope = scope
        self.site_id = site_id
        self.minted = False
        self.edges: dict = {}

    def carry(self, state):
        edge = getattr(state, "edge", None)
        if edge is None:
            return state
        self.edges.setdefault(edge, None)
        return _HaltEdgeState(state, edge=edge, join=self)

    def arm_halt_state(self, handler, index, handler_net, scope):
        """The state a halt raised inside arm ``index`` carries to ``finally``."""
        changed = [
            name
            for name, entry in handler_net.items()
            if name != handler.name and scope.get(name) is not entry
        ]
        state = dict(handler_net)
        if changed:
            from .container_mutation import _havoc
            from .shadow import occurrence_tags_of

            tags = occurrence_tags_of(handler)
            binding = {name: _havoc(handler, name, tags) for name in changed}
            state.update(handler._binding_entries(binding, scope))
        edge = f"arm{index}"
        self.edges.setdefault(edge, None)
        return _HaltEdgeState(state, edge=edge, join=self)

    def _value(self, state, name):
        if name in state:
            return state[name]
        return _explicit_state(name, self.scope)

    def _joined(self, name, edge_states, fallback):
        """``s0 if edge0 else (s1 if edge1 else ... fallback)``, or _MISSING."""
        by_edge = []
        seen = set()
        for state in edge_states:
            edge = getattr(state, "edge", None)
            if edge in seen:
                continue
            seen.add(edge)
            by_edge.append((edge, self._value(state, name)))
        if fallback is _MISSING:
            if not by_edge:
                return _MISSING
            *by_edge, (_edge, fallback) = by_edge
        if fallback is _MISSING or any(v is _MISSING for _e, v in by_edge):
            return _MISSING
        if all(v is fallback or v == fallback for _e, v in by_edge):
            return fallback
        joined = fallback
        for edge, value in reversed(by_edge):
            if edge is None:
                return _MISSING
            joined = join_binding_state(
                slot=try_edge_slot(self.site_id, edge),
                when_true=value,
                when_false=joined,
                make_ifexp=self.try_node._make_ifexp,
            )
            self.minted = True
        return joined

    def disagreement(self, states, agreed):
        names = set().union(*(state.keys() for state in states)) - set(agreed)
        out = {}
        for name in _ordered_binding_keys(names):
            joined = self._joined(name, states, _MISSING)
            if joined is not _MISSING:
                out[name] = joined
        return out

    def finally_state(self, escaping):
        """What ``finally`` sees under a halt: the escaping edges joined."""
        if not escaping:
            return {}
        names = set().union(*(state.keys() for state in escaping))
        out = {}
        for name in _ordered_binding_keys(names):
            joined = self._joined(name, escaping, _MISSING)
            if joined is not _MISSING:
                out[name] = joined
        return out

    def edge_keys(self):
        """``(slot id, occurrence keys)`` per body statement that is an edge."""
        body = self.try_node.body
        keys = []
        for edge in sorted((e for e in self.edges if e is not None), key=str):
            if isinstance(edge, str):
                # An arm's own halt: no body statement holds it, so a body halt
                # decides it false and nothing decides it true.
                keys.append((try_edge_slot(self.site_id, edge).slot_id, ()))
                continue
            if edge >= len(body):
                continue
            statement = body[edge]
            keys.append(
                (
                    try_edge_slot(self.site_id, edge).slot_id,
                    tuple(
                        sorted(
                            key
                            for node in statement.walk()
                            for key in _occurrence_keys_of(node.fragment)
                        )
                    ),
                )
            )
        return tuple(keys)


class Try(Statement):
    body: Tuple[Statement, ...]
    handlers: Tuple[ExceptHandler, ...]
    orelse: Tuple[Statement, ...]
    finalbody: Tuple[Statement, ...]
    _child_fields = ("body", "handlers", "orelse", "finalbody")

    def substitute(self, scope):
        """Rewrite each routed completion edge and export its binding state."""
        from .shadow import rewrite

        if type(self) is not Try:
            # ``except*``: each handler is keyed as this evaluation's, as for
            # ``except`` below, so a duplicated ``try ... except*`` observes
            # one effect group per evaluation (temporal choice 1).
            changed = {}
            handlers = Try._keyed_handlers(self, scope)
            new_handlers, d = self._substitute_field(handlers, scope)
            if d or handlers is not self.handlers:
                changed["handlers"] = new_handlers
            for field_name in ("body", "orelse", "finalbody"):
                new_value, d = self._substitute_body(getattr(self, field_name), scope)
                if d:
                    changed[field_name] = new_value
            node = self if not changed else rewrite(self, **changed)
            return self._keyed_evaluation(node, scope)

        changed = {}
        site_id = getattr(self, "try_route_site_id", None)
        retained_site = site_id is not None
        if not retained_site:
            site_id = try_route_site(self)
        body_edge_states: list = []
        new_body, d, body_net = self._substitute_body_tracked(
            self.body, scope, edge_states=body_edge_states
        )
        if d:
            changed["body"] = new_body
        # The state the body leaves with closes the last statement's interval,
        # so each statement's halt edge can see what that statement changed.
        body_edge_states.append((None, {**scope, **body_net}))
        join = _HaltEdgeJoin(self, scope, site_id)
        halt_edges = self._body_halt_edges(body_edge_states, scope)
        halt_edges = [
            (identity, mro, join.carry(state)) for identity, mro, state in halt_edges
        ]
        routed = self._route_halt_edges(halt_edges)
        body_state = {**scope, **body_net}
        new_orelse, d, else_net = self._substitute_body_tracked(self.orelse, body_state)
        if d:
            changed["orelse"] = new_orelse
        body_completion = {**body_net, **else_net}

        handler_nets = []
        new_handlers = []
        for handler_index, handler in enumerate(Try._keyed_handlers(self, scope)):
            handler_changed = {}
            new_type, type_changed = handler._substitute_field(handler.type_, scope)
            if type_changed:
                handler_changed["type_"] = new_type
            # THE LAW: the handler begins from the state its routed halt edges
            # carry, never from a snapshot of the pre-try scope and never from
            # a union of everything the body could have bound.  ``incoming`` is
            # what every edge that reaches THIS handler agrees on; an edge that
            # halted before an assignment simply does not carry it.
            incoming = self._incoming_halt_state(routed.get(handler_index))
            handler_scope = {**scope, **incoming}
            if handler.name:
                handler_scope[handler.name] = handler._make_effect_ref(
                    handler._effect_slot_id()
                )
            new_handler_body, body_changed, handler_net = (
                handler._substitute_body_tracked(handler.body, handler_scope)
            )
            if body_changed:
                handler_changed["body"] = new_handler_body
            rewritten = (
                handler if not handler_changed else rewrite(handler, **handler_changed)
            )
            new_handlers.append(rewritten)
            if handler.name:
                handler_net = {
                    **handler_net,
                    handler.name: UnboundBinding(
                        name=handler.name, cause=handler.fragment
                    ),
                }
            # The handler edge leaves the try carrying the state it arrived
            # with, updated by the handler's own threading -- same law, one
            # layer in.
            handler_nets.append({**incoming, **handler_net})
        if any(new is not old for new, old in zip(new_handlers, self.handlers)):
            changed["handlers"] = tuple(new_handlers)

        unconditional = self._unconditional_raise_testimony(self.body)
        # A completion route is one way the try can leave by falling through:
        # the body (then ``else``) completed, or handler ``k`` received a
        # routed halt edge and its own body completed.  Which handlers can
        # receive an edge is exactly what ``_route_halt_edges`` already
        # decided -- every edge, untyped ones reaching every arm -- never a
        # guess from one testified raise.
        completion_routes = []
        if unconditional is None:
            completion_routes.append((None, body_completion))
        for handler_index, (handler, handler_net) in enumerate(
            zip(self.handlers, handler_nets)
        ):
            if handler_index in routed and self._block_has_completed_fallthrough(
                handler.body
            ):
                completion_routes.append((handler_index, handler_net))

        merged, minted = self._merge_completion_nets(
            scope, completion_routes, site_id=site_id
        )
        final_scope = {**scope, **merged}
        if self.finalbody:
            # ``finally`` also runs on every body halt no arm surely catches,
            # beginning from that halt's own state -- never the pre-try state.
            escaping = [
                state
                for identity, mro, state in halt_edges
                if not any(
                    self._handler_surely_matches(handler, identity, mro)
                    for handler in self.handlers
                )
            ]
            # An arm may itself raise (or re-raise) after its own stores: that
            # halt reaches ``finally`` with every name the arm changed unknown.
            for handler_index, (handler, handler_net) in enumerate(
                zip(self.handlers, handler_nets)
            ):
                if handler_index not in routed:
                    continue
                arm_state = join.arm_halt_state(
                    handler, handler_index, handler_net, scope
                )
                if arm_state is not None:
                    escaping.append(arm_state)
            halted_entries = join.finally_state(escaping)
        else:
            halted_entries = {}
        new_finalbody, d, final_net = self._substitute_body_tracked(
            self.finalbody, _exit_path_scope(self, "completion", final_scope)
        )
        if d:
            changed["finalbody"] = new_finalbody
        merged = {**merged, **final_net}
        # A halt reaches ``finally`` with its own state, not the completion
        # join: the same clause is substituted once more for the halted faces
        # (``TrySugar`` reduces it for every incoming halt).  The tail after
        # the try runs only on completion, so ``merged`` keeps the completion
        # threading.  Each copy is substituted for its own exit path, so a
        # statement evaluation in it is keyed once per path; a clause holding
        # one always gets its halted copy, or the halted faces would reduce
        # the completion copy and bind its key a second time.
        finalbody_halted = None
        if any(
            final_scope.get(name) is not entry for name, entry in halted_entries.items()
        ) or _holds_evaluation(new_finalbody):
            finalbody_halted, _d = self._substitute_body(
                self.finalbody,
                _exit_path_scope(self, "halt", {**final_scope, **halted_entries}),
            )

        edge_keys = join.edge_keys() if join.minted else ()
        if (
            (minted and not retained_site)
            or (edge_keys and edge_keys != getattr(self, "try_edge_keys", ()))
            or finalbody_halted is not None
        ):
            node = self._rewrite_with_route_site(
                changed,
                site_id if not retained_site else None,
                edge_keys,
                finalbody_halted,
            )
        else:
            node = self if not changed else rewrite(self, **changed)
        node = self._keyed_evaluation(node, scope)
        return _Splice((node,), merged) if merged else node

    def _keyed_handlers(self, scope) -> tuple:
        """This ``try``'s (or ``try ... except*``'s) handlers, each keyed as
        this evaluation's when the statement is one of several evaluations of
        its source (a loop iteration's copy, a duplicated ``finally``'s
        exit-path copy; ``_duplicated_evaluation_key``).  A keyed handler's
        slot (``ExceptHandler._effect_slot_id``) -- read by the ``as`` name's
        EffectRef, the routing and a bare re-raise -- is then never a sibling
        evaluation's (temporal choice 1).  ``self.handlers`` unchanged for a
        statement evaluated once."""
        evaluation = self._duplicated_evaluation_key(scope)
        if evaluation is None:
            return self.handlers
        from .shadow import rewrite_with_leaves

        return tuple(
            rewrite_with_leaves(handler, {"evaluation": evaluation})
            for handler in self.handlers
        )

    def _rewrite_with_route_site(
        self, changed, site_id, edge_keys=(), finalbody_halted=None
    ):
        """Carry the route-slot address onto the rewritten try so its sugar
        confirms the same slots the joined bindings read; ``edge_keys`` lets it
        ground the halt-edge slots a handler's or ``finally``'s state reads."""
        from .backend import Leaf, materialize
        from .shadow import rewrite

        rewritten = rewrite(self, **changed) if changed else self
        desc = rewritten.ref.describe()
        from .shadow import ShadowNode

        extra = []
        slots = tuple(
            slot
            for slot in desc.slots
            if slot[0] not in ("try_edge_keys", "try_finalbody_halted")
        )
        if site_id is not None:
            extra.append(("try_route_site_id", Leaf(site_id)))
        if edge_keys:
            if getattr(self, "try_route_site_id", None) is None and site_id is None:
                extra.append(("try_route_site_id", Leaf(try_route_site(self))))
            extra.append(("try_edge_keys", Leaf(edge_keys)))
        if finalbody_halted is not None:
            from .backend import Children
            from .shadow import _handle_of

            extra.append(
                (
                    "try_finalbody_halted",
                    Children(tuple(_handle_of(stmt) for stmt in finalbody_halted)),
                )
            )
        return materialize(
            self.unit,
            ShadowNode(
                desc.kind,
                desc.raw_span or self.span,
                (*slots, *extra),
            ),
            self.reporter,
            self.control_context,
        )

    #: Node classes whose evaluation cannot itself raise.  A statement built
    #: only from these leaves the block by completing -- it contributes no
    #: halt edge.  Everything else (a call, an attribute, a subscript, an
    #: operator, a comprehension, a nested block) may halt at an occurrence
    #: this layer cannot name, so it contributes an UNTYPED halt edge that
    #: every handler must be prepared to receive.
    _HALT_FREE_NODES = ("Assign", "Name", "Constant", "Tuple_", "List", "Pass")

    def _halt_free_classes(self, *extra):
        return tuple(extra) + tuple(
            cls
            for cls in (globals().get(name) for name in self._HALT_FREE_NODES)
            if isinstance(cls, type)
        )

    def _statement_cannot_halt(self, statement) -> bool:
        allowed = self._halt_free_classes()
        return all(isinstance(node, allowed) for node in statement.walk())

    def _raise_testimony_of(self, statement):
        """The (identity, mro) a single ``raise`` occurrence testifies to, or
        ``None`` when the raised expression is not a resolvable type name."""
        node = statement.exc
        if isinstance(node, Call):
            node = node.func
        if not isinstance(node, Name):
            return None
        return (
            self.unit.exception_type_identity(node),
            self.unit.exception_type_mro(node),
        )

    def _body_halt_edges(self, edge_states, scope):
        """The body's halted exits, each paired with the temporal state in
        effect at its own occurrence.

        This does not compute a scope: ``edge_states`` is the threading the
        block already performed, reported per statement.  Each entry is
        ``(exception_identity, exception_mro, state)`` where ``state`` is the
        block-local net at that occurrence -- what an exit leaving *here*
        carries.  ``exception_identity is None`` means the occurrence is not
        type-testified (an opaque step), so every handler may receive it."""
        from .container_mutation import cited_call_cannot_halt

        edges = []
        for index, (statement, pre_statement_scope) in enumerate(edge_states):
            if statement is None:
                continue
            if cited_call_cannot_halt(statement, pre_statement_scope):
                continue
            net = {
                name: state
                for name, state in pre_statement_scope.items()
                if scope.get(name) is not state
            }
            post = (
                edge_states[index + 1][1] if index + 1 < len(edge_states) else None
            )
            net = self._mid_statement_state(statement, pre_statement_scope, post, net)
            net = _HaltEdgeState(net, edge=index)
            edges.extend(self._statement_halt_edges(statement, net))
        return edges

    #: States a statement's completion binds to an object some code it ran may
    #: have changed (``container_mutation.havoc_after``): that code may change
    #: it and THEN raise, so a halt at the statement cannot claim the old one.
    _MID_STATEMENT_MUTATION_KINDS = frozenset(
        {"ReceiverAfterCall", "SourceCallActualAfter", "OpaqueObjectStateV1"}
    )
    _COMPOUND_KINDS = frozenset(
        {
            "For",
            "AsyncFor",
            "While",
            "With",
            "AsyncWith",
            "If",
            "Try",
            "TryStar",
            "Match",
        }
    )

    def _mid_statement_state(self, statement, pre, post, net):
        """The state a halt INSIDE ``statement`` carries.

        A simple statement binds its own targets only once it completes, so a
        halt in it carries the state it began with -- except an object code it
        ran may have changed before raising.  A compound statement may halt
        after any of its inner stores: every name it changes is unknown at its
        halt, never the state it began with."""
        if post is None:
            return net
        compound = getattr(statement, "kind", None) in self._COMPOUND_KINDS
        changed = []
        for name, before in pre.items():
            after = post.get(name, _MISSING)
            if after is _MISSING or after is before:
                continue
            if isinstance(unwrap_binding_state(before), UnboundBinding):
                continue
            if compound or (
                getattr(unwrap_binding_state(after), "kind", None)
                in self._MID_STATEMENT_MUTATION_KINDS
            ):
                changed.append(name)
        if not changed:
            return net
        from .container_mutation import _havoc
        from .shadow import occurrence_tags_of

        tags = occurrence_tags_of(statement)
        binding = {name: _havoc(statement, name, tags) for name in changed}
        binding = statement._binding_entries(binding, pre)
        return {**net, **binding}

    def _statement_halt_edges(self, statement, net):
        """The halted exits ONE statement contributes, all carrying ``net`` --
        the state in effect when that statement begins."""
        if self._statement_cannot_halt(statement):
            return []
        if isinstance(statement, Raise) and all(
            isinstance(node, self._halt_free_classes(Raise))
            for node in statement.walk()
        ):
            testimony = self._raise_testimony_of(statement)
            if testimony is not None:
                return [(testimony[0], testimony[1], net)]
            return [(None, None, net)]
        if isinstance(statement, If) and self._statement_cannot_halt(statement.test):
            # A partition halts on whichever branch is taken; both branches
            # begin from the same incoming state, so each branch's own exits
            # are edges of this statement.
            return [
                edge
                for branch in (statement.body, statement.orelse)
                for inner in branch
                for edge in self._statement_halt_edges(inner, net)
            ]
        return [(None, None, net)]

    def _route_halt_edges(self, halt_edges):
        """Send each halted edge to the handler that receives it: source order,
        first match only -- the same arm selection the router already applies.
        An untyped edge could be any exception, so it reaches every arm."""
        routed: dict[int, list] = {}
        for identity, mro, state in halt_edges:
            if identity is None:
                for index in range(len(self.handlers)):
                    routed.setdefault(index, []).append(state)
                continue
            for index, handler in enumerate(self.handlers):
                if self._handler_matches(handler, identity, mro):
                    routed.setdefault(index, []).append(state)
                    # Only a DECIDED match stops the edge: a handler that may
                    # match (missing ancestry) may also miss, so the later
                    # arms can still receive it.
                    if self._handler_surely_matches(handler, identity, mro):
                        break
        return routed

    def _handler_surely_matches(self, handler, exception_identity, exception_mro) -> bool:
        if handler.type_ is None:
            return True
        nodes = (
            handler.type_.elts
            if isinstance(handler.type_, Tuple_)
            else (handler.type_,)
        )
        for node in nodes:
            if not isinstance(node, Name):
                continue
            handler_identity = self.unit.exception_type_identity(node)
            if handler_identity is None:
                continue
            if handler_identity == exception_identity or (
                exception_mro is not None and handler_identity in exception_mro
            ):
                return True
        return False

    def _incoming_halt_state(self, states):
        """What the edges reaching one handler AGREE on.

        Not a union: a name survives only if every routed edge carries it, and
        carries the same entry.  A handler with no routed edge (the body's
        halts are all typed elsewhere, or the body cannot halt at all) begins
        from the pre-try state -- there is no occurrence to inherit from."""
        if not states:
            return {}
        first, rest = states[0], states[1:]
        agreed = {
            name: entry
            for name, entry in first.items()
            if all(
                name in other and (other[name] is entry or other[name] == entry)
                for other in rest
            )
        }
        join = getattr(first, "join", None)
        if join is None:
            return agreed
        # A name the edges DISAGREE on is not the pre-try state: it is the
        # state of whichever edge raised, joined over that edge's slot.
        return {**agreed, **join.disagreement(states, agreed)}

    def _handler_matches(self, handler, exception_identity, exception_mro) -> bool:
        if handler.type_ is None:
            return True
        if exception_identity is None:
            return True
        nodes = (
            handler.type_.elts
            if isinstance(handler.type_, Tuple_)
            else (handler.type_,)
        )
        for node in nodes:
            if not isinstance(node, Name):
                # An unresolved handler operand may name the raised class.
                return True
            handler_identity = self.unit.exception_type_identity(node)
            if handler_identity is None or handler_identity == exception_identity:
                return True
            if exception_mro is None:
                # Missing ancestry is not a miss: the handler may match.
                return True
            if handler_identity in exception_mro:
                return True
        return False

    def _unconditional_raise_testimony(self, statements):
        for statement in statements:
            if isinstance(statement, Raise):
                node = statement.exc
                if isinstance(node, Call):
                    node = node.func
                if not isinstance(node, Name):
                    return (None, None)
                return (
                    self.unit.exception_type_identity(node),
                    self.unit.exception_type_mro(node),
                )
            if isinstance(statement, Return):
                return None
            if isinstance(statement, If):
                left = self._unconditional_raise_testimony(statement.body)
                right = self._unconditional_raise_testimony(statement.orelse)
                if left is not None and left == right:
                    return left
            # The first ordinary statement can complete, so continue scanning.
        return None

    def _block_has_completed_fallthrough(self, statements) -> bool:
        """Whether one source path reaches the statement after this block.

        Completion-state merging must exclude handlers that unconditionally
        leave by ``raise`` or ``return``. Including such a handler invents a
        fallthrough edge and erases bindings carried by the real completed
        try-body edge (for example ``enum_class`` after ``type.__new__``).
        """
        for statement in statements:
            if isinstance(statement, (Raise, Return, Break, Continue)):
                return False
            if isinstance(statement, If):
                if not statement.orelse:
                    continue
                if not (
                    self._block_has_completed_fallthrough(statement.body)
                    or self._block_has_completed_fallthrough(statement.orelse)
                ):
                    return False
        return True

    def _merge_completion_nets(self, scope, routes, *, site_id):
        """Join each name over the routes the try can complete by.

        THE LAW: a name whose state depends on which route left the try is
        joined exactly like an ``if``'s branch result -- an if-expression over
        the handler's ``try-route`` slot, nested in handler order, with the
        body route as the innermost fallback.  Never dropped, never read from
        the pre-try state: a route that did not assign the name carries the
        state it arrived with (``UnboundBinding`` for a local not yet bound,
        whose read then halts with ``UnboundLocalError`` under that route).
        ``TrySugar`` confirms the slots on every routed outcome.

        Returns ``(merged, minted)``; ``minted`` says a route slot was read."""
        if not routes:
            return {}, False
        if len(routes) == 1:
            return dict(routes[0][1]), False
        names = set().union(*(net.keys() for _arm, net in routes))
        merged: BindingMap = {}
        minted = False
        for name in _ordered_binding_keys(names):
            states = [
                (arm, net.get(name, _explicit_state(name, scope)))
                for arm, net in routes
            ]
            if any(state is _MISSING for _arm, state in states):
                # No incoming binding at all (a module/global name): the same
                # refusal ``If`` keeps -- the later read stays unresolved.
                continue
            first = states[0][1]
            if all(state is first or state == first for _arm, state in states[1:]):
                merged[name] = first
                continue
            # Handler routes in source order, the body route (when it can
            # complete) innermost: ``h0 if route0 else (h1 if route1 else
            # body)``.  Without a completing body the last handler is the
            # fallback -- it is the only route left once the others are false.
            ordered = [entry for entry in states if entry[0] is not None] + [
                entry for entry in states if entry[0] is None
            ]
            joined = ordered[-1][1]
            for arm, state in reversed(ordered[:-1]):
                joined = join_binding_state(
                    slot=try_route_slot(site_id, arm),
                    when_true=state,
                    when_false=joined,
                    make_ifexp=self._make_ifexp,
                )
                minted = True
            merged[name] = joined
        return merged, minted

    def _make_ifexp(self, test, body, orelse):
        return If._make_ifexp(self, test, body, orelse)

    def _make_branch_result_ref(self, slot):
        return If._make_branch_result_ref(self, slot)

    def _construct_sugar(self):
        """`try: body (except E: handler)+ [else] [finally]` -- the STRUCTURAL
        sibling of with-raises. A typed clause contributes one constructed,
        authenticated exception coordinate per Name element of a tuple; a bare
        clause contributes the widest raise matcher. Unresolved/dotted/computed
        type expressions and empty tuples stay loud. ``except*`` lives on
        TryStar and stays loud there.

        ``except <type> as <name>``: substitute already rewrote loads of
        ``name`` to ``EffectRef(slot)`` inside the handler. Routing
        authenticates that slot with the matched Halted raise — never E().
        """
        from sugar_lift_py_tests.sugar.try_sugar import TrySugar

        if not self.handlers:
            # try/finally-only (no except): same TrySugar with empty handlers;
            # finally is ExitSet.and_finally over the body exits.
            if not self.finalbody:
                return super()._construct_sugar()
            return TrySugar(
                body=tuple(stmt.sugar() for stmt in self.body),
                handlers=(),
                orelse=tuple(stmt.sugar() for stmt in self.orelse),
                finalbody=tuple(stmt.sugar() for stmt in self.finalbody),
                site=self.fragment,
                route_site=getattr(self, "try_route_site_id", None),
                edge_keys=getattr(self, "try_edge_keys", ()) or (),
                finalbody_halted=self._finalbody_halted_sugar(),
            )

        handler_specs = self._authenticated_handler_specs()
        if handler_specs is None:
            return super()._construct_sugar()
        return TrySugar(
            body=tuple(stmt.sugar() for stmt in self.body),
            handlers=tuple(handler_specs),
            orelse=tuple(stmt.sugar() for stmt in self.orelse),
            finalbody=tuple(stmt.sugar() for stmt in self.finalbody),
            site=self.fragment,
            route_site=getattr(self, "try_route_site_id", None),
            edge_keys=getattr(self, "try_edge_keys", ()) or (),
            finalbody_halted=self._finalbody_halted_sugar(),
        )

    def _finalbody_halted_sugar(self):
        """``finally`` as substituted for the halted faces, or None."""
        halted = getattr(self, "try_finalbody_halted", None)
        if halted is None:
            return None
        return tuple(stmt.sugar() for stmt in halted)

    def _authenticated_handler_specs(self):
        """``(type Sugar|None, body sugars, slot id)`` per arm, or None.

        The one roster ``TrySugar`` routes through. ``None`` is an empty
        ``except ()``, which has no honest matcher; an arm type without an
        authenticated exception identity stays a loud ``SugarNotWritten``.
        Shared with the generator step producer so a generator manager's
        ``try: yield / except`` arms match exactly like an ordinary try.
        """
        handler_specs = []
        for handler in self.handlers:
            # Every handler owns an effect slot. ``as e`` projects it; a bare
            # re-raise cites the same slot even without a lexical target.
            slot_id = handler._effect_slot_id()
            body_sugars = tuple(stmt.sugar() for stmt in handler.body)
            if handler.type_ is None:
                handler_specs.append((None, body_sugars, slot_id))
                continue

            type_nodes = (
                handler.type_.elts
                if handler.type_.kind == "Tuple"
                else (handler.type_,)
            )
            if not type_nodes:
                return None  # empty tuple: no honest matcher
            for type_node in type_nodes:
                # A bare Name authenticates through the lexical builtin/source
                # vocabulary; a dotted import-bound type (``except re.error``)
                # authenticates through the same closed import identity used for
                # ``raise re.error(...)`` operands.  Only a head that is neither
                # -- a computed, shadowed, or instance-attribute except type --
                # stays loud.
                class_value = None
                if isinstance(type_node, Name):
                    identity = self.unit.exception_type_identity(type_node)
                    mro = (
                        self.unit.exception_type_mro(type_node)
                        if identity is not None
                        else None
                    )
                else:
                    identity = self.unit.imported_exception_type_identity(type_node)
                    mro = None
                if identity is None and type_node.kind == "Call":
                    # ``except tuple(types):`` -- a computed arm, read when a
                    # raise reaches it (ComputedExceptionTypeSugar).
                    from sugar_lift_py_tests.sugar.computed_exception_type_sugar import (
                        ComputedExceptionTypeSugar,
                    )

                    handler_specs.append(
                        (
                            ComputedExceptionTypeSugar(
                                type_node.sugar(), type_node.fragment
                            ),
                            body_sugars,
                            slot_id,
                        )
                    )
                    continue
                if identity is None:
                    raise SugarNotWritten(
                        owner="Try._construct_sugar",
                        blame=self.fragment,
                        observed="typed except handler lacks authenticated exception identity",
                        requested="a constructed exception-type coordinate",
                        fix="resolve the handler type lexically or keep the try loud",
                    )
                from sugar_lift_py_tests.sugar.authenticated_exception_type_sugar import (
                    AuthenticatedExceptionTypeSugar,
                )

                if not isinstance(type_node, Name):
                    # Seal the import-bound dotted head as an exception class
                    # value, exactly as the Raise-operand door does, so the
                    # handler carries a concrete class rather than a bare
                    # module-attribute floor.
                    from sugar_lift_py_tests.floor.exception_class_value import (
                        ExceptionClassValue,
                    )

                    qualified = getattr(identity.args[1], "value", None)
                    if isinstance(qualified, str) and qualified:
                        class_value = ExceptionClassValue(qualified)

                handler_specs.append(
                    (
                        AuthenticatedExceptionTypeSugar(
                            type_node.sugar(),
                            identity,
                            mro,
                            type_node.fragment,
                            class_value=class_value,
                        ),
                        body_sugars,
                        slot_id,
                    )
                )

        return tuple(handler_specs)

class TryStar(Statement):
    body: Tuple[Statement, ...]
    handlers: Tuple[ExceptHandler, ...]
    orelse: Tuple[Statement, ...]
    finalbody: Tuple[Statement, ...]
    _child_fields = ("body", "handlers", "orelse", "finalbody")

    def substitute(self, scope):
        """Same block-aware substitute as Try (identical fields)."""
        return Try.substitute(self, scope)

    def _construct_sugar(self):
        """Construct the distinct except* router with authenticated type operands."""
        from sugar_lift_py_tests.sugar.authenticated_exception_type_sugar import (
            AuthenticatedExceptionTypeSugar,
        )
        from sugar_lift_py_tests.sugar.try_star_sugar import TryStarSugar

        handlers = []
        for handler in self.handlers:
            # `except* (A, B)` is ONE handler over a union of types, not two
            # handlers. The tuple is expanded into a tuple of matchers that the
            # router partitions with in a single pass, so the body runs once no
            # matter how many of the listed types the group carries. Expanding
            # it into one handler spec per type -- which is honest for ordinary
            # `except (A, B)`, where at most one exception is in flight -- would
            # run an except* body twice on a group holding both.
            if handler.type_ is None:
                raise SugarNotWritten(
                    blame=self.fragment,
                    owner="TryStar._construct_sugar",
                    observed="unsupported except* handler type",
                    requested="one authenticated exception type operand",
                    fix="keep unsupported native handler behavior loud",
                )
            type_nodes = (
                handler.type_.elts
                if handler.type_.kind == "Tuple"
                else (handler.type_,)
            )
            if not type_nodes or any(
                not isinstance(type_node, Name) for type_node in type_nodes
            ):
                raise SugarNotWritten(
                    blame=self.fragment,
                    owner="TryStar._construct_sugar",
                    observed="unsupported except* handler type",
                    requested="one authenticated exception type operand",
                    fix="keep unsupported native handler behavior loud",
                )
            matchers = []
            for type_node in type_nodes:
                identity = self.unit.exception_type_identity(type_node)
                if identity is None:
                    raise SugarNotWritten(
                        owner="TryStar._construct_sugar",
                        blame=self.fragment,
                        observed="except* type lacks authenticated exception identity",
                        requested="a constructed exception-type coordinate",
                        fix="resolve the handler type lexically or keep it loud",
                    )
                matchers.append(
                    AuthenticatedExceptionTypeSugar(
                        type_node.sugar(),
                        identity,
                        self.unit.exception_type_mro(type_node),
                        type_node.fragment,
                        class_value=self.unit.exception_class_value(type_node),
                    )
                )
            handlers.append(
                (
                    tuple(matchers),
                    tuple(stmt.sugar() for stmt in handler.body),
                    handler._effect_slot_id(),
                )
            )
        return TryStarSugar(
            body=tuple(stmt.sugar() for stmt in self.body),
            handlers=tuple(handlers),
            orelse=tuple(stmt.sugar() for stmt in self.orelse),
            finalbody=tuple(stmt.sugar() for stmt in self.finalbody),
            site=self.fragment,
        )


class Assert(Statement):
    test: Expression
    msg: Optional[Expression]
    _child_fields = ("test", "msg")

    def substitute(self, scope):
        """`assert <test>[, <msg>]` binds nothing: recurse into test and msg."""
        return self._substitute_children(scope)

    def _construct_sugar(self):
        """`assert <test>[, <msg>]` constructs AssertSugar WITH the test's
        sugar. The test recognizes itself (self.test.sugar()) — the recursion.
        The message is provenance only (#4593/#4594): AssertSugar never builds
        or reduces it; its pinned fragment rides separately from the condition.
        """
        from sugar_lift_py_tests.sugar.assert_sugar import AssertSugar

        return AssertSugar(
            test=self.test.sugar(),
            message=self.msg.fragment if self.msg is not None else None,
            site=self.fragment,
        )


class Import(Statement):
    names: Tuple[ImportAlias, ...]
    _child_fields = ("names",)

    def substitute(self, scope):
        """Binds nothing, no hole: substitutes to itself."""
        return self

    def _construct_sugar(self):
        """`import <module>` binds a module name that stays a FREE SYMBOLIC
        in the meaning layer: nothing about the import itself is stated as
        a fact. A later `pd.concat(...)` reduces as a method coordinate on
        the free name `pd` -- correct without the import ever having stated
        anything. So the import contributes an honestly empty record."""
        from sugar_lift_py_tests.sugar.inert_sugar import InertSugar

        return InertSugar(site=self.fragment)


class ImportFrom(Statement):
    module: Optional[str]
    names: Tuple[ImportAlias, ...]
    level: int
    _child_fields = ("names",)

    def substitute(self, scope):
        """Binds nothing, no hole: substitutes to itself."""
        return self

    def _construct_sugar(self):
        """`from <module> import <names>` binds free symbolics the same way
        plain `import` does: the bound names stay FREE SYMBOLIC in the
        meaning layer, reduced only where a later expression uses them as a
        coordinate. The import statement itself states nothing."""
        from sugar_lift_py_tests.sugar.inert_sugar import InertSugar

        return InertSugar(site=self.fragment)


class Global(Statement):
    _bound_name_fields = ("names",)
    names: Tuple[str, ...]

    def substitute(self, scope):
        """Binds nothing, no hole: substitutes to itself."""
        return self

    def _construct_sugar(self):
        """`global <names>` is a scope DECLARATION, not a fact: it tells
        substitute which enclosing binding a name resolves against. That
        binding semantics lives entirely in substitute (see above) -- by
        the time sugar/meaning runs, the declaration itself has nothing
        left to state."""
        from sugar_lift_py_tests.sugar.inert_sugar import InertSugar

        return InertSugar(site=self.fragment)


class Nonlocal(Statement):
    _bound_name_fields = ("names",)
    names: Tuple[str, ...]

    def substitute(self, scope):
        """Binds nothing, no hole: substitutes to itself."""
        return self

    def _construct_sugar(self):
        """`nonlocal <names>` is a scope DECLARATION like `global`: it
        routes a name to an enclosing function scope during substitute.
        Once substitute has resolved the binding, the declaration carries
        no further meaning-layer content of its own."""
        from sugar_lift_py_tests.sugar.inert_sugar import InertSugar

        return InertSugar(site=self.fragment)


class Expr(Statement):
    """An expression in statement position."""

    value: Expression
    _child_fields = ("value",)

    def substitute(self, scope):
        """Rewrite children and thread authenticated mutating-call post-state."""
        rewritten = self._substitute_children(scope)
        mutation = self._builtin_container_mutation(scope)
        if mutation is not None:
            return mutation
        from .container_mutation import path_mutation_statement

        mutation = path_mutation_statement(self, scope, call=rewritten.value)
        if mutation is not None:
            return mutation
        state = self._dict_setdefault_append_state(scope)
        statement_kind = "DictSetDefaultAppendStatement"
        if state is None:
            state = self._mapping_pop_state(scope)
            statement_kind = "MappingPopStatement"
        if state is None:
            return rewritten

        name, post_state = state
        from .backend import Child, Leaf, materialize
        from .shadow import ShadowNode, _handle_of

        return materialize(
            self.unit,
            ShadowNode(
                statement_kind,
                rewritten.span,
                (
                    ("value", Child(_handle_of(rewritten.value))),
                    ("receiver_name", Leaf(name)),
                    ("post_state", Child(_handle_of(post_state))),
                ),
            ),
            self.reporter,
        )

    def _builtin_container_mutation(self, scope):
        """``r.<mutator>(*args)`` on a decided list/dict/set (container_mutation.py)."""
        call = self.value
        if (
            not isinstance(call, Call)
            or call.keywords
            or not isinstance(call.func, Attribute)
            or any(isinstance(arg, Starred) for arg in call.args)
        ):
            return None
        from .container_mutation import mutation_statement

        return mutation_statement(
            self,
            scope,
            call_site=call,
            receiver=call.func.value.substitute(scope),
            method=call.func.attr,
            args=tuple(arg.substitute(scope) for arg in call.args),
        )

    def _dict_setdefault_append_state(self, scope):
        """Recognize ``d.setdefault(k, v).append(x)`` by source structure.

        The method spellings select a Python built-in operation only after the
        receiver resolves through the ordinary binding map.  The shadow node
        carries that receiver and every evaluated operand; its Sugar/Floor door
        later decides whether the receiver is actually a constructed dict.
        """
        outer = self.value
        if (
            not isinstance(outer, Call)
            or outer.keywords
            or len(outer.args) != 1
            or not isinstance(outer.func, Attribute)
            or outer.func.attr != "append"
        ):
            return None
        inner = outer.func.value
        if (
            not isinstance(inner, Call)
            or inner.keywords
            or len(inner.args) != 2
            or not isinstance(inner.func, Attribute)
            or inner.func.attr != "setdefault"
            or not isinstance(inner.func.value, Name)
        ):
            return None
        receiver_name = inner.func.value.id
        receiver = inner.func.value.substitute(scope)
        if _has_authenticated_source_method(receiver, "setdefault"):
            return None
        key = inner.args[0].substitute(scope)
        default = inner.args[1].substitute(scope)
        appended = outer.args[0].substitute(scope)

        from .backend import Child, materialize
        from .shadow import ShadowNode, _handle_of

        post_state = materialize(
            self.unit,
            ShadowNode(
                "DictSetDefaultAppendState",
                self.span,
                (
                    ("receiver", Child(_handle_of(receiver))),
                    ("key", Child(_handle_of(key))),
                    ("default", Child(_handle_of(default))),
                    ("appended", Child(_handle_of(appended))),
                ),
            ),
            self.reporter,
        )
        return receiver_name, post_state

    def _mapping_pop_state(self, scope):
        """Recognize one inherited ``dict.pop(key, default)`` mutation.

        The two-argument form has one completed post-state whether or not the
        key exists.  One-argument ``pop`` can raise and remains on the ordinary
        method-call path until its exceptional ExitSet is represented.
        """
        call = self.value
        if (
            not isinstance(call, Call)
            or call.keywords
            or len(call.args) != 2
            or not isinstance(call.func, Attribute)
            or call.func.attr != "pop"
            or not isinstance(call.func.value, Name)
        ):
            return None
        receiver_name = call.func.value.id
        receiver = call.func.value.substitute(scope)
        if _has_authenticated_source_method(receiver, "pop"):
            return None

        from .backend import Child, materialize
        from .shadow import ShadowNode, _handle_of

        post_state = materialize(
            self.unit,
            ShadowNode(
                "MappingPopState",
                self.span,
                (
                    ("receiver", Child(_handle_of(receiver))),
                    ("key", Child(_handle_of(call.args[0].substitute(scope)))),
                    ("default", Child(_handle_of(call.args[1].substitute(scope)))),
                ),
            ),
            self.reporter,
        )
        return receiver_name, post_state

    def _construct_sugar(self):
        """`<expr>` as a statement constructs ExprStatementSugar WITH the
        value's sugar. States nothing; an effect in the value rides."""
        from sugar_lift_py_tests.sugar.expr_statement_sugar import (
            ExprStatementSugar,
        )

        return ExprStatementSugar(value=self.value.sugar(), site=self.fragment)


class DictSetDefaultAppendStatement(Statement):
    """Shadow statement for ``d.setdefault(k, v).append(x)``.

    This is the rewritten AST statement itself.  Its expression preserves the
    source occurrence; its post-state is the value bound to ``d`` for the
    remainder of the block through the ordinary statement-binding protocol.
    """

    value: Expression
    receiver_name: str
    post_state: Expression
    _child_fields = ("value", "post_state")

    def substitute(self, scope):
        del scope
        return self

    def substitution_binding(self, scope):
        del scope
        return {self.receiver_name: self.post_state}

    def _construct_sugar(self):
        from sugar_lift_py_tests.sugar.expr_statement_sugar import (
            ExprStatementSugar,
        )

        # The shadow statement IS the mutation.  Re-running ``self.value``
        # here would execute the original method-call spelling in parallel
        # with the authenticated post-state and demand a second setdefault
        # authority.  Its post-state sugar evaluates receiver/key/default/
        # appended exactly once and owns the resulting receiver mutation.
        return ExprStatementSugar(self.post_state.sugar(), self.fragment)


class MappingPopStatement(DictSetDefaultAppendStatement):
    """Shadow statement for completed ``mapping.pop(key, default)`` state."""


class MappingPopAssignStatement(Statement):
    """One pop occurrence exporting its result and receiver post-state."""

    target_name: str
    receiver_name: str
    result: Expression
    post_state: Expression
    _child_fields = ("result", "post_state")

    def substitute(self, scope):
        del scope
        return self

    def substitution_binding(self, scope):
        del scope
        return {
            self.target_name: self.result,
            self.receiver_name: self.post_state,
        }

    def _construct_sugar(self):
        # The shadow projections own the operation.  This statement only
        # publishes them into the temporal rewrite and states no second call.
        from sugar_lift_py_tests.sugar.inert_sugar import InertSugar

        return InertSugar(site=self.fragment)


class Pass(Statement):
    pass

    def substitute(self, scope):
        """Binds nothing, no hole: substitutes to itself."""
        return self

    def _construct_sugar(self):
        """`pass` states nothing by definition: it is the syntax for an
        intentionally empty statement body. Its sugar is the honestly
        empty record, not a placeholder awaiting content."""
        from sugar_lift_py_tests.sugar.inert_sugar import InertSugar

        return InertSugar(site=self.fragment)


class Break(Statement):
    pass

    def substitute(self, scope):
        """Binds nothing, no hole: substitutes to itself."""
        return self

    def _construct_sugar(self):
        from sugar_lift_py_tests.sugar.loop_control_sugar import LoopControlSugar

        target = self.control_context.nearest_loop_target()
        return LoopControlSugar(
            "break", target.target_cid, self.fragment.seal().cid, self.fragment
        )


class ReceiverFieldStoreStatement(Statement):
    receiver_name: str
    post_state: Expression
    _child_fields = ("post_state",)

    def substitute(self, scope):
        del scope
        return self

    def substitution_binding(self, scope):
        del scope
        return {self.receiver_name: self.post_state}

    def _construct_sugar(self):
        from sugar_lift_py_tests.sugar.expr_statement_sugar import ExprStatementSugar

        return ExprStatementSugar(self.post_state.sugar(), self.fragment)


class Continue(Statement):
    pass

    def substitute(self, scope):
        """Binds nothing, no hole: substitutes to itself."""
        return self

    def _construct_sugar(self):
        from sugar_lift_py_tests.sugar.loop_control_sugar import LoopControlSugar

        target = self.control_context.nearest_loop_target()
        return LoopControlSugar(
            "continue", target.target_cid, self.fragment.seal().cid, self.fragment
        )


class Match(Statement):
    subject: Expression
    cases: Tuple[MatchCase, ...]
    _child_fields = ("subject", "cases")

    def substitute(self, scope):
        """The subject evaluates in the enclosing scope; each case's captures
        bind to that SUBJECT for its body. `case x:` is x = subject, so the
        subject node is threaded into that case's body substitution as the
        capture binding -- the temporal half of a capture, exactly as an
        assignment's rhs threads to the rest of a block."""
        from .shadow import rewrite

        new_subject, subj_changed = self._substitute_field(self.subject, scope)
        subject = new_subject if subj_changed else self.subject

        new_cases = []
        cases_changed = False
        for case in self.cases:
            capture = self._capture_name(case.pattern)
            if capture is not None:
                new_case = case.substitute(scope, extra_bindings={capture: subject})
            else:
                new_case = case.substitute(scope)
            if new_case is not case:
                cases_changed = True
            new_cases.append(new_case)

        changed = {}
        if subj_changed:
            changed["subject"] = new_subject
        if cases_changed:
            changed["cases"] = tuple(new_cases)
        return self if not changed else rewrite(self, **changed)

    def _pattern_alternatives(self, pattern):
        """The value-pattern alternatives a case matches, as literal sugars:
        ``()`` for a catch-all (`case _:` / capture `case x:`), ``(sugar,)`` for a
        value or singleton, the concatenation for an OR-pattern `a | b`. Returns
        None for a pattern this cut does not own (structural: sequence / mapping /
        class / star, or a nested capture inside an OR)."""
        if pattern.kind == "MatchValue":
            return (pattern.value.sugar(),)
        if pattern.kind == "MatchSingleton":
            return (self._singleton_sugar(pattern.value),)
        if pattern.kind == "MatchAs" and pattern.pattern is None:
            return ()  # wildcard or capture -- always matches
        if pattern.kind == "MatchOr":
            alts: list = []
            for sub in pattern.patterns:
                sub_alts = self._pattern_alternatives(sub)
                # An OR of value/singleton patterns only; a catch-all or
                # structural arm inside an OR is not a value alternative.
                if not sub_alts:
                    return None
                alts.extend(sub_alts)
            return tuple(alts)
        return None

    def _singleton_sugar(self, value):
        """The literal sugar for a MatchSingleton value (None / True / False)."""
        if value is None:
            from sugar_lift_py_tests.sugar.none_literal_sugar import NoneLiteralSugar

            return NoneLiteralSugar(site=self.fragment)
        if value:
            from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
                TrueBoolLiteralSugar,
            )

            return TrueBoolLiteralSugar(site=self.fragment)
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )

        return FalseBoolLiteralSugar(site=self.fragment)

    @staticmethod
    def _capture_name(pattern):
        """The name a bare capture pattern (`case x:`) binds, or None. A capture
        is a MatchAs with no sub-pattern and a name; `case _:` (name None) is the
        wildcard and binds nothing."""
        if (
            pattern.kind == "MatchAs"
            and pattern.pattern is None
            and pattern.name is not None
        ):
            return pattern.name
        return None

    def _construct_sugar(self):
        """`match <subject>: case P: body ...` constructs MatchSugar -- an n-way
        guarded split. This first cut owns VALUE patterns (`case <literal>:`) and
        the wildcard (`case _:`), with no pattern guard and no capture. Any other
        pattern, a `case P if g:` guard, or a capture inherits the loud throw --
        each is real matching semantics, never guessed.
        """
        from sugar_lift_py_tests.sugar.match_sugar import MatchCaseSpec, MatchSugar

        specs = []
        for case in self.cases:
            if case.guard is not None:
                return super()._construct_sugar()  # `case P if g:` not written
            alternatives = self._pattern_alternatives(case.pattern)
            if alternatives is None:
                return (
                    super()._construct_sugar()
                )  # structural pattern (sequence/class/...)
            specs.append(
                MatchCaseSpec(
                    alternatives=alternatives,
                    body=tuple(s.sugar() for s in case.body),
                )
            )
        return MatchSugar(
            subject=self.subject.sugar(), cases=tuple(specs), site=self.fragment
        )


# --------------------------------------------------------------------------
# Expressions
# --------------------------------------------------------------------------


class BoolOp(Expression):
    op: BooleanOperator
    values: Tuple[Expression, ...]
    _child_fields = ("values",)

    def substitute(self, scope):
        """Binds nothing: recurse into children and reassemble."""
        return self._substitute_children(scope)

    def _construct_sugar(self):
        """`a and b` / `a or b` constructs BoolOpSugar WITH each operand's sugar.
        The node knows its connective (And/Or); the operands recognize themselves."""
        from sugar_lift_py_tests.sugar.bool_op_sugar import BoolOpSugar

        return BoolOpSugar(
            op_kind=self.op.kind,
            values=tuple(v.sugar() for v in self.values),
            site=self.fragment,
        )


class NamedExpr(Expression):
    _bound_target_fields = ("target",)
    target: Expression
    value: Expression
    _child_fields = ("target", "value")

    # A walrus's evaluation is keyed exactly as a statement's is.
    _evaluation_exit_path = Statement._evaluation_exit_path
    _evaluation_key = Statement._evaluation_key

    def substitute(self, scope):
        """`(<target> := <value>)` -- substitute the value; the target is a
        binding site, not substituted. The walrus's binding leaks to the
        enclosing block (collected by `_substitute_body`).

        A plain Name target carries the coordinate of this walrus's one
        evaluation (``evaluation``, minted as ``AugAssign._evaluation_key``
        mints a statement's, with the exit path it is keyed under):
        ``NamedExpressionValue`` binds the assigned value under it, and every
        later read substitution rewrites is an ``EvaluationRef`` to it
        (temporal choice 1, #7661)."""
        from .backend import Leaf, materialize
        from .shadow import (
            OccurrenceShadowNode,
            ShadowNode,
            occurrence_tags_of,
            rewrite,
        )

        new_value, d = self._substitute_field(self.value, scope)
        rewritten = self if not d else rewrite(self, value=new_value)
        if not isinstance(rewritten.target, Name):
            return rewritten
        desc = rewritten.ref.describe()
        span = desc.raw_span or self.span
        # A re-substitution replaces the key slots it was given: a node
        # answers its FIRST slot of a name.
        slots = (
            *(
                slot
                for slot in desc.slots
                if slot[0] not in ("evaluation", "evaluation_exit_path", "deferred")
            ),
            ("evaluation", Leaf(self._evaluation_key(scope))),
            ("evaluation_exit_path", Leaf(self._evaluation_exit_path(scope))),
        )
        if scope.get(_DEFERRED_WALRUS):
            # In a generator expression's element or conditions: this walrus
            # writes when the generator is consumed (``GeneratorExp``).
            slots = (*slots, ("deferred", Leaf(True)))
        tags = occurrence_tags_of(rewritten)
        # As ``rewrite`` does: one evaluation's rewrite is still that
        # evaluation, and keeps its enclosing control context.
        shadow = (
            OccurrenceShadowNode(desc.kind, span, slots, tags)
            if tags
            else ShadowNode(desc.kind, span, slots)
        )
        return materialize(self.unit, shadow, self.reporter, self.control_context)

    def substitution_binding(self, scope):
        # `x := e` binds x to a reference to this walrus's one evaluation
        # (temporal choice 1, #7661).  Only a plain Name target binds.  The
        # read resolves through the key only: a walrus nested in an operand
        # carries its bind out to the enclosing statement on the value
        # (``carry_walrus_binds``), and a comprehension's element and
        # conditions write it per member.  A walrus in a generator
        # expression writes when the generator is consumed: its reference is
        # ``deferred``.  A walrus that was never substituted carries no key:
        # it binds x to its value.
        if not isinstance(self.target, Name):
            return None
        evaluation = getattr(self, "evaluation", None)
        if not isinstance(evaluation, str):
            return {self.target.id: self.value}
        return {
            self.target.id: _evaluation_ref(
                self,
                self.target.span,
                evaluation,
                self.target.id,
                walrus=True,
                deferred=getattr(self, "deferred", False) is True,
            )
        }

    def _construct_sugar(self):
        """`(name := value)` constructs NamedExprSugar for a plain Name target.

        Other targets stay loud — no silent destructuring walrus.
        """
        if not isinstance(self.target, Name):
            return super()._construct_sugar()
        from sugar_lift_py_tests.sugar.named_expr_sugar import NamedExprSugar

        evaluation = getattr(self, "evaluation", None)
        return NamedExprSugar(
            name=self.target.id,
            value=self.value.sugar(),
            site=self.fragment,
            evaluation=evaluation if isinstance(evaluation, str) else None,
        )


class BinOp(Expression):
    left: Expression
    op: BinaryOperator
    right: Expression
    _child_fields = ("left", "right")

    def substitute(self, scope):
        """A binary operation binds nothing: it just recurses into its two
        operands and reassembles. The op itself is a leaf, carried through."""
        return self._substitute_children(scope)

    def _construct_sugar(self):
        """`<left> <op> <right>` constructs BinOpSugar WITH both sides' sugars.
        The node already knows its operator, so one sugar dispatches to the
        floor method that operator names. An operator with no floor method is a
        genuine gap -- it inherits the base throw, never a silent default."""
        from sugar_lift_py_tests.sugar.binop_sugar import BINOP_METHODS, BinOpSugar

        if self.op.kind not in BINOP_METHODS:
            return super()._construct_sugar()
        return BinOpSugar(
            op_kind=self.op.kind,
            left=self.left.sugar(),
            right=self.right.sugar(),
            site=self.fragment,
        )


class UnaryOp(Expression):
    op: UnaryOperator
    operand: Expression
    _child_fields = ("operand",)

    def substitute(self, scope):
        """Binds nothing: recurse into children and reassemble."""
        return self._substitute_children(scope)

    def _construct_sugar(self):
        """`<op> <operand>` constructs UnaryOpSugar WITH the operand's sugar. The
        node already knows its operator; an operator with no floor method inherits
        the base throw, never a silent default."""
        from sugar_lift_py_tests.sugar.unary_op_sugar import (
            UNARYOP_METHODS,
            UnaryOpSugar,
        )

        if self.op.kind != "Not" and self.op.kind not in UNARYOP_METHODS:
            return super()._construct_sugar()
        return UnaryOpSugar(
            op_kind=self.op.kind, operand=self.operand.sugar(), site=self.fragment
        )


class Lambda(Expression):
    params: Tuple[Param, ...]
    body: Expression
    _child_fields = ("params", "body")

    @property
    def args(self):
        return _arguments_projection(self.params)

    def substitute(self, scope):
        """Mask formals and mark the result as substitution-authenticated.

        A lambda an eager comprehension stores in what it produces is called
        after the comprehension, so its body reads each comprehension name
        through the comprehension's cell (``_closure_cell_scope``): what the
        cell holds once the comprehension is done, never the member of the
        iteration that built the lambda.  This holds for every enclosing
        comprehension whose result the lambda escapes, one cell layer each
        (``[[lambda: x for _ in ys] for x in xs]`` reads the outer's final
        ``x``); an inner comprehension's cell masks an outer one's.  The
        formals' defaults are evaluated when the lambda is built and read the
        current member."""
        from .shadow import rewrite

        layers = scope.get(_CLOSURE_CELLS)
        if layers is not None:
            scope = {k: v for k, v in scope.items() if k is not _CLOSURE_CELLS}
        bound = {p.name for p in self.params}
        bs = {k: v for k, v in scope.items() if k not in bound} if bound else scope
        position = _source_position(self)
        for stored, held in layers or ():
            if position in stored:
                cell_reads = {
                    name: cell for name, cell in held.items() if name not in bound
                }
                bs = {**bs, **cell_reads}
        new_params, d = self._substitute_field(self.params, scope)
        del d
        new_body, d = self._substitute_field(self.body, bs)
        del d
        # Always rewrite, even when the children are identical.  A ShadowNode
        # is the construction-time testimony that capture substitution ran.
        return rewrite(self, params=new_params, body=new_body)

    def source_visible_call_frame(self):
        """Project the lambda through the ordinary source-call-frame door."""
        from sugar_lift_py_tests.context_manager_resolution import (
            SourceFragmentCoordinateV1,
        )
        from sugar_lift_py_tests.source_call_frame import SourceVisibleCallFrameV1
        from sugar_source_tree.binding_provenance import BindingCoordinateV1

        span = self.line_col_span()
        site = SourceFragmentCoordinateV1(
            self.unit.source_cid,
            span.start_line,
            span.start_col,
            span.end_line,
            span.end_col,
        )
        owner_cid = self.fragment.seal().cid
        coordinates = tuple(
            BindingCoordinateV1.mint(owner_cid, param.fragment, ("formal", index))
            for index, param in enumerate(self.params)
        )
        formal_scope = {
            param.name: self._make_coordinate_ref(param, coordinate)
            for param, coordinate in zip(self.params, coordinates, strict=True)
        }
        return SourceVisibleCallFrameV1(
            source_identity_cid=self.unit.source_cid,
            definition_site=site,
            definition_fragment_cid=owner_cid,
            parameters=tuple(param.name for param in self.params),
            formal_coordinates=coordinates,
            formal_declaration_sites=tuple(
                param.fragment.seal().to_dict() for param in self.params
            ),
            formal_projection_paths=tuple(
                ("formal", index) for index, _ in enumerate(self.params)
            ),
            parameter_kinds=tuple(param.param_kind for param in self.params),
            default_sugars=tuple(
                param.default.sugar() if param.default is not None else None
                for param in self.params
            ),
            default_nodes=tuple(param.default for param in self.params),
            default_fragments=tuple(
                param.default.fragment if param.default is not None else None
                for param in self.params
            ),
            default_fragment_cids=tuple(
                param.default.fragment.seal().cid if param.default is not None else None
                for param in self.params
            ),
            body=self._source_visible_body(formal_scope),
            owner=self,
        )

    def _source_visible_body(self, scope):
        from sugar_lift_py_tests.sugar.return_sugar import ReturnSugar
        from sugar_lift_py_tests.sugar.source_visible_function_body_sugar import (
            SourceVisibleFunctionBodySugar,
        )

        body = self.body.substitute(scope)
        return SourceVisibleFunctionBodySugar(
            (ReturnSugar(value=body.sugar(), site=self.fragment),), self.fragment
        )

    def _make_coordinate_ref(self, param: "Param", coordinate) -> "Node":
        from .backend import Leaf, materialize
        from .shadow import ShadowNode

        return materialize(
            self.unit,
            ShadowNode(
                "BindingCoordinateRef",
                param.span,
                (("coordinate", Leaf(coordinate)),),
            ),
            self.reporter,
        )

    def _construct_sugar(self):
        """Construct an expression lambda carrying its ordinary source frame."""
        from .shadow import ShadowNode

        if not isinstance(self.ref, ShadowNode):
            # Asked for outside a substituted body (a default formal:
            # ``f=lambda x: x.sum()``, 1 row on the 2026-09-05 board). The law
            # is the same as inside one: mask the formals by substitution
            # first, then construct. Never the bare gap.
            return self.substitute({}).sugar()

        from sugar_lift_py_tests.sugar.lambda_sugar import LambdaSugar

        frame = self.source_visible_call_frame()
        return LambdaSugar(
            formals=tuple(param.name for param in self.params),
            body=self.body.sugar(),
            source_call_frame=frame,
            formal_coordinate_cids=tuple(
                coordinate.cid for coordinate in frame.formal_coordinates
            ),
            body_fragment_cid=self.body.fragment.seal().cid,
            site=self.fragment,
            closure_coordinates=self._closure_coordinates(),
        )

    def _closure_coordinates(self) -> tuple:
        """The final-member coordinates this lambda's body reads through an
        enclosing comprehension's cell (``cell`` references,
        ``_final_member_cells``), in pre-order.  ``LambdaSugar`` carries
        their bindings in the lambda value, so its body reduces after the
        comprehension is done."""
        found = []
        for node in self.body.walk():
            if (
                isinstance(node, EvaluationRef)
                and getattr(node, "cell", False) is True
                and node.evaluation not in found
            ):
                found.append(node.evaluation)
        return tuple(found)


class IfExp(Expression):
    test: Expression
    body: Expression
    orelse: Expression
    _child_fields = ("body", "test", "orelse")

    def substitute(self, scope):
        """Binds nothing: recurse into children and reassemble.

        A walrus in an arm (``a if c else (x := 5)``) runs on its arm only,
        and a later read of ``x`` is a reference to its key.  On the other arm
        ``x`` keeps the value it had before the expression, so for each such
        walrus whose name is bound here the expression carries the read of
        that name (``walrus_priors``, keyed by ``walrus_prior_keys``); the arm
        the walrus did not run on holds it under the walrus's key
        (``IfExpSugar._holding``).  A walrus in a lambda or a generator
        expression inside an arm does not run with the arm and is not
        listed."""
        rewritten = self._substitute_children(scope)
        keys = []
        priors = []
        for arm in (rewritten.body, rewritten.orelse):
            for walrus in _arm_walruses(arm):
                if walrus.target.id not in scope:
                    continue
                prior = walrus.target.substitute(scope)
                if prior is walrus.target:
                    continue
                keys.append((walrus.evaluation, walrus.target.id))
                priors.append(prior)
        if not keys:
            return rewritten
        from .backend import Children, Leaf, materialize
        from .shadow import OccurrenceShadowNode, ShadowNode, occurrence_tags_of

        desc = rewritten.ref.describe()
        span = desc.raw_span or rewritten.span
        # A re-substitution replaces the priors it was given.
        slots = (
            *(
                slot
                for slot in desc.slots
                if slot[0] not in ("walrus_priors", "walrus_prior_keys")
            ),
            ("walrus_priors", Children(tuple(prior.ref for prior in priors))),
            ("walrus_prior_keys", Leaf(tuple(keys))),
        )
        tags = occurrence_tags_of(rewritten)
        shadow = (
            OccurrenceShadowNode(desc.kind, span, slots, tags)
            if tags
            else ShadowNode(desc.kind, span, slots)
        )
        return materialize(
            rewritten.unit, shadow, rewritten.reporter, rewritten.control_context
        )

    def _construct_sugar(self):
        """`<body> if <test> else <orelse>` constructs IfExpSugar -- the
        conditional VALUE the phi produces. It desugars to a GuardedValue that
        DISTRIBUTES (a return/equality splits into per-arm implications, each arm
        resolved per-atom), so the conditional never becomes a single mixed-sort
        term; the compiler stays Python-ignorant and only ever sees ir.eq.

        Arms must be ConstructedTermSugar so IfExpSugar can project to_term.
        SpreadCollectionSugar IS ConstructedTermSugar (to_term admitted) — a
        ``[a, *xs] if c else ys`` arm constructs. Any arm that is still only
        Sugar refuses with SugarNotWritten, never a raw TypeError.
        """
        from sugar_lift_py_tests.sugar.if_exp_sugar import IfExpSugar
        from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
        from sugar_source_tree.panic import SugarNotWritten

        test = self.test.sugar()
        body = self.body.sugar()
        orelse = self.orelse.sugar()
        for arm_name, arm in (("test", test), ("body", body), ("orelse", orelse)):
            if isinstance(arm, ConstructedTermSugar):
                continue
            raise SugarNotWritten(
                blame=self.fragment,
                owner="IfExp._construct_sugar",
                observed=(
                    f"IfExp.{arm_name} constructed {type(arm).__name__}, which is "
                    "not ConstructedTermSugar"
                ),
                requested=(
                    "IfExp arms that are ordinary constructed terms so "
                    "IfExpSugar can project to_term and distribute"
                ),
                fix=(
                    f"write IfExp+{type(arm).__name__} construction (promote the "
                    "arm sugar to ConstructedTermSugar with to_term), or keep "
                    "this coordinate loud until that sugar exists — never a "
                    "bare TypeError from a type assertion"
                ),
            )
        return IfExpSugar(
            test=test,
            body=body,
            orelse=orelse,
            site=self.fragment,
            # A phi's test already IS a slot (an ``if``'s branch result or a
            # ``try``'s route): the expression is guarded by that slot itself,
            # the one its owner confirms.  Minting a second slot from the
            # reference's span left the joined value under a coordinate
            # nothing authenticates.
            branch_slot=(
                BranchResultSlot(self.test.slot_id)
                if isinstance(self.test, BranchResultRef)
                else branch_result_slot(self.test)
            ),
            walrus_priors=tuple(
                (evaluation, name, prior.sugar())
                for (evaluation, name), prior in zip(
                    getattr(self, "walrus_prior_keys", ()),
                    getattr(self, "walrus_priors", ()),
                )
            ),
        )


class Dict(Expression):
    items: Tuple[DictItem, ...]
    _child_fields = ("items",)

    @property
    def keys(self) -> Tuple[Optional[Expression], ...]:
        return tuple(item.key for item in self.items)

    @property
    def values(self) -> Tuple[Expression, ...]:
        return tuple(item.value for item in self.items)

    def substitute(self, scope):
        """Binds nothing: recurse into children and reassemble."""
        return self._substitute_children(scope)

    def _construct_sugar(self):
        """`{k: v, ...}` constructs DictSugar WITH each key and value sugar.
        A `**d` entry uses the reference lifter's None-key spread shape."""
        from sugar_lift_py_tests.sugar.collection_sugar import DictSugar

        if any(item.key is None for item in self.items):
            from sugar_lift_py_tests.sugar.spread_sugar import SpreadDictSugar

            return SpreadDictSugar(
                entries=tuple(
                    (
                        item.key.sugar() if item.key is not None else None,
                        item.value.sugar(),
                    )
                    for item in self.items
                ),
                site=self.fragment,
            )
        return DictSugar(
            keys=tuple(item.key.sugar() for item in self.items),
            values=tuple(item.value.sugar() for item in self.items),
            site=self.fragment,
        )


class Set(Expression):
    elts: Tuple[Expression, ...]
    _child_fields = ("elts",)

    def substitute(self, scope):
        """Binds nothing: recurse into children and reassemble."""
        return self._substitute_children(scope)

    def _construct_sugar(self):
        """`{e, ...}` constructs SetSugar; a spread uses its reference term."""
        from sugar_lift_py_tests.sugar.collection_sugar import SetSugar

        if any(isinstance(e, Starred) for e in self.elts):
            from sugar_lift_py_tests.sugar.spread_sugar import SpreadCollectionSugar

            return SpreadCollectionSugar(
                kind="set",
                elements=tuple(
                    (
                        ("python:starred", e.value.sugar())
                        if isinstance(e, Starred)
                        else (None, e.sugar())
                    )
                    for e in self.elts
                ),
                site=self.fragment,
            )
        return SetSugar(
            elements=tuple(e.sugar() for e in self.elts), site=self.fragment
        )


class ListComp(Expression):
    elt: Expression
    generators: Tuple[Comprehension, ...]
    _child_fields = ("elt", "generators")

    def substitute(self, scope):
        """A comprehension: thread each generator's target, then substitute the
        element against the scope with every target masked.

        Over a CONCRETE iterable it DISSOLVES -- `map` disappearing for real:
        `[e for x in [1, 2, 3]]` is three substitutions of x into e, and the
        comprehension rewrites to the List DISPLAY of those elements. The
        comprehension was never a meaning; it was a count of rewrites."""
        unrolled = (
            None
            if scope.get(_NESTED_COMPREHENSION_TEMPLATE)
            else self._try_unroll_to_display(scope)
        )
        if unrolled is not None:
            return unrolled
        from .shadow import rewrite

        new_gens, inner, gc = self._substitute_generators(self.generators, scope)
        template_scope = _member_closure_scope(self, inner, (self.elt,))
        if ListComp._contains_forbidden_shape(self, (self.elt,)):
            template_scope = {**template_scope, _NESTED_COMPREHENSION_TEMPLATE: True}
        new_elt, de = self._substitute_field(self.elt, template_scope)
        changed = {}
        if gc:
            changed["generators"] = new_gens
        if de:
            changed["elt"] = new_elt
        rewritten = rewrite(self, **changed) if changed else self
        return ListComp._carrying_walrus_priors(
            self, rewritten, (rewritten.elt,), scope
        )

    def _try_unroll_to_display(self, scope):
        """The List display this comprehension dissolves to, or None. One
        synchronous generator with ground-decidable filters,
        over a CONCRETE iterable whose elements destructure into the target:
        each element substitutes into `elt`, and the results are the display's
        elements. Reuses For's readers (same structural recognition).

        A lambda the display stores reads the last element's projection
        (``_closure_cell_scope``): the cell holds it once the comprehension is
        done, whichever members the filters kept."""
        if len(self.generators) != 1 or ListComp._contains_forbidden_shape(
            self, (self.elt,)
        ):
            return None
        gen = self.generators[0]
        if gen.is_async or ListComp._contains_forbidden_shape(
            self, (gen.iter, *gen.ifs)
        ):
            return None
        new_iter, ic = self._substitute_field(gen.iter, scope)
        it = new_iter if ic else gen.iter
        if ListComp._calls_shadowed_range(self, it, scope):
            return None
        elements = For._concrete_elements(self, it, (self.elt, *gen.ifs), scope)
        if elements is None:
            return None
        if len(elements) > For._UNROLL_FUEL:
            return None
        target = gen.target
        final = ListComp._final_element_cells(self, target, elements, (self.elt,))
        if final is None:
            return None
        results = []
        for index, element in enumerate(elements):
            bindings = self.unit.require_target_pattern(self, target).bindings_for(
                element
            )
            if bindings is None:
                return None
            inner = {**scope, **bindings}
            filters_pass = ListComp._ground_filters_pass(self, gen.ifs, inner)
            if filters_pass is None:
                return None
            if not filters_pass:
                continue
            new_elt, _d = self._substitute_field(
                self.elt, _closure_cell_scope(inner, (self.elt,), final)
            )
            # Each member is its own evaluation of the element expression.
            (member,) = _iteration_copies(self, index, (new_elt if _d else self.elt,))
            results.append(member)
        return ListComp._make_list(self, tuple(results))

    def _final_element_cells(self, target, elements, roots) -> "Optional[dict]":
        """What a dissolving comprehension's cells hold once it is done: the
        last element's projection through ``target``, for the lambdas
        ``roots`` store (``_closure_cell_scope``).  Empty when ``roots`` store
        no lambda or there is no element; None when the last element does not
        project (the comprehension does not dissolve)."""
        if not elements or not _stored_closures(roots):
            return {}
        return self.unit.require_target_pattern(self, target).bindings_for(
            elements[-1]
        )

    def _ground_filters_pass(self, filters, scope) -> "Optional[bool]":
        """The conjunction of constructed ground filters, or no testimony.

        Every comprehension kind shares this reader. A symbolic guard yields
        ``None`` so the enclosing node stays loud; no guard verdict is guessed.
        """
        verdicts = []
        for guard in filters:
            new_guard, changed = self._substitute_field(guard, scope)
            verdict = While._ground_truth(self, new_guard if changed else guard)
            if verdict is None:
                return None
            verdicts.append(verdict)
        return all(verdicts)

    def _contains_forbidden_shape(self, roots: tuple) -> bool:
        """True for a nested comprehension or walrus in this comprehension."""
        return any(
            node.kind
            in ("ListComp", "SetComp", "DictComp", "GeneratorExp", "NamedExpr")
            for root in roots
            for node in root.walk()
        )

    def _contains_named_expression(self, roots: tuple) -> bool:
        """True when a walrus would bind outside the comprehension coordinate.

        This -- not `_contains_forbidden_shape` -- is the obstruction every
        comprehension kind consults when constructing its sugar, for the one
        position whose bind no fold carries: a generator's iterable, where
        Python rejects a walrus at compile time (PEP 572: "assignment
        expression cannot be used in a comprehension iterable expression").
        A walrus in an element, a key or value, or a condition constructs:
        it writes its key per member and the value carries the last write to
        the enclosing statement (``ComprehensionSugar``); a generator
        expression's writes wait for the generator to be consumed
        (``_DEFERRED_WALRUS``). A nested comprehension is no obstruction at
        all: it is simply another sugar in that position, constructed by its
        own `_construct_sugar` when the element is lifted. All four kinds
        share this one reader; `_contains_forbidden_shape` remains the
        separate, stricter question asked only when DISSOLVING to a display.
        """
        return any(node.kind == "NamedExpr" for root in roots for node in root.walk())

    def _carrying_walrus_priors(self, node, roots: tuple, scope):
        """``node`` (this comprehension, substituted) carrying its walrus
        roster: each walrus in ``roots`` and its generators' conditions, as
        ``(name, evaluation key)``, and the read of that name in the scope
        the comprehension is evaluated in, before any member runs.

        A list, set or dict comprehension whose members never reach a walrus
        writes nothing: after it the name keeps the binding it had before,
        and the read after it is that binding (``ComprehensionSugar``).  The
        prior read is substitution's own read of the name at this point, the
        same read a source ``name`` here would be, never the name looked up
        by spelling at reduce.  ``node`` without a walrus is returned as it
        is.

        A walrus in a lambda binds the lambda's own scope, and a generator
        expression's (``deferred``) writes when it is consumed: neither is a
        write this comprehension makes or withholds, so neither is rostered.
        """
        from .backend import Children, Leaf, materialize
        from .shadow import (
            OccurrenceShadowNode,
            ShadowNode,
            _handle_of,
            occurrence_tags_of,
        )

        roots = (*roots, *(guard for gen in node.generators for guard in gen.ifs))
        candidates = [
            walrus
            for root in roots
            for walrus in root.walk()
            if walrus.kind == "NamedExpr"
        ]
        if not candidates:
            return node
        in_lambda = {
            id(inner)
            for root in roots
            for lam in root.walk()
            if lam.kind == "Lambda"
            for inner in lam.walk()
        }
        walruses = [
            walrus
            for walrus in candidates
            if walrus.target.kind == "Name"
            and isinstance(getattr(walrus, "evaluation", None), str)
            and getattr(walrus, "deferred", False) is not True
            and id(walrus) not in in_lambda
        ]
        if not walruses:
            return node
        roster = tuple((walrus.target.id, walrus.evaluation) for walrus in walruses)
        priors = tuple(
            For._make_name(self, name).substitute(scope) for name, _key in roster
        )
        desc = node.ref.describe()
        span = desc.raw_span or node.span
        slots = (
            *(
                slot
                for slot in desc.slots
                if slot[0] not in ("walrus_roster", "walrus_priors")
            ),
            ("walrus_roster", Leaf(roster)),
            ("walrus_priors", Children(tuple(_handle_of(prior) for prior in priors))),
        )
        tags = occurrence_tags_of(node)
        shadow = (
            OccurrenceShadowNode(desc.kind, span, slots, tags)
            if tags
            else ShadowNode(desc.kind, span, slots)
        )
        return materialize(node.unit, shadow, node.reporter, node.control_context)

    def _walrus_prior_sugars(self) -> tuple:
        """``(name, evaluation key, prior read sugar)`` for each walrus
        ``_carrying_walrus_priors`` rostered; empty when it rostered none."""
        roster = getattr(self, "walrus_roster", None)
        if not roster:
            return ()
        return tuple(
            (name, evaluation, prior.sugar())
            for (name, evaluation), prior in zip(
                roster, self.walrus_priors, strict=True
            )
        )

    def _calls_shadowed_range(self, iterable, scope) -> bool:
        return (
            (
                iterable.kind == "Call"
                and iterable.func.kind == "Name"
                and iterable.func.id == "range"
                and "range" in scope
            )
            or (
                iterable.kind == "Call"
                and iterable.func.kind == "Name"
                and iterable.func.id == "range"
                and "range" in scope.get(_LEXICALLY_BOUND_NAMES, ())
            )
            or (
                iterable.kind == "Call"
                and iterable.func.kind == "Name"
                and iterable.func.id == "range"
                and "range" in self.unit.module_bound_names
            )
        )

    def _ground_hash_key(self, expression):
        """A Python-equality key for the small ground scalar domain, or None."""
        integer = For._concrete_int(self, expression)
        if integer is not None:
            return ("number", integer)
        if expression.kind != "Constant":
            return None
        value = expression.value
        if type(value) is bool:
            return ("number", int(value))
        if type(value) is str:
            return ("str", value)
        if value is None:
            return ("none", None)
        return None

    def _make_list(self, elements: tuple) -> "Node":
        """Synthesize a List display of these element nodes, borrowing this
        comprehension's span -- the dissolved `map`, a display like any other."""
        from .backend import Children, materialize
        from .shadow import ShadowNode, _handle_of

        slots = (("elts", Children(tuple(_handle_of(e) for e in elements))),)
        return materialize(
            self.unit, ShadowNode("List", self.span, slots), self.reporter
        )

    def _construct_sugar(self):
        # A walrus in the element or a condition constructs: it writes its
        # key per member, and the comprehension's value carries the last
        # write out to the enclosing statement; where no member writes it,
        # the name keeps its prior binding (``walrus_priors``).  A walrus in
        # an iterable is a Python compile error and stays loud
        # (``_recurrence_generators``).
        generators = ListComp._recurrence_generators(self)
        if generators is None:
            return super()._construct_sugar()
        from sugar_lift_py_tests.sugar.comprehension_sugar import (
            ComprehensionSugar,
        )

        return ComprehensionSugar(
            kind="py.listcomp",
            generators=generators,
            element=self.elt.sugar(),
            site=self.fragment,
            walrus_priors=ListComp._walrus_prior_sugars(self),
        )

    def _comprehension_target(self, target: "Node"):
        """The binding pattern a generator target denotes, or None when its
        shape has no sugar written.

        A `Name` binds the element whole; a tuple/list target destructures it
        position by position, nesting as the source nests. A starred or
        attribute/subscript target builds nothing -- the comprehension then
        stays loud rather than binding a shape this does not model.
        """
        from sugar_lift_py_tests.sugar.comprehension_sugar import (
            ComprehensionTargetSugar,
        )

        if target.kind == "Name":
            return ComprehensionTargetSugar(source_name=target.id)
        if target.kind not in ("Tuple", "List"):
            return None
        coordinates = []
        for position in target.elts:
            child = ListComp._comprehension_target(self, position)
            if child is None:
                return None
            coordinates.append(child)
        if not coordinates:
            return None
        return ComprehensionTargetSugar(coordinates=tuple(coordinates))

    def _generator_binding_coordinate(self, generator_index: int, gen) -> str:
        """The coordinate generator ``generator_index`` binds each member
        under: the comprehension's source occurrence and the target's site.
        A rewrite borrows the origin's span, so substitution and construction
        mint the same coordinate."""
        from sugar_lift_python_source.canonical import cid_of_json
        from .binding_state import mint_binding_coordinate_v1

        scope_owner_cid = cid_of_json(
            {
                "kind": "comprehension-binding-scope",
                "schemaVersion": "1",
                "source": self.fragment.seal().to_dict(),
            }
        )
        return mint_binding_coordinate_v1(
            scope_owner_cid=scope_owner_cid,
            binding_site=gen.target.fragment,
            projection_path=("generators", generator_index, "target"),
        ).cid

    def _target_references(self, generator_index: int, gen) -> dict:
        """Each name generator ``generator_index``'s target binds, to an
        ``EvaluationRef`` to the coordinate ``ComprehensionSugar`` binds its
        value under per member (temporal choice 1, #7661): the generator's
        coordinate for a name target, the target pattern's leaf coordinate
        for a destructuring one. Empty for a shape with no sugar
        (``_comprehension_target`` is None): that comprehension stays loud.
        """
        target = ListComp._comprehension_target(self, gen.target)
        if target is None:
            return {}
        if target.source_name is not None:
            return {
                target.source_name: _evaluation_ref(
                    self,
                    gen.target.span,
                    ListComp._generator_binding_coordinate(self, generator_index, gen),
                    target.source_name,
                    member=True,
                )
            }
        pattern = self.unit.require_target_pattern_for_target(gen.target)
        return {
            leaf.id: _evaluation_ref(
                self, leaf.span, coordinate.cid, leaf.id, member=True
            )
            for leaf, coordinate in zip(
                pattern.leaves, pattern.target_coordinates, strict=True
            )
        }

    def _recurrence_generators(self):
        from sugar_lift_py_tests.sugar.comprehension_sugar import (
            ComprehensionGeneratorSugar,
        )

        specs = []
        for generator_index, gen in enumerate(self.generators):
            # A walrus in an iterable never compiles (PEP 572); a walrus in
            # a condition writes per member (``ComprehensionSugar``).
            if gen.is_async or ListComp._contains_named_expression(self, (gen.iter,)):
                return None
            target = ListComp._comprehension_target(self, gen.target)
            if target is None:
                return None
            target_pattern = None
            target_coordinates = ()
            if target.coordinates is not None:
                # A destructuring generator target IS an enrolled consumer
                # site.  Zero rows here is a stranded relation, never "this
                # comprehension is symbolic" -- so read strictly and let the
                # refusal out instead of degrading to ``target_pattern=None``.
                target_pattern = self.unit.require_target_pattern(self, gen.target)
                target_coordinates = target_pattern.target_coordinates
                self.unit.require_target_pattern_coordinates(
                    target_pattern, target_coordinates
                )
            specs.append(
                ComprehensionGeneratorSugar(
                    target=target,
                    binding_coordinate_cid=ListComp._generator_binding_coordinate(
                        self, generator_index, gen
                    ),
                    iterable=gen.iter.sugar(),
                    filters=tuple(guard.sugar() for guard in gen.ifs),
                    target_coordinates=target_coordinates,
                    target_pattern=target_pattern,
                    target_pattern_enrollment=self.unit.target_pattern_enrollment(
                        self
                    ),
                )
            )
        return tuple(specs)

    def _simple_generator(self, *, allow_nested_iterable=False):
        if len(self.generators) != 1:
            return None
        gen = self.generators[0]
        if (
            gen.is_async
            or gen.ifs
            or gen.target.kind != "Name"
            or (
                ListComp._contains_named_expression(self, (gen.iter,))
                if allow_nested_iterable
                else ListComp._contains_forbidden_shape(self, (gen.iter,))
            )
        ):
            return None
        return gen


class SetComp(Expression):
    elt: Expression
    generators: Tuple[Comprehension, ...]
    _child_fields = ("elt", "generators")

    def substitute(self, scope):
        """A comprehension: thread each generator's target, then substitute the
        element against the scope with every target masked."""
        display = (
            None
            if scope.get(_NESTED_COMPREHENSION_TEMPLATE)
            else self._try_unroll_to_display(scope)
        )
        if display is not None:
            return display
        from .shadow import rewrite

        new_gens, inner, gc = self._substitute_generators(self.generators, scope)
        template_scope = _member_closure_scope(self, inner, (self.elt,))
        if ListComp._contains_forbidden_shape(self, (self.elt,)):
            template_scope = {**template_scope, _NESTED_COMPREHENSION_TEMPLATE: True}
        new_elt, de = self._substitute_field(self.elt, template_scope)
        changed = {}
        if gc:
            changed["generators"] = new_gens
        if de:
            changed["elt"] = new_elt
        rewritten = rewrite(self, **changed) if changed else self
        return ListComp._carrying_walrus_priors(
            self, rewritten, (rewritten.elt,), scope
        )

    def _try_unroll_to_display(self, scope):
        if len(self.generators) != 1 or ListComp._contains_forbidden_shape(
            self, (self.elt,)
        ):
            return None
        gen = self.generators[0]
        if (
            gen.is_async
            or ListComp._contains_forbidden_shape(self, (gen.iter,))
            # A walrus in a condition writes the enclosing scope per member:
            # a display would drop the write.
            or ListComp._contains_named_expression(self, gen.ifs)
        ):
            return None
        new_iter, changed = self._substitute_field(gen.iter, scope)
        iterable = new_iter if changed else gen.iter
        if ListComp._calls_shadowed_range(self, iterable, scope):
            return None
        elements = For._concrete_elements(
            self, iterable, (self.elt, *gen.ifs), scope
        )
        if elements is None or len(elements) > For._UNROLL_FUEL:
            return None
        results = []
        seen = set()
        for element in elements:
            bindings = self.unit.require_target_pattern(self, gen.target).bindings_for(
                element
            )
            if bindings is None:
                return None
            inner = {**scope, **bindings}
            filters_pass = ListComp._ground_filters_pass(self, gen.ifs, inner)
            if filters_pass is None:
                return None
            if not filters_pass:
                continue
            new_elt, changed = self._substitute_field(self.elt, inner)
            result = new_elt if changed else self.elt
            key = ListComp._ground_hash_key(self, result)
            if key is None:
                return None
            if key not in seen:
                seen.add(key)
                results.append(result)
        return SetComp._make_set(self, tuple(results))

    def _make_set(self, elements: tuple) -> "Node":
        from .backend import Children, materialize
        from .shadow import ShadowNode, _handle_of

        slots = (("elts", Children(tuple(_handle_of(e) for e in elements))),)
        return materialize(
            self.unit, ShadowNode("Set", self.span, slots), self.reporter
        )

    def _construct_sugar(self):
        # A walrus in the element or a condition constructs: it writes its
        # key per member (``ListComp._construct_sugar``).
        generators = ListComp._recurrence_generators(self)
        if generators is None:
            return super()._construct_sugar()
        from sugar_lift_py_tests.sugar.comprehension_sugar import ComprehensionSugar

        return ComprehensionSugar(
            kind="py.setcomp",
            generators=generators,
            element=self.elt.sugar(),
            site=self.fragment,
            walrus_priors=ListComp._walrus_prior_sugars(self),
        )


class DictComp(Expression):
    key: Expression
    value: Expression
    generators: Tuple[Comprehension, ...]
    _child_fields = ("key", "value", "generators")

    def substitute(self, scope):
        """A dict comprehension: thread the generators, then key and value
        against the scope with every target masked."""
        display = (
            None
            if scope.get(_NESTED_COMPREHENSION_TEMPLATE)
            else self._try_unroll_to_display(scope)
        )
        if display is not None:
            return display
        from .shadow import rewrite

        new_gens, inner, gc = self._substitute_generators(self.generators, scope)
        template_scope = _member_closure_scope(self, inner, (self.key, self.value))
        if ListComp._contains_forbidden_shape(self, (self.key, self.value)):
            template_scope = {**template_scope, _NESTED_COMPREHENSION_TEMPLATE: True}
        changed = {}
        if gc:
            changed["generators"] = new_gens
        for fld in ("key", "value"):
            new, d = self._substitute_field(getattr(self, fld), template_scope)
            if d:
                changed[fld] = new
        rewritten = rewrite(self, **changed) if changed else self
        return ListComp._carrying_walrus_priors(
            self, rewritten, (rewritten.key, rewritten.value), scope
        )

    def _try_unroll_to_display(self, scope):
        if len(self.generators) != 1 or ListComp._contains_forbidden_shape(
            self, (self.key, self.value)
        ):
            return None
        gen = self.generators[0]
        if (
            gen.is_async
            or ListComp._contains_forbidden_shape(self, (gen.iter,))
            # A walrus in a condition writes the enclosing scope per member:
            # a display would drop the write.
            or ListComp._contains_named_expression(self, gen.ifs)
        ):
            return None
        new_iter, changed = self._substitute_field(gen.iter, scope)
        iterable = new_iter if changed else gen.iter
        if ListComp._calls_shadowed_range(self, iterable, scope):
            return None
        elements = For._concrete_elements(
            self, iterable, (self.key, self.value, *gen.ifs), scope
        )
        if elements is None or len(elements) > For._UNROLL_FUEL:
            return None
        roots = (self.key, self.value)
        final = ListComp._final_element_cells(self, gen.target, elements, roots)
        if final is None:
            return None
        pairs = []
        key_indexes = {}
        for element in elements:
            bindings = self.unit.require_target_pattern(self, gen.target).bindings_for(
                element
            )
            if bindings is None:
                return None
            inner = {**scope, **bindings}
            filters_pass = ListComp._ground_filters_pass(self, gen.ifs, inner)
            if filters_pass is None:
                return None
            if not filters_pass:
                continue
            # A lambda the display stores reads the last element's projection
            # (``_closure_cell_scope``).
            cell_scope = _closure_cell_scope(inner, roots, final)
            key, key_changed = self._substitute_field(self.key, cell_scope)
            value, value_changed = self._substitute_field(self.value, cell_scope)
            result_key = key if key_changed else self.key
            result_value = value if value_changed else self.value
            hash_key = ListComp._ground_hash_key(self, result_key)
            if hash_key is None:
                return None
            pair = (result_key, result_value)
            prior = key_indexes.get(hash_key)
            if prior is None:
                key_indexes[hash_key] = len(pairs)
                pairs.append(pair)
            else:
                pairs[prior] = pair
        return DictComp._make_dict(self, tuple(pairs))

    def _make_dict(self, pairs: tuple) -> "Node":
        from .backend import Child, Children, materialize
        from .shadow import ShadowNode, _handle_of

        items = []
        for key, value in pairs:
            slots = (
                ("key", Child(_handle_of(key))),
                ("value", Child(_handle_of(value))),
            )
            item = materialize(
                self.unit, ShadowNode("DictItem", self.span, slots), self.reporter
            )
            items.append(_handle_of(item))
        return materialize(
            self.unit,
            ShadowNode("Dict", self.span, (("items", Children(tuple(items))),)),
            self.reporter,
        )

    def _construct_sugar(self):
        # A walrus in the key or value constructs: they write its key per
        # member (``ListComp._construct_sugar``).
        generators = ListComp._recurrence_generators(self)
        if generators is None:
            return super()._construct_sugar()
        from sugar_lift_py_tests.sugar.comprehension_sugar import ComprehensionSugar

        return ComprehensionSugar(
            kind="py.dictcomp",
            generators=generators,
            key=self.key.sugar(),
            element=self.value.sugar(),
            site=self.fragment,
            walrus_priors=ListComp._walrus_prior_sugars(self),
        )


class GeneratorExp(Expression):
    elt: Expression
    generators: Tuple[Comprehension, ...]
    _child_fields = ("elt", "generators")

    def substitute(self, scope):
        """A comprehension: thread each generator's target, then substitute the
        element against the scope with every target masked.

        A walrus in the element or a condition runs when the generator is
        consumed, not here: it is substituted ``deferred``
        (``_DEFERRED_WALRUS``), so a read after the generator is made does
        not claim its write."""
        from .shadow import rewrite

        if ListComp._contains_named_expression(
            self, (self.elt, *(guard for gen in self.generators for guard in gen.ifs))
        ):
            scope = {**scope, _DEFERRED_WALRUS: True}
        new_gens, inner, gc = self._substitute_generators(self.generators, scope)
        template_scope = inner
        if ListComp._contains_forbidden_shape(self, (self.elt,)):
            template_scope = {**inner, _NESTED_COMPREHENSION_TEMPLATE: True}
        new_elt, de = self._substitute_field(self.elt, template_scope)
        changed = {}
        if gc:
            changed["generators"] = new_gens
        if de:
            changed["elt"] = new_elt
        return self if not changed else rewrite(self, **changed)

    def _construct_sugar(self):
        # A generator's element and conditions run when it is consumed, not
        # here: a walrus in them writes nothing where the generator is made
        # (``ComprehensionSugar`` carries no write for a generator), and its
        # read is ``deferred`` (``GeneratorExp.substitute``).
        generators = ListComp._recurrence_generators(self)
        if generators is None:
            return super()._construct_sugar()
        from sugar_lift_py_tests.sugar.comprehension_sugar import ComprehensionSugar

        return ComprehensionSugar(
            kind="py.generatorexp",
            generators=generators,
            element=self.elt.sugar(),
            site=self.fragment,
        )


class Await(Expression):
    value: Expression
    _child_fields = ("value",)

    def substitute(self, scope):
        """Binds nothing: recurse into children and reassemble."""
        return self._substitute_children(scope)


class Yield(Expression):
    value: Optional[Expression]
    _child_fields = ("value",)

    def substitute(self, scope):
        """Binds nothing: recurse into children and reassemble."""
        return self._substitute_children(scope)

    def _construct_sugar(self):
        from sugar_lift_py_tests.sugar.yield_suspension_sugar import (
            YieldSuspensionSugar,
        )

        return YieldSuspensionSugar(
            value=None if self.value is None else self.value.sugar(),
            site=self.fragment,
        )


class YieldFrom(Expression):
    value: Expression
    _child_fields = ("value",)

    def substitute(self, scope):
        """Binds nothing: recurse into children and reassemble."""
        return self._substitute_children(scope)

    def _construct_sugar(self):
        """`yield from <iterable>` — delegated suspension for generators."""
        from sugar_lift_py_tests.sugar.yield_from_sugar import YieldFromSugar

        return YieldFromSugar(
            value=self.value.sugar(),
            site=self.fragment,
        )


class Compare(Expression):
    left: Expression
    ops: Tuple[ComparisonOperator, ...]
    comparators: Tuple[Expression, ...]
    _child_fields = ("left", "comparators")

    def substitute(self, scope):
        """A comparison binds nothing: recurse into its operands (the operators
        are leaves, carried through)."""
        return self._substitute_children(scope)

    def _comparison_leg_site(self, index: int, operands: tuple[Expression, ...]):
        """Return the enumerated operator occurrence for one chained leg.

        The operator token, not operand content or the enclosing Compare span,
        distinguishes adjacent operations.  Authenticate that token against
        the two operands it separates before allowing it to become an effect
        occurrence coordinate.
        """
        left = operands[index]
        right = operands[index + 1]

        def reject():
            from sugar_source_tree.panic import SugarNotWritten

            raise SugarNotWritten(
                blame=self.fragment,
                owner="Compare._comparison_leg_site",
                observed=(index, left.span, right.span),
                requested="the source-authenticated operator interval between adjacent operands",
                fix="preserve each Compare leg's adjacent operand spans in source order",
            )

        if not (
            self.span.start <= left.span.start < left.span.end
            and left.span.end < right.span.start
            and right.span.end <= self.span.end
        ):
            reject()
        gap = Span(left.span.end, right.span.start)
        if not gap.slice(self.unit.source).strip():
            reject()
        from .fragment import SourceFragment

        # Comparison operators have no backend node of their own.  The exact
        # source-authenticated occurrence is the non-empty source interval
        # between the adjacent operand nodes; the Compare grammar testifies
        # which operator occupies that interval.  Repeated operand content
        # cannot collapse these positional intervals.
        return SourceFragment(
            unit=self.unit,
            span=gap,
            node=self,
        )

    def _construct_sugar(self):
        """A comparison constructs its operator's sugar, built WITH its
        children's sugar. `==` is EqualityOpSugar (it also refines); the ordering
        family and `!=` are ComparisonOpSugar. A CHAINED comparison `a < b < c`
        constructs each adjacent pair under ChainedCompareSugar, which evaluates
        `b` once and carries that reduced value from the first leg into the second.
        """
        from .operators import Eq
        from sugar_lift_py_tests.sugar.comparison_op_sugar import (
            COMPARISON_KINDS,
            ComparisonOpSugar,
        )
        from sugar_lift_py_tests.sugar.equality_op_sugar import EqualityOpSugar

        def supported(op):
            return isinstance(op, Eq) or op.kind in COMPARISON_KINDS

        if not all(supported(op) for op in self.ops):
            return super()._construct_sugar()

        operands = (self.left, *self.comparators)
        if len(self.ops) == 1 and self.ops[0].kind in ("Is", "IsNot"):
            from .container_mutation import decided_identity

            decided = decided_identity(self.left, self.comparators[0])
            if decided is not None:
                # Object identity between decided containers (see
                # ``decided_identity``); value equality never answers ``is``.
                from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
                    FalseBoolLiteralSugar,
                )
                from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
                    TrueBoolLiteralSugar,
                )

                if decided == (self.ops[0].kind == "Is"):
                    return TrueBoolLiteralSugar(site=self.fragment)
                return FalseBoolLiteralSugar(site=self.fragment)

        def pair(index):
            op = self.ops[index]
            left_s = operands[index].sugar()
            right_s = operands[index + 1].sugar()
            site = (
                self._comparison_leg_site(index, operands)
                if len(self.ops) > 1
                else self.fragment
            )
            if isinstance(op, Eq):
                # The refinement coordinate is the PAIR's left operand, read
                # here where the tree is in hand. In a chain `a.k == b == c` the
                # second pair's left is `b`, not `a.k`; a Compare-level fragment
                # cannot tell them apart, which is why the coordinate is passed
                # rather than rediscovered from the site.
                return EqualityOpSugar(
                    left=left_s,
                    right=right_s,
                    site=site,
                    left_coordinate=operands[index].dotted_expr_name(),
                )
            return ComparisonOpSugar(
                op_kind=op.kind, left=left_s, right=right_s, site=site
            )

        pairs = tuple(pair(i) for i in range(len(self.ops)))
        if len(pairs) == 1:
            return pairs[0]
        from sugar_lift_py_tests.sugar.chained_compare_sugar import (
            ChainedCompareSugar,
        )

        return ChainedCompareSugar(values=pairs, site=self.fragment)


class Call(Expression):
    def substitute(self, scope: "dict[str, Node]") -> "Node":
        snapshot = self._locals_snapshot(scope)
        if snapshot is not None:
            return snapshot
        rewritten = self._substitute_children(scope)
        cells = self._closure_cells(scope)
        if cells:
            from .shadow import rewrite_with_leaves

            rewritten = rewrite_with_leaves(rewritten, {"closure_cells": cells})
        if (
            rewritten is not self
            and isinstance(rewritten, Call)
            and isinstance(
                self.unit.lexical_call_enrollment(self), LexicalCallEnrolledV1
            )
        ):
            self.unit.retain_lexical_call_row(self, rewritten)
        return rewritten

    func: Expression
    args: Tuple[Expression, ...]
    keywords: Tuple[Keyword, ...]
    _child_fields = ("func", "args", "keywords")

    def _closure_cells(self, scope) -> tuple:
        """``((name, binding), ...)``: what a call of a local ``def`` reads
        for each enclosing local the function's body reads
        (``FunctionDef._captured_bindings``) -- the binding this scope holds
        for the name here, at the call, as every other read of the name here
        is (``Name.substitute``).  Python reads the enclosing cell when the
        function runs, so ``y = 1; def g(): return y; y = 2; g()`` reads
        ``y``'s binding of ``y = 2``.  The call binds each value under the
        frame's captured coordinate (``CallSiteSugar``); the name is never
        read in the callee.

        Empty when the callee is not a local ``def`` this scope binds, when a
        read name is ``nonlocal`` (the body writes the cell), or when a read
        name has no value binding here (unbound, or bound to a definition or
        an import): the call then stays refused by name
        (``CallSiteSugar``)."""
        func = self.func
        if not isinstance(func, Name) or func.id not in scope:
            return ()
        from .binding_state import unwrap_binding_state

        definition = unwrap_binding_state(scope[func.id])
        if not isinstance(definition, FunctionDef):
            return ()
        names, _coordinates = definition._captured_bindings()
        if not names or definition.lacks_captured_binding_testimony(
            covered=frozenset(names)
        ):
            return ()
        cells = []
        for name in names:
            if name not in scope:
                return ()
            read = For._make_name(self, name)
            binding = read.substitute(scope)
            read.discharge_by_substitution()
            if not isinstance(binding, Node) or binding.kind in (
                "Name",
                "GuardedBindingRead",
            ):
                return ()
            cells.append((name, binding))
        return tuple(cells)

    def _captured_cells(self, frame) -> tuple:
        """``((name, coordinate cid, sugar), ...)`` for ``frame``'s captured
        names (``FunctionDef._captured_bindings``) from the cells this call
        carries (``_closure_cells``); empty unless every one is carried."""
        names = tuple(getattr(frame, "captured_names", ()) or ())
        if not names:
            return ()
        cells = getattr(self, "closure_cells", None)
        if not cells:
            return ()
        by_name = dict(cells)
        if any(name not in by_name for name in names):
            return ()
        return tuple(
            (name, coordinate.cid, by_name[name].sugar())
            for name, coordinate in zip(
                names, frame.captured_coordinates, strict=True
            )
        )

    def _locals_snapshot(self, scope) -> "Optional[Node]":
        """``locals()`` before any other local is bound: a dict of the formals.

        See ``locals_snapshot``: the builtin, called bare, directly in a
        module-level function's frame.  The snapshot is ``{name: value}`` over
        the parameters in ``co_varnames`` order, each value the parameter's
        current binding.  When any other local of the frame is already in
        scope, or a parameter's binding is not definite (deleted, guarded),
        which names the snapshot holds is not fixed here and the call stays
        an ordinary call.
        """
        if not (
            isinstance(self.func, Name)
            and self.func.id == "locals"
            and not self.args
            and not self.keywords
        ):
            return None
        from .binding_state import unwrap_binding_state
        from .locals_snapshot import locals_snapshot_shape

        span = self.line_col_span()
        shape = locals_snapshot_shape(self.unit, span.start_line, span.start_col)
        if shape is None or any(name in scope for name in shape.other_locals):
            return None
        values = []
        for name in shape.parameters:
            bound = unwrap_binding_state(scope.get(name))
            if not isinstance(bound, Node):
                return None
            values.append(bound)
        from .backend import Child, Children, Leaf, materialize
        from .shadow import ShadowNode, _handle_of

        items = []
        for name, value in zip(shape.parameters, values):
            key = materialize(
                self.unit,
                ShadowNode(
                    "Constant",
                    self.span,
                    (("value", Leaf(name)), ("literal_kind", Leaf(None))),
                ),
                self.reporter,
            )
            item = materialize(
                self.unit,
                ShadowNode(
                    "DictItem",
                    self.span,
                    (("key", Child(_handle_of(key))), ("value", Child(_handle_of(value)))),
                ),
                self.reporter,
            )
            items.append(_handle_of(item))
        return materialize(
            self.unit,
            ShadowNode("Dict", self.span, (("items", Children(tuple(items))),)),
            self.reporter,
        )

    def receiver(self) -> Optional[Expression]:
        """The object a method call is invoked on, when the callee is an
        attribute access. ``None`` is a structural absence (a plain call)."""
        func = self.func
        if isinstance(func, Attribute):
            return func.value
        return None

    def exposed_object_places(self) -> tuple["ObjectPlaceStateV1", ...]:
        """Object states crossing this call without a frame-condition proof."""
        roots = list(self.args) + [keyword.value for keyword in self.keywords]
        receiver = self.receiver()
        if receiver is not None:
            roots.append(receiver)
        seen = {}
        for root in roots:
            for node in root.walk():
                if isinstance(node, ObjectPlaceStateV1):
                    seen[node.object_identity_cid] = node
        return tuple(seen.values())

    def _project_call_definition_occurrence(
        self, definition: object, *, coordinate: str
    ) -> "FunctionDef | AsyncFunctionDef | ClassDef":
        """Reconcile a producer definition with this call reporter before mint."""
        if not isinstance(definition, (FunctionDef, AsyncFunctionDef, ClassDef)):
            raise BackendDefect(
                owner="Call._construct_sugar",
                blame=self.fragment,
                observed=f"{coordinate} producer supplied {type(definition).__name__}",
                requested="a typed source definition occurrence to reconcile",
                fix="project the parser handle through the call reporter before minting CallSiteSugar",
            )
        if self.reporter is definition.reporter:
            return definition
        retain = getattr(self.reporter, "retain_registered_node_from", None)
        if retain is None:
            return definition
        projected = retain(definition, definition.reporter)
        if not isinstance(projected, (FunctionDef, AsyncFunctionDef, ClassDef)):
            raise BackendDefect(
                owner="Call._construct_sugar",
                blame=self.fragment,
                observed=f"{coordinate} could not project {type(definition.ref).__name__}",
                requested="this roll's exact typed source definition occurrence",
                fix="repair definition registration or keep the call loud before CallSiteSugar construction",
            )
        return projected

    def _construct_sugar(self):
        """A call the module body runs at import
        (``SourceUnit.module_execution_site``: in the module body or a class
        body, not in a ``def`` or ``lambda`` body) constructs under that
        site, so every function body it reaches -- its callee's frame, and
        the frames that frame's calls reach -- reads a module global as the
        module holds it at this call (``FunctionDef._module_global_references``).
        Any other call constructs under the site it was reached from, or
        none: called from outside the module's execution.  The call itself
        constructs in ``_construct_call_sugar``."""
        unit = self.unit
        if not unit.module_evaluation_bound_names():
            return self._construct_call_sugar()
        site = unit.module_execution_site(self)
        if site is None:
            return self._construct_call_sugar()
        return construct_at_module_execution_site(site, self._construct_call_sugar)

    def _construct_call_sugar(self):
        """A call constructs its callee's sugar WITH the argument sugars.
        `<name>(<args>)` -> CallSiteSugar, the call-site coordinate (THE DIG
        CUE). `<receiver>.<name>(<args>)` -> MethodCallSugar, the method
        coordinate `call:<name>(receiver, args)` with the receiver riding as
        runtime_dispatch_receiver. Any other callee expression (`fs[i](x)`,
        `d["k"](x)`) -> ComputedCallSugar, the `py.call(callee, args)`
        coordinate -- the callee reduces through whatever sugar its own node
        built, so a callee with no sugar (a Lambda called inline) still stays
        loud through the ordinary recursion. Named keywords and ``**`` spreads
        ride explicitly on every coordinate; none is dropped or interpreted."""
        context = self._require_construction_context(owner="Call._construct_sugar")
        from sugar_lift_py_tests.context_manager_resolution import (
            TreeConstructionContextV1,
        )

        # Unconditional: this is WHERE the call is, not WHETHER a context was
        # seated. See ``Node.source_occurrence``.
        coordinate = self.source_occurrence()

        # The callee's identity, read once from its binding (never its
        # spelling); the behaviour the language fixes for it lives here.
        language_callee = self.language_callee()
        if (
            language_callee is LanguageCallee.TYPING_CAST
            and len(self.args) == 2
            and not self.keywords
            and not any(isinstance(arg, Starred) for arg in self.args)
        ):
            # typing.cast(typ, val) returns val unchanged
            # (https://docs.python.org/3/library/typing.html#typing.cast), so
            # the call constructs as its second operand: no call-site value
            # ever carries a cast for a later reader to recognise by name.
            self._discharge_callee_spelling()
            return self.args[1].sugar()

        if isinstance(context, TreeConstructionContextV1):
            # The roster states the ONE classification every authenticated
            # owner gave this call; owners that disagreed panicked at install,
            # so there is nothing here to choose between.
            obligation = context.opaque_source_call_obligations.get(coordinate)
            if obligation is not None:
                return self._not_bridged_call_site(
                    args=tuple(a.sugar() for a in self.args),
                    keywords=tuple(
                        (
                            kw.arg if kw.arg is not None else "**",
                            kw.value.sugar(),
                        )
                        for kw in self.keywords
                    ),
                    gap=f"{obligation.resolution_kind}:{obligation.target_name}",
                    language_callee=language_callee,
                )

        # Either spread form selects the reference call coordinate. In
        # particular, a lone ``**d`` must not fall through to the legacy
        # keyword bridge as ``py.kwarg("**", d)``.
        has_spread = any(isinstance(arg, Starred) for arg in self.args) or any(
            keyword.arg is None for keyword in self.keywords
        )
        if has_spread:
            from sugar_lift_py_tests.sugar.spread_sugar import SpreadCallSugar

            arguments = tuple(
                (
                    ("star", None, arg.value.sugar())
                    if isinstance(arg, Starred)
                    else ("positional", None, arg.sugar())
                )
                for arg in self.args
            ) + tuple(
                (
                    "double-star" if kw.arg is None else "keyword",
                    kw.arg,
                    kw.value.sugar(),
                )
                for kw in self.keywords
            )
            if isinstance(self.func, Name):
                # Absorbed as a spelling, never constructed -- see the
                # call-site branch below.
                self.func.discharge_by_substitution()
            # An import-bound callee is spelled by its target symbol, the one
            # spelling of every call (#7837); any other callee by its source.
            reference = self.unit.import_reference_of(self.func)
            callee_name = (
                reference[len("python:") :]
                if reference is not None and reference.startswith("python:")
                else self._spread_callee_name(self.func)
            )
            # Enroll an authenticated source-visible frame when the call is a
            # local constructor/function use-site. Typed ``**`` actuals then
            # project onto formals at desugar (SpreadCallSugar) so the manager
            # factory return `CM(x, **kwargs)` carries a body — the law that
            # bare CallSiteSugar already obeys for non-spread calls.
            source_call_frame = self._spread_source_call_frame()
            return SpreadCallSugar(
                callee_name=callee_name,
                callee=(None if isinstance(self.func, Name) else self.func.sugar()),
                arguments=arguments,
                site=self.fragment,
                source_call_frame=source_call_frame,
            )

        keyword_sugars = tuple(
            (kw.arg if kw.arg is not None else "**", kw.value.sugar())
            for kw in self.keywords
        )
        source_call_frame = None
        recursion_seat = None

        if isinstance(context, TreeConstructionContextV1):
            assert coordinate is not None
            source_call_frame = context.source_call_frames.get(coordinate)
        # Applicability first, relation second.  A non-lexical call is lawfully
        # not enrolled; a stranded enrolled row refuses instead of quietly
        # losing the source frame (#7348 caller 4).
        lexical_row = (
            self.unit.require_lexical_call_rows(self)[0]
            if isinstance(
                self.unit.lexical_call_enrollment(self), LexicalCallEnrolledV1
            )
            else None
        )
        if lexical_row is not None:
            function_definition = lexical_row.definition_occurrence
            if (
                lexical_row.source_cid != self.unit.source_cid
                or not isinstance(function_definition, (FunctionDef, AsyncFunctionDef))
                or lexical_row.definition_occurrence_identity
                is not function_definition.ref
                or lexical_row.lexical_scope_identity
                is not lexical_row.lexical_scope.ref
            ):
                from .panic import backend_defect

                backend_defect(
                    blame=self.fragment,
                    owner="Call._construct_sugar",
                    observed="foreign or malformed lexical source-call row",
                    requested="this source unit's exact call, definition, and lexical scope",
                    fix="repair lexical call enrollment before constructing the source frame",
                )
            if source_call_frame is None:
                try:
                    source_call_frame = function_definition.source_visible_call_frame()
                except SourceCallFrameCycle as cycle:
                    # The callee's frame is under construction up the stack: this
                    # call is the recursion seat. Definition known, body not unfolded.
                    source_call_frame = None
                    recursion_seat = (
                        f"call-graph-cycle:{cycle.definition.name}"
                        f"@{cycle.definition.line_col_span().start_line}"
                    )
        if source_call_frame is not None:
            from sugar_lift_py_tests.source_call_frame import SourceCallBindingGap
            from sugar_lift_py_tests.sugar.call_site_sugar import (
                CallSiteSugar,
                DefinitionOccurrenceAbsentV1,
                DefinitionOccurrenceAbsenceReasonV1,
            )

            if any(keyword.arg is None for keyword in self.keywords):
                raise SourceCallBindingGap(
                    "spread keyword requires typed variadic projection"
                )
            bind_args = self.args
            frame_owner = getattr(source_call_frame, "owner", None)
            class_owner = (
                frame_owner.unit.lexical_class_owner_for(frame_owner)
                if isinstance(frame_owner, FunctionDef)
                else None
            )
            if (
                isinstance(self.func, Attribute)
                and class_owner is not None
                and class_owner._method_descriptor_kind(frame_owner)
                == "classmethod"
                and getattr(source_call_frame, "bound_receiver_class", None)
                is None
            ):
                # ExceptionInfo.for_later() supplies the class as cls.
                bind_args = (self.func.value,) + tuple(self.args)
            bound_frame = source_call_frame.bind_node_actuals(
                bind_args,
                tuple(
                    (keyword.arg, keyword.value)
                    for keyword in self.keywords
                    if keyword.arg is not None
                ),
            )
            projected_definition = self._project_call_definition_occurrence(
                bound_frame.owner,
                coordinate="CallSiteSugar.expected_definition_ref",
            )
            bound_frame = replace(bound_frame, owner=projected_definition)
            # The call is spelled by its callee, as every other call is; the
            # frame rides beside it.  It never mints a name of its own.
            return CallSiteSugar(
                target_name=(
                    self.func.id
                    if isinstance(self.func, Name)
                    else self._spread_callee_name(self.func)
                ),
                reference_symbol=self._import_reference_callee(),
                args=tuple(a.sugar() for a in bind_args),
                site=self.fragment,
                call_occurrence=coordinate,
                keywords=keyword_sugars,
                source_call_frame=bound_frame,
                # The frame TABLE lives on the construction context, so it is
                # carried only when the context HAS one. That is asked directly
                # now. It used to be asked as ``coordinate is not None``, on the
                # reasoning that the coordinate was minted solely under
                # ``isinstance(context, TreeConstructionContextV1)`` -- true at
                # the time, and exactly the double duty that made the call's
                # occurrence answer a question about the context instead of a
                # question about the call. A missing table is now spelled as a
                # missing table.
                source_call_frame_table=getattr(
                    context, "source_call_frames", None
                )
                if lexical_row is not None
                else None,
                source_call_frame_coordinate=(
                    coordinate if lexical_row is not None else None
                ),
                expected_source_call_frame_owner=(
                    self._project_call_definition_occurrence(
                        lexical_row.definition_occurrence,
                        coordinate="CallSiteSugar.expected_source_call_frame_owner",
                    )
                    if lexical_row is not None
                    else DefinitionOccurrenceAbsentV1(
                        DefinitionOccurrenceAbsenceReasonV1.NO_LEXICAL_SOURCE_CALL_ROW
                    )
                ),
                expected_definition_ref=projected_definition,
                language_callee=language_callee,
                captured=self._captured_cells(bound_frame),
            )
        if isinstance(self.func, Name):
            from sugar_lift_py_tests.sugar.call_site_sugar import (
                CallSiteSugar,
                DefinitionOccurrenceAbsentV1,
                DefinitionOccurrenceAbsenceReasonV1,
            )

            # The call-site coordinate absorbs the callee's spelling instead of
            # its sugar, so the callee never constructs. That absorption IS its
            # discharge; without it the Name registers and never answers.
            self.func.discharge_by_substitution()

            # The call's edge symbol, and the unanswered-call member's, is the
            # one import table's target symbol at the callee's own coordinate
            # (#7837). Nothing is bound into the kit to supply it.
            import_target_symbol = self.unit.import_reference_of(self.func)
            contract_resolution_gap = None

            source_call_frame = None
            formal_function_sugar = None
            formal_coordinates = ()
            formal_coordinate_cids = ()
            # Applicability first, relation second (#7348 caller 5): an
            # external/module/shadowed Name call is lawfully not enrolled, but
            # a stranded enrolled row must not fall through to a weaker
            # ordinary CallSiteSugar.
            lexical_row = (
                self.unit.require_lexical_call_rows(self)[0]
                if isinstance(
                    self.unit.lexical_call_enrollment(self), LexicalCallEnrolledV1
                )
                else None
            )
            if lexical_row is not None:
                function_definition = lexical_row.definition_occurrence
                if (
                    lexical_row.source_cid != self.unit.source_cid
                    or not isinstance(
                        function_definition, (FunctionDef, AsyncFunctionDef)
                    )
                    or lexical_row.definition_occurrence_identity
                    is not function_definition.ref
                    or lexical_row.lexical_scope_identity
                    is not lexical_row.lexical_scope.ref
                ):
                    from .panic import backend_defect

                    backend_defect(
                        blame=self.fragment,
                        owner="Call._construct_sugar",
                        observed="foreign or malformed lexical source-call row",
                        requested="this source unit's exact call, definition, and lexical scope",
                        fix="repair lexical call enrollment before constructing the source frame",
                    )
            else:
                function_definition = self.unit.source_function_definition_for_call(
                    self
                )
            if function_definition is not None:
                try:
                    formal_function_sugar = function_definition.sugar()
                except SourceCallFrameCycle as cycle:
                    # Recursion seat: the callee's universe is under
                    # construction up the stack. Definition known, no second
                    # unfolding; the call carries a call-graph-cycle gap.
                    formal_function_sugar = None
                    recursion_seat = (
                        f"call-graph-cycle:{cycle.definition.name}"
                        f"@{cycle.definition.line_col_span().start_line}"
                    )
                formal_coordinates = function_definition.formal_coordinates()
                formal_coordinate_cids = tuple(
                    coordinate.coordinate_cid for coordinate in formal_coordinates
                )
                try:
                    source_call_frame = function_definition.source_visible_call_frame()
                except SourceCallFrameCycle as cycle:
                    # The callee's frame is under construction up the stack: this
                    # call is the recursion seat. Definition known, body not unfolded.
                    source_call_frame = None
                    recursion_seat = (
                        f"call-graph-cycle:{cycle.definition.name}"
                        f"@{cycle.definition.line_col_span().start_line}"
                    )
                if recursion_seat is not None:
                    contract_resolution_gap = recursion_seat
                if lexical_row is not None:
                    if source_call_frame is not None:
                        if (
                            source_call_frame.owner
                            is not lexical_row.definition_occurrence
                        ):
                            from .panic import backend_defect

                            backend_defect(
                                blame=self.fragment,
                                owner="Call._construct_sugar",
                                observed="seated source frame has foreign lexical owner",
                                requested="the lexical row's authenticated scope owner",
                                fix="retain the seated frame or keep the call loud",
                            )
                    else:
                        try:
                            source_call_frame = (
                                function_definition.source_visible_call_frame()
                            )
                        except SourceCallFrameCycle as cycle:
                            source_call_frame = None
                            recursion_seat = (
                                f"call-graph-cycle:{cycle.definition.name}"
                                f"@{cycle.definition.line_col_span().start_line}"
                            )
            definition = self.unit.source_allocation_definition_for_call(self)
            if (
                definition is not None
                and self.unit.source_class_admits_source_constructor_frame(
                    definition
                )
            ):
                from sugar_lift_py_tests.source_call_frame import SourceCallBindingGap

                if any(keyword.arg is None for keyword in self.keywords):
                    raise SourceCallBindingGap(
                        "spread keyword requires typed variadic projection"
                    )
                source_call_frame = (
                    definition.source_visible_constructor_frame().bind_node_actuals(
                        self.args,
                        tuple(
                            (keyword.arg, keyword.value)
                            for keyword in self.keywords
                            if keyword.arg is not None
                        ),
                    )
                )

            definition_occurrence = (
                function_definition
                if function_definition is not None
                else definition
            )
            if definition_occurrence is None:
                expected_definition = DefinitionOccurrenceAbsentV1(
                    DefinitionOccurrenceAbsenceReasonV1.NOT_SOURCE_RESOLVED
                )
            else:
                expected_definition = self._project_call_definition_occurrence(
                    definition_occurrence,
                    coordinate="CallSiteSugar.expected_definition_ref",
                )
                if source_call_frame is not None:
                    source_call_frame = replace(
                        source_call_frame, owner=expected_definition
                    )

            return CallSiteSugar(
                target_name=self.func.id,
                args=tuple(a.sugar() for a in self.args),
                site=self.fragment,
                call_occurrence=coordinate,
                keywords=keyword_sugars,
                contract_resolution_gap=contract_resolution_gap,
                import_target_symbol=import_target_symbol,
                reference_symbol=self._import_reference_callee(),
                source_call_frame=source_call_frame,
                formal_function_sugar=formal_function_sugar,
                formal_coordinate_cids=formal_coordinate_cids,
                expected_definition_ref=expected_definition,
                native_operation_formal_coordinates=tuple(formal_coordinates),
                language_callee=language_callee,
                captured=self._captured_cells(source_call_frame),
            )
        if isinstance(self.func, Attribute):
            # Lexical import binding is the ONLY door to a closed callee
            # coordinate. `None` here means the head is a parameter, a local, a
            # shadowed or ambiguous name -- and it must REFUSE, falling through
            # to the ordinary method-call construction below. Do not "helpfully"
            # fall back to the dotted spelling: that is precisely the defect the
            # With census carries (keyed on `pytest.raises` as a string, 6353
            # rows of spelling), and it would let a local named `warnings` mint
            # authenticated warning testimony it has no authority for.
            closed_symbol = self._import_reference_callee()
            if closed_symbol is not None:
                from sugar_lift_py_tests.sugar.call_site_sugar import CallSiteSugar

                # The head is lexically bound to an import: the callee is a
                # CLOSED coordinate (`numpy.rot90`), so the call-site absorbs
                # the whole dotted spelling exactly as it does for a Name
                # callee. No receiver constructs, so no module alias is minted
                # as a universe Var it was never declared as.
                args_sugar = tuple(a.sugar() for a in self.args)
                if language_callee is LanguageCallee.WARNINGS_WARN:
                    args_sugar, keyword_sugars = self._authenticate_warning_category(
                        args_sugar, keyword_sugars
                    )
                # The same call form as a Name callee: its coordinate, and an
                # edge carrying the one import table's target symbol.
                return CallSiteSugar(
                    target_name=closed_symbol,
                    args=args_sugar,
                    site=self.fragment,
                    call_occurrence=coordinate,
                    keywords=keyword_sugars,
                    import_target_symbol=self.unit.import_reference_of(self.func),
                    reference_symbol=closed_symbol,
                    language_callee=language_callee,
                )
            from sugar_lift_py_tests.sugar.method_call_sugar import MethodCallSugar

            return MethodCallSugar(
                receiver=self.func.value.sugar(),
                name=self.func.attr,
                args=tuple(a.sugar() for a in self.args),
                site=self.fragment,
                keywords=keyword_sugars,
            )
        from sugar_lift_py_tests.sugar.computed_call_sugar import ComputedCallSugar

        source_call_frame = None
        # ``f = lambda x: ...; f(1)``: the read of ``f`` is a reference to
        # its assignment's evaluation, which denotes the lambda it was given
        # (``_evaluation_ref``, ``of``).  Which function is called is that
        # object's; the callee's value is still the key's.
        callee = self.func
        while isinstance(callee, EvaluationRef) and isinstance(
            getattr(callee, "of", None), Node
        ):
            callee = callee.of
        if isinstance(callee, Lambda):
            from sugar_lift_py_tests.source_call_frame import SourceCallBindingGap

            if any(keyword.arg is None for keyword in self.keywords):
                raise SourceCallBindingGap(
                    "spread keyword requires typed variadic projection"
                )
            source_call_frame = callee.source_visible_call_frame().bind_node_actuals(
                self.args,
                tuple(
                    (keyword.arg, keyword.value)
                    for keyword in self.keywords
                    if keyword.arg is not None
                ),
            )

        return ComputedCallSugar(
            callee=self.func.sugar(),
            args=tuple(a.sugar() for a in self.args),
            site=self.fragment,
            keywords=keyword_sugars,
            source_call_frame=source_call_frame,
        )

    def language_callee(self) -> Optional[LanguageCallee]:
        """The language-fixed callee this call applies, read from its binding
        (``SourceUnit.language_callee_of``: ``typing.cast`` under ``import
        typing``, ``cast`` under ``from typing import cast``)."""
        return self.unit.language_callee_of(self.func)

    def _discharge_callee_spelling(self) -> None:
        """Answer the roll call for every node of a callee the call absorbed."""
        chain = self.func
        while isinstance(chain, Attribute):
            chain.discharge_by_substitution()
            chain = chain.value
        chain.discharge_by_substitution()

    def _import_reference_callee(self) -> Optional[str]:
        """The target symbol of an import-bound callee, read from the one
        import reference table (#7837), or ``None``.

        ``ident`` under ``from idn import ident`` and ``np.rot90`` under
        ``import numpy as np`` are both references the lexical pass already
        resolved at the callee's own coordinate: ``idn.ident`` and
        ``numpy.rot90``. A callee that is not uniquely import-bound -- a
        parameter, a local, a shadowed or ambiguous name -- has no row and
        constructs as before. The symbol is read, never built here.
        """
        target = self._import_reference_symbol()
        if target is None:
            return None
        # The spelling is absorbed into the call-site coordinate, so every node
        # of a dotted callee chain answers the roll call as present-inert (a
        # Name callee has already answered in its own branch).
        if isinstance(self.func, Attribute):
            chain = self.func
            while isinstance(chain, Attribute):
                chain.discharge_by_substitution()
                chain = chain.value
            chain.discharge_by_substitution()
        return target

    def _import_reference_symbol(self) -> Optional[str]:
        """The callee's target symbol in the one import reference table
        (#7837), without its ``python:`` namespace, or ``None``. A read only."""
        target = self.unit.import_reference_of(self.func)
        if target is None:
            return None
        return target[len("python:") :] if target.startswith("python:") else target

    def _not_bridged_call_site(
        self, *, args, keywords, gap: str, language_callee=None
    ):
        """A call nothing bridges stays its own edge.

        The callee keeps the spelling it was written with, and its edge the
        target symbol the import reference table holds for it, exactly as a
        bridged call. Only the gap says it is not bridged: the call is never
        renamed to a shared stand-in. ``language_callee`` is the member the
        node bound the callee to, carried for the language's own dispatch.
        """
        from sugar_lift_py_tests.sugar.call_site_sugar import CallSiteSugar

        return CallSiteSugar(
            target_name=self._spread_callee_name(self.func) or self.func.segment(),
            args=args,
            site=self.fragment,
            keywords=keywords,
            contract_resolution_gap=gap,
            import_target_symbol=self.unit.import_reference_of(self.func),
            reference_symbol=self._import_reference_symbol(),
            language_callee=language_callee,
        )

    def _authenticate_warning_category(self, args_sugar, keyword_sugars):
        """Attach the floor-owned class identity to a ``warnings.warn`` category.

        The category operand of a warning occurrence is an ordinary Python
        exception class, so the SAME lexical authenticator that owns ``raise``
        and ``except`` operands owns it -- no warning name table is minted. The
        operand position comes from CPython's own fixed ``warnings.warn``
        signature, not from a vendor convention.

        An operand that is not a bare ``Name``, or a ``Name`` with no closed
        class identity, is left exactly as constructed: the call then stays an
        ordinary unresolved call site and the consuming boundary reports it as
        an unresolved warning producer. Absent identity is never inferred.
        """
        from sugar_lift_py_tests.sugar.authenticated_exception_type_sugar import (
            AuthenticatedExceptionTypeSugar,
        )
        from sugar_lift_py_tests.sugar.warning_observation_producer import (
            WARNING_CATEGORY_PARAMETER_INDEX,
            WARNING_CATEGORY_PARAMETER_NAME,
        )

        location = None
        if len(self.args) > WARNING_CATEGORY_PARAMETER_INDEX:
            actual = self.args[WARNING_CATEGORY_PARAMETER_INDEX]
            location = ("arg", WARNING_CATEGORY_PARAMETER_INDEX)
        else:
            actual = None
            for keyword in self.keywords:
                if keyword.arg == WARNING_CATEGORY_PARAMETER_NAME:
                    actual, location = keyword.value, ("keyword", keyword.arg)
                    break
        if not isinstance(actual, Name):
            return args_sugar, keyword_sugars
        identity = self.unit.exception_type_identity(actual)
        if identity is None:
            return args_sugar, keyword_sugars
        mro = self.unit.exception_type_mro(actual)
        if location[0] == "arg":
            args = list(args_sugar)
            args[location[1]] = AuthenticatedExceptionTypeSugar(
                args[location[1]], identity, mro, site=actual.fragment
            )
            return tuple(args), keyword_sugars
        keywords = list(keyword_sugars)
        for position, (name, sugar) in enumerate(keywords):
            if name == location[1]:
                keywords[position] = (
                    name,
                    AuthenticatedExceptionTypeSugar(
                        sugar, identity, mro, site=actual.fragment
                    ),
                )
                break
        return args_sugar, tuple(keywords)

    def _spread_source_call_frame(self):
        """Authenticated source frame for a ``*``/``**`` call, when enrolled.

        Looks up the same ``source_call_frames`` table the non-spread Call path
        uses, then binds non-spread positionals and named keywords onto the
        frame. Double-star keywords are *not* node-bound here — their FloorValue
        is projected at desugar via ``bind_actuals`` once the mapping is a
        constructed DictValue. Star operands leave the frame unbound so
        SpreadCallSugar stays bodyless (no typed vararg projection yet).
        """
        starred = any(isinstance(arg, Starred) for arg in self.args)
        context = self._require_construction_context(
            owner="Call._spread_source_call_frame"
        )
        from sugar_lift_py_tests.context_manager_resolution import (
            TreeConstructionContextV1,
        )
        from sugar_lift_py_tests.source_call_frame import SourceCallBindingGap

        source_call_frame = None
        if (
            isinstance(context, TreeConstructionContextV1)
            and context.source_call_frames
        ):
            # Same pure function as every other occurrence mint; the lookup is
            # what the context gates, not the coordinate.
            source_call_frame = context.source_call_frames.get(
                self.source_occurrence()
            )
        if source_call_frame is None and isinstance(self.func, Name):
            definition = self.unit.source_allocation_definition_for_call(self)
            if (
                definition is not None
                and self.unit.source_class_admits_source_constructor_frame(
                    definition
                )
            ):
                source_call_frame = definition.source_visible_constructor_frame()
        lexical = False
        if source_call_frame is None:
            # ``g(*t)`` and ``g(**k)`` alike name a module function the
            # lexical scope resolves; its frame is the callee's own.
            source_call_frame = self._spread_lexical_source_call_frame()
            lexical = source_call_frame is not None
        if source_call_frame is None:
            return None
        if starred or lexical:
            # A ``*`` operand's arity is decided only when it reduces, so no
            # actual Node is bound here.  SpreadCallSugar splats a decided
            # tuple into the positional roster and binds the values onto this
            # unspecialized frame at desugar; any other operand stays bodyless.
            # The lexical frame binds every actual there too (``**`` merges a
            # constructed DictValue onto the formals).
            return source_call_frame
        try:
            return source_call_frame.bind_node_actuals(
                tuple(arg for arg in self.args if not isinstance(arg, Starred)),
                tuple(
                    (keyword.arg, keyword.value)
                    for keyword in self.keywords
                    if keyword.arg is not None
                ),
            )
        except SourceCallBindingGap:
            return None

    def _spread_lexical_source_call_frame(self):
        """The ordinary source function a spread call names, if any.

        The same resolution the non-spread Call path uses: the producer's
        lexical row, else the symtable-classified module binding.  A callee
        whose frame is under construction up the stack (a recursion seat)
        projects no frame.
        """
        if not isinstance(self.func, Name):
            return None
        definition = self.unit.source_function_definition_for_call(self)
        if definition is None:
            return None
        try:
            return definition.source_visible_call_frame()
        except SourceCallFrameCycle:
            return None

    @staticmethod
    def _spread_callee_name(callee: Expression) -> Optional[str]:
        """The reference lifter spells Name/Attribute chains as one callee.

        A computed callee has no spelling and is carried by its constructed
        child sugar instead.
        """
        if isinstance(callee, Name):
            return callee.id
        if isinstance(callee, FormalRef):
            return callee.coordinate.declared_name
        if isinstance(callee, Attribute):
            base = Call._spread_callee_name(callee.value)
            return f"{base}.{callee.attr}" if base is not None else None
        return None


class FormattedValue(Expression):
    value: Expression
    conversion: int
    format_spec: Optional["JoinedStr"]
    _child_fields = ("value", "format_spec")

    def substitute(self, scope):
        """Binds nothing: recurse into children and reassemble."""
        return self._substitute_children(scope)

    def _construct_sugar(self):
        """Project the Python-reference three-operand formatted-value shape.

        CPython carries conversion as ``-1`` or the codepoint for exactly
        ``a``/``r``/``s``.  Anything else is malformed backend testimony, not
        a new language arm.  The optional format spec remains its own nested
        JoinedStr sugar; neither operand is dropped or replaced with an empty
        string.
        """
        from sugar_lift_py_tests.sugar.fstring_sugar import FormattedValueSugar

        if self.conversion == -1:
            conversion = None
        elif self.conversion in {ord("a"), ord("r"), ord("s")}:
            conversion = chr(self.conversion)
        else:
            backend_defect(
                blame=self.fragment,
                owner="FormattedValue._construct_sugar",
                observed=f"unsupported f-string conversion slot {self.conversion!r}",
                requested="-1 or the codepoint for 'a', 'r', or 's'",
                fix="repair the backend adapter; never invent a conversion",
            )
        format_spec = self.format_spec
        if format_spec is not None and not isinstance(format_spec, JoinedStr):
            backend_defect(
                blame=self.fragment,
                owner="FormattedValue._construct_sugar",
                observed=f"format_spec constructed as {type(format_spec).__name__}",
                requested="None or a nested JoinedStr",
                fix="repair the backend adapter; never coerce a bare expression",
            )
        return FormattedValueSugar(
            value=self.value.sugar(),
            conversion=conversion,
            format_spec=format_spec.sugar() if format_spec is not None else None,
            site=self.fragment,
        )


class JoinedStr(Expression):
    values: Tuple[Expression, ...]
    _child_fields = ("values",)

    def substitute(self, scope):
        """Binds nothing: recurse into children and reassemble."""
        return self._substitute_children(scope)

    def _construct_sugar(self):
        """The f-string: JoinedStrSugar over each part's sugar (literal chunks
        and {value} interpolations), concatenated."""
        from sugar_lift_py_tests.sugar.fstring_sugar import JoinedStrSugar

        return JoinedStrSugar(
            parts=tuple(v.sugar() for v in self.values), site=self.fragment
        )


class Constant(Expression):
    value: object
    literal_kind: Optional[str]

    def substitute(self, scope):
        """A literal is inert: no children, no hole, so it substitutes to
        itself under any scope. The terminus of the rewrite."""
        return self

    def _construct_sugar(self):
        """A literal constructs its literal sugar directly — a leaf: no child
        sugar, the value stands. Dispatch on the value's exact type (bool is a
        subclass of int, so it is checked first and is its own sugar). Every
        literal kind not yet converted inherits the loud SugarNotWritten throw.
        """
        v = self.value
        if v is None:
            from sugar_lift_py_tests.sugar.none_literal_sugar import NoneLiteralSugar

            return NoneLiteralSugar(site=self.fragment)
        if isinstance(v, bool):
            if v:
                from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
                    TrueBoolLiteralSugar,
                )

                return TrueBoolLiteralSugar(site=self.fragment)
            from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
                FalseBoolLiteralSugar,
            )

            return FalseBoolLiteralSugar(site=self.fragment)
        if isinstance(v, int):
            from sugar_lift_py_tests.sugar.int_literal_sugar import IntLiteralSugar

            return IntLiteralSugar(value=v, site=self.fragment)
        if type(v) is float:
            from sugar_lift_py_tests.sugar.real_literal_sugar import RealLiteralSugar

            return RealLiteralSugar(value=v, site=self.fragment)
        if type(v) is str:
            from sugar_lift_py_tests.sugar.string_literal_sugar import (
                StringLiteralSugar,
            )

            return StringLiteralSugar(value=v, site=self.fragment)
        if type(v) is bytes:
            from sugar_lift_py_tests.sugar.bytes_literal_sugar import (
                BytesLiteralSugar,
            )

            return BytesLiteralSugar(value=v, site=self.fragment)
        if v is Ellipsis:
            from sugar_lift_py_tests.sugar.ellipsis_literal_sugar import (
                EllipsisLiteralSugar,
            )

            return EllipsisLiteralSugar(site=self.fragment)
        if type(v) is complex:
            from sugar_lift_py_tests.sugar.complex_literal_sugar import (
                ComplexLiteralSugar,
            )

            return ComplexLiteralSugar(real=v.real, imag=v.imag, site=self.fragment)
        return super()._construct_sugar()  # every literal kind is now converted


class OpaqueObjectStateV1(Expression):
    """Authenticated opaque call-result identity with no field testimony."""

    object_coordinate: object
    base: Expression
    _child_fields = ("base",)

    def substitute(self, scope):
        del scope
        return self

    def _construct_sugar(self):
        """Identity is transparent until a consumer asks for unproved behavior."""
        from .object_identity import decode_object_coordinate_v1

        decode_object_coordinate_v1(self.object_coordinate.wire())
        return self.base.sugar()


class ObjectPlaceStateV1(Expression):
    """Immutable field versions carried only inside runtime BindingEntryV1.

    This is a constructed Node value, not a binding resolver or heap.  Its sole
    identity source is ``object_coordinate.cid``, authenticated from the exact
    construction occurrence.  If it escapes the attribute store/read
    projections, its base value constructs normally.
    """

    object_coordinate: object
    class_definition_cid: str
    construction_testimony: object
    constructed_value: object
    object_identity_cid: str
    base: Expression
    selectors: Tuple[object, ...]
    values: Tuple[Expression, ...]
    value_testimonies: Tuple[object, ...]
    version_cids: Tuple[str, ...]
    version_records: Tuple[object, ...]
    prior_version_cids: Tuple[Optional[str], ...]
    store_occurrence_cids: Tuple[str, ...]
    invalidated_by_opaque_call: bool
    _child_fields = ("base", "values")

    def substitute(self, scope):
        del scope
        return self

    def _construct_sugar(self):
        self.validate_identity()
        if self.invalidated_by_opaque_call:
            # A call that may have run code holding this object came between
            # its construction and this read: its fields are unknown, never
            # the constructed (pre-call) value.
            from sugar_lift_py_tests.sugar.builtin_container_call_sugar import (
                ReceiverAfterCallSugar,
            )

            return ReceiverAfterCallSugar(
                label=f"object:{self.object_identity_cid}", site=self.fragment
            )
        from sugar_lift_py_tests.sugar.constructed_object_place_sugar import (
            ConstructedObjectPlaceSugar,
        )

        return ConstructedObjectPlaceSugar(
            self.constructed_value,
            self.construction_testimony,
            self.fragment,
        )

    def validate_identity(self) -> None:
        from .binding_provenance import (
            BindingProvenanceGap,
            ConstructedValueTestimonyV1,
        )
        from .object_identity import decode_object_coordinate_v1

        coordinate = decode_object_coordinate_v1(self.object_coordinate.wire())
        ConstructedValueTestimonyV1.decode(self.construction_testimony.wire())
        from sugar_lift_py_tests.ir import _term_content_cid

        observed = _term_content_cid(
            self.constructed_value.to_term(owner="ObjectPlaceStateV1")
        )
        if observed != self.construction_testimony.semantic_value_cid:
            raise BindingProvenanceGap("object construction testimony mismatch")
        if coordinate.cid != self.object_identity_cid:
            raise BindingProvenanceGap("object place identity CID mismatch")

    def version(self, selector) -> Optional[str]:
        try:
            return self.version_cids[self.selectors.index(selector)]
        except ValueError:
            return None

    def with_attribute_store(self, name, value, occurrence):
        from .object_identity import AttributeFieldCoordinateV1

        return self._with_store(
            AttributeFieldCoordinateV1.mint(self.object_coordinate, name),
            value,
            occurrence,
        )

    @staticmethod
    def subscript_key_projection(key):
        if isinstance(key, ConstructedValueProjectionV1):
            key.validate_testimony()
            constructed = (key.constructed_value, key.construction_testimony)
        else:
            constructed = Assign._constructed_floor_value(key)
        if constructed is None:
            return None
        floor_value, testimony = constructed
        from sugar_lift_py_tests.floor import StringValue, TermValue

        supported = isinstance(floor_value, StringValue) or (
            isinstance(floor_value, TermValue) and type(floor_value.value) is int
        )
        if not supported:
            return None
        if isinstance(key, ConstructedValueProjectionV1):
            return key
        return ConstructedValueProjectionV1.create(key, floor_value, testimony)

    def _subscript_coordinate(self, key):
        projected = self.subscript_key_projection(key)
        if projected is None:
            return None
        from sugar_lift_py_tests.ir import _term_content_cid
        from .object_identity import (
            SubscriptFieldCoordinateV1,
            SubscriptKeyCoordinateV1,
        )

        key_coordinate = SubscriptKeyCoordinateV1.mint(
            constructed_value_cid=_term_content_cid(
                projected.constructed_value.to_term(owner="subscript-key")
            ),
            construction_testimony_cid=projected.construction_testimony.cid,
        )
        return SubscriptFieldCoordinateV1.mint(self.object_coordinate, key_coordinate)

    def with_subscript_store(self, key, value, occurrence):
        selector = self._subscript_coordinate(key)
        if selector is None:
            return None
        return self._with_store(selector, value, occurrence)

    def _with_store(self, selector, value, occurrence, *, constructed=None):
        self.validate_identity()
        constructed = constructed or Assign._constructed_floor_value(value)
        if constructed is None:
            return None
        floor_value, testimony = constructed
        projected = ConstructedValueProjectionV1.create(value, floor_value, testimony)
        from .object_identity import (
            AttributeFieldCoordinateV1,
            AttributeFieldVersionV1,
            SubscriptFieldVersionV1,
        )

        prior = self.version(selector)
        version_type = (
            AttributeFieldVersionV1
            if isinstance(selector, AttributeFieldCoordinateV1)
            else SubscriptFieldVersionV1
        )
        version = version_type.mint(
            owner=self.object_coordinate,
            field=selector,
            store_occurrence=occurrence,
            construction_generation=self.object_coordinate.construction_generation
            + len(self.version_cids)
            + 1,
            stored_value_testimony_cid=testimony.cid,
            prior_version_cid=prior,
        )
        occurrence_memento = occurrence.seal().to_dict()
        selectors = list(self.selectors)
        values = list(self.values)
        testimonies = list(self.value_testimonies)
        versions = list(self.version_cids)
        records = list(self.version_records)
        priors = list(self.prior_version_cids)
        occurrences = list(self.store_occurrence_cids)
        if selector in selectors:
            index = selectors.index(selector)
            values[index] = projected
            testimonies[index] = testimony
            versions[index] = version.cid
            records[index] = version
            priors[index] = prior
            occurrences[index] = occurrence_memento
        else:
            selectors.append(selector)
            values.append(projected)
            testimonies.append(testimony)
            versions.append(version.cid)
            records.append(version)
            priors.append(prior)
            occurrences.append(occurrence_memento)
        return self._replace_state(
            span=occurrence.node.span,
            selectors=tuple(selectors),
            values=tuple(values),
            value_testimonies=tuple(testimonies),
            version_cids=tuple(versions),
            version_records=tuple(records),
            prior_version_cids=tuple(priors),
            store_occurrence_cids=tuple(occurrences),
            invalidated=False,
        )

    def attribute_field(self, name: str):
        from .object_identity import AttributeFieldCoordinateV1

        return self.field(AttributeFieldCoordinateV1.mint(self.object_coordinate, name))

    def subscript_field(self, key):
        selector = self._subscript_coordinate(key)
        return None if selector is None else self.field(selector)

    def field(self, selector):
        self.validate_identity()
        if self.invalidated_by_opaque_call:
            return None
        try:
            index = self.selectors.index(selector)
        except ValueError:
            return None
        from .binding_provenance import (
            BindingProvenanceGap,
            ConstructedValueTestimonyV1,
        )
        from .object_identity import (
            AttributeFieldCoordinateV1,
            AttributeFieldVersionV1,
            SubscriptFieldVersionV1,
        )

        testimony = self.value_testimonies[index]
        ConstructedValueTestimonyV1.decode(testimony.wire())
        projected = self.values[index]
        if not isinstance(projected, ConstructedValueProjectionV1):
            raise BindingProvenanceGap("field value lacks constructed projection")
        projected.validate_testimony()
        if projected.construction_testimony != testimony:
            raise BindingProvenanceGap("field value testimony mismatch")
        version_type = (
            AttributeFieldVersionV1
            if isinstance(selector, AttributeFieldCoordinateV1)
            else SubscriptFieldVersionV1
        )
        version = version_type.decode(self.version_records[index].wire())
        if (
            version.cid != self.version_cids[index]
            or version.owner.cid != self.object_coordinate.cid
            or version.field != selector
            or version.stored_value_testimony_cid != testimony.cid
            or version.prior_version_cid != self.prior_version_cids[index]
        ):
            raise BindingProvenanceGap("field version CID mismatch")
        return projected

    def invalidate(self, occurrence):
        self.validate_identity()
        return self._replace_state(
            span=occurrence.node.span,
            selectors=self.selectors,
            values=self.values,
            value_testimonies=self.value_testimonies,
            version_cids=self.version_cids,
            version_records=self.version_records,
            prior_version_cids=self.prior_version_cids,
            store_occurrence_cids=self.store_occurrence_cids,
            invalidated=True,
        )

    def _replace_state(
        self,
        *,
        span,
        selectors,
        values,
        value_testimonies,
        version_cids,
        version_records,
        prior_version_cids,
        store_occurrence_cids,
        invalidated,
    ):
        from .backend import Child, Children, Leaf, materialize
        from .shadow import ShadowNode, _handle_of

        return materialize(
            self.unit,
            ShadowNode(
                "ObjectPlaceStateV1",
                span,
                (
                    ("object_coordinate", Leaf(self.object_coordinate)),
                    ("class_definition_cid", Leaf(self.class_definition_cid)),
                    ("construction_testimony", Leaf(self.construction_testimony)),
                    ("constructed_value", Leaf(self.constructed_value)),
                    ("object_identity_cid", Leaf(self.object_identity_cid)),
                    ("base", Child(_handle_of(self.base))),
                    ("selectors", Leaf(selectors)),
                    ("values", Children(tuple(_handle_of(item) for item in values))),
                    ("value_testimonies", Leaf(value_testimonies)),
                    ("version_cids", Leaf(version_cids)),
                    ("version_records", Leaf(version_records)),
                    ("prior_version_cids", Leaf(prior_version_cids)),
                    ("store_occurrence_cids", Leaf(store_occurrence_cids)),
                    ("invalidated_by_opaque_call", Leaf(invalidated)),
                ),
            ),
            self.reporter,
        )


class ConstructedValueProjectionV1(Expression):
    """A source value already constructed once and sealed by its testimony."""

    constructed_value: object
    construction_testimony: object
    base: Expression
    _child_fields = ("base",)

    @classmethod
    def create(cls, base, constructed_value, testimony):
        from .backend import Child, Leaf, materialize
        from .shadow import ShadowNode, _handle_of

        return materialize(
            base.unit,
            ShadowNode(
                "ConstructedValueProjectionV1",
                base.span,
                (
                    ("constructed_value", Leaf(constructed_value)),
                    ("construction_testimony", Leaf(testimony)),
                    ("base", Child(_handle_of(base))),
                ),
            ),
            base.reporter,
        )

    def substitute(self, scope):
        del scope
        return self

    def validate_testimony(self):
        from .binding_provenance import (
            BindingProvenanceGap,
            ConstructedValueTestimonyV1,
        )
        from sugar_lift_py_tests.ir import _term_content_cid

        ConstructedValueTestimonyV1.decode(self.construction_testimony.wire())
        observed = _term_content_cid(
            self.constructed_value.to_term(owner="ConstructedValueProjectionV1")
        )
        if observed != self.construction_testimony.semantic_value_cid:
            raise BindingProvenanceGap("constructed field testimony mismatch")

    def _construct_sugar(self):
        self.validate_testimony()
        from sugar_lift_py_tests.sugar.constructed_object_place_sugar import (
            ConstructedObjectPlaceSugar,
        )

        return ConstructedObjectPlaceSugar(
            self.constructed_value,
            self.construction_testimony,
            self.fragment,
        )


class Attribute(Expression):
    value: Expression
    attr: str
    _child_fields = ("value",)

    def dotted_expr_name(self) -> Optional[str]:
        # `a.b.c` is a place only while every link is itself a place: a call or
        # subscript in the chain (`f().b`, `d[k].b`) names nothing stable.
        receiver = self.value.dotted_expr_name()
        return None if receiver is None else f"{receiver}.{self.attr}"

    def _construct_sugar(self):
        """`<value>.<attr>` constructs AttributeSugar WITH the receiver's sugar.
        The attr name is a static identifier carried onto the coordinate.

        An opaque receiver still constructs this native operation. Its floor
        decides whether source testimony supplies a value or exceptional exit;
        when neither is known, the producer refuses instead of inventing a
        completed ``py.getattr`` projection or guessing ``AttributeError``."""
        span = self.line_col_span()
        # A deferred (proven message-only) value-use constructs its ordinary
        # AttributeSugar here; the opacity is a force-floor concern resolved at
        # reduce (AttributeSugar.project_attribute yields a MessageOpaqueValue).
        receipt = self.unit.import_value_use_receipt(
            (span.start_line, span.start_col, span.end_line, span.end_col)
        )
        from sugar_lift_py_tests.import_binding import AuthenticatedImportUseV1

        if type(receipt) is AuthenticatedImportUseV1:
            receipt.revalidate()
            site = receipt.use["useSite"]
            if (
                receipt.source_cid != self.unit.source_cid
                or site.get("sourceCid") != self.unit.source_cid
                or (
                    site.get("startLine"),
                    site.get("startCol"),
                    site.get("endLine"),
                    site.get("endCol"),
                )
                != (span.start_line, span.start_col, span.end_line, span.end_col)
            ):
                from sugar_source_tree.panic import BackendDefect

                raise BackendDefect(
                    blame=self.fragment,
                    owner="Attribute._construct_sugar",
                    observed="import value-use receipt does not own this Attribute",
                    requested="same-source exact full-Attribute occurrence testimony",
                    fix="consume the receipt only at its producer-minted useSite",
                )
            from sugar_lift_py_tests.floor.import_member_value import (
                _import_member_export_path,
            )

            if not _import_member_export_path(receipt):
                # ``import urllib.request`` then ``urllib.request``: the dotted
                # module alias itself, no member of it.  The same law as a
                # module-alias Name: never an empty-path import member; the
                # ordinary attribute read of the bound package stands.
                from sugar_lift_py_tests.sugar.attribute_sugar import AttributeSugar

                return AttributeSugar(
                    receiver=self.value.sugar(), name=self.attr, site=self.fragment
                )
            from sugar_lift_py_tests.sugar.import_member_sugar import ImportMemberSugar

            qualified_name = receipt.target_symbol
            if not qualified_name.startswith("python:"):
                from sugar_source_tree.panic import BackendDefect

                raise BackendDefect(
                    blame=self.fragment,
                    owner="Attribute._construct_sugar",
                    observed=f"target_symbol={qualified_name!r}",
                    requested="authenticated python: import target symbol",
                    fix="preserve the lexical receipt targetSymbol unchanged",
                )
            qualified_name = qualified_name[len("python:") :]
            return ImportMemberSugar(
                qualified_name=qualified_name,
                receipt=receipt,
                site=self.fragment,
            )

        from sugar_lift_py_tests.sugar.attribute_sugar import AttributeSugar

        return AttributeSugar(
            receiver=self.value.sugar(), name=self.attr, site=self.fragment
        )

    def substitute(self, scope):
        """Project only from a construction-authenticated object place."""
        from .shadow import rewrite

        receiver, changed = self._substitute_field(self.value, scope)
        receiver_coordinate_cid = _receiver_coordinate_cid(receiver)
        projections = scope.get(_RECEIVER_FIELD_PROJECTIONS, {})
        if receiver_coordinate_cid is not None and isinstance(projections, dict):
            projection = projections.get((receiver_coordinate_cid, self.attr))
            if isinstance(projection, _ReceiverFieldProjection):
                return projection.value
        if (
            isinstance(receiver, IfExp)
            and isinstance(receiver.body, ObjectPlaceStateV1)
            and isinstance(receiver.orelse, ObjectPlaceStateV1)
            and receiver.body.object_identity_cid == receiver.orelse.object_identity_cid
        ):
            when_true = receiver.body.attribute_field(self.attr)
            when_false = receiver.orelse.attribute_field(self.attr)
            if when_true is not None and when_false is not None:
                return rewrite(receiver, body=when_true, orelse=when_false)
        if isinstance(receiver, ObjectPlaceStateV1):
            projected = receiver.attribute_field(self.attr)
            if projected is not None:
                return projected
        return self if not changed else rewrite(self, value=receiver)


class Subscript(Expression):
    value: Expression
    slice_: Expression
    _child_fields = ("value", "slice_")

    def substitute(self, scope):
        """`<value>[<slice>]` binds nothing: recurse into receiver and index."""
        from .shadow import rewrite

        receiver, receiver_changed = self._substitute_field(self.value, scope)
        index, index_changed = self._substitute_field(self.slice_, scope)
        if isinstance(receiver, ObjectPlaceStateV1):
            projected_key = receiver.subscript_key_projection(index)
            if projected_key is not None:
                projected = receiver.subscript_field(projected_key)
                if projected is not None:
                    return projected
        if not receiver_changed and not index_changed:
            return self
        return rewrite(self, value=receiver, slice_=index)

    def _construct_sugar(self):
        """`<value>[<slice_>]` constructs SubscriptSugar WITH the receiver's and
        index's sugars. A Slice index reduces to its own gap through the
        recursion (slice_.sugar()), never silently handled here.

        An OpaqueObjectStateV1 receiver is NOT withheld: `[key]` on an opaque
        call result is a symbolic read the witness resolves at runtime, not a
        gap. It reduces to the honest `py.subscript(recv, key)` EUF coordinate,
        carrying whatever the call term guarantees and nothing invented.
        Withholding it here was the gap, not the construct."""
        from sugar_lift_py_tests.sugar.subscript_sugar import SubscriptSugar
        from sugar_lift_py_tests.context_manager_resolution import (
            SourceFragmentCoordinateV1,
            TreeConstructionContextV1,
        )

        occurrence = None
        if isinstance(
            self._require_construction_context(owner="Subscript._construct_sugar"),
            TreeConstructionContextV1,
        ):
            span = self.line_col_span()
            occurrence = SourceFragmentCoordinateV1(
                self.unit.source_cid,
                span.start_line,
                span.start_col,
                span.end_line,
                span.end_col,
            )

        return SubscriptSugar(
            receiver=self.value.sugar(),
            index=self.slice_.sugar(),
            site=self.fragment,
            use_occurrence=occurrence,
        )


class Starred(Expression):
    value: Expression
    _child_fields = ("value",)

    def substitute(self, scope):
        """Binds nothing: recurse into children and reassemble."""
        return self._substitute_children(scope)

    def _construct_sugar(self):
        """`*expr` constructs StarredSugar so the node is never an unowned gap.

        Call/list/tuple/set parents already project ``python:starred``; this
        arm keeps sole-construction total when the node is walked alone.
        Unpack store targets remain Assign's residual (#6078).
        """
        from sugar_lift_py_tests.sugar.starred_sugar import StarredSugar

        return StarredSugar(
            value=self.value.sugar(),
            site=self.fragment,
        )


class DictSetDefaultAppendState(Expression):
    """Shadow post-state of one authenticated ``setdefault(...).append(...)``."""

    receiver: Expression
    key: Expression
    default: Expression
    appended: Expression
    _child_fields = ("receiver", "key", "default", "appended")

    def substitute(self, scope):
        del scope
        return self

    def _construct_sugar(self):
        from sugar_lift_py_tests.sugar.dict_setdefault_append_state_sugar import (
            DictSetDefaultAppendStateSugar,
        )

        return DictSetDefaultAppendStateSugar(
            receiver=self.receiver.sugar(),
            key=self.key.sugar(),
            default=self.default.sugar(),
            appended=self.appended.sugar(),
            site=self.fragment,
        )


class MappingPopState(Expression):
    """Shadow post-state of inherited ``dict.pop(key, default)``."""

    receiver: Expression
    key: Expression
    default: Expression
    _child_fields = ("receiver", "key", "default")

    def substitute(self, scope):
        del scope
        return self

    def _construct_sugar(self):
        from sugar_lift_py_tests.sugar.mapping_pop_state_sugar import (
            MappingPopStateSugar,
        )

        return MappingPopStateSugar(
            receiver=self.receiver.sugar(),
            key=self.key.sugar(),
            default=self.default.sugar(),
            site=self.fragment,
        )


class ReceiverFieldStoreState(Expression):
    receiver: Expression
    value: Expression
    attr: str
    _child_fields = ("receiver", "value")

    def substitute(self, scope):
        del scope
        return self

    def _construct_sugar(self):
        from sugar_lift_py_tests.sugar.receiver_field_store_state_sugar import (
            ReceiverFieldStoreStateSugar,
        )

        return ReceiverFieldStoreStateSugar(
            self.receiver.sugar(), self.value.sugar(), self.attr, self.fragment
        )


class BuiltinContainerCall(Expression):
    """One mutating method call on a decided list/dict/set (container_mutation.py)."""

    receiver: Expression
    args: Tuple[Expression, ...]
    method: str
    container_kind: str
    value_first: bool
    occurrence: str
    _child_fields = ("receiver", "args")

    def substitute(self, scope):
        del scope
        return self

    def _construct_sugar(self):
        from sugar_lift_py_tests.sugar.builtin_container_call_sugar import (
            BuiltinContainerCallSugar,
        )

        return BuiltinContainerCallSugar(
            receiver=self.receiver.sugar(),
            method=self.method,
            args=tuple(arg.sugar() for arg in self.args),
            kind=self.container_kind,
            site=self.fragment,
            value_first=self.value_first,
            evaluation_token=self.occurrence,
        )


class PathContainerCall(Expression):
    """One mutating-named call on a receiver reached through a path."""

    receiver: Expression
    args: Tuple[Expression, ...]
    method: str
    fallback: Expression
    occurrence: str
    _child_fields = ("receiver", "args", "fallback")

    def substitute(self, scope):
        del scope
        return self

    def _construct_sugar(self):
        from sugar_lift_py_tests.sugar.builtin_container_call_sugar import (
            PathContainerCallSugar,
        )

        return PathContainerCallSugar(
            receiver=self.receiver.sugar(),
            method=self.method,
            args=tuple(arg.sugar() for arg in self.args),
            fallback=self.fallback.sugar(),
            site=self.fragment,
            evaluation_token=self.occurrence,
        )


class PathAfterCall(Expression):
    """A path's root (``mode='root'``) or its object (``'inner'``) after a call."""

    call: Expression
    root: Expression
    steps: tuple
    mode: str
    label: str
    unshared: bool
    occurrence: str
    inner: Optional[Expression]
    _child_fields = ("call", "root", "inner")

    def substitute(self, scope):
        del scope
        return self

    def _construct_sugar(self):
        from sugar_lift_py_tests.sugar.builtin_container_call_sugar import (
            PathAfterCallSugar,
        )

        return PathAfterCallSugar(
            call=self.call.sugar(),
            root=self.root.sugar(),
            steps=self.steps,
            mode=self.mode,
            unshared=self.unshared,
            site=self.fragment,
            evaluation_token=self.occurrence,
        )


class BuiltinContainerProjection(Expression):
    """The receiver's post-state (0) or the call's value (1) of one call."""

    call: Expression
    index: int
    _child_fields = ("call",)

    def substitute(self, scope):
        del scope
        return self

    def _construct_sugar(self):
        from sugar_lift_py_tests.sugar.builtin_container_call_sugar import (
            BuiltinContainerProjectionSugar,
        )

        return BuiltinContainerProjectionSugar(
            call=self.call.sugar(), index=self.index, site=self.fragment
        )


class ReceiverAfterCall(Expression):
    """A value a call may have changed: unknown after that call."""

    label: str
    occurrence: str

    def substitute(self, scope):
        del scope
        return self

    def _construct_sugar(self):
        from sugar_lift_py_tests.sugar.builtin_container_call_sugar import (
            ReceiverAfterCallSugar,
        )

        return ReceiverAfterCallSugar(
            label=self.label, site=self.fragment, evaluation_token=self.occurrence
        )


class SourceCallActualAfter(Expression):
    """An actual's object after a source helper's cited stores on it."""

    state: Expression
    label: str
    occurrence: str
    _child_fields = ("state",)

    def substitute(self, scope):
        del scope
        return self

    def _construct_sugar(self):
        from sugar_lift_py_tests.sugar.builtin_container_call_sugar import (
            SourceCallActualAfterSugar,
        )

        return SourceCallActualAfterSugar(
            state=self.state.sugar(),
            label=self.label,
            site=self.fragment,
            evaluation_token=self.occurrence,
        )


class ContainerMutationStatement(Statement):
    """A statement whose mutating call rebinds every alias of its receiver."""

    names: Tuple[str, ...]
    states: Tuple[Expression, ...]
    evaluated: Tuple[Expression, ...]
    _child_fields = ("states", "evaluated")

    def substitute(self, scope):
        del scope
        return self

    def substitution_binding(self, scope):
        del scope
        return dict(zip(self.names, self.states))

    def _construct_sugar(self):
        from sugar_lift_py_tests.sugar.builtin_container_call_sugar import (
            ContainerMutationStatementSugar,
        )

        return ContainerMutationStatementSugar(
            evaluated=tuple(node.sugar() for node in self.evaluated),
            site=self.fragment,
        )


class MappingPopResult(MappingPopState):
    """Shadow expression result of inherited ``mapping.pop(key, default)``."""

    def _construct_sugar(self):
        from sugar_lift_py_tests.sugar.mapping_pop_result_sugar import (
            MappingPopResultSugar,
        )

        return MappingPopResultSugar(
            receiver=self.receiver.sugar(),
            key=self.key.sugar(),
            default=self.default.sugar(),
            site=self.fragment,
        )


class Name(Expression):
    id: str

    def dotted_expr_name(self) -> Optional[str]:
        return self.id

    def substitute(self, scope: BindingMap) -> "Node":
        # A name resolves to its bound node, or stands unbound. This is the
        # whole substitution base case — it returns an EXISTING node, so it
        # needs no synthetic construction.
        bound = scope.get(self.id, _MISSING)
        if bound is _MISSING:
            return self
        bound = unwrap_binding_state(bound)
        if isinstance(bound, (FunctionDef, AsyncFunctionDef, ClassDef)):
            # A local definition bound this name: the read is the ordinary
            # name, resolved by the definition's own runtime binding, never
            # the definition statement spliced into expression position.
            return self
        if isinstance(bound, Node):
            # Formal / binding-coordinate refs carry identity in ``coordinate``,
            # not in the Param's declaration span. Replacing every use with the
            # declaration-span node collapses source order: a chained compare
            # ``1 <= month`` becomes operands (const@use, formal@decl) with decl
            # left of the use, so Compare._comparison_leg_site rejects a
            # well-formed chain (datetime._days_in_month assert; claim-mass
            # line 160). Both doors that mint formals share this shape:
            # FunctionDef.substitute → FormalRef, source_visible_call_frame →
            # BindingCoordinateRef. Re-span to the use site; coordinate CID is
            # unchanged.
            if (
                bound.kind in ("FormalRef", "BindingCoordinateRef")
                and bound.span != self.span
                and hasattr(bound, "coordinate")
            ):
                from .backend import Leaf, materialize
                from .shadow import ShadowNode

                return materialize(
                    self.unit,
                    ShadowNode(
                        bound.kind,
                        self.span,
                        (("coordinate", Leaf(bound.coordinate)),),
                    ),
                    self.reporter,
                )
            if bound.kind == "EvaluationRef" and bound.span != self.span:
                # The same reason: an evaluation reference was minted at its
                # binding site (the `x += e` target, a walrus target, a
                # comprehension target, a live loop's header, the target of
                # ``y = e``), which is not where this read sits.  Re-span to
                # the read; the evaluation key (a walrus's mark, a
                # comprehension member's mark) and the object it denotes
                # (``of``) are unchanged.  After ``y = e`` the binding is
                # ``y``'s own projection of the assignment's evaluation
                # (``Assign.target_evaluations``), so the key read here holds
                # the value ``e`` had at ``y = e``.
                return _evaluation_ref(
                    self,
                    self.span,
                    bound.evaluation,
                    bound.name,
                    member=getattr(bound, "member", False) is True,
                    walrus=getattr(bound, "walrus", False) is True,
                    cell=getattr(bound, "cell", False) is True,
                    deferred=getattr(bound, "deferred", False) is True,
                    of=getattr(bound, "of", None),
                )
            return bound
        span = self.line_col_span()
        if (
            self.unit.import_reference_target(
                (span.start_line, span.start_col, span.end_line, span.end_col)
            )
            is not None
        ):
            # The sole lexical import pass proves that this exact use has one
            # reaching import definition.  Preserve the source node so its
            # consumer can project that coordinate; do not replace it with an
            # unbound temporal read merely because imports are inert facts.
            return self
        return self._make_binding_read(bound)

    def _make_binding_read(self, state: BindingState) -> "Node":
        from .backend import Leaf, materialize
        from .shadow import ShadowNode

        return materialize(
            self.unit,
            ShadowNode(
                "GuardedBindingRead",
                self.span,
                (("name", Leaf(self.id)), ("state", Leaf(state))),
            ),
            self.reporter,
        )

    def _construct_sugar(self):
        """A name constructs NameSugar with its identifier. A name is a leaf:
        nothing to build from children, only to look up against the temporal
        scope when the body reduces (an unbound name panics there, loudly).

        A seated import value-use receipt for ``from re import Pattern``
        constructs the same ImportMemberSugar Attribute uses for ``re.Pattern``.
        A module-alias Name (``import re``) has no member path and stays a
        NameSugar so we do not invent an empty-path import member.
        """
        span = self.line_col_span()
        receipt = self.unit.import_value_use_receipt(
            (span.start_line, span.start_col, span.end_line, span.end_col)
        )
        from sugar_lift_py_tests.import_binding import AuthenticatedImportUseV1

        if type(receipt) is AuthenticatedImportUseV1:
            receipt.revalidate()
            site = receipt.use["useSite"]
            if (
                receipt.source_cid != self.unit.source_cid
                or site.get("sourceCid") != self.unit.source_cid
                or (
                    site.get("startLine"),
                    site.get("startCol"),
                    site.get("endLine"),
                    site.get("endCol"),
                )
                != (span.start_line, span.start_col, span.end_line, span.end_col)
            ):
                from sugar_source_tree.panic import BackendDefect

                raise BackendDefect(
                    blame=self.fragment,
                    owner="Name._construct_sugar",
                    observed="import value-use receipt does not own this Name",
                    requested="same-source exact Name occurrence testimony",
                    fix="consume the receipt only at its producer-minted useSite",
                )
            from sugar_lift_py_tests.floor.import_member_value import (
                _import_member_export_path,
            )

            if _import_member_export_path(receipt):
                from sugar_lift_py_tests.sugar.import_member_sugar import (
                    ImportMemberSugar,
                )

                qualified_name = receipt.target_symbol
                if not qualified_name.startswith("python:"):
                    from sugar_source_tree.panic import BackendDefect

                    raise BackendDefect(
                        blame=self.fragment,
                        owner="Name._construct_sugar",
                        observed=f"target_symbol={qualified_name!r}",
                        requested="authenticated python: import target symbol",
                        fix="preserve the lexical receipt targetSymbol unchanged",
                    )
                qualified_name = qualified_name[len("python:") :]
                return ImportMemberSugar(
                    qualified_name=qualified_name,
                    receipt=receipt,
                    site=self.fragment,
                )

        from sugar_lift_py_tests.sugar.name_sugar import NameSugar

        return NameSugar(name=self.id, site=self.fragment)


class FormalRef(Expression):
    """The declaration-owned authenticated reference for one formal."""

    coordinate: object

    def substitute(self, scope):
        del scope
        return self

    def _construct_sugar(self):
        from sugar_lift_py_tests.sugar.formal_ref_sugar import FormalRefSugar

        return FormalRefSugar(coordinate=self.coordinate, site=self.fragment)


class BindingCoordinateRef(Expression):
    """Projection of one authenticated formal binding in a source call frame."""

    coordinate: object

    def substitute(self, scope):
        del scope
        return self

    def _construct_sugar(self):
        from sugar_lift_py_tests.sugar.binding_coordinate_ref_sugar import (
            BindingCoordinateRefSugar,
        )

        return BindingCoordinateRefSugar(self.coordinate, self.fragment)


class EvaluationRef(Expression):
    """A read rewritten to a reference to one statement's evaluation.

    Temporal choice 1 (#7661): after ``x += e`` or ``(x := e)`` substitution
    rewrites a read of ``x`` to ``EvaluationRef(<the evaluation key>)``; the
    statement (or walrus) binds its completed value under that key at reduce
    (``Statement._evaluation_key``, ``EvaluationRefSugar``).  After
    ``a, b = f()`` a read of ``a`` is an ``EvaluationRef`` to ``a``'s
    projection of the statement's key (``projection_key``).  In a
    comprehension's element and conditions a read of a target name is an
    ``EvaluationRef`` to the coordinate the comprehension binds each member
    under (``ListComp._target_references``, ``ComprehensionSugar``), marked
    ``member``: it reads that coordinate only.  In the body of a lambda the
    comprehension stores, the read is a member reference to the final
    member's coordinate (``final_member_coordinate``, ``_closure_cell_scope``),
    marked ``cell``: the lambda carries that binding in its closure.
    A walrus's reference is marked
    ``walrus``: it resolves through the key only, and is refused where the
    key was never bound (undecided by name where it is also ``deferred``: a
    generator expression's walrus, which writes when the generator is
    consumed).  In a live loop's body a carried name reads the loop
    header's evaluation of it (``_loop_header_evaluation_key``), which the
    recurrence binds per item.  Built by ``_evaluation_ref`` only.
    """

    evaluation: str
    name: str

    def substitute(self, scope):
        del scope
        return self

    def ground_value(self) -> "Optional[Node]":
        """The ground literal this key holds (``_ground_value``), or None:
        the value an assignment's ``of`` gives, when it is ground.  Asked
        only to decide a shape; the read is still this reference."""
        return _ground_value(self)

    def _construct_sugar(self):
        from sugar_lift_py_tests.sugar.evaluation_ref_sugar import (
            EvaluationRefSugar,
        )

        return EvaluationRefSugar(
            evaluation=self.evaluation,
            name=self.name,
            site=self.fragment,
            member=getattr(self, "member", False) is True,
            walrus=getattr(self, "walrus", False) is True,
            deferred=getattr(self, "deferred", False) is True,
        )


class LoopBindingRef(Expression):
    """Construction-owned reference to one guarded loop post-binding face."""

    target_cid: str
    binding_coordinate_cid: str
    completion_kind: str

    def substitute(self, scope):
        del scope
        return self

    def _construct_sugar(self):
        from sugar_lift_py_tests.sugar.loop_recurrence_sugar import (
            LoopBindingRefSugar,
        )

        return LoopBindingRefSugar(
            self.target_cid,
            self.binding_coordinate_cid,
            self.completion_kind,
            self.fragment,
        )


class LoopRecurrenceStatement(Statement):
    """A decoded live LoopConstructionV1 enrolled in the source statement list."""

    loop: Statement
    construction: object
    target_cid: str
    binding_coordinate_cids: tuple[str, ...]
    outward_faces: tuple[object, ...]
    _child_fields = ("loop",)

    def substitute(self, scope):
        del scope
        return self

    def _construct_sugar(self):
        from sugar_lift_py_tests.sugar.loop_recurrence_sugar import (
            LoopRecurrenceSugar,
        )

        return LoopRecurrenceSugar(
            self.target_cid,
            self.construction.loop_construction_cid,
            self.binding_coordinate_cids,
            self.outward_faces,
            self.construction,
            self.fragment,
        )


class DecoratedDefinitionRef(Expression):
    """The value a decorated local ``def``/``class`` binds: not constructed.

    ``@d def g(): ...`` binds ``g`` to ``d(<function g>)``, the decorator's
    result. Decorator application is not constructed here, so a later read
    refuses by name instead of standing as the bare definition (a wrong
    value) or as unbound (a false NameError).
    """

    definition_name: str

    def substitute(self, scope):
        del scope
        return self

    def _construct_sugar(self):
        from sugar_lift_py_tests.sugar.decorated_definition_ref_sugar import (
            DecoratedDefinitionRefSugar,
        )

        return DecoratedDefinitionRefSugar(self.definition_name, self.fragment)


def _local_definition_binding(definition, scope):
    """A local ``def``/``class`` binds its name for the statements after it.

    Only a name the enclosing function holds as a lexical local is threaded;
    an undecorated definition binds itself, a decorated one binds a loud
    ``DecoratedDefinitionRef``.
    """
    lexical = scope.get(_LEXICALLY_BOUND_NAMES)
    if not isinstance(lexical, frozenset) or definition.name not in lexical:
        return None
    if not definition.decorators:
        return {definition.name: definition}
    from .backend import Leaf, materialize
    from .shadow import ShadowNode

    return {
        definition.name: materialize(
            definition.unit,
            ShadowNode(
                "DecoratedDefinitionRef",
                definition.span,
                (("definition_name", Leaf(definition.name)),),
            ),
            definition.reporter,
        )
    }


class ConstructedReceiverRef(Expression):
    """Typed projection of the receiver constructed by this exact class call."""

    class_name: str
    binding_coordinate_cid: str

    def substitute(self, scope):
        return self

    def _construct_sugar(self):
        from sugar_lift_py_tests.sugar.constructed_receiver_ref_sugar import (
            ConstructedReceiverRefSugar,
        )

        return ConstructedReceiverRefSugar(
            self.class_name, self.binding_coordinate_cid, self.fragment
        )


class BranchResultRef(Expression):
    """Projection of the one condition result authenticated by its owning if."""

    slot_id: str

    def substitute(self, scope):
        del scope
        return self

    def _construct_sugar(self):
        from sugar_lift_py_tests.sugar.branch_result_ref_sugar import (
            BranchResultRefSugar,
        )

        return BranchResultRefSugar(
            slot=BranchResultSlot(self.slot_id), site=self.fragment
        )


def _construct_binding_projection(state):
    from sugar_lift_py_tests.sugar.binding_projection import (
        GuardedProjection,
        LoopGuardedCompletedFace,
        LoopGuardedProjection,
        UnboundProjection,
    )

    state = unwrap_binding_state(state)
    if isinstance(state, Node):
        return state.sugar()
    if isinstance(state, UnboundBinding):
        return UnboundProjection(state.name, state.cause)
    if isinstance(state, GuardedBinding):
        return GuardedProjection(
            state.slot,
            _construct_binding_projection(state.when_true),
            _construct_binding_projection(state.when_false),
        )
    if isinstance(state, LoopProjectedBinding):
        # A loop routes HERE, not to GuardedProjection -- which is why a loop
        # never mints ("binding.projection", slot_id). That matters: a loop is
        # the one shape supplying many executions over one source location by
        # construction, and that partition's key has no execution component.
        # See tests/test_binding_partition_execution_conflation.py
        # (test_tripwire_c_a_loop_body_does_not_mint_this_partition).
        if any(face.guard_formula is None for face in state.completed_faces):
            raise BindingStateWireGap(
                "loop projected binding has CID-only guards; exact guard formula "
                "testimony is required before downstream construction"
            )
        return LoopGuardedProjection(
            tuple(
                LoopGuardedCompletedFace(
                    face.completion_kind,
                    face.guard_formula,
                    _construct_binding_projection(face.state),
                    face.exit_partition_arity,
                )
                for face in state.completed_faces
            ),
            state.target_cid,
        )
    # Missing arm over BindingState: name the species and the constructor door.
    # A bare TypeError(type(state)) aborts the file as instrument noise and
    # names neither the union nor the unwritten arm.
    from sugar_source_tree.panic import SugarNotWritten

    raise SugarNotWritten(
        owner="_construct_binding_projection",
        blame=f"binding-state:{type(state).__name__}",
        observed=(
            f"binding state species {type(state).__name__} has no projection "
            f"constructor arm"
        ),
        requested=(
            "Node | UnboundBinding | GuardedBinding | LoopProjectedBinding "
            "(with formula-bearing guards)"
        ),
        fix=(
            f"write _construct_binding_projection arm for {type(state).__name__} "
            f"or project it before this door; do not raise TypeError"
        ),
    )


class GuardedBindingRead(Expression):
    """A read-site projection of immutable binding-state testimony."""

    name: str
    state: BindingState

    def substitute(self, scope):
        del scope
        return self

    def _construct_sugar(self):
        from sugar_lift_py_tests.sugar.guarded_binding_read_sugar import (
            GuardedBindingReadSugar,
        )

        return GuardedBindingReadSugar(
            name=self.name,
            state=_construct_binding_projection(self.state),
            site=self.fragment,
        )


class DeleteName(Statement):
    """A plain-name delete carrying its pre-delete availability."""

    name: str
    prior: BindingState

    def substitute(self, scope):
        del scope
        return self

    def substitution_binding(self, scope):
        del scope
        return {self.name: UnboundBinding(name=self.name, cause=self.fragment)}

    def _construct_sugar(self):
        from sugar_lift_py_tests.sugar.delete_name_sugar import DeleteNameSugar

        return DeleteNameSugar(
            name=self.name,
            prior=_construct_binding_projection(self.prior),
            site=self.fragment,
        )


class DeleteAttribute(Statement):
    receiver: Expression
    attr: str
    _child_fields = ("receiver",)

    def substitute(self, scope):
        del scope
        return self

    def _construct_sugar(self):
        from sugar_lift_py_tests.sugar.delete_effect_sugar import (
            AttributeDeleteEffectSugar,
        )

        return AttributeDeleteEffectSugar(
            receiver=self.receiver.sugar(), attr=self.attr, site=self.fragment
        )


class DeleteSubscript(Statement):
    receiver: Expression
    index: Expression
    _child_fields = ("receiver", "index")

    def substitute(self, scope):
        del scope
        return self

    def _construct_sugar(self):
        from sugar_lift_py_tests.sugar.delete_effect_sugar import (
            SubscriptDeleteEffectSugar,
        )

        return SubscriptDeleteEffectSugar(
            receiver=self.receiver.sugar(),
            index=self.index.sugar(),
            site=self.fragment,
        )


class EffectRef(Expression):
    """Preallocated effect coordinate: syntax creates it; routing authenticates.

    Not an exception object and not a floor witness. ``except E as e`` rewrites
    ``e`` to ``EffectRef(slot)`` in the handler only. Routing later associates
    the matched Halted raise payload with that slot — never E().
    """

    slot_id: str

    def substitute(self, scope: "dict[str, Node]") -> "Node":
        # Already a coordinate — never re-captured as a free name.
        del scope
        return self

    def _construct_sugar(self):
        from sugar_lift_py_tests.sugar.effect_ref_sugar import EffectRefSugar

        return EffectRefSugar(slot_id=self.slot_id, site=self.fragment)


class ManagerRef(Expression):
    """Once-evaluated manager coordinate for resource ``with``.

    Context expression evaluates once; ``ManagerRef(M)`` is the stable
    receiver for ``__enter__`` / ``__exit__`` — never a second evaluation of
    the context expression.
    """

    slot_id: str

    def substitute(self, scope: "dict[str, Node]") -> "Node":
        del scope
        return self

    def _construct_sugar(self):
        from sugar_lift_py_tests.sugar.resource_coord_sugar import ManagerRefSugar

        return ManagerRefSugar(slot_id=self.slot_id, site=self.fragment)


class ExitTypeRef(Expression):
    """Parametric ``__exit__`` type argument: ``ExitTypeRef(X)``."""

    face_id: str

    def substitute(self, scope: "dict[str, Node]") -> "Node":
        del scope
        return self

    def _construct_sugar(self):
        from sugar_lift_py_tests.sugar.resource_coord_sugar import ExitTypeRefSugar

        return ExitTypeRefSugar(face_id=self.face_id, site=self.fragment)


class ExitValueRef(Expression):
    """Parametric ``__exit__`` value argument: ``ExitValueRef(X)``."""

    face_id: str

    def substitute(self, scope: "dict[str, Node]") -> "Node":
        del scope
        return self

    def _construct_sugar(self):
        from sugar_lift_py_tests.sugar.resource_coord_sugar import ExitValueRefSugar

        return ExitValueRefSugar(face_id=self.face_id, site=self.fragment)


class ExitTracebackRef(Expression):
    """Parametric ``__exit__`` traceback argument: ``ExitTracebackRef(X)``."""

    face_id: str

    def substitute(self, scope: "dict[str, Node]") -> "Node":
        del scope
        return self

    def _construct_sugar(self):
        from sugar_lift_py_tests.sugar.resource_coord_sugar import (
            ExitTracebackRefSugar,
        )

        return ExitTracebackRefSugar(face_id=self.face_id, site=self.fragment)


class ObservationRef(Expression):
    """Contract-declared observation of an effect slot (e.g. ExceptionInfo).

    ``with Expects(...) as ei`` rewrites ``ei`` to ``ObservationRef(slot,
    projection)``. ``.value`` projects the same slot as EffectRef. Projection
    comes from the membrane contract, not from vendor names in the tree.
    """

    slot_id: str
    projection: str  # exception_info | warning_observation | effect | enter_result

    def substitute(self, scope: "dict[str, Node]") -> "Node":
        del scope
        return self

    def _construct_sugar(self):
        from sugar_lift_py_tests.sugar.effect_ref_sugar import ObservationRefSugar

        return ObservationRefSugar(
            slot_id=self.slot_id,
            projection=self.projection,
            site=self.fragment,
        )


class List(Expression):
    elts: Tuple[Expression, ...]
    _child_fields = ("elts",)

    def substitute(self, scope):
        """Binds nothing: recurse into children and reassemble."""
        return self._substitute_children(scope)

    def _construct_sugar(self):
        """`[e, ...]` constructs ListSugar; a spread uses its reference term."""
        from sugar_lift_py_tests.sugar.collection_sugar import ListSugar

        if any(isinstance(e, Starred) for e in self.elts):
            from sugar_lift_py_tests.sugar.spread_sugar import SpreadCollectionSugar

            return SpreadCollectionSugar(
                kind="list",
                elements=tuple(
                    (
                        ("python:starred", e.value.sugar())
                        if isinstance(e, Starred)
                        else (None, e.sugar())
                    )
                    for e in self.elts
                ),
                site=self.fragment,
            )
        return ListSugar(
            elements=tuple(e.sugar() for e in self.elts), site=self.fragment
        )


class Tuple_(Expression):
    elts: Tuple[Expression, ...]
    _child_fields = ("elts",)

    def substitute(self, scope):
        """Binds nothing: recurse into children and reassemble."""
        return self._substitute_children(scope)

    def _construct_sugar(self):
        """`(e, ...)` constructs TupleSugar; a spread uses its reference term."""
        from sugar_lift_py_tests.sugar.collection_sugar import TupleSugar

        if any(isinstance(e, Starred) for e in self.elts):
            from sugar_lift_py_tests.sugar.spread_sugar import SpreadCollectionSugar

            return SpreadCollectionSugar(
                kind="tuple",
                elements=tuple(
                    (
                        ("python:starred", e.value.sugar())
                        if isinstance(e, Starred)
                        else (None, e.sugar())
                    )
                    for e in self.elts
                ),
                site=self.fragment,
            )
        return TupleSugar(
            elements=tuple(e.sugar() for e in self.elts), site=self.fragment
        )


# Wire word for tuples is "Tuple"; the class name carries a trailing
# underscore only to avoid shadowing typing.Tuple inside this module.
Tuple_._kind = "Tuple"
KIND_REGISTRY["Tuple"] = KIND_REGISTRY.pop("Tuple_")


class Slice(Expression):
    lower: Optional[Expression]
    upper: Optional[Expression]
    step: Optional[Expression]
    _child_fields = ("lower", "upper", "step")

    def substitute(self, scope):
        """Binds nothing: recurse into children and reassemble."""
        return self._substitute_children(scope)

    def _construct_sugar(self):
        """`lower:upper:step` constructs SliceSugar; an omitted bound stays None
        (its NoneValue), as Python fills it."""
        from sugar_lift_py_tests.sugar.slice_sugar import SliceSugar

        return SliceSugar(
            lower=None if self.lower is None else self.lower.sugar(),
            upper=None if self.upper is None else self.upper.sugar(),
            step=None if self.step is None else self.step.sugar(),
            site=self.fragment,
        )


# --------------------------------------------------------------------------
# match patterns
# --------------------------------------------------------------------------


class MatchValue(Pattern):
    value: Expression
    _child_fields = ("value",)

    def substitute(self, scope):
        """Binds nothing itself: recurse into children and reassemble."""
        return self._substitute_children(scope)


class MatchSingleton(Pattern):
    value: object

    def substitute(self, scope):
        """Binds nothing itself: recurse into children and reassemble."""
        return self._substitute_children(scope)


class MatchSequence(Pattern):
    patterns: Tuple[Pattern, ...]
    _child_fields = ("patterns",)

    def substitute(self, scope):
        """Binds nothing itself: recurse into children and reassemble."""
        return self._substitute_children(scope)


class MatchMapping(Pattern):
    _bound_name_fields = ("rest",)
    keys: Tuple[Expression, ...]
    patterns: Tuple[Pattern, ...]
    rest: Optional[str]
    _child_fields = ("keys", "patterns")

    def substitute(self, scope):
        """Binds nothing itself: recurse into children and reassemble."""
        return self._substitute_children(scope)


class MatchClass(Pattern):
    cls_: Expression
    patterns: Tuple[Pattern, ...]
    kwd_attrs: Tuple[str, ...]
    kwd_patterns: Tuple[Pattern, ...]
    _child_fields = ("cls_", "patterns", "kwd_patterns")

    def substitute(self, scope):
        """Binds nothing itself: recurse into children and reassemble."""
        return self._substitute_children(scope)


class MatchStar(Pattern):
    _bound_name_fields = ("name",)
    name: Optional[str]

    def substitute(self, scope):
        """Binds nothing itself: recurse into children and reassemble."""
        return self._substitute_children(scope)


class MatchAs(Pattern):
    _bound_name_fields = ("name",)
    pattern: Optional[Pattern]
    name: Optional[str]
    _child_fields = ("pattern",)

    def substitute(self, scope):
        """Binds nothing itself: recurse into children and reassemble."""
        return self._substitute_children(scope)


class MatchOr(Pattern):
    patterns: Tuple[Pattern, ...]
    _child_fields = ("patterns",)

    def substitute(self, scope):
        """Binds nothing itself: recurse into children and reassemble."""
        return self._substitute_children(scope)


# --------------------------------------------------------------------------
# PEP 695 type parameters
# --------------------------------------------------------------------------


class TypeVar(TypeParam):
    name: str
    bound: Optional[Expression]
    default_value: Optional[Expression] = None  # PEP 696 (3.13+)
    _child_fields = ("bound", "default_value")

    def substitute(self, scope):
        """Binds nothing itself: recurse into children and reassemble."""
        return self._substitute_children(scope)


class ParamSpec(TypeParam):
    name: str
    default_value: Optional[Expression] = None  # PEP 696 (3.13+)
    _child_fields = ("default_value",)

    def substitute(self, scope):
        """Binds nothing itself: recurse into children and reassemble."""
        return self._substitute_children(scope)


class TypeVarTuple(TypeParam):
    name: str
    default_value: Optional[Expression] = None  # PEP 696 (3.13+)
    _child_fields = ("default_value",)

    def substitute(self, scope):
        """Binds nothing itself: recurse into children and reassemble."""
        return self._substitute_children(scope)


def resolve_kind(kind: str, observed_at: str) -> type[Node]:
    """Two arms: a registered concrete node class, or panic.

    A backend kind with no node class is a MISSING grammar class — the
    conformance finding itself — never a permissive fallback.
    """
    cls = KIND_REGISTRY.get(kind)
    if cls is None or cls in _ABSTRACT:
        vocabulary_missing(
            blame=observed_at,
            owner="nodes.resolve_kind",
            observed=f"backend kind {kind!r} at {observed_at} has no node class",
            requested="a concrete Node subclass for every constructible shape",
            fix="add the missing grammar class to nodes.py — never map to a fallback",
        )
        raise AssertionError("unreachable")
    return cls


def _declared_fields(cls: type[Node]) -> Tuple[str, ...]:
    """Annotated accessor names across the class's MRO, base fields excluded."""
    names: list[str] = []
    for klass in reversed(cls.__mro__):
        for name in getattr(klass, "__annotations__", {}):
            if name.startswith("_") or name in ("unit", "ref"):
                continue
            if name not in names:
                names.append(name)
    return tuple(names)
