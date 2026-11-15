from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from enum import Enum
from typing import TYPE_CHECKING, Any, TypeAlias

from sugar_lift_py_tests.call_symbol import call_symbol
from sugar_lift_py_tests.context_manager_resolution import SourceFragmentCoordinateV1

from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.ir import Term
from sugar_lift_py_tests.sugar.sugar_base import (
    ConstructedTermSugar,
    require_constructed_term_sugar,
)
from sugar_lift_py_tests.sugar.witnesses import _call_pair


class DefinitionOccurrenceAbsenceReasonV1(str, Enum):
    """Why a call producer positively claims no source definition occurrence."""

    NOT_SOURCE_RESOLVED = "not-source-resolved"
    NO_LEXICAL_SOURCE_CALL_ROW = "no-lexical-source-call-row"


@dataclass(frozen=True)
class DefinitionOccurrenceAbsentV1:
    """Positive absence arm for a call's definition reconciliation fields."""

    reason: DefinitionOccurrenceAbsenceReasonV1

    def __post_init__(self) -> None:
        if type(self.reason) is not DefinitionOccurrenceAbsenceReasonV1:
            raise TypeError(
                "DefinitionOccurrenceAbsentV1.reason must be "
                "DefinitionOccurrenceAbsenceReasonV1"
            )


if TYPE_CHECKING:
    from sugar_source_tree.nodes import AsyncFunctionDef, ClassDef, FunctionDef

    DefinitionOccurrenceReconciliationV1: TypeAlias = (
        FunctionDef
        | AsyncFunctionDef
        | ClassDef
        | DefinitionOccurrenceAbsentV1
    )
else:
    DefinitionOccurrenceReconciliationV1 = object


_DEFINITION_NOT_SOURCE_RESOLVED = DefinitionOccurrenceAbsentV1(
    DefinitionOccurrenceAbsenceReasonV1.NOT_SOURCE_RESOLVED
)
_NO_LEXICAL_SOURCE_CALL_ROW = DefinitionOccurrenceAbsentV1(
    DefinitionOccurrenceAbsenceReasonV1.NO_LEXICAL_SOURCE_CALL_ROW
)



def _import_bound_unanswered_call(sugar):
    """The may-raise testimony for a bodiless call to an import-bound callee.

    The one import table (``SourceUnit.import_reference_of``) names the
    callee's target symbol; no dependency source is read to decide what the
    name is (step 3).  Nothing in this proof answers the call, so it is the
    unanswered ``undecided`` member under that symbol and two-faced -- never a
    total completion.  A call cited off the population is the same unanswered
    call (``_off_population_unanswered_call``).
    """
    if sugar.reference_symbol is None or sugar.contract_resolution_gap is not None:
        return None
    if sugar.site is None:
        return None
    from sugar_lift_py_tests.source_call_resolution import UnknownCalleeCallV1

    return UnknownCalleeCallV1(sugar.spelled_target)


_OFF_POPULATION = "call-target-off-population:"

# The target-symbol prefix of a binding to the builtin namespace
# (``SourceUnit.builtin_reference_at``).
_BUILTINS_PREFIX = "python:builtins."


def _off_population_unanswered_call(sugar):
    """The may-raise testimony for a call cited off the enrolled population.

    Not bridged is cited one way: the callee's body was not looked at and
    nothing here answers the call, so it is the same ``UnknownCalleeCallV1``
    every unanswered call is, under the call's one spelling (#7837)."""
    gap = sugar.contract_resolution_gap
    if not isinstance(gap, str) or not gap.startswith(_OFF_POPULATION):
        return None
    from sugar_lift_py_tests.source_call_resolution import UnknownCalleeCallV1

    return UnknownCalleeCallV1(sugar.spelled_target)


def _unknown_callee_call(sugar, callsite):
    """The may-raise testimony for a bodiless call nothing answered.

    Reached once every answer has declined: no source frame (a seated frame
    is the definition's edge, ``CallSiteSugar._definition_edge``) and no
    builtin law answers the call
    (``_builtin_law_answers``).  Whatever the name is bound to -- nothing, a
    value (``len = 5; len(x)``), a class whose constructor frame was not
    built, any name a star import may rebind (``from m import *; int('x')``),
    or a builtin the lifter does not model (``open``, ``getattr``, ``next``)
    -- what runs was not looked at, so the call is the one unanswered
    citation, two-faced and owed, never a completion (#7757: a raise is never
    a completion; a halt is never dropped)."""
    if _builtin_law_answers(sugar, callsite):
        return None
    from sugar_lift_py_tests.source_call_resolution import UnknownCalleeCallV1

    return UnknownCalleeCallV1(sugar.spelled_target)


def _builtin_law_answers(sugar, callsite) -> bool:
    """A law the lifter models answers this bodiless builtin-bound call.

    Read from the callee's binding, never its spelling: a shape CPython
    documents as never raising (``builtin_call_total`` on the bound
    ``LanguageCallee``: ``type(obj)``, ``id(obj)``, ``callable(obj)``,
    ``object()``, ...).  A builtin exception class's construction never
    reaches here (``_builtin_exception_construction``).  A builtin binding
    with none of these answers nothing: binding a name to the builtin
    namespace is not a law for what that builtin does."""
    from sugar_lift_py_tests.source_call_resolution import builtin_call_total

    return builtin_call_total(
        sugar.language_callee,
        callsite.arg_values,
        getattr(callsite, "keyword_names", ()) or (),
    )


def _builtin_exception_construction(sugar, callsite):
    """A bodiless call of a builtin exception class (``callsite.
    builtin_exception_class``, by the callee's binding): its construction.

    Over ground actuals the pinned interpreter decides it, through the one
    cited fold (``builtin_exception_cited_fold``): the class it constructs
    and the ``args`` it stores, or its ``TypeError``.  An actual known only
    by its type:

    - with a keyword actual, ``_builtin_exception_keyword_call``;
    - where the class's constructor reads its actuals' values
      (``builtin_exception_construction_reads_values``: ``OSError(e, 'x')``,
      whose errno selects the subclass; ``SyntaxError('m', d)``, whose
      details tuple is parsed; the ``Unicode*Error`` signatures; the
      exception groups' members), the one unanswered call, whose completed
      face names no class;
    - otherwise the constructor stores its positional actuals as ``args``
      (BaseException's law, or ``OSError(msg)``): the call completes holding
      them (``constructed_args``)."""
    from dataclasses import replace

    from sugar_lift_py_tests.source_call_resolution import (
        UnknownCalleeCallV1,
        builtin_exception_cited_fold,
    )
    from sugar_lift_py_tests.temporal.builtin_name_bindings import (
        builtin_exception_construction_reads_values,
    )

    folded = builtin_exception_cited_fold(callsite, sugar.site)
    if folded is not None:
        return folded
    if callsite.keyword_names:
        return _builtin_exception_keyword_call(sugar, callsite)
    if builtin_exception_construction_reads_values(
        callsite.builtin_exception_class.name, len(callsite.arg_values)
    ):
        return UnknownCalleeCallV1(sugar.spelled_target).faces(
            replace(callsite, exception_type_coordinate=None, exception_type_mro=None),
            sugar.site,
        )
    from sugar_lift_py_tests.floor.tuple_value import TupleValue

    return ExitSet.completed(
        replace(callsite, constructed_args=TupleValue(tuple(callsite.arg_values)))
    )


def _builtin_exception_keyword_call(sugar, callsite):
    """``ValueError(x, code=1)``: a bodiless call of a builtin exception
    class (``callsite.builtin_exception_class``, by the callee's binding)
    with a keyword actual and an actual known only by its type (over
    ground actuals the interpreter decides it, ``builtin_exception_cited_fold``).

    Keyword values are never ``args``: ``BaseException_new`` stores only the
    positional actuals.  A class whose constructor is BaseException's law
    initializes through ``BaseException_init``, which raises TypeError for
    any keyword (``builtin_exception_constructor_rejects_keywords``): the
    call is that halt, after its actuals were evaluated.  A class whose
    constructor may read keywords (``ImportError``, ``AttributeError``,
    ``NameError``) or is not BaseException's (``OSError``, ``SyntaxError``,
    ...) is not read here: the call is the one unanswered call."""
    from sugar_lift_py_tests.temporal.builtin_name_bindings import (
        builtin_exception_constructor_rejects_keywords,
    )

    if builtin_exception_constructor_rejects_keywords(
        callsite.builtin_exception_class.name
    ):
        from sugar_lift_py_tests.floor.ground_exit import ground_type_error

        return ground_type_error(
            site=sugar.site, owner="CallSiteSugar.builtin_exception_keywords"
        )
    from sugar_lift_py_tests.source_call_resolution import UnknownCalleeCallV1

    return UnknownCalleeCallV1(sugar.spelled_target).faces(callsite, sugar.site)


