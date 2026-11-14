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
    call (``_off_population_unanswered_call``), and a ``with`` item's resolved
    manager keeps its resolution's faces.
    """
    if sugar.reference_symbol is None or sugar.contract_resolution_gap is not None:
        return None
    if sugar.site is None or _resolved_manager_construction(sugar):
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


def _lexically_unknown_head(site, head: str) -> bool:
    """``head`` is bound nowhere in ``site``'s module, or only by an import.

    A head bound nowhere is known only when its read at ``site`` falls through
    to the builtin namespace (``SourceUnit.builtin_reference_at``, the read's
    binding); the spelling is never asked whether some builtin has it."""
    unit = getattr(site, "unit", None)
    table = getattr(unit, "module_symtable", None)
    if table is None:
        return False
    imported = False

    def visit(scope) -> bool:
        nonlocal imported
        try:
            symbol = scope.lookup(head)
        except KeyError:
            symbol = None
        if symbol is not None:
            if symbol.is_imported():
                imported = True
            elif symbol.is_assigned() or symbol.is_namespace() or symbol.is_parameter():
                return True
        return any(visit(child) for child in scope.get_children())

    if visit(table):
        return False
    return imported or unit.builtin_reference_at(head, site.line_col_span) is None


def _resolved_manager_construction(sugar) -> bool:
    """This call is a ``with`` item's manager, which the manager resolution
    resolved: its construction faces are that resolution's testimony, not an
    unknown callee's."""
    unit = getattr(sugar.site, "unit", None)
    context = getattr(unit, "construction_context", None)
    refs = getattr(context, "source_derived_contract_refs", None)
    if not refs:
        return False
    try:
        span = sugar.site.line_col_span
        coordinate = SourceFragmentCoordinateV1(
            sugar.site.source_cid,
            span.start_line,
            span.start_col,
            span.end_line,
            span.end_col,
        )
    except (AttributeError, TypeError):
        return False
    from sugar_lift_py_tests.context_manager_resolution import (
        ContextManagerResolutionGapV1,
    )

    resolved = refs.get(coordinate)
    return resolved is not None and not isinstance(
        resolved, ContextManagerResolutionGapV1
    )


def _unknown_callee_call(sugar, source_call_frame, callsite):
    """The may-raise testimony for a bodiless call nothing answered.

    Reached once every answer has declined: no source frame (so no body the
    lifter applies) and no builtin law answers the call
    (``_builtin_law_answers``).  Whatever the name is bound to -- nothing, a
    value (``len = 5; len(x)``), a class whose constructor frame was not
    built, any name a star import may rebind (``from m import *; int('x')``),
    or a builtin the lifter does not model (``open``, ``getattr``, ``next``)
    -- what runs was not looked at, so the call is the one unanswered
    citation, two-faced and owed, never a completion (#7757: a raise is never
    a completion; a halt is never dropped).  A ``with`` item's resolved
    manager keeps its resolution's faces."""
    if source_call_frame is not None:
        return None
    if _builtin_law_answers(sugar, callsite):
        return None
    if _resolved_manager_construction(sugar):
        return None
    from sugar_lift_py_tests.source_call_resolution import UnknownCalleeCallV1

    return UnknownCalleeCallV1(sugar.spelled_target)


