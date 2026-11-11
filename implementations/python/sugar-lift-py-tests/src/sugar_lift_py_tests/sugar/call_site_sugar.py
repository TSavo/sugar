from __future__ import annotations

import builtins
from dataclasses import dataclass, field as dataclass_field
from enum import Enum
from typing import TYPE_CHECKING, Any, TypeAlias

from sugar_lift_py_tests.context_manager_resolution import SourceFragmentCoordinateV1

from sugar_lift_py_tests.outcome import Complete, Outcome
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



def _language_owned_call_floor(sugar):
    """Return the Cut 2 floor hung on this named call, if any."""
    unit = getattr(sugar.site, "unit", None)
    context = getattr(unit, "construction_context", None) if unit is not None else None
    floors = getattr(context, "language_owned_call_floors", None) if context is not None else None
    if not floors:
        return None
    named = floors.get(sugar.target_name)
    if named is not None:
        return named
    try:
        span = sugar.site.line_col_span
        key = (
            "call-site",
            sugar.site.source_cid,
            span.start_line,
            span.start_col,
            span.end_line,
            span.end_col,
        )
    except (AttributeError, TypeError):
        return None
    return floors.get(key)


def _unprojected_source_call(sugar):
    """Return the may-raise testimony seated at this exact call, if any."""
    unit = getattr(sugar.site, "unit", None)
    context = getattr(unit, "construction_context", None) if unit is not None else None
    calls = getattr(context, "unprojected_source_calls", None) if context is not None else None
    if not calls:
        return None
    try:
        span = sugar.site.line_col_span
        key = (
            "call-site",
            sugar.site.source_cid,
            span.start_line,
            span.start_col,
            span.end_line,
            span.end_col,
        )
    except (AttributeError, TypeError):
        return None
    return calls.get(key)


_OFF_POPULATION = "call-target-off-population:"


def _off_population_source_call(sugar):
    """The may-raise testimony for a call cited off the enrolled population."""
    gap = sugar.contract_resolution_gap
    if not isinstance(gap, str) or not gap.startswith(_OFF_POPULATION):
        return None
    if _language_owned_call_floor(sugar) is not None:
        return None
    from sugar_lift_py_tests.source_call_resolution import OffPopulationSourceCallV1

    return OffPopulationSourceCallV1(gap[len(_OFF_POPULATION) :])


def _lexically_unknown_callee(sugar) -> bool:
    """The callee's head name is bound nowhere in its module, or only by an
    import (a module member the import door did not cite).  A name a ``def``,
    ``class`` or assignment in the module binds is source the lift holds, not
    an unknown callee."""
    return _lexically_unknown_head(sugar.site, sugar.target_name.split(".", 1)[0])


def _lexically_unknown_head(site, head: str) -> bool:
    """``head`` is bound nowhere in ``site``'s module, or only by an import."""
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
    return imported or not hasattr(builtins, head)


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