@dataclass(frozen=True)
class CallSiteSugar(ConstructedTermSugar):
    """`<name>(<args>)` -> a call-site coordinate: THE DIG CUE.

    Reduce each argument, then stand as a CallSiteValue whose term is the bridge
    coordinate `call:<name>(<arg terms>)`. That coordinate is the cue: an assert
    that consumes it carries it into the InvValue's operand_callsites, which
    projects the callEdge -- and a cue is the signal that this call warrants a
    dig (reduce the callee into its universe; its call sites cue further digs).

    An opaque call keeps ``body=None`` and remains a dig cue.  When construction
    carries a source-authenticated body, however, Call is an effect producer:
    it reduces that already-constructed body once and publishes its halted
    ExitSet faces at this expression.  Completed faces retain the CallSiteValue
    coordinate, so ordinary return-floor digging is unchanged.  No assertion
    or other consumer is consulted to decide whether the call may halt.

    Meaning-only, node-constructed. Plain positional calls to a named callee;
    method/attribute/computed callees and keyword args stay gaps (the tree node
    guards them).
    """

    target_name: str
    args: tuple[ConstructedTermSugar, ...]
    site: object = dataclass_field(compare=False)
    keywords: tuple[tuple[str, ConstructedTermSugar], ...] = ()
    contract_resolution_gap: str | None = dataclass_field(default=None, compare=False)
    # The target symbol of an import-bound callee, `python:<module>.<name>`,
    # as the one import table (#7837) holds it at the callee's coordinate.
    # The call stands as its coordinate, and its edge (and its `undecided`
    # member when nothing here answers it) carries this symbol, unbound;
    # prove's join binds it (step 9). The symbol has one source, the table.
    import_target_symbol: str | None = dataclass_field(default=None, compare=False)
    # The import reference table's target symbol for an import-bound callee
    # (#7837): ``idn.ident`` for ``from idn import ident``, ``numpy.add`` for
    # ``np.add``. It is the call's one spelling, never the local alias; a
    # callee with no row keeps its own name.
    reference_symbol: str | None = None
    exception_type_coordinate: Any = dataclass_field(default=None, compare=False)
    exception_type_mro: tuple | None = dataclass_field(default=None, compare=False)
    source_call_frame: Any = dataclass_field(default=None, compare=False)
    # A lexical call's frame is owned by its lexical row's definition
    # (testified); ``_NO_LEXICAL_SOURCE_CALL_ROW`` for every other call.
    expected_source_call_frame_owner: DefinitionOccurrenceReconciliationV1 = (
        dataclass_field(default=_NO_LEXICAL_SOURCE_CALL_ROW, compare=False)
    )
    formal_function_sugar: Any = dataclass_field(default=None, compare=False)
    formal_coordinate_cids: tuple[str, ...] = dataclass_field(default=(), compare=False)
    expected_definition_ref: DefinitionOccurrenceReconciliationV1 = dataclass_field(
        default=_DEFINITION_NOT_SOURCE_RESOLVED, compare=False
    )
    native_operation_formal_coordinates: tuple = dataclass_field(
        default=(), compare=False
    )
    call_occurrence: SourceFragmentCoordinateV1 | None = dataclass_field(
        default=None, compare=False
    )
    # The language-fixed callee the Call node bound this call to
    # (``sugar_source_tree.nodes.LanguageCallee``), read from the callee's
    # binding, never its spelling; ``None`` for every other callee. What the
    # language decides for that callee is dispatched on this member.
    language_callee: Any = dataclass_field(default=None, compare=False)
    # ``((name, coordinate cid, sugar), ...)``: a call of a local ``def`` in
    # its enclosing body carries, for each enclosing local the body reads, the
    # binding the enclosing scope holds at the call
    # (``Call._closure_cells``).  Its value is bound under the frame's
    # captured coordinate before the body runs (``_captured_values``); the
    # name is never read in the callee.
    captured: tuple = dataclass_field(default=(), compare=False)

    def __post_init__(self) -> None:
        for argument in self.args:
            require_constructed_term_sugar(argument, owner="CallSiteSugar.args")
        for _name, argument in self.keywords:
            require_constructed_term_sugar(argument, owner="CallSiteSugar.keywords")
        if (
            self.call_occurrence is not None
            and type(self.call_occurrence) is not SourceFragmentCoordinateV1
        ):
            raise TypeError(
                "CallSiteSugar.call_occurrence must be SourceFragmentCoordinateV1"
            )
        self._require_definition_reconciliation(
            self.expected_definition_ref,
            coordinate="CallSiteSugar.expected_definition_ref",
        )
        self._require_definition_reconciliation(
            self.expected_source_call_frame_owner,
            coordinate="CallSiteSugar.expected_source_call_frame_owner",
        )
        if isinstance(
            self.expected_definition_ref, DefinitionOccurrenceAbsentV1
        ) and self.source_call_frame is not None:
            raise TypeError(
                "CallSiteSugar.expected_definition_ref cannot claim absence "
                "when source_call_frame is present"
            )

    @staticmethod
    def _require_definition_reconciliation(
        value: object, *, coordinate: str
    ) -> None:
        from sugar_source_tree.nodes import AsyncFunctionDef, ClassDef, FunctionDef

        if not isinstance(
            value,
            (
                FunctionDef,
                AsyncFunctionDef,
                ClassDef,
                DefinitionOccurrenceAbsentV1,
            ),
        ):
            raise TypeError(
                f"{coordinate} must be a projected definition occurrence or "
                "DefinitionOccurrenceAbsentV1; got "
                f"{type(value).__name__}"
            )

    @staticmethod
    def _reconciled_definition_ref(value: object) -> object | None:
        from sugar_source_tree.nodes import AsyncFunctionDef, ClassDef, FunctionDef

        match value:
            case DefinitionOccurrenceAbsentV1():
                return None
            case FunctionDef() | AsyncFunctionDef() | ClassDef() as definition:
                return definition.ref
            case _:
                raise TypeError(
                    "definition reconciliation must be a projected definition "
                    "occurrence or DefinitionOccurrenceAbsentV1"
                )

    @classmethod
    def witnesses(cls):
        # A user callee's returned value is asserted through the call site: the
        # truthful twin asserts the dug value, the lying twin another -- the pair
        # proves the lift discriminates on what the call computes.
        prefix = "def A(z):\n    return z\n\n"
        return _call_pair(
            name="call_site_return",
            owner_sugar="CallSiteSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(5) == 6\n",
        )

    @property
    def spelled_target(self) -> str:
        """The call's one spelling: its import target symbol when the callee
        is import-bound, else the callee's own name (#7837)."""
        return self.reference_symbol or self.target_name

    def to_term(self, *, owner: str) -> Term:
        """Project authenticated callee, arguments, authority, and occurrence."""
        from sugar_lift_py_tests.ir import ctor, str_const

        occurrence = self.occurrence_term(owner=owner)
        if self.source_call_frame is not None:
            callee = ctor(
                "python:source-callee",
                (str_const(self.source_call_frame.frame_cid),),
                symbol_kind="coordinate",
            )
        else:
            # The exact call occurrence is the available callee authority for
            # builtin/opaque calls; never elevate the target spelling.
            callee = ctor(
                "python:occurrence-callee", (occurrence,), symbol_kind="coordinate"
            )
        definition_authority = []
        if self.exception_type_coordinate is not None:
            coordinate_cid = getattr(self.exception_type_coordinate, "cid", None)
            if coordinate_cid is not None:
                definition_authority.append(str_const(coordinate_cid))
            else:
                from sugar_lift_py_tests.ir import (
                    _ConstBool,
                    _ConstInt,
                    _ConstReal,
                    _ConstStr,
                    _Ctor,
                    _Lambda,
                    _Var,
                )

                if not isinstance(
                    self.exception_type_coordinate,
                    (
                        _Ctor,
                        _ConstInt,
                        _ConstStr,
                        _ConstBool,
                        _ConstReal,
                        _Var,
                        _Lambda,
                    ),
                ):
                    raise TypeError(
                        f"{owner} requires authenticated exception definition "
                        "coordinate or term"
                    )
                definition_authority.append(self.exception_type_coordinate)
        definition_authority.extend(
            str_const(cid) for cid in self.formal_coordinate_cids
        )
        # The kit applies no contract to a call (step 6 as amended); the
        # coordinate keeps its constant contract slot so no call CID moves.
        contract_authority = ctor("python:no-resolved-call-contract", ())
        positional = tuple(argument.to_term(owner=owner) for argument in self.args)
        keywords = tuple(
            ctor(
                "python:keyword-argument",
                (str_const(name), argument.to_term(owner=owner)),
            )
            for name, argument in self.keywords
        )
        return ctor(
            "python:call-construction",
            (
                occurrence,
                callee,
                ctor("python:positional-arguments", positional),
                ctor("python:keyword-arguments", keywords),
                ctor(
                    "python:definition-authority",
                    tuple(definition_authority),
                    symbol_kind="coordinate",
                ),
                contract_authority,
            ),
            symbol_kind="coordinate",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        if self.source_call_frame is not None:
            from sugar_source_tree.panic import SugarNotWritten
            from sugar_source_tree.nodes import (
                AsyncFunctionDef,
                FunctionDef,
            )

            expected_definition_ref = self._reconciled_definition_ref(
                self.expected_definition_ref
            )
            owner_matches = (
                expected_definition_ref is not None
                and self.source_call_frame.owner.ref is expected_definition_ref
            )
            if not owner_matches:
                raise SugarNotWritten(
                    owner="CallSiteSugar.desugar",
                    blame=self.site,
                    observed="cached source frame has foreign definition owner",
                    requested="authenticated lexical definition owner",
                    fix="retain the seated frame or keep the call loud",
                )
            # Closure testimony belongs to function frames.  A class
            # constructor frame is owned by ClassDef and has a class symtable,
            # not a function symtable named after the class.  Asking the
            # function-only lookup for it turns an authenticated constructor
            # into a SourceTreePanic before its existing binder can run.
            free_names: tuple[str, ...] = ()
            if isinstance(
                owner := self.source_call_frame.owner, (FunctionDef, AsyncFunctionDef)
            ):
                table = owner.unit.function_symtable(
                    owner.name, owner.line_col_span().start_line
                )
                free_names = tuple(
                    symbol.get_name()
                    for symbol in table.get_symbols()
                    if symbol.is_free() or symbol.is_nonlocal()
                )
            carried = {name for name, _cid, _sugar in self.captured}
            uncarried = tuple(name for name in free_names if name not in carried)
            if uncarried:
                raise SugarNotWritten(
                    owner="CallSiteSugar.desugar",
                    blame=self.site,
                    observed=(
                        "closure bindings lack producer coordinates: " f"{uncarried!r}"
                    ),
                    requested="captured binding coordinate testimony",
                    fix=("enroll producer-owned closure actuals before body reduction"),
                )
        if self.contract_resolution_gap is not None:
            # Off-population is "we know exactly which callee this is, and we
            # have decided not to look inside it". Raising here would abort an
            # enrolled constructor that stores ``re.compile(match)`` as a
            # field. Missing or value-bound callees stay a typed resolution
            # gap so a factory ``return Path(...)`` cannot become a manager.
            if str(self.contract_resolution_gap).startswith(
                "call-target-off-population"
            ):
                return self._collect(self.args, (), ctx)
            from sugar_source_tree.panic import OpaqueSourceCallResolutionGap

            raise OpaqueSourceCallResolutionGap(
                owner="CallSiteSugar.desugar",
                blame=self.site,
                observed=self.contract_resolution_gap,
                requested="authenticated resolved-call contract reference",
                fix="publish and resolve the imported target contract or keep the call loud",
            )
        return self._collect(self.args, (), ctx)

    def _builtin_reference(self) -> str | None:
        """``python:builtins.<name>``: the builtin this call's callee is
        bound to, else None.

        Read from the callee's binding at its own coordinate
        (``SourceUnit.name_reference_at``: the one import reference table,
        then the builtin namespace nothing rebinds), never its spelling: a
        user class, parameter or rebinding named ``ValueError`` or ``len``
        reaches no builtin, and ``from builtins import len as L`` does.
        """
        from sugar_source_tree.nodes import Name

        callee = getattr(getattr(self.site, "node", None), "func", None)
        unit = getattr(self.site, "unit", None)
        if not isinstance(callee, Name) or unit is None:
            return None
        target = unit.name_reference_at(callee.id, callee.line_col_span())
        if target is None or not target.startswith(_BUILTINS_PREFIX):
            return None
        return target

    def _builtin_floor_value(self):
        """The builtin floor's value this call's callee is bound to, else None.

        The value the builtin floor holds under the name the callee's binding
        (``_builtin_reference``) names, never under the call's spelling: a
        callee a star import, a module or function rebinding, or a parameter
        may bind reaches no builtin value, and ``from builtins import len as
        L`` reaches ``len``'s.
        """
        target = self._builtin_reference()
        if target is None:
            return None
        from sugar_lift_py_tests.temporal.builtin_name_bindings import (
            builtin_name_temporal,
        )

        return builtin_name_temporal().value_if_bound(
            target[len(_BUILTINS_PREFIX) :]
        )

    def _applied_builtin_exception_class(self, source_call_frame):
        """The builtin exception class this call applies, by its binding.

        The builtin floor's class the callee's binding names
        (``_builtin_floor_value``), never the call's spelling: a user class or
        rebinding named ``ValueError`` is not a builtin exception.
        """
        if source_call_frame is not None:
            return None
        from sugar_lift_py_tests.floor import BuiltinExceptionClassValue

        receiver = self._builtin_floor_value()
        if not isinstance(receiver, BuiltinExceptionClassValue):
            return None
        return receiver

    def _applied_builtin_type_of(
        self, source_call_frame, positional, kw_values, term
    ):
        """The class coordinate ``type(obj)`` returns, by the callee's binding.

        One positional actual applied through the language-owned ``type``
        binding returns ``obj``'s class: a type object on every evaluation,
        never a non-class and never a raise.  The coordinate is the call term
        itself (which class is undecided).  Read from the callee's binding
        (``LanguageCallee.BUILTIN_TYPE``), never the spelling: a rebound,
        source-defined or contracted ``type`` and the three-argument class
        constructor get no coordinate.
        """
        from sugar_source_tree.nodes import LanguageCallee

        if (
            self.language_callee is not LanguageCallee.BUILTIN_TYPE
            or source_call_frame is not None
            or len(positional) != 1
            or kw_values
        ):
            return None
        return term

    def _captured_values(self, ctx) -> tuple:
        """``((name, coordinate cid, value), ...)``: each carried enclosing
        binding (``captured``) read here, at the call
        (``read_captured_values``)."""
        return read_captured_values(self.captured, ctx, site=self.site)

    def _with_captured_values(self, ctx, frame, captured_values):
        """``ctx`` with each captured value bound under ``frame``'s captured
        coordinate for its name (``with_captured_values``)."""
        return with_captured_values(
            ctx, frame, captured_values, site=self.site, blame=self.target_name
        )

    def _collect(
        self, remaining: tuple, accumulated: tuple, ctx: object, inside=()
    ) -> ExitSet:
        from sugar_lift_py_tests.floor.named_expression_value import (
            consume_operands,
            evaluated_after,
            written_by,
        )

        if remaining:
            head, *rest = remaining
            actual_ctx = _actual_reduce_context(ctx)
            # The actual is an operand: a walrus in it (``f((x := 5))``) binds
            # once, through the one operand door.  The later actuals, the
            # keywords and the call itself (the closure cells it reads among
            # them) are evaluated after it, with its writes applied
            # (``written_by``: ``f((a := 1), a)``), inside its door, which
            # lays its stores in their halts; a later actual's halt is
            # recorded where it was evaluated, after every earlier actual's
            # writes (``inside``, ``evaluated_after``).  The actual is
            # collected as evaluated: it is converted to the operation
            # receiver it is once, where the call is applied (``_applied``).
            return evaluated_after((), head, actual_ctx, inside=inside).and_then(
                lambda value: consume_operands(
                    lambda presented: self._collect(
                        tuple(rest),
                        accumulated + (presented,),
                        written_by(value, ctx),
                        (*inside, value),
                    ),
                    value,
                )
            )
        return self._collect_kwargs(self.keywords, (), accumulated, ctx, inside)

    def _collect_kwargs(
        self,
        remaining: tuple,
        kw_values: tuple,
        positional: tuple,
        ctx: object,
        inside=(),
    ) -> ExitSet:
        if remaining:
            from sugar_lift_py_tests.floor.named_expression_value import (
                consume_operands,
                evaluated_after,
                written_by,
            )

            (name, sugar), *rest = remaining
            actual_ctx = _actual_reduce_context(ctx)
            # Same order as the positional actuals (``_collect``).
            return evaluated_after((), sugar, actual_ctx, inside=inside).and_then(
                lambda value: consume_operands(
                    lambda presented: self._collect_kwargs(
                        tuple(rest),
                        kw_values + ((name, presented),),
                        positional,
                        written_by(value, ctx),
                        (*inside, value),
                    ),
                    value,
                )
            )
        from sugar_lift_py_tests.floor.call_site_value import bind_after_call

        # A same-file definition's edge carries, on its completed face, what
        # it names of what it was handed, under this call's key: the
        # exposure rule reads each object it may have changed there (#7757
        # step 7).
        return bind_after_call(self._applied(positional, kw_values, ctx), self.site)

    def _applied(self, positional: tuple, kw_values: tuple, ctx: object) -> ExitSet:
        """The call over its actuals as evaluated (``_collect``), each
        converted to the operation receiver it is exactly once
        (``as_operation_receivers``): by the one application of a
        function's value when the name is bound to one
        (``LambdaCallable.callable_application_with``), else here, before
        any other callee is applied (``_applied_to_receivers``)."""
        from sugar_lift_py_tests.callable_application import CallableApplication
        from sugar_lift_py_tests.floor import LambdaCallable
        from sugar_lift_py_tests.floor.lambda_callable import as_operation_receivers

        receiver = self._value_callee(positional, kw_values, ctx)
        names = tuple(name for name, _ in kw_values)
        actuals = positional + tuple(value for _, value in kw_values)
        if isinstance(receiver, LambdaCallable):
            # A name bound to a function's value (``key(item)`` in a
            # function given ``key=lambda v: ...``) calls that value: its
            # own frame, the one binder and the one application, which
            # converts each actual.
            return receiver.callable_application_with(
                CallableApplication(
                    actuals, names, self.site, call_occurrence=self.call_occurrence
                ),
                ctx,
            )
        count = len(positional)
        return as_operation_receivers(
            actuals,
            ctx,
            lambda converted: self._applied_to_receivers(
                receiver,
                converted[:count],
                tuple(zip(names, converted[count:])),
                ctx,
            ),
            owner="CallSiteSugar actual",
        )

    def _value_callee(self, positional: tuple, kw_values: tuple, ctx: object):
        """The value this call applies through its own application, or None:
        the builtin its binding is, a class statement's value called with no
        actual, or a function's value a name is bound to with no source frame
        seated at the call."""
        if ctx is None:
            return None
        from sugar_lift_py_tests.floor import (
            BuiltinSemanticCallable,
            ClassDefinitionValue,
            LambdaCallable,
        )

        # A builtin's semantics (``len``, ``isinstance``, ``set``,
        # ``tuple``, ...) apply only when the callee's binding is the
        # builtin namespace (``_builtin_floor_value``), never because the
        # temporal floor holds a builtin under the call's spelling: under
        # ``from m import *`` or ``len = f`` the call is not the builtin's.
        receiver = self._builtin_floor_value()
        if not isinstance(receiver, BuiltinSemanticCallable):
            receiver = ctx.temporal.value_if_bound(self.target_name)
            if isinstance(receiver, BuiltinSemanticCallable):
                receiver = None
        if (
            isinstance(receiver, BuiltinSemanticCallable)
            or (
                isinstance(receiver, ClassDefinitionValue)
                and self.source_call_frame is None
                and not positional
                and not kw_values
            )
            or (
                isinstance(receiver, LambdaCallable)
                and self.source_call_frame is None
                and isinstance(
                    self.expected_source_call_frame_owner,
                    DefinitionOccurrenceAbsentV1,
                )
                and self.formal_function_sugar is None
            )
        ):
            return receiver
        return None

    def _applied_to_receivers(
        self, receiver, positional: tuple, kw_values: tuple, ctx: object
    ) -> ExitSet:
        """``_applied`` for a callee other than a function's value, over its
        actuals as operation receivers: the builtin's or the class value's
        own application (``receiver``), else the call by name through its
        seated frame or as its bodiless coordinate."""
        if receiver is not None:
            from sugar_lift_py_tests.callable_application import CallableApplication

            return receiver.callable_application_with(
                CallableApplication(
                    positional + tuple(value for _, value in kw_values),
                    tuple(name for name, _ in kw_values),
                    self.site,
                    call_occurrence=self.call_occurrence,
                ),
                ctx,
            )
        from sugar_lift_py_tests.ir import ctor, str_const

        owner = str(self.site)
        kwarg_terms = [
            ctor("py.kwarg", [str_const(name), value.to_term(owner=owner)])
            for name, value in kw_values
        ]
        # What the callee reads from its enclosing scope is an input of this
        # call as its actuals are: two calls that read different values are
        # two coordinates.
        captured_values = self._captured_values(ctx)
        closure_terms = [
            ctor("py.closure", [str_const(name), value.to_term(owner=owner)])
            for name, _cid, value in captured_values
        ]
        # The head is classified by the callee's binding, never its spelling:
        # a ``len`` the module rebinds is a coordinate, not the builtin.
        term = ctor(
            call_symbol(self.spelled_target),
            [value.to_term(owner=owner) for value in positional]
            + kwarg_terms
            + closure_terms,
            symbol_kind=(
                "builtin" if self._builtin_reference() is not None else "coordinate"
            ),
        )
        # The frame is the one construction read (``Call._construct_sugar``:
        # the lexical row's definition's own), carried as
        # ``source_call_frame``.
        source_call_frame = self.source_call_frame
        if not isinstance(
            self.expected_source_call_frame_owner, DefinitionOccurrenceAbsentV1
        ):
            from sugar_source_tree.panic import SugarNotWritten

            # A lexical call: the frame it carries is owned by the lexical
            # row's exact definition.
            expected_owner_ref = self._reconciled_definition_ref(
                self.expected_source_call_frame_owner
            )
            owner_matches = (
                source_call_frame is not None
                and expected_owner_ref is not None
                and source_call_frame.owner.ref is expected_owner_ref
            )
            if source_call_frame is None or not owner_matches:
                raise SugarNotWritten(
                    owner="CallSiteSugar.desugar",
                    blame=self.site,
                    observed="seated source frame has foreign lexical owner",
                    requested="the lexical row's exact definition-owned source frame",
                    fix="retain the authenticated frame at the exact call coordinate or keep loud",
                )
        if source_call_frame is not None:
            return self._definition_edge(
                source_call_frame, positional, kw_values, captured_values, term, ctx
            )
        # The one binder (``object_value.bind_call``): a call with no frame
        # binds bodyless.  No call by name applies a body (#7757 step 6): a
        # seated frame is a ``def``'s, and its call is its coordinate and
        # edge (``_definition_edge``).
        callsite = bind_source_frame_call(
            self.target_name,
            positional,
            kw_values,
            frame=None,
            ctx=ctx,
            owner="CallSiteSugar.desugar",
            blame=self.site,
            term=term,
            defaults=(),
            call_occurrence=self.call_occurrence,
            authenticated_target_symbol=self.import_target_symbol,
            exception_type_coordinate=self.exception_type_coordinate,
            exception_type_mro=self.exception_type_mro,
            builtin_exception_class=self._applied_builtin_exception_class(None),
            python_type_coordinate=self._applied_builtin_type_of(
                None, positional, kw_values, term
            ),
            language_callee=self.language_callee,
        )
        return self._apply_bound(callsite)

    def _definition_edge(
        self, frame, positional, kw_values, captured_values, term, ctx
    ):
        """The call of the ``def`` whose frame ``Call._construct_sugar``
        seated by the callee's name -- a generator function, an ``async
        def``, a ``contextmanager`` generator -- as its coordinate and edge
        (#7757 step 6, the owner's ruling of 2026-11-15, "Edge, join at
        prove"), through the one edge every call of a same-file definition
        stands as (``lambda_callable.definition_edge_call``).

        The frame is entered and the call bound by the one binder
        (``object_value.bind_call``, no body) only to read what the edge
        supplies; a call that does not fit the signature is refused by name
        there.  The body is never applied: what the call returns (a
        generator, a coroutine, a manager) and what iterating, awaiting or
        entering it does are what the callee's contract states, joined at
        prove, and otherwise undecided and owed."""
        from sugar_lift_py_tests.floor.lambda_callable import (
            definition_edge_call,
            variadic_formals,
        )
        from sugar_lift_py_tests.floor.object_value import bind_call

        caller_ctx = ctx
        ctx, module_halt = enter_source_frame(
            frame,
            ctx,
            owner="CallSiteSugar.desugar",
            blame=self.site,
            covered=frozenset(name for name, _cid, _value in captured_values),
        )
        ctx = self._with_captured_values(ctx, frame, captured_values)
        if module_halt is not None:
            return module_halt
        bound = bind_call(
            self.target_name,
            positional,
            kw_values,
            frame=frame,
            parameters=frame.parameters,
            frame_cid=frame.frame_cid,
            formal_coordinate_cids=tuple(
                item.cid for item in frame.formal_coordinates
            ),
            ctx=ctx,
            owner="CallSiteSugar.desugar",
            blame=self.site,
            refuse=_refuse_loud,
            term=term,
        )
        return definition_edge_call(
            symbol_definition=frame.owner,
            signature=frame.owner,
            parameters=tuple(frame.parameters),
            packed=variadic_formals(frame),
            positional=positional,
            keywords=kw_values,
            captured=captured_values,
            actuals=tuple(bound.arg_values),
            site=self.site,
            call_occurrence=self.call_occurrence,
            caller_ctx=caller_ctx,
            fallback_target=self.target_name,
        )

    def _apply_bound(self, callsite):
        """The bodiless call ``callsite`` the one binder bound: a builtin
        exception's construction, a law the lifter models, or an unanswered
        callee's faces; else the call itself, completed."""
        if callsite.builtin_exception_class is not None:
            return _builtin_exception_construction(self, callsite)
        unprojected = _import_bound_unanswered_call(self)
        if unprojected is None:
            unprojected = _off_population_unanswered_call(self)
        if unprojected is None and self.contract_resolution_gap is None:
            from sugar_lift_py_tests.source_call_resolution import (
                builtin_dunder_call,
            )

            unprojected = builtin_dunder_call(
                self.language_callee,
                callsite.arg_values,
                getattr(callsite, "keyword_names", ()) or (),
            )
            if unprojected is None:
                from sugar_lift_py_tests.source_call_resolution import (
                    builtin_list_construct,
                )

                constructed = builtin_list_construct(
                    self.language_callee,
                    callsite.arg_values,
                    getattr(callsite, "keyword_names", ()) or (),
                    site=self.site,
                )
                if constructed is not None:
                    return constructed
        if unprojected is not None:
            # What CPython's own source decides: an import-bound stdlib
            # call, or a builtin over ground operands (``int('3')`` is
            # ``3``, ``int('x')`` the one ``ValueError`` halt).  Anything
            # else stays the one unanswered call.
            from sugar_lift_py_tests.source_call_resolution import (
                cpython_cited_fold,
            )

            folded = cpython_cited_fold(
                unprojected,
                callsite.arg_values,
                getattr(callsite, "keyword_names", ()) or (),
                site=self.site,
                language_callee=self.language_callee,
                callsite=callsite,
            )
            if folded is not None:
                return folded
        if unprojected is None:
            unprojected = _unknown_callee_call(self, callsite)
        if unprojected is not None:
            return unprojected.faces(callsite, self.site)
        return ExitSet.completed(callsite)


def read_captured_values(captured, ctx, *, site) -> tuple:
    """``((name, coordinate cid, value), ...)``: each enclosing binding a
    call carries for its callee's captured names (``captured``: ``(name,
    coordinate cid, sugar)``, ``Call._captured_cells``) read here, at the
    call, in the caller's context -- the enclosing scope's binding of the
    name at the point of the call, as Python reads the cell when the
    function runs.  The one reader for a local ``def``'s call
    (``CallSiteSugar``) and a lambda's (``ComputedCallSugar``), and through
    ``carried_captured_values`` for a lambda passed to a callee that runs it
    during the call.  A read that
    does not complete with one plain value is refused by name: the callee's
    body never reads the name instead, nor the binding it had where the
    function was made."""
    if not captured:
        return ()
    from sugar_source_tree.panic import SugarNotWritten

    values = []
    for name, cid, value in _captured_reads(captured, ctx):
        if value is None:
            raise SugarNotWritten(
                owner="CallSiteSugar.captured",
                blame=site,
                observed=(
                    f"enclosing binding of `{name}` read at the call did not "
                    "complete with one value"
                ),
                requested="the enclosing scope's value of the name at the call",
                fix="read the captured binding as one completed value",
            )
        values.append((name, cid, value))
    return tuple(values)


def _captured_reads(captured, ctx):
    """``(name, coordinate cid, value)`` for each carried binding
    (``captured``), read in order in the caller's context; ``value`` is
    ``None`` where the read does not complete with one plain value."""
    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        plain_completed_value,
    )

    actual_ctx = _actual_reduce_context(ctx)
    for name, cid, sugar in captured:
        yield name, cid, plain_completed_value(sugar.desugar(actual_ctx))