def _builtin_law_answers(sugar, callsite) -> bool:
    """A law the lifter models answers this bodiless builtin-bound call.

    Each is read from the callee's binding, never its spelling: a builtin
    exception class's construction (``callsite.builtin_exception_class``,
    ``_applied_builtin_exception_class``), ``type(obj)``'s class coordinate
    (``callsite.python_type_coordinate``, ``_applied_builtin_type_of``), or a
    shape CPython documents as never raising over decided operands
    (``builtin_call_total`` on the bound ``LanguageCallee``).  A builtin
    binding with none of these answers nothing: binding a name to the
    builtin namespace is not a law for what that builtin does."""
    if callsite.builtin_exception_class is not None:
        return True
    if callsite.python_type_coordinate is not None:
        return True
    from sugar_lift_py_tests.source_call_resolution import builtin_call_total

    return builtin_call_total(
        sugar.language_callee,
        callsite.arg_values,
        getattr(callsite, "keyword_names", ()) or (),
    )


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
    # Lookup aid: the frame is read OUT of this table by
    # ``source_call_frame_coordinate`` (testified) and reconciled against
    # ``expected_source_call_frame_owner`` (testified); the table itself is
    # never testimony (see ConstructedValueV2's lookup rule).
    source_call_frame_table: Any = dataclass_field(
        default=None, compare=False, metadata={"testimony": "lookup"}
    )
    source_call_frame_coordinate: Any = dataclass_field(default=None, compare=False)
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
        if isinstance(
            self.expected_source_call_frame_owner,
            DefinitionOccurrenceAbsentV1,
        ) and self.source_call_frame_table is not None:
            raise TypeError(
                "CallSiteSugar.expected_source_call_frame_owner cannot claim "
                "absence when source_call_frame_table is present"
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

    def _collect(self, remaining: tuple, accumulated: tuple, ctx: object) -> ExitSet:
        from sugar_lift_py_tests.floor.named_expression_value import (
            consume_operands,
            written_by,
        )

        if remaining:
            head, *rest = remaining
            actual_ctx = _actual_reduce_context(ctx)
            # The actual is an operand: a walrus in it (``f((x := 5))``) binds
            # once, through the one operand door.  The later actuals, the
            # keywords and the call itself (the closure cells it reads among
            # them) are evaluated after it, with its writes applied
            # (``written_by``: ``f((a := 1), a)``).
            return head.desugar(actual_ctx).and_then(
                lambda value: consume_operands(
                    lambda presented: presented.project_operation_receiver_outcome(
                        actual_ctx, owner="CallSiteSugar positional actual"
                    ).and_then(
                        lambda actual: self._collect(
                            tuple(rest),
                            accumulated + (actual,),
                            written_by(value, ctx),
                        )
                    ),
                    value,
                )
            )
        return self._collect_kwargs(self.keywords, (), accumulated, ctx)

    def _collect_kwargs(
        self, remaining: tuple, kw_values: tuple, positional: tuple, ctx: object
    ) -> ExitSet:
        if remaining:
            from sugar_lift_py_tests.floor.named_expression_value import (
                consume_operands,
                written_by,
            )

            (name, sugar), *rest = remaining
            actual_ctx = _actual_reduce_context(ctx)
            # Same order as the positional actuals (``_collect``).
            return sugar.desugar(actual_ctx).and_then(
                lambda value: consume_operands(
                    lambda presented: presented.project_operation_receiver_outcome(
                        actual_ctx, owner="CallSiteSugar keyword actual"
                    ).and_then(
                        lambda actual: self._collect_kwargs(
                            tuple(rest),
                            kw_values + ((name, actual),),
                            positional,
                            written_by(value, ctx),
                        )
                    ),
                    value,
                )
            )
        if ctx is not None:
            from sugar_lift_py_tests.callable_application import CallableApplication
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
            # A name bound to a lambda value (``key(item)`` in a function
            # given ``key=lambda v: ...``) calls that lambda: its own frame,
            # the one binder and the one application.
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
                    and self.source_call_frame_table is None
                    and self.formal_function_sugar is None
                )
            ):
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
        source_call_frame = self.source_call_frame
        if self.source_call_frame_table is not None:
            from sugar_source_tree.panic import SugarNotWritten

            source_call_frame = self.source_call_frame_table.get(
                self.source_call_frame_coordinate
            )
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
            ctx, module_halt = enter_source_frame(
                source_call_frame,
                ctx,
                owner="CallSiteSugar.desugar",
                blame=self.site,
                covered=frozenset(name for name, _cid, _value in captured_values),
            )
            ctx = self._with_captured_values(ctx, source_call_frame, captured_values)
            if module_halt is not None:
                return module_halt
        # The one binder (``object_value.bind_call``): every call form binds
        # its actuals there, and ``_apply_bound`` applies the body.
        body = (
            None
            if source_call_frame is None
            else source_frame_body(
                source_call_frame, owner="CallSiteSugar.desugar", blame=self.site
            )
        )

        def bind(defaults, body):
            return bind_source_frame_call(
                self.target_name,
                positional,
                kw_values,
                frame=source_call_frame,
                ctx=ctx,
                owner="CallSiteSugar.desugar",
                blame=self.site,
                term=term,
                body=body,
                defaults=defaults,
                call_occurrence=self.call_occurrence,
                authenticated_target_symbol=self.import_target_symbol,
                exception_type_coordinate=self.exception_type_coordinate,
                exception_type_mro=self.exception_type_mro,
                builtin_exception_class=self._applied_builtin_exception_class(
                    source_call_frame
                ),
                python_type_coordinate=self._applied_builtin_type_of(
                    source_call_frame, positional, kw_values, term
                ),
                language_callee=self.language_callee,
            )

        from sugar_lift_py_tests.sugar.class_constructor_body_sugar import (
            ClassConstructorBodySugar,
        )

        if isinstance(body, ClassConstructorBodySugar):
            # ``Cls(...)``: the class statement's one outcome is read, and on
            # each completed face the call binds the constructor defaults its
            # class value carries (``bind_class_call``).
            return body.bind_class_call(
                ctx,
                lambda defaults, entered: self._apply_bound(
                    bind(defaults, entered), source_call_frame, ctx
                ),
                site=self.site,
            )
        return self._apply_bound(bind((), body), source_call_frame, ctx)

    def _apply_bound(self, callsite, source_call_frame, ctx):
        """Apply the call ``callsite`` the one binder bound into
        ``source_call_frame`` (None for a frameless call): a generator's
        construction, a pending native operation's discharge, an unanswered
        callee's faces, or the body's application
        (``CallSiteValue.producer_outcome``)."""
        bound_source_actuals = callsite.bound_source_actuals
        if (
            source_call_frame is not None
            and source_call_frame.generator_steps is not None
        ):
            from sugar_lift_py_tests.generator_construction import (
                FormalFloorBindingV1,
                GeneratorConstructionV1,
            )

            # Binder boundary: pair each formal coordinate with the exact
            # Floor actual bind_actuals already produced (object identity).
            # Guard temporal installs these Floors; it never rebuilds from
            # runtime_entries Nodes via sugar()/desugar().
            formal_floor_bindings = tuple(
                FormalFloorBindingV1(coordinate.cid, floor)
                for coordinate, floor in zip(
                    source_call_frame.formal_coordinates,
                    callsite.arg_values,
                    strict=True,
                )
            ) + tuple(
                FormalFloorBindingV1(
                    pair.coordinate.cid,
                    pair.actual,
                    coordinate=pair.coordinate,
                )
                for pair in bound_source_actuals.projected_pairs
            )
            from sugar_lift_py_tests.occurrence import site_coordinate_cid

            return ExitSet.completed(
                GeneratorConstructionV1.allocate(
                    allocation_coordinate=site_coordinate_cid(self.site),
                    frame_coordinate=source_call_frame.frame_cid,
                    binding_state=source_call_frame.runtime_entries,
                    steps=source_call_frame.generator_steps,
                    formal_floor_bindings=formal_floor_bindings,
                    reduction_context=ctx,
                    source_frame=source_call_frame,
                )
            )
        # The body is applied by ``producer_outcome`` alone (#7757): a frame's
        # deferred native operation discharges there against the bound
        # actuals, and a call with no frame applies no body -- the callee's
        # universe (``formal_function_sugar``) is never reduced at the call.
        if callsite.body is None:
            unprojected = _import_bound_unanswered_call(self)
            if unprojected is None:
                unprojected = _off_population_unanswered_call(self)
            if unprojected is not None:
                from sugar_lift_py_tests.source_call_resolution import (
                    cpython_cited_fold,
                )

                folded = cpython_cited_fold(
                    unprojected,
                    callsite.arg_values,
                    getattr(callsite, "keyword_names", ()) or (),
                    site=self.site,
                    language_callee=self.language_callee,
                )
                if folded is not None:
                    return folded
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
                    )
                    if constructed is not None:
                        return constructed
            if unprojected is None:
                unprojected = _unknown_callee_call(self, source_call_frame, callsite)
            if unprojected is not None:
                return unprojected.faces(callsite, self.site)
        return callsite.producer_outcome(ctx)


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
    call runs after import (``with_module_final_globals``, at the site the
    frame's body is read at: ``source_frame_body``), and a module whose
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


def source_frame_body(frame, *, owner: str, blame: object):
    """The body a call into ``frame`` reduces: its declaration's.

    The declaration body keeps formal BindingCoordinateRefs whose cids match
    the frame's formal coordinates, which the call curries with its bound
    FloorValue actuals.  ``Call._construct_sugar`` may have
    ``bind_node_actuals``-specialized the frame body by inlining the caller's
    formal nodes (e.g. make_guard's BindingCoordinateRef into
    Class.__init__); those refs are not this frame's, so the specialized body
    is never the one reduced.  A class call reduces the class statement's
    constructor frame.

    The declaration frame is read again at the module execution site the
    call was constructed at: a body reads a module global as the module
    binds it where the call runs (#7757 item 7).
    """
    from sugar_source_tree.nodes import construct_at_module_execution_site

    module_execution_site = getattr(frame, "module_execution_site", None)
    owner_node = getattr(frame, "owner", None)
    if owner_node is not None and hasattr(
        owner_node, "source_visible_constructor_frame"
    ):
        return construct_at_module_execution_site(
            module_execution_site, owner_node.source_visible_constructor_frame
        ).body
    if owner_node is not None and hasattr(owner_node, "source_visible_call_frame"):
        from sugar_lift_py_tests.source_call_frame import (
            frame_read_at_module_execution_site,
        )

        declaration_frame = frame_read_at_module_execution_site(
            frame, module_execution_site
        )
        if declaration_frame.frame_cid != frame.declaration_frame_cid:
            from sugar_source_tree.panic import BackendDefect

            raise BackendDefect(
                owner=owner,
                blame=blame,
                observed="declaration/source frame mismatch",
                requested="byte-identical authenticated source frame",
                fix="retain the callee declaration frame across node binding",
            )
        return declaration_frame.body
    return frame.body


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
    body=None,
    **testimony,
):
    """``target_name(*positional, **keywords)`` bound by the one binder.

    ``object_value.bind_call`` with what ``frame`` (entered through
    ``enter_source_frame``) says about the callee: its formals, its
    declaration body (``source_frame_body``, or ``body`` where the caller
    already has it: a class call's constructor body entered on its class
    value, ``ClassConstructorBodySugar.bind_class_call``), its coordinates.
    With no frame the call is bound bodyless.  The result is applied by
    ``CallSiteValue.producer_outcome``, as every call is.
    """
    from sugar_lift_py_tests.floor.object_value import bind_call

    if body is None and frame is not None:
        body = source_frame_body(frame, owner=owner, blame=blame)
    return bind_call(
        target_name,
        positional,
        keywords,
        frame=frame,
        parameters=() if frame is None else frame.parameters,
        body=body,
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
    is read (``TemporalContext.value_read``) or a slot selects an arm
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
    decide was refused by name when the body was constructed.  The name is
    never bound.

    Called while the reader's own module body runs, the body reads the
    binding standing at ``site``, whose key that run bound: nothing is
    bound here, and the module run is not asked for.  ``ctx`` comes back
    unchanged when nothing is bound.
    """
    from sugar_source_tree.nodes import (
        module_final_default_keys,
        module_final_global_references,
    )

    finals = []
    slots = []
    for reader in readers:
        evaluations = []
        decisions = []
        for _name, state in sorted(
            module_final_global_references(reader, site).items()
        ):
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
    else None, and the run's refusal raised at this read.  Every read of a
    bound value reads it through ``bound_value_read``: a read of a key
    (``TemporalContext.value_read``) and a scan over every binding (a
    store's alias advance, ``ReceiverFieldStoreValue.extend_scope``) alike,
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


def bound_value_read(value):
    """``value``, held by a binding of a temporal, as a read of it reads it:
    a ``ModuleFinalValue`` asked for here (``ModuleFinalValue.read``: the
    module run demanded, its refusal raised), anything else as it is.

    The one read of a bound value.  A read of a key
    (``TemporalContext.value_read``) and a scan over every binding (a
    store's or a mutation's alias advance, ``ReceiverFieldStoreValue`` /
    ``ReceiverOwnedMutationResult.extend_scope``) both read here, so a
    module-final binding answers one value wherever it is read and
    whatever was read before: a scan that skipped an unasked run and used
    an answered one gave one file two answers by order (#7757, entry 4)."""
    if isinstance(value, ModuleFinalValue):
        return value.read()
    return value


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
    """The value the module run bound ``key`` to, read off ``ends`` (the
    run's completed arms, each holding the context it ended with under its
    own guard and faces, ``ModuleBlockSugar.run``), else None.

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
    from sugar_lift_py_tests.outcome import Completed
    from sugar_lift_py_tests.sugar.if_sugar import _joined_evaluation

    bound = []
    for end in ends:
        value = end.value.temporal.value_if_bound(key)
        if value is not None:
            bound.append(Completed(end.guard, value, end.faces))
    if not bound:
        return None
    return _joined_evaluation(bound)


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
    (``decisions``): an evaluation reference's key, a decorated
    ``def``/``class`` statement's value (``DecoratedDefinitionRef``: the key
    its statement bound the decorators' result under, whose function
    carries the defaults the statement evaluated), a live loop's own key of
    a name it carries (``LoopBindingRef.post_key``, each face of its
    ``LoopProjectedBinding``), each arm of the phi the module block built
    over a module ``if`` or ``try`` route (``IfExp`` on a
    ``BranchResultRef``, whose slot is collected), and each arm of a binding
    joined over a slot (``GuardedBinding``: a live loop's write slot over
    its post-loop key, ``nodes._live_loop_publication``).  An undecorated
    definition, an import's row, an effect slot or an unbound state reads
    no key."""
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
    )

    state = unwrap_binding_state(state)
    if isinstance(state, EvaluationRef):
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