def _unknown_callee_call(sugar, ctx):
    """The may-raise testimony for a call whose callee nothing resolved.

    The callee name has no binding in this reduction's scope (an undefined
    name, or a dotted module member the import door did not cite), and no
    contract, gap, language-owned floor or source frame speaks for it."""
    if sugar.contract_resolution_gap is not None or sugar.contract_ref is not None:
        return None
    if sugar.site is None or sugar.formal_function_sugar is not None:
        return None
    temporal = getattr(ctx, "temporal", None)
    if temporal is None or temporal.value_if_bound(sugar.target_name) is not None:
        return None
    if _language_owned_call_floor(sugar) is not None:
        return None
    if not _lexically_unknown_callee(sugar):
        return None
    if _resolved_manager_construction(sugar):
        return None
    from sugar_lift_py_tests.source_call_resolution import UnknownCalleeCallV1

    return UnknownCalleeCallV1(sugar.target_name)


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
    contract_ref: Any = dataclass_field(default=None, compare=False)
    contract_resolution_gap: str | None = dataclass_field(default=None, compare=False)
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
        if self.contract_ref is None:
            contract_authority = ctor("python:no-resolved-call-contract", ())
        else:
            from sugar_lift_py_tests.call_contract_resolution import (
                ResolvedCallContractRefV1,
            )

            if not isinstance(self.contract_ref, ResolvedCallContractRefV1):
                raise TypeError(
                    f"{owner} requires authenticated ResolvedCallContractRefV1, "
                    f"got {type(self.contract_ref).__name__}"
                )
            contract_authority = ctor(
                "python:resolved-call-contract",
                (
                    str_const(self.contract_ref.resolution_cid),
                    str_const(self.contract_ref.contract_cid),
                ),
                symbol_kind="coordinate",
            )
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

    def desugar(self, ctx: object = None) -> Outcome:
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
            if free_names and not getattr(
                self.source_call_frame, "captured_binding_coordinates", ()
            ):
                raise SugarNotWritten(
                    owner="CallSiteSugar.desugar",
                    blame=self.site,
                    observed=(
                        "closure bindings lack producer coordinates: " f"{free_names!r}"
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
            if _language_owned_call_floor(self) is not None:
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

    def _applied_builtin_exception_class(self, ctx, source_call_frame):
        """The builtin exception class this call applies, by its bound value.

        Read from the callee's temporal binding, never its spelling: a user
        class or rebinding named ``ValueError`` is not a builtin exception.
        """
        if ctx is None or source_call_frame is not None or self.contract_ref is not None:
            return None
        from sugar_lift_py_tests.floor import BuiltinExceptionClassValue

        temporal = getattr(ctx, "temporal", None)
        if temporal is None:
            return None
        receiver = temporal.value_if_bound(self.target_name)
        if not isinstance(receiver, BuiltinExceptionClassValue):
            return None
        # The reduce scope's builtin seat is necessary, not sufficient: the
        # unit's lexical exception-type authority must agree that the exact
        # callee occurrence reaches the builtin class, so a same-spelled
        # module or enclosing class never borrows builtin semantics.
        from sugar_source_tree.nodes import Name

        node = getattr(self.site, "node", None)
        callee = getattr(node, "func", None)
        unit = getattr(self.site, "unit", None)
        if (
            not isinstance(callee, Name)
            or callee.id != self.target_name
            or getattr(unit, "typed_module", None) is None
        ):
            # No typed Module bound: no lexical authority, so no decision.
            return None
        lexical = unit.exception_type_identity(callee)
        if lexical is None or lexical != receiver.exception_type_identity():
            return None
        return receiver

    def _collect(self, remaining: tuple, accumulated: tuple, ctx: object) -> Outcome:
        if remaining:
            head, *rest = remaining
            actual_ctx = _actual_reduce_context(ctx)
            return head.desugar(actual_ctx).and_then(
                lambda value: value.project_operation_receiver_outcome(
                    actual_ctx, owner="CallSiteSugar positional actual"
                ).and_then(
                    lambda actual: self._collect(
                        tuple(rest), accumulated + (actual,), ctx
                    )
                )
            )
        return self._collect_kwargs(self.keywords, (), accumulated, ctx)

    def _collect_kwargs(
        self, remaining: tuple, kw_values: tuple, positional: tuple, ctx: object
    ) -> Outcome:
        if remaining:
            (name, sugar), *rest = remaining
            actual_ctx = _actual_reduce_context(ctx)
            return sugar.desugar(actual_ctx).and_then(
                lambda value: value.project_operation_receiver_outcome(
                    actual_ctx, owner="CallSiteSugar keyword actual"
                ).and_then(
                    lambda actual: self._collect_kwargs(
                        tuple(rest),
                        kw_values + ((name, actual),),
                        positional,
                        ctx,
                    )
                )
            )
        if ctx is not None:
            from sugar_lift_py_tests.callable_application import CallableApplication
            from sugar_lift_py_tests.floor import (
                BuiltinSemanticCallable,
                ClassDefinitionValue,
            )

            receiver = ctx.temporal.value_if_bound(self.target_name)
            if isinstance(receiver, BuiltinSemanticCallable) or (
                isinstance(receiver, ClassDefinitionValue)
                and self.source_call_frame is None
                and not positional
                and not kw_values
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
            floored = _language_owned_call_floor(self)
            if floored is not None:
                return floored.callable_application_with(
                    CallableApplication(
                        positional + tuple(value for _, value in kw_values),
                        tuple(name for name, _ in kw_values),
                        self.site,
                        call_occurrence=self.call_occurrence,
                    ),
                    ctx,
                )
        from sugar_lift_py_tests.floor import CallSiteValue
        from sugar_lift_py_tests.ir import ctor, str_const

        owner = str(self.site)
        kwarg_terms = [
            ctor("py.kwarg", [str_const(name), value.to_term(owner=owner)])
            for name, value in kw_values
        ]
        term = ctor(
            f"call:{self.target_name}",
            [value.to_term(owner=owner) for value in positional] + kwarg_terms,
            symbol_kind=(
                "builtin" if hasattr(builtins, self.target_name) else "coordinate"
            ),
        )
        if self.contract_ref is not None:
            return self._collect_bridged(positional)
        source_body = None
        source_frame_cid = None
        native_operation_actuals = None
        bound_source_actuals = None
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
            from sugar_source_tree.nodes import (
                AsyncFunctionDef as SourceAsyncFunctionDef,
                FunctionDef as SourceFunctionDef,
            )

            closure_owner = source_call_frame.owner
            if (
                isinstance(closure_owner, (SourceFunctionDef, SourceAsyncFunctionDef))
                and closure_owner.lacks_captured_binding_testimony()
            ):
                from sugar_source_tree.panic import SugarNotWritten

                raise SugarNotWritten(
                    owner="CallSiteSugar.desugar",
                    blame=self.site,
                    observed="free or nonlocal source binding has no captured coordinate testimony",
                    requested="producer-owned captured binding coordinates for every closure read",
                    fix="construct closure bindings at the lexical frame boundary or keep loud",
                )
        if source_call_frame is not None:
            from sugar_lift_py_tests.source_call_frame import SourceVisibleCallFrameV1
            from sugar_source_tree.panic import SugarNotWritten

            if not isinstance(source_call_frame, SourceVisibleCallFrameV1):
                raise SugarNotWritten(
                    owner="CallSiteSugar.desugar",
                    blame=self.site,
                    observed=type(source_call_frame).__name__,
                    requested="a closed SourceCallFrameV1 variant",
                    fix="construct a typed source frame or keep the call loud",
                )
            ctx = _with_frame_mutable_globals(ctx, source_call_frame)
            from sugar_lift_py_tests.source_call_frame import SourceCallBindingGap

            try:
                if source_call_frame.pending_native_operation is None:
                    bound_source_actuals = source_call_frame.bind_actuals(
                        positional, kw_values, ctx
                    )
                    positional = bound_source_actuals.actuals
                else:
                    native_operation_actuals = (
                        source_call_frame.bind_native_operation_actuals(
                            positional, kw_values, ctx
                        )
                    )
                    bound_source_actuals = native_operation_actuals.source_actuals
                    positional = native_operation_actuals.actuals
            except SourceCallBindingGap as exc:
                raise SugarNotWritten(
                    owner="CallSiteSugar.desugar",
                    blame=self.site,
                    observed=str(exc),
                    requested="actuals matching the authenticated source signature",
                    fix="supply a real actual/default/variadic occurrence or keep loud",
                ) from exc
            # Declaration body keeps formal BindingCoordinateRefs whose cids
            # match formal_coordinate_cids. Call._construct_sugar may have
            # bind_node_actuals-specialized the frame body by inlining outer
            # formal nodes (e.g. make_guard's BindingCoordinateRef into
            # Class.__init__). force_floor curries THIS frame's formal cids
            # with FloorValue actuals; mismatched outer formal refs stay
            # unspecialized and abort source-derived manager construction.
            source_body = source_call_frame.body
            owner = getattr(source_call_frame, "owner", None)
            if owner is not None and hasattr(owner, "source_visible_constructor_frame"):
                source_body = owner.source_visible_constructor_frame().body
            elif owner is not None and hasattr(owner, "source_visible_call_frame"):
                # Imported helper calls are node-specialized when the caller's
                # Sugar is built. Their FloorValue actuals are curried below,
                # so reduction must use the callee's declaration body whose
                # BindingCoordinateRefs match this frame's formal coordinates,
                # not the caller's inlined formal nodes.
                declaration_frame = owner.source_visible_call_frame()
                if (
                    declaration_frame.frame_cid
                    != source_call_frame.declaration_frame_cid
                ):
                    from sugar_source_tree.panic import BackendDefect

                    raise BackendDefect(
                        owner="CallSiteSugar.desugar",
                        blame=self.site,
                        observed="declaration/source frame mismatch",
                        requested="byte-identical authenticated source frame",
                        fix="retain the callee declaration frame across node binding",
                    )
                source_body = declaration_frame.body
            source_frame_cid = source_call_frame.frame_cid
            # bind_actuals returned the complete formal-ordered tuple,
            # including keyword/default actuals. They must not be appended a
            # second time below.
            kw_values = ()
            if source_call_frame.generator_steps is not None:
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
                        positional,
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
                return Complete(
                    GeneratorConstructionV1.allocate(
                        allocation_coordinate=str(self.site),
                        frame_coordinate=source_call_frame.frame_cid,
                        binding_state=source_call_frame.runtime_entries,
                        steps=source_call_frame.generator_steps,
                        formal_floor_bindings=formal_floor_bindings,
                        reduction_context=ctx,
                        source_frame=source_call_frame,
                    )
                )
        callsite = CallSiteValue(
            target_name=self.target_name,
            arg_values=positional + tuple(value for _, value in kw_values),
            parameters=(
                source_call_frame.parameters if source_call_frame is not None else ()
            ),
            term=term,
            body=source_body,
            keyword_names=tuple(name for name, _ in kw_values),
            site=self.site,
            call_occurrence=self.call_occurrence,
            exception_type_coordinate=self.exception_type_coordinate,
            exception_type_mro=self.exception_type_mro,
            source_call_frame_cid=source_frame_cid,
            formal_coordinate_cids=(
                tuple(item.cid for item in source_call_frame.formal_coordinates)
                if source_call_frame is not None
                else ()
            ),
            bound_native_actuals_by_coordinate=(
                native_operation_actuals.by_formal_coordinate
                if native_operation_actuals is not None
                else (
                    bound_source_actuals.by_native_formal_coordinate
                    if bound_source_actuals is not None
                    and bound_source_actuals.native_formal_coordinates
                    else None
                )
            ),
            bound_native_source_actuals=(
                None
                if native_operation_actuals is None
                else native_operation_actuals.source_actuals
            ),
            bound_source_actuals=bound_source_actuals,
            builtin_exception_class=self._applied_builtin_exception_class(
                ctx, source_call_frame
            ),
        )
        if native_operation_actuals is not None:
            pending = source_call_frame.pending_native_operation.discharge(
                native_operation_actuals.by_formal_coordinate
            )
            return callsite.project_producer_outcome(
                pending,
                carrier_actuals=callsite.bound_native_actuals_by_coordinate,
            )
        if self.formal_function_sugar is not None and self.source_call_frame is None:
            pending = self.formal_function_sugar.desugar(ctx)
            from sugar_lift_py_tests.caller_parameter_contract import (
                NativeOperationExitCarrierV1,
            )

            if isinstance(pending, NativeOperationExitCarrierV1):
                actuals = (
                    None
                    if native_operation_actuals is None
                    else native_operation_actuals.by_formal_coordinate
                )
                if actuals is None and bound_source_actuals is not None:
                    actuals = bound_source_actuals.by_native_formal_coordinate
                if actuals is not None:
                    pending = pending.discharge(actuals)
            return callsite.project_producer_outcome(
                pending,
                carrier_actuals=callsite.bound_native_actuals_by_coordinate,
            )
        from sugar_lift_py_tests.context.reduce_context import ReduceContext
        from sugar_source_tree.panic import SugarNotWritten

        if (
            ctx is not None
            and not isinstance(ctx, ReduceContext)
            and callsite.body is not None
        ):
            raise SugarNotWritten(
                owner="CallSiteSugar.desugar",
                blame=self.site,
                observed="source-visible call under a temporal-only reduction context",
                requested="a ReduceContext that can record the call",
                fix=(
                    "keep the call loud until allocate carries a reduction "
                    "context; do not invent the callee body"
                ),
            )
        if callsite.body is None:
            unprojected = _unprojected_source_call(self)
            if unprojected is None:
                unprojected = _off_population_source_call(self)
            if unprojected is not None:
                from sugar_lift_py_tests.source_call_resolution import (
                    cpython_cited_fold,
                )

                folded = cpython_cited_fold(
                    unprojected,
                    callsite.arg_values,
                    getattr(callsite, "keyword_names", ()) or (),
                )
                if folded is not None:
                    return folded
            if unprojected is None and self.contract_resolution_gap is None:
                from sugar_lift_py_tests.source_call_resolution import (
                    builtin_dunder_call,
                )

                unprojected = builtin_dunder_call(
                    self.target_name,
                    callsite.arg_values,
                    ctx,
                    getattr(callsite, "keyword_names", ()) or (),
                )
                if unprojected is None:
                    from sugar_lift_py_tests.source_call_resolution import (
                        builtin_list_construct,
                    )

                    constructed = builtin_list_construct(
                        self.target_name,
                        callsite.arg_values,
                        ctx,
                        getattr(callsite, "keyword_names", ()) or (),
                    )
                    if constructed is not None:
                        return constructed
            if unprojected is None:
                unprojected = _unknown_callee_call(self, ctx)
            if unprojected is not None:
                return unprojected.faces(callsite, self.site)
        produced = callsite.producer_outcome(
            ctx,
            carrier_actuals=callsite.bound_native_actuals_by_coordinate,
        )
        return produced

    def _collect_bridged(self, positional: tuple) -> Outcome:
        from sugar_lift_py_tests.floor.bridged_contract_value import (
            BridgedContractValue,
        )
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
        from sugar_lift_py_tests.ir import _Ctor, _free_vars_in_term, subst_var_in_term
        from sugar_lift_py_tests.outcome import Complete
        from sugar_source_tree.panic import SugarNotWritten

        reference = self.contract_ref
        if len(reference.formals) != len(positional):
            raise SugarNotWritten(
                owner="CallSiteSugar.desugar",
                blame=self.site,
                observed="signature mismatch",
                requested="actual arguments matching the authenticated import signature",
                fix="correct the call signature or keep the call loud",
            )
        term = reference.return_term
        if term is None:
            raise SugarNotWritten(
                owner="CallSiteSugar.desugar",
                blame=self.site,
                observed="authenticated contract has no exact return equality",
                requested="exact structural return testimony",
                fix="strengthen the contract or keep the imported value loud",
            )
        if not _free_vars_in_term(term) <= set(reference.formals):
            raise SugarNotWritten(
                owner="CallSiteSugar.desugar",
                blame=self.site,
                observed="authenticated structural return contains an unbound projection",
                requested="return variables authenticated by the target formal list",
                fix="reject the stale or lying contract reference",
            )
        for formal, actual in zip(reference.formals, positional):
            term = subst_var_in_term(term, formal, actual.to_term(owner=str(self.site)))
        if not isinstance(term, _Ctor) or term.name not in {
            "tuple",
            "python:tuple",
            "python:list",
        }:
            raise SugarNotWritten(
                owner="CallSiteSugar.desugar",
                blame=self.site,
                observed="authenticated contract has no exact structural return",
                requested="structural return term carried by the target contract",
                fix="strengthen the target contract or keep the imported value loud",
            )
        callsite = CallSiteValue(
            target_name=self.target_name,
            arg_values=positional,
            parameters=reference.formals,
            term=term,
            body=None,
            site=self.site,
            target_contract_cid=reference.contract_cid,
            authenticated_target_symbol=reference.bridge_source_symbol,
        )
        return Complete(
            BridgedContractValue(
                term, reference.contract_cid, reference.member_cid, callsite
            )
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


def _with_frame_mutable_globals(ctx, frame):
    bindings = frame.mutable_global_bindings
    decorated_bindings = getattr(frame, "decorated_class_bindings", ())
    immutable_bindings = getattr(frame, "immutable_global_bindings", ())
    if not bindings and not decorated_bindings and not immutable_bindings:
        return ctx
    from dataclasses import replace

    from sugar_lift_py_tests.context import ReduceContext
    from sugar_lift_py_tests.floor.mutable_global_value import MutableGlobalValue
    from sugar_lift_py_tests.temporal import TemporalContext

    if ctx is None:
        ctx = ReduceContext.root(owner="CallSiteSugar mutable module globals")
    module_temporal = ctx.module_temporal or TemporalContext.empty()
    temporal = ctx.temporal
    for binding in bindings:
        value = MutableGlobalValue(
            name=binding.name,
            kind=binding.kind,
            pin_source_cid=binding.source_cid,
            binding_memento=binding.binding_occurrence,
        )
        module_temporal = module_temporal.bind_value(binding.name, value)
        temporal = temporal.bind_value(binding.name, value)
    for binding in decorated_bindings:
        module_temporal = module_temporal.bind_value(binding.name, binding.value)
        temporal = temporal.bind_value(binding.name, binding.value)
    for binding in immutable_bindings:
        module_temporal = module_temporal.bind_value(binding.name, binding.value)
        temporal = temporal.bind_value(binding.name, binding.value)
    return replace(ctx, temporal=temporal, module_temporal=module_temporal)