def carried_captured_values(captured, ctx) -> tuple:
    """``((name, coordinate cid, value), ...)``: the caller's binding at a
    call of each enclosing local a lambda passed to it reads, whose callee
    runs the lambda during the call (``captured``: ``(name, coordinate cid,
    sugar)``, ``Call._carry_argument_cells``), read where the argument is
    evaluated (``LambdaSugar``, ``carry_captured_values``) as
    ``read_captured_values`` reads a call's.  Empty when a read does not
    complete with one plain value: the lambda then carries nothing, and its
    call stays refused by name (``with_captured_values``).  The argument
    itself is never refused here: the callee may not call it."""
    if not captured:
        return ()
    values = []
    for name, cid, value in _captured_reads(captured, ctx):
        if value is None:
            return ()
        values.append((name, cid, value))
    return tuple(values)


def carry_captured_values(value, captured, ctx):
    """``value`` -- what a name bound to a lambda reduced to, passed to a
    callee that runs it during the call (``Call._carry_argument_cells``) --
    carrying each enclosing binding the call carries for the lambda's
    captured names (``carried_captured_values``).  Its call inside the
    callee binds them (``LambdaCallable.callable_application_with``).  A
    value that is not a lambda carries nothing: its call is not the
    lambda's."""
    from sugar_lift_py_tests.floor import LambdaCallable

    if not captured or not isinstance(value, LambdaCallable):
        return value
    from dataclasses import replace

    return replace(value, captured=carried_captured_values(captured, ctx))


def with_captured_values(ctx, frame, captured_values, *, site, blame):
    """``ctx`` with each captured value (``read_captured_values``) bound
    under ``frame``'s captured coordinate for its name
    (``FunctionDef._captured_bindings``, ``Lambda._captured_bindings``), as a
    formal's actual is bound under its coordinate: the one way a call of a
    local ``def`` (``CallSiteSugar``) or of a lambda (``ComputedCallSugar``)
    binds what its body reads from the enclosing scope.  Refused by name
    unless every captured name is carried (``require_frame_captures``)."""
    require_frame_captures(frame, captured_values, site=site)
    if not captured_values:
        return ctx
    from sugar_lift_py_tests.temporal import curry_temporal

    return curry_temporal(
        _actual_reduce_context(ctx),
        tuple(cid for _name, cid, _value in captured_values),
        tuple(value for _name, _cid, value in captured_values),
        owner="CallSiteSugar captured bindings",
        blame=blame,
    )


def require_frame_captures(frame, captured_values, *, site) -> None:
    """Refuse by name unless the call carries a value for every captured
    name of ``frame`` (``captured_names``), each under the frame's own
    coordinate for it.  A captured name the call does not carry is a
    function called where its enclosing binding at the call is not known
    (returned, stored, or passed to a callee that may keep it past the call):
    it is never read at the binding it had where the function was made."""
    from sugar_source_tree.panic import SugarNotWritten

    coordinates = {
        name: coordinate.cid
        for name, coordinate in zip(
            getattr(frame, "captured_names", ()),
            getattr(frame, "captured_coordinates", ()),
            strict=True,
        )
    }
    if any(coordinates.get(name) != cid for name, cid, _value in captured_values):
        raise SugarNotWritten(
            owner="CallSiteSugar.captured",
            blame=site,
            observed="captured binding coordinate is not the frame's",
            requested="the frame's own captured coordinate for each name",
            fix="carry the captured cells minted for this exact frame",
        )
    carried = {name for name, _cid, _value in captured_values}
    uncarried = tuple(name for name in coordinates if name not in carried)
    if uncarried:
        raise SugarNotWritten(
            owner="CallSiteSugar.captured",
            blame=site,
            observed=(
                "enclosing binding at the call is not known for captured "
                f"names {uncarried!r}"
            ),
            requested="the enclosing scope's binding of each name at the call",
            fix=(
                "call the function where its enclosing scope binds each "
                "captured name, or keep the call loud"
            ),
        )


def _actual_reduce_context(ctx):
    """Reduce call actuals under the builtin floor when the caller passed none.

    TemporalContext.empty() already is builtin_name_temporal. A language-owned
    name such as FutureWarning must cite that class, not a free SymbolicValue.
    Does not replace the caller's context for later body or machine reduction.
    """
    if ctx is not None:
        return ctx
    from sugar_lift_py_tests.context import ReduceContext

    return ReduceContext.root(owner="CallSiteSugar.desugar")


def enter_source_frame(
    frame, ctx, *, owner: str, blame: object, covered=frozenset()
):
    """What a call into a source frame does before it binds, for every form.

    A plain call, a computed callee and a call with ``*``/``**`` enter the
    frame here: it is the one typed variant, a closure body has its captured
    coordinates (``covered``: the captured names the call carries), the
    keys of the module-final bindings its body reads are bound when the
    call runs after import (``with_module_final_globals``, at the frame's
    module execution site), and a module whose
    constant halts is the call's halt.  Returns ``(ctx, halt)``: ``halt``
    is that module halt, else ``None``.
    """
    from sugar_lift_py_tests.source_call_frame import SourceVisibleCallFrameV1
    from sugar_source_tree.nodes import AsyncFunctionDef, FunctionDef
    from sugar_source_tree.panic import SugarNotWritten

    if not isinstance(frame, SourceVisibleCallFrameV1):
        raise SugarNotWritten(
            owner=owner,
            blame=blame,
            observed=type(frame).__name__,
            requested="a closed SourceCallFrameV1 variant",
            fix="construct a typed source frame or keep the call loud",
        )
    closure_owner = frame.owner
    if (
        isinstance(closure_owner, (FunctionDef, AsyncFunctionDef))
        and closure_owner.lacks_captured_binding_testimony(covered=covered)
    ):
        raise SugarNotWritten(
            owner=owner,
            blame=blame,
            observed="free or nonlocal source binding has no captured coordinate testimony",
            requested="producer-owned captured binding coordinates for every closure read",
            fix="construct closure bindings at the lexical frame boundary or keep loud",
        )
    ctx = with_module_final_globals(
        ctx,
        _frame_global_readers(frame),
        site=frame.module_execution_site,
    )
    return ctx, _frame_module_halt(frame)


def _frame_global_readers(frame) -> tuple:
    """The function bodies a call into ``frame`` runs: its ``def``, ``async
    def`` or lambda; for a class call, the source ``__init__`` and the
    source ``__new__`` the class call runs."""
    from sugar_source_tree.nodes import (
        AsyncFunctionDef,
        ClassDef,
        FunctionDef,
        Lambda,
    )

    owner = frame.owner
    if isinstance(owner, (FunctionDef, AsyncFunctionDef, Lambda)):
        return (owner,)
    if not isinstance(owner, ClassDef):
        return ()
    readers = []
    initializer = owner._source_initializer()
    if initializer is not None:
        readers.append(initializer)
    new_method = frame.constructed_new_method
    if new_method is not None:
        readers.append(new_method.source_call_frame.owner)
    return tuple(readers)


def _refuse_loud(*, owner, blame, observed, requested, fix):
    from sugar_source_tree.panic import SugarNotWritten

    raise SugarNotWritten(
        owner=owner,
        blame=blame,
        observed=observed,
        requested=requested,
        fix=fix,
    )


def bind_source_frame_call(
    target_name: str,
    positional: tuple,
    keywords: tuple,
    *,
    frame,
    ctx,
    owner: str,
    blame: object,
    term,
    refuse=_refuse_loud,
    **testimony,
):
    """``target_name(*positional, **keywords)`` bound by the one binder.

    ``object_value.bind_call`` with what ``frame`` (entered through
    ``enter_source_frame``) says about the callee: its formals and its
    coordinates.  With no frame the call is bound with its actuals as
    written.  No body is bound: a call is its coordinate and edge, and no
    callee body is applied at lift (#7757 step 6).
    """
    from sugar_lift_py_tests.floor.object_value import bind_call

    return bind_call(
        target_name,
        positional,
        keywords,
        frame=frame,
        parameters=() if frame is None else frame.parameters,
        frame_cid=None if frame is None else frame.frame_cid,
        formal_coordinate_cids=(
            ()
            if frame is None
            else tuple(item.cid for item in frame.formal_coordinates)
        ),
        ctx=ctx,
        owner=owner,
        blame=blame,
        refuse=refuse,
        term=term,
        **testimony,
    )


def _frame_module_halt(frame):
    """The halt of the frame's module, when one of its constants halts.

    ``X = 1 // 0`` at module level: importing the module halts there, so a
    call into any frame of it is that halt -- the first such constant in
    source order, reduced once per module and carried on the frame as its one
    ``Halted`` arm.  Never dropped, never a free name.
    """
    from sugar_lift_py_tests.outcome import ExitSet

    halt = getattr(frame, "module_halt", None)
    return None if halt is None else ExitSet((halt,))


def with_module_final_globals(ctx, readers, *, site):
    """``ctx`` at the entry of the bodies of ``readers`` (``def``, ``async
    def`` or lambda nodes), called at the module execution ``site``: the key
    of each module-final binding a body reads, bound.

    A function called after import (``site`` None, or another module's) is
    "called from outside the module's run" (#7945, #7956): its body reads a
    global through the module's final binding of it, a reference to the
    evaluation of the module body's last write
    (``nodes.module_final_global_references``: the one reader,
    ``_module_references_where_called``, with no site).  No
    statement of the module body runs in its frame, so nothing else binds
    that key there.  Each reference's key is bound here, at the frame
    entry, to the value the module body's own run bound it to: the one
    source of module-final values (``tree_enumerate.module_end_contexts``,
    the context each completed arm of THE module reduction ended with).
    So is each default key of a reader that is a ``def``
    (``nodes.module_final_default_keys``): its module ``def`` statement
    evaluated the default once in that run, and a call that omits the
    formal binds that value (``DefaultValueSugar``).
    The run evaluated each write once, whatever it wrote (a literal,
    ``x += e``, a call's result, a list), so its value is the module's,
    never a second evaluation of the write here.  A live loop's publication
    is read the same way: its post-loop key (``nodes._live_loop_publication``)
    and its own key of a name it carries (``LoopBindingRef.post_key``) are
    what the loop left them as in the run, and each slot a phi of the
    binding selects its arm by -- the loop's write slot
    (``loop_write_slot``), a module ``if``'s -- is decided as the run
    decided it (``ground_branch_results``), so the read takes the arm the
    run took.

    Each key is bound to its ``ModuleFinalValue``, and each slot to its
    ``ModuleFinalDecision``: the module run is asked for only where a key
    is read (``TemporalContext.key_read``) or a slot selects an arm
    (``branch_result_read``), never at the frame entry.  A body that reads
    no key and selects by no slot on the path it takes never asks for the
    run, so a module whose run refuses refuses only the reads of its final
    bindings, each at the read, by the run's own gap.  A key exclusive
    completed arms bound to different values reads each arm's value under
    its guard; one that arms not provably exclusive bound to different
    values has no value, and where the run completes on no arm, or no
    completed arm bound the key, it has none either: each such read is
    refused by name, naming the key (``EvaluationRefSugar._unbound``).  A slot they decided differently, or
    that none decided, reads as undecided.  A global the module body does not
    decide is read through its undecided key
    (``nodes.undecided_module_binding_key``), which no run binds: it is
    never bound here, so a read nothing else bound it for is refused by
    name, naming the key (``EvaluationRefSugar._unbound``), and a function's
    own contract binds it to the free input (``bind_global_inputs``).  The
    name is never bound.

    Called while the reader's own module body runs, the body reads the
    binding standing at ``site``, whose key that run bound: nothing is
    bound here, and the module run is not asked for.  ``ctx`` comes back
    unchanged when nothing is bound.
    """
    from sugar_source_tree.nodes import (
        module_final_default_keys,
        module_final_global_references,
        undecided_module_binding_key,
    )

    finals = []
    slots = []
    for reader in readers:
        evaluations = []
        decisions = []
        for name, state in sorted(
            module_final_global_references(reader, site).items()
        ):
            if getattr(state, "evaluation", None) == undecided_module_binding_key(
                reader.unit, name
            ):
                continue
            _collect_final_evaluations(state, evaluations, decisions)
        finals.extend(ModuleFinalValue(reader.unit, key) for key in evaluations)
        # The reader's own defaults, which its module ``def`` statement
        # evaluated in the same run: a formal the call omits binds that
        # value, never its default expression evaluated here.
        finals.extend(
            ModuleFinalValue(reader.unit, key)
            for key in module_final_default_keys(reader, site)
        )
        slots.extend(
            ModuleFinalDecision(reader.unit, slot_id) for slot_id in decisions
        )
    if not finals and not slots:
        return ctx
    from dataclasses import replace

    from sugar_lift_py_tests.context import ReduceContext

    entered = (
        ReduceContext.root(owner="with_module_final_globals") if ctx is None else ctx
    )
    bound_any = False
    # Each slot a phi of a final binding selects its arm by (a live loop's
    # write slot, ``loop_write_slot``; a module ``if``'s), decided as the
    # run decided it (``BranchResultDecision``, ``IfSugar``), where the phi
    # selects: the read takes that arm, whose key the run bound, never the
    # arm it did not.
    for decision in slots:
        table = entered.ground_branch_results
        if decision.slot_id in table:
            continue
        entered = replace(
            entered, ground_branch_results={**table, decision.slot_id: decision}
        )
        bound_any = True
    for final in finals:
        if entered.temporal.value_if_bound(final.key) is not None:
            continue
        entered = replace(
            entered,
            temporal=entered.temporal.bind_value(
                final.key, final, blame="with_module_final_globals"
            ),
        )
        bound_any = True
    return entered if bound_any else ctx


class ModuleFinalValue:
    """What a frame entry binds a module-final key to
    (``with_module_final_globals``): the value ``unit``'s module run bound
    ``key`` to, demanded where the key is read, never where it is bound.

    ``read`` asks for the run (``tree_enumerate.module_end_contexts``, run
    once per unit, its refusal remembered as loudly as its answer): the
    arms that bound the key joined by the one rule (``_module_end_value``),
    one completed arm owing every debt of each of them, else None, and the
    run's refusal raised at this read.  Every read of a bound value reads it
    through ``bound_read``: a read of a key (``TemporalContext.key_read``)
    and a scan over every binding (a store's alias advance,
    ``ReceiverFieldStoreValue.extend_scope``, ``bound_value_read``) alike,
    so what a binding holds never depends on whether the run was asked for
    before.
    """

    __slots__ = ("unit", "key")

    def __init__(self, unit, key: str) -> None:
        self.unit = unit
        self.key = key

    def __repr__(self) -> str:
        return f"ModuleFinalValue({self.key!r})"

    def read(self):
        from sugar_lift_py_tests.tree_enumerate import module_end_contexts

        return _module_end_value(module_end_contexts(self.unit), self.key)


def bound_read(value):
    """``value``, held by a binding of a temporal, as a read of it reads it:
    one completed arm holding what the read reads, owing what the read owes
    (an ``ExitSet``), or None where it reads no value.  A
    ``ModuleFinalValue`` is asked for here (``ModuleFinalValue.read``: the
    module run demanded, its refusal raised, every debt of the arms that
    bound the key owed); anything else is itself, owing nothing.

    The one read of a bound value.  A read of a key
    (``TemporalContext.key_read``) reads here, and a scan over every
    binding reads the value of the same read (``bound_value_read``), so a
    module-final binding answers one value wherever it is read and
    whatever was read before: a scan that skipped an unasked run and used
    an answered one gave one file two answers by order (#7757, entry 4)."""
    if isinstance(value, ModuleFinalValue):
        return value.read()
    from sugar_lift_py_tests.outcome import ExitSet

    return ExitSet.completed(value)


def bound_value_read(value):
    """The value ``bound_read`` reads off ``value``, or None: what a scan
    over every binding compares (a store's or a mutation's alias advance,
    ``ReceiverFieldStoreValue`` / ``ReceiverOwnedMutationResult.
    extend_scope``).  The scan rebinds a binding that names the receiver's
    object, and that binding was read to reach the receiver, so the read's
    debts are already owed on this path; only the value is compared here.
    Anything but a ``ModuleFinalValue`` is itself, so the scan builds no
    read per binding."""
    if not isinstance(value, ModuleFinalValue):
        return value
    read = value.read()
    return None if read is None else read.completed_value()


class ModuleFinalDecision:
    """What a frame entry decides a module slot by
    (``with_module_final_globals``): how ``unit``'s module run decided
    ``slot_id`` (a live loop's write slot, a module ``if``'s), asked for
    where a phi selects its arm by the slot (``branch_result_read``), never
    where it is bound.  ``read`` is the one decision every completed arm
    that decided it agrees on, else None (undecided), and the run's refusal
    raised at this read."""

    __slots__ = ("unit", "slot_id")

    def __init__(self, unit, slot_id: str) -> None:
        self.unit = unit
        self.slot_id = slot_id

    def __repr__(self) -> str:
        return f"ModuleFinalDecision({self.slot_id!r})"

    def read(self):
        from sugar_lift_py_tests.tree_enumerate import module_end_contexts

        return _module_end_decision(module_end_contexts(self.unit), self.slot_id)


def branch_result_read(table, slot_id):
    """The decision ``table`` (``ground_branch_results``) holds for
    ``slot_id`` as a selection by the slot reads it: a
    ``ModuleFinalDecision`` asked for here, anything else as it is; None
    where the slot is undecided."""
    bound = table.get(slot_id)
    if isinstance(bound, ModuleFinalDecision):
        return bound.read()
    return bound


def _module_end_value(ends, key):
    """The read of the value the module run bound ``key`` to, off ``ends``
    (the run's completed arms, each holding the context it ended with under
    its own guard, faces and debts, ``ModuleBlockSugar.run``): one completed
    arm holding the value, owing every debt of every arm that bound the key;
    else None.

    Each arm owes what its route through the module body left unanswered
    (``Completed.owed``: an imported decorator's application, a module-level
    call nothing here answers), and the value is what those arms made, so a
    read of it owes every debt of each (``ExitSet.owed_items``, the one join
    of debts): a function called after import that reads the value owes
    them, and never reads a value whose making its proof silently lacks.

    The arms that bound the key are joined by the one rule a join of a key
    over arms has (``if_sugar._joined_evaluation``, the rule an ``if``
    carries its keys out by): arms that bound it to one value answer that
    value; exclusive arms that bound it to different values answer each
    arm's value under that arm's guard (one ``GuardedValue``); arms that
    cannot be proved exclusive hold it at two values on one path, so there
    is no value and the read is refused by name (``EvaluationRefSugar``).
    An arm that never reached the write (a route the write's ``if``/``try``
    arm did not take) binds nothing under the key, and a read of the key
    stands only on the route that wrote it (the phi over that route,
    ``IfExp`` on a ``BranchResultRef``)."""
    from sugar_lift_py_tests.outcome import Completed, ExitSet
    from sugar_lift_py_tests.sugar.if_sugar import _joined_evaluation

    bound = []
    for end in ends:
        value = end.value.temporal.value_if_bound(key)
        if value is not None:
            bound.append(Completed(end.guard, value, end.faces, end.owed))
    if not bound:
        return None
    joined = _joined_evaluation(bound)
    if joined is None:
        return None
    return ExitSet.completed(joined, owed=ExitSet(tuple(bound)).owed_items())


def _module_end_decision(ends, slot_id):
    """How the module run decided the slot ``slot_id``, read off ``ends``
    (the context each completed arm holds, its ``ground_branch_results``:
    a ``TrueBoolLiteralSugar`` or a
    ``FalseBoolLiteralSugar``): the one decision every completed arm that
    decided it agrees on, else None.  An arm that never reached the slot's
    owner (a loop or an ``if`` in a route it did not take) decides nothing;
    an arm that holds it undecided (a loop over a symbolic iterable, which
    authenticates the slot as a guard) leaves it undecided."""
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
        FalseBoolLiteralSugar,
    )
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
        TrueBoolLiteralSugar,
    )

    decisions = [
        decided
        for decided in (
            getattr(end.value, "ground_branch_results", {}).get(slot_id)
            for end in ends
        )
        if decided is not None
    ]
    if not decisions:
        return None
    first = decisions[0]
    if not isinstance(first, (TrueBoolLiteralSugar, FalseBoolLiteralSugar)):
        return None
    if any(type(decided) is not type(first) for decided in decisions[1:]):
        return None
    return first


def _collect_final_evaluations(state, evaluations: list, decisions: list) -> None:
    """Every key a module-final binding ``state`` reads through
    (``evaluations``), and every slot a phi of it selects its arm by
    (``decisions``): an evaluation reference's key, a decorated ``def``'s
    or any ``class`` statement's value (``DecoratedDefinitionRef``: the key
    its statement bound the decorators' result under, whose function
    carries the defaults the statement evaluated; for a class, decorated or
    not, the class its body's run built in the module run, carrying its
    methods' defaults, so a frame called after import never runs the class
    body again where no module key is bound), a live loop's own key of
    a name it carries (``LoopBindingRef.post_key``, each face of its
    ``LoopProjectedBinding``), each arm of the phi the module block built
    over a module ``if`` or ``try`` route (``IfExp`` on a
    ``BranchResultRef``, whose slot is collected), and each arm of a binding
    joined over a slot (``GuardedBinding``: a live loop's write slot over
    its post-loop key, ``nodes._live_loop_publication``).  An undecorated
    ``def``, an import's row, an effect slot or an unbound state reads no
    key."""
    from sugar_source_tree.binding_state import (
        GuardedBinding,
        LoopProjectedBinding,
        unwrap_binding_state,
    )
    from sugar_source_tree.nodes import (
        BranchResultRef,
        DecoratedDefinitionRef,
        EvaluationRef,
        IfExp,
        LoopBindingRef,
        ObjectPlaceStateV1,
        OpaqueObjectStateV1,
    )

    state = unwrap_binding_state(state)
    if isinstance(state, (EvaluationRef, ObjectPlaceStateV1, OpaqueObjectStateV1)):
        # The object a call's result is bound as reads through its
        # assignment's key, as the reference it refines does.
        evaluations.append(state.evaluation)
    elif isinstance(state, DecoratedDefinitionRef) and isinstance(
        getattr(state, "evaluation", None), str
    ):
        evaluations.append(state.evaluation)
    elif isinstance(state, LoopBindingRef):
        evaluations.append(state.post_key)
    elif isinstance(state, LoopProjectedBinding):
        for face in state.completed_faces:
            _collect_final_evaluations(face.state, evaluations, decisions)
    elif isinstance(state, IfExp) and isinstance(state.test, BranchResultRef):
        decisions.append(state.test.slot_id)
        _collect_final_evaluations(state.body, evaluations, decisions)
        _collect_final_evaluations(state.orelse, evaluations, decisions)
    elif isinstance(state, GuardedBinding):
        decisions.append(state.slot.slot_id)
        _collect_final_evaluations(state.when_true, evaluations, decisions)
        _collect_final_evaluations(state.when_false, evaluations, decisions)


# ---------------------------------------------------------------------------
# A function's module global inputs (#7757 step 5).
#
# A function reads its own module's globals where it is called: after import,
# at the values the module's one run left; while the module body runs, at the
# binding standing at that call.  Its contract states its post and claims
# over each ``global:<name>`` input free (``bind_global_inputs``), its row
# states the value the run left for each (``stated_global_values``), and a
# call of it supplies the binding where the call runs (``global_value_at_call``,
# ``py.global``).  Prove's one binder binds an input no call supplies to the
# stated value, as it binds an omitted parameter to its default.  A class or a
# decorated ``def`` is a definition, never an input
# (``SourceUnit.module_definition_names``).
# ---------------------------------------------------------------------------


def global_input_keys(unit, name: str, site=None) -> tuple:
    """The evaluation keys the module binding of ``name`` reads through
    where a function of ``unit`` is called at the module execution ``site``
    (None: after import, the module's final binding): each key
    ``_collect_final_evaluations`` collects off the binding
    (``SourceUnit.module_bindings_at``).  Where the module does not decide
    the binding there, the one key a reader reads it through
    (``nodes.undecided_module_binding_key``), which no statement of the
    module's run binds."""
    from sugar_source_tree.nodes import (
        UNDECIDED_MODULE_BINDING,
        undecided_module_binding_key,
    )

    state = unit.module_bindings_at(site, frozenset({name})).get(
        name, UNDECIDED_MODULE_BINDING
    )
    if state is UNDECIDED_MODULE_BINDING:
        return (undecided_module_binding_key(unit, name),)
    evaluations: list = []
    decisions: list = []
    _collect_final_evaluations(state, evaluations, decisions)
    return tuple(dict.fromkeys(evaluations))


def _global_inputs(definition) -> tuple:
    """The ``global:`` inputs of ``definition``'s contract
    (``nodes._contract_inputs``), in their order."""
    from sugar_lift_py_tests.contract_input import GLOBAL_INPUT

    return tuple(
        item
        for item in definition.contract_inputs()
        if item.coordinate.input_kind == GLOBAL_INPUT
    )


def bind_global_inputs(ctx, definition, *, owner: str):
    """``ctx`` at the entry of ``definition``'s own contract (a ``def``,
    ``async def`` or lambda), with each key the module's final binding of a
    ``global:<name>`` input reads through (``global_input_keys``) bound to
    the free input (``ContractInputV1.value``), as a captured cell is bound
    to its free input (``contract_input.bind_contract_inputs``).  So the
    contract's post and claims are stated over the input, and every call the
    body makes of a function that reads the global supplies the input
    (``global_value_at_call``).  A key already bound in ``ctx`` keeps its
    binding.  ``ctx`` comes back unchanged when nothing is bound."""
    inputs = _global_inputs(definition)
    if not inputs:
        return ctx
    from dataclasses import replace

    from sugar_lift_py_tests.context import ReduceContext

    entered = ReduceContext.root(owner=owner) if ctx is None else ctx
    bound_any = False
    for item in inputs:
        value = item.value()
        for key in global_input_keys(definition.unit, item.coordinate.name):
            if entered.temporal.value_if_bound(key) is not None:
                continue
            entered = replace(
                entered,
                temporal=entered.temporal.bind_value(key, value, blame=owner),
            )
            bound_any = True
    return entered if bound_any else ctx


def stated_global_values(definition) -> tuple:
    """``((formal, term), ...)``: the value the module's one run left for
    each ``global:<name>`` input of ``definition``'s contract, read where
    its one key is read (``ModuleFinalValue``: the run asked for, its
    refusal raised here).  The row states them (``inputValues``) and prove's
    one binder binds an input no call supplies to its stated value (a call
    after import, pytest's call of a test function).  A final binding that
    is a phi over a slot the run decided reads through the keys of the arm
    the run took (``_keys_on_the_arm_the_run_took``).  An input whose final
    binding reads through more than one key there (a branch merge the run
    left undecided, a loop's faces), or that the run leaves undecided,
    owing, or not one completed value, is not stated: a claim that reads it
    is not decided.  One the
    module body does not decide (read through its undecided key,
    ``nodes.undecided_module_binding_key``) is never stated, and the run is
    not asked for it."""
    from sugar_source_tree.nodes import undecided_module_binding_key

    stated = []
    for item in _global_inputs(definition):
        name = item.coordinate.name
        keys = global_input_keys(definition.unit, name)
        if len(keys) != 1:
            keys = _keys_on_the_arm_the_run_took(definition.unit, name)
        if len(keys) != 1:
            continue
        if keys[0] == undecided_module_binding_key(definition.unit, name):
            continue
        read = ModuleFinalValue(definition.unit, keys[0]).read()
        if read is None or read.owed_items():
            continue
        value = read.completed_value()
        if value is None:
            continue
        stated.append((item.formal, value.to_term(owner="stated_global_values")))
    return tuple(stated)


def _keys_on_the_arm_the_run_took(unit, name: str) -> tuple:
    """The keys ``name``'s module-final binding reads through on the arm the
    module's one run took, or ``()`` where the run did not decide it.

    The final binding of a name a module ``if``, ``try`` or live loop bound
    on more than one route is a phi over that statement's slot (``IfExp`` on
    a ``BranchResultRef``; a live loop's write slot, ``GuardedBinding``),
    and reads through every arm's key (``global_input_keys``).  Where the
    run decided the slot (``ModuleFinalDecision``: a ground ``if``, a
    concrete loop's exit, a route every completed arm took), the value the
    run left is that arm's, so the phi is read down that arm, slot by slot,
    to the keys it reads through.  A slot the run left undecided -- a
    symbolic module ``if``, whose test the run reads over values a reading
    function's proof does not decide, or arms that decided it differently --
    gives ``()``: no value is stated, and a claim that reads the input is
    decided for every value of it at prove (#8843), never at a value the
    test selects by a flag (#7757)."""
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
        FalseBoolLiteralSugar,
    )
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
        TrueBoolLiteralSugar,
    )
    from sugar_source_tree.binding_state import GuardedBinding, unwrap_binding_state
    from sugar_source_tree.nodes import (
        UNDECIDED_MODULE_BINDING,
        BranchResultRef,
        IfExp,
    )

    state = unit.module_bindings_at(None, frozenset({name})).get(
        name, UNDECIDED_MODULE_BINDING
    )
    if state is UNDECIDED_MODULE_BINDING:
        return ()
    state = unwrap_binding_state(state)
    while True:
        if isinstance(state, IfExp) and isinstance(state.test, BranchResultRef):
            slot_id, when_true, when_false = (
                state.test.slot_id,
                state.body,
                state.orelse,
            )
        elif isinstance(state, GuardedBinding):
            slot_id, when_true, when_false = (
                state.slot.slot_id,
                state.when_true,
                state.when_false,
            )
        else:
            break
        decided = ModuleFinalDecision(unit, slot_id).read()
        if isinstance(decided, TrueBoolLiteralSugar):
            state = unwrap_binding_state(when_true)
        elif isinstance(decided, FalseBoolLiteralSugar):
            state = unwrap_binding_state(when_false)
        else:
            return ()
    evaluations: list = []
    _collect_final_evaluations(state, evaluations, [])
    return tuple(dict.fromkeys(evaluations))


def global_value_at_call(callee, name: str, ctx, *, module_site, call_site):
    """The term a call of ``callee`` (a ``def`` or lambda of this file)
    supplies for its ``global:<name>`` input (``py.global``): the binding of
    ``name`` standing where the call runs, read through the keys it reads
    through (``global_input_keys``) in the caller's ``ctx``.  While the
    module body runs (``module_site``, the module execution site the call is
    reduced under, when it is ``callee``'s module's) that is the binding the
    run made there; called from a function's own contract, the caller's own
    input (``bind_global_inputs``).  Where the keys hold no one value, the
    term is a variable no contract binds (named by the call's ``call_site``),
    so the join's instance is open and the call stays owed: never the
    module-final value where the call may run before it."""
    from sugar_lift_py_tests.ir import make_var
    from sugar_lift_py_tests.occurrence import site_coordinate_cid

    value = global_read_at_call(callee, name, ctx, module_site=module_site)
    if value is not None:
        return value.to_term(owner="global_value_at_call")
    return make_var(f"undecided:global:{name}@{site_coordinate_cid(call_site)}")


def global_read_at_call(callee, name: str, ctx, *, module_site):
    """The one value a call of ``callee`` reads for its ``global:<name>``
    input where the call runs: every key the binding reads through
    (``global_input_keys``) holds a value in the caller's ``ctx``, and all of
    them state one term.  None otherwise.  What ``global_value_at_call``
    states as the input's term, and what the alias rule asks of the call
    with its actuals (``object_identity.actuals_share_an_object``,
    ``lambda_callable.definition_edge_call``): an actual that is, or holds,
    the object the callee reads as the global binds that input's object
    too."""
    from sugar_source_tree.nodes import _site_where_called

    unit = callee.unit
    keys = global_input_keys(unit, name, _site_where_called(unit, module_site))
    values = []
    for key in keys:
        bound = None if ctx is None else ctx.temporal.value_if_bound(key)
        value = None if bound is None else bound_value_read(bound)
        if value is None:
            return None
        values.append(value)
    if not values:
        return None
    terms = [value.to_term(owner="global_value_at_call") for value in values]
    if any(term != terms[0] for term in terms[1:]):
        return None
    return values[0]
