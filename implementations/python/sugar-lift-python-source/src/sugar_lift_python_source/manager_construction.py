"""Authenticated dependency module prefixes, import receipts and call seats.

An imported call is a coordinate plus an edge: no route here reads an
imported callee's body.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from sugar_lift_py_tests.call_symbol import call_symbol
from sugar_lift_py_tests.context_manager_resolution import (
    OpaqueSourceCallObligationV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.floor import (
    BlockValue,
    CallSiteValue,
    FloorValue,
    GuardedReturn,
    ObjectValue,
    ReceiverStatePartitionValue,
    ReturnValue,
)
from sugar_lift_py_tests.ir import _term_content_cid
from sugar_source_tree.binding_state import BindingEntryV1
from sugar_source_tree.nodes import (
    Assign,
    AsyncFunctionDef,
    Call,
    ClassDef,
    FunctionDef,
    Name,
    Node,
)
from sugar_source_tree.tree import SourceFile

from .canonical import cid_of_json
from .dependency_artifact import (
    DependencyArtifactGraph,
    ResolvedPythonObjectV1,
    resolve_import_binding,
)
from .resolution_session import (
    SourceResolutionSession,
    session_or_new,
)


class ImportValueUseSeatingGap(ValueError):
    """Authenticated value-use testimony cannot be seated on this SourceUnit."""

    def __init__(self, kind: str, detail: str) -> None:
        self.kind = kind
        super().__init__(f"{kind}: {detail}")


def _bind_dependency_graphs(
    session: SourceResolutionSession,
    dependency_graphs: dict[str, DependencyArtifactGraph] | None,
) -> dict[str, DependencyArtifactGraph]:
    """Local graph map seeded from the session so auth tops are asked once.

    Frame projection used to mint ``dependency_graphs={}`` per definition,
    re-entering ``authenticate_dependency_top_level`` for the same warnings/re/
    inspect tops (21× each on one test_pandas open). Session owns the map;
    local overlays seed from it and write through on first auth. Walk-scoped
    sessions (#7081) extend the once-ask across multi-file open/enumerate.
    """
    if dependency_graphs is None:
        if session.enabled:
            return session.dependency_graphs
        return {}
    if session.enabled:
        for top, graph in session.dependency_graphs.items():
            dependency_graphs.setdefault(top, graph)
    return dependency_graphs


def _dependency_graph_for_top(
    top_level: str,
    *,
    session: SourceResolutionSession,
    dependency_graphs: dict[str, DependencyArtifactGraph],
    distribution_index=None,
) -> DependencyArtifactGraph:
    """Authenticate ``top_level`` once per session (and local map)."""
    hit = dependency_graphs.get(top_level)
    if hit is not None:
        return hit
    if session.enabled:
        hit = session.dependency_graphs.get(top_level)
        if hit is not None:
            dependency_graphs[top_level] = hit
            return hit
    from .dependency_artifact import authenticate_dependency_top_level

    graph = authenticate_dependency_top_level(
        top_level, distribution_index=distribution_index
    )
    dependency_graphs[top_level] = graph
    if session.enabled:
        session.dependency_graphs[top_level] = graph
    return graph


def _project_metaclass_final_class(value: FloorValue, *, blame) -> FloorValue:
    """Select the sole authenticated returned class for module publication."""
    from sugar_lift_py_tests.floor.source_return_projection import (
        project_authenticated_source_return,
    )
    from sugar_source_tree.panic import SugarNotWritten

    final_class = project_authenticated_source_return(value)
    if isinstance(final_class, BlockValue) or not isinstance(final_class, FloorValue):

        def describe(statement):
            if isinstance(statement, (ReturnValue, GuardedReturn)):
                guards = getattr(statement, "guards", ())
                return (
                    f"{type(statement).__name__}<{type(statement.value).__name__}>"
                    f"[guards={len(guards)}]"
                )
            if isinstance(statement, CallSiteValue):
                occurrence = getattr(statement, "call_occurrence", None)
                occurrence_kind = (
                    type(occurrence).__name__ if occurrence is not None else "None"
                )
                return (
                    f"CallSiteValue<target={statement.target_name!r};"
                    f"body={type(statement.body).__name__};"
                    f"occurrence={occurrence_kind};"
                    f"sourceFrame={statement.source_call_frame_cid!r};"
                    "retainedCompletion="
                    f"{statement._retained_source_completion is not None}>"
                )
            if type(statement).__name__ == "BranchResultAuthentication":
                slot = getattr(statement, "slot", None)
                return (
                    "BranchResultAuthentication<slot="
                    f"{getattr(slot, 'slot_id', None)!r};"
                    f"observed={getattr(statement, 'observed_guard', None)!r}>"
                )
            return type(statement).__name__

        shape = (
            (
                "BlockValue["
                + ",".join(describe(statement) for statement in final_class.statements)
                + "]"
                + f"; canFallThrough={final_class.can_fall_through}"
                + f"; fallThroughGuards={len(final_class.fall_through)}"
            )
            if isinstance(final_class, BlockValue)
            else type(final_class).__name__
        )
        raise SugarNotWritten(
            owner="module definition execution",
            blame=blame,
            observed=(
                "metaclass application has no unique authenticated returned class Floor; "
                f"shape={shape}"
            ),
            requested="one non-block returned class Floor",
            fix=(
                "preserve multi-return, guarded, fall-through, raise, and halted "
                "metaclass bodies as typed loud"
            ),
        )
    return final_class


@dataclass(frozen=True)
class _ModuleSourceFrameCallableV1(FloorValue):
    """Exact module FunctionDef callable used during definition execution."""

    callable_name: str
    frame: object
    defining_class: object | None = None

    def to_term(self, *, owner):
        del owner
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:module-source-frame-callable",
            [str_const(self.frame.frame_cid)],
            symbol_kind="coordinate",
        )

    def callable_application_with(self, operation, ctx):
        from sugar_lift_py_tests.floor import CallSiteValue
        from sugar_lift_py_tests.ir import ctor
        from sugar_source_tree.panic import SugarNotWritten

        if operation.keyword_names:
            raise SugarNotWritten(
                owner="module definition source callable",
                blame=operation.site,
                observed="keyword decorator application lacks value pairing",
                requested="ordered authenticated keyword actuals",
                fix="carry keyword values with their formal names",
            )
        bound = self.frame.bind_actuals(operation.arguments, (), ctx)
        call = CallSiteValue(
            self.callable_name,
            bound.actuals,
            self.frame.parameters,
            ctor(
                call_symbol("module-source-frame"),
                [
                    self.to_term(owner=self.callable_name),
                    *(item.to_term(owner=self.callable_name) for item in bound.actuals),
                ],
            ),
            self.frame.body,
            site=operation.site,
            source_call_frame_cid=self.frame.frame_cid,
            formal_coordinate_cids=tuple(
                coordinate.cid for coordinate in self.frame.formal_coordinates
            ),
            bound_source_actuals=bound,
        )
        call_ctx = ctx
        if self.defining_class is not None:
            call_ctx = ctx.with_temporal(
                ctx.temporal.bind_value(
                    "__class__",
                    self.defining_class,
                    blame=f"{self.callable_name} defining class",
                )
            )
        produced = call.producer_outcome(call_ctx)
        # Projection is a continuation over the producer ExitSet.  Completed
        # faces project their retained source return; halted faces remain owned
        # by the source call with their guards and effects unchanged.  Requiring
        # ``Complete`` here used to discard Python's authenticated nonlinear
        # control at the exact metaclass publication boundary.
        return produced.and_then(
            lambda value: value.project_operation_receiver_outcome(
                ctx, owner="module definition source callable"
            )
        )


@dataclass(frozen=True)
class _ModuleFunctionDefinitionCallableV1(FloorValue):
    """An exact module function definition constructed only when called."""

    definition: FunctionDef | AsyncFunctionDef

    def to_term(self, *, owner):
        del owner
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:module-function-definition-callable",
            [str_const(self.definition.fragment.seal().cid)],
            symbol_kind="coordinate",
        )

    def callable_application_with(self, operation, ctx):
        from sugar_source_tree.panic import SugarNotWritten

        if isinstance(self.definition, AsyncFunctionDef):
            raise SugarNotWritten(
                owner="module function definition application",
                blame=operation.site,
                observed="AsyncFunctionDef reached the synchronous module callable floor",
                requested="an authenticated coroutine-construction Floor",
                fix="publish and consume a dedicated async callable owner before application",
            )
        return _ModuleSourceFrameCallableV1(
            self.definition.name,
            self.definition.source_visible_call_frame(),
        ).callable_application_with(operation, ctx)


@dataclass(frozen=True)
class _ModuleFunctionDefinitionBindingSugar:
    definition: FunctionDef | AsyncFunctionDef

    def desugar(self, ctx=None):
        from sugar_lift_py_tests.floor.scope_rebind import ScopeRebind
        from sugar_lift_py_tests.outcome import Complete
        from sugar_source_tree.panic import SugarNotWritten

        if self.definition.decorators:
            definition_kind = type(self.definition).__name__
            raise SugarNotWritten(
                owner="module function definition execution",
                blame=self.definition.fragment,
                observed=f"decorated {definition_kind} has no completed publication",
                requested="the exact final decorated function Floor",
                fix="execute and authenticate the function decorator chain",
            )
        return Complete(
            ScopeRebind(
                self.definition.name,
                _ModuleFunctionDefinitionCallableV1(self.definition),
            )
        )


@dataclass(frozen=True)
class _ModuleNameAssignmentBindingSugar:
    """Execute one exact module chained-name assignment into temporal state.

    Python evaluates the RHS once, then binds that same object to every target.
    Keeping the targets together here preserves both laws; expanding the source
    into independent assignments would evaluate the RHS more than once.
    """

    statement: Assign
    targets: tuple[Name, ...]

    def desugar(self, ctx=None):
        from sugar_lift_py_tests.floor import (
            CallSiteValue,
            ComprehensionValue,
            ListValue,
        )
        from sugar_lift_py_tests.floor.scope_rebind import ScopeRebinds
        from sugar_lift_py_tests.ir import _Ctor
        from sugar_lift_py_tests.outcome import Complete

        def bind_projected_value(value):
            if (
                type(value) is ComprehensionValue
                and type(value.term) is _Ctor
                and value.term.name == "py.listcomp"
                and value.finite_elements is not None
            ):
                value = ListValue(tuple(value.finite_elements))
            return Complete(
                ScopeRebinds(tuple((target.id, value) for target in self.targets))
            )

        def bind_completed_value(value):
            if type(value) is CallSiteValue:
                return value.project_operation_receiver_outcome(
                    ctx,
                    owner="module name assignment source return",
                ).and_then(bind_projected_value)
            return bind_projected_value(value)

        return self.statement.value.sugar().desugar(ctx).and_then(bind_completed_value)


@dataclass(frozen=True)
class _ModuleSubscriptDeleteBindingSugar:
    """Thread one exact module ``del name[index]`` result into its binding."""

    statement: Delete
    target: Name

    def desugar(self, ctx=None):
        from sugar_lift_py_tests.floor.scope_rebind import ScopeRebind
        from sugar_lift_py_tests.outcome import Complete

        return (
            self.statement.sugar()
            .desugar(ctx)
            .and_then(lambda value: Complete(ScopeRebind(self.target.id, value)))
        )


@dataclass(frozen=True)
class _ModuleClassDefinitionBindingSugar:
    """Execute one module ClassDef and bind its exact constructed Floor.

    This is deliberately a producer-owned wrapper rather than a Name-based
    reconstruction in the prefix consumer.  Decorated definitions require the
    separate publication chain and remain loud here until that chain supplies
    the final class Floor.
    """

    definition: ClassDef
    module_construction_receipt_cid: str

    def desugar(self, ctx=None):
        from sugar_lift_py_tests.floor import ClassDefinitionValue
        from sugar_lift_py_tests.callable_application import CallableApplication
        from sugar_lift_py_tests.floor.decorated_class_value import (
            DecoratedClassPublicationV1,
            DecoratedClassValue,
            DecoratorApplicationPublicationV1,
            MetaclassClassValue,
            _mint_metaclass_class_publication,
        )
        from sugar_lift_py_tests.floor import DictValue, StringValue, TupleValue
        from sugar_lift_py_tests.floor.scope_rebind import ScopeRebind
        from sugar_lift_py_tests.outcome import Complete
        from sugar_source_tree.panic import SugarNotWritten

        unsupported_keywords = tuple(
            keyword
            for keyword in self.definition.keywords
            if keyword.arg != "metaclass"
        )
        if unsupported_keywords:
            keyword = unsupported_keywords[0]
            label = keyword.arg if keyword.arg is not None else "**"
            raise SugarNotWritten(
                owner="module definition execution",
                blame=keyword.value.fragment,
                observed=f"unsupported class creation keyword {label}",
                requested="one transported class creation keyword roster",
                fix=(
                    "transport the exact parser-owned class keyword through "
                    "the metaclass call or keep publication loud"
                ),
            )
        sugar = self.definition.sugar()
        outcome = sugar.desugar(ctx)

        def bind(value):
            if type(value) is not ClassDefinitionValue:
                raise SugarNotWritten(
                    owner="module definition execution",
                    blame=self.definition.fragment,
                    observed=f"ClassDef constructed {type(value).__name__}",
                    requested="one exact ClassDefinitionValue",
                    fix="keep nonlinear or substituted class construction loud",
                )
            metaclass_keywords = tuple(
                keyword
                for keyword in self.definition.keywords
                if keyword.arg == "metaclass"
            )
            if len(metaclass_keywords) > 1:
                raise SugarNotWritten(
                    owner="module definition execution",
                    blame=self.definition.fragment,
                    observed="multiple metaclass keyword occurrences",
                    requested="one exact metaclass application",
                    fix="preserve the parser-owned class keyword roster",
                )
            if metaclass_keywords:
                if sugar.decorator_sugars:
                    raise SugarNotWritten(
                        owner="module definition execution",
                        blame=self.definition.fragment,
                        observed="combined metaclass and decorator publication",
                        requested="one ordered metaclass-then-decorator publication",
                        fix="compose both authenticated application products",
                    )
                keyword = metaclass_keywords[0]
                metaclass_outcome = keyword.value.sugar().desugar(ctx)
                if (
                    not isinstance(metaclass_outcome, Complete)
                    or type(metaclass_outcome.value) is not ClassDefinitionValue
                ):
                    raise SugarNotWritten(
                        owner="module definition execution",
                        blame=keyword.value.fragment,
                        observed="metaclass expression did not construct a source class",
                        requested="one exact ClassDefinitionValue metaclass",
                        fix="retain the metaclass binding and source definition",
                    )
                metaclass_floor = metaclass_outcome.value
                constructors = tuple(
                    method
                    for method in metaclass_floor.methods
                    if method.name == "__new__"
                )
                if len(constructors) != 1:
                    raise SugarNotWritten(
                        owner="module definition execution",
                        blame=keyword.value.fragment,
                        observed=f"metaclass has {len(constructors)} __new__ methods",
                        requested="one exact source-visible metaclass constructor",
                        fix="preserve unique method-definition testimony",
                    )
                constructor = constructors[0]
                callable_floor = _ModuleSourceFrameCallableV1(
                    constructor.name,
                    constructor.source_call_frame,
                    defining_class=metaclass_floor,
                )
                class_name_floor = StringValue(self.definition.name)
                bases_floor = TupleValue(tuple(value.base_classes))
                fallback_namespace = DictValue(
                    tuple(
                        (StringValue(field.name), field.value)
                        for field in value.class_fields
                    )
                )
                occurrence = _call_coordinate(keyword.value)
                preparers = tuple(
                    method
                    for method in metaclass_floor.methods
                    if method.name == "__prepare__"
                )
                if len(preparers) > 1:
                    raise SugarNotWritten(
                        owner="module definition execution",
                        blame=keyword.value.fragment,
                        observed=f"metaclass has {len(preparers)} __prepare__ methods",
                        requested="at most one exact source-visible namespace producer",
                        fix="preserve unique method-definition testimony",
                    )

                def apply_new(namespace_floor):
                    applied = CallableApplication(
                        (
                            metaclass_floor,
                            class_name_floor,
                            bases_floor,
                            namespace_floor,
                        ),
                        (),
                        occurrence,
                        owner="module metaclass application",
                        call_occurrence=occurrence,
                    ).apply(callable_floor, ctx)

                    def publish_metaclass_result(result):
                        final_class = _project_metaclass_final_class(
                            result, blame=keyword.value.fragment
                        )
                        publication = _mint_metaclass_class_publication(
                            source_cid=self.definition.unit.source_cid,
                            definition=_call_coordinate(self.definition),
                            binding_occurrence=sugar.binding_target_occurrence,
                            metaclass_occurrence=occurrence,
                            raw_class=value,
                            metaclass_floor=metaclass_floor,
                            metaclass_callable=callable_floor,
                            class_name_floor=class_name_floor,
                            bases_floor=bases_floor,
                            namespace_floor=namespace_floor,
                            final_class=final_class,
                            module_construction_receipt_cid=(
                                self.module_construction_receipt_cid
                            ),
                        )
                        return Complete(
                            ScopeRebind(
                                self.definition.name,
                                MetaclassClassValue(publication),
                            )
                        )

                    return applied.and_then(publish_metaclass_result)

                if not preparers:
                    return apply_new(fallback_namespace)
                prepare = preparers[0]
                prepare_callable = _ModuleSourceFrameCallableV1(
                    prepare.name,
                    prepare.source_call_frame,
                    defining_class=metaclass_floor,
                )
                prepared = CallableApplication(
                    (metaclass_floor, class_name_floor, bases_floor),
                    (),
                    occurrence,
                    owner="module metaclass namespace preparation",
                    call_occurrence=occurrence,
                ).apply(prepare_callable, ctx)
                return prepared.and_then(apply_new)
            if not sugar.decorator_sugars:
                return Complete(ScopeRebind(self.definition.name, value))
            decorator_floors = []
            for decorator_sugar in sugar.decorator_sugars:
                decorator_outcome = decorator_sugar.desugar(ctx)
                if not isinstance(decorator_outcome, Complete):
                    raise SugarNotWritten(
                        owner="module definition execution",
                        blame=self.definition.fragment,
                        observed="decorator expression reduced nonlinearly",
                        requested="one completed source decorator callable",
                        fix="sequence decorator expression effects before publication",
                    )
                decorator_floors.append(decorator_outcome.value)
            current = value
            applications = []
            for callable_floor, occurrence in reversed(
                tuple(
                    zip(
                        decorator_floors,
                        sugar.decorator_occurrences,
                        strict=True,
                    )
                )
            ):
                from sugar_lift_py_tests.floor import CallSiteValue

                if (
                    type(callable_floor) is CallSiteValue
                    and callable_floor.body is not None
                    and callable_floor.source_call_frame_cid is not None
                ):
                    callable_floor = callable_floor.force_floor(
                        ctx,
                        owner="module authenticated decorator factory return",
                    )
                before = current
                applied = CallableApplication(
                    (before,),
                    (),
                    occurrence,
                    owner="module decorated class application",
                    call_occurrence=occurrence,
                ).apply(callable_floor, ctx)
                if not isinstance(applied, Complete):
                    raise SugarNotWritten(
                        owner="module definition execution",
                        blame=occurrence,
                        observed="decorator application reduced nonlinearly",
                        requested="one completed final class Floor",
                        fix="sequence decorator application effects before publication",
                    )
                current = applied.value
                applications.append(
                    DecoratorApplicationPublicationV1.mint(
                        occurrence=occurrence,
                        callable_floor=callable_floor,
                        input_floor=before,
                        output_floor=current,
                    )
                )
            publication = DecoratedClassPublicationV1.mint(
                source_cid=self.definition.unit.source_cid,
                definition=_call_coordinate(self.definition),
                binding_occurrence=sugar.binding_target_occurrence,
                raw_class=value,
                decorator_applications=tuple(applications),
                final_class=current,
                module_construction_receipt_cid=(self.module_construction_receipt_cid),
            )
            return Complete(
                ScopeRebind(self.definition.name, DecoratedClassValue(publication))
            )

        return outcome.and_then(bind)


def _session_lexical_import_runner(session: SourceResolutionSession, module):
    """One lexical import walk per source body per session.

    Prefer the prefix-door SourceFile when the export path already built it —
    measured residual after #7066 was still 2× SourceFile(config) from call-door
    and value-door each re-running ``_run_lexical_import_pass`` (fresh Materialize).
    One walk fills both roster doors.
    """
    from pathlib import Path

    hit = session.lexical_pass_hit(module.source_cid)
    if hit is not None:
        return hit
    root = Path(".")
    path = Path(module.source_seat)
    # §4 process residency: lexical pass is module preparation under content CID.
    # Prefer typed module from prefix door / process-resident SourceFile.
    from sugar_source_tree.process_resident_file import (
        get_or_prepare_lexical_import_pass,
        get_resident,
    )
    from sugar_source_tree.tree import SourceFile

    source_file = session.prefix_file_hit(module.source_cid, module.source_seat)
    if source_file is None:
        resident = get_resident(module.source_cid, module.source_seat)
        if resident is not None:
            source_file = resident.source_file
    if source_file is not None:
        runner = get_or_prepare_lexical_import_pass(
            source_file.root,
            root=root,
            path=path,
            source=module.source,
            source_cid=module.source_cid,
            module_identities={},
        )
    else:
        # Opens SourceFile (process-resident MaterializeModule) then lexical once.
        # SEAT A REGISTERING REPORTER (#7171 class). This open is often the
        # FIRST opener of a dependency module in the process, so its bind-time
        # roster and the lexical rows' ``definition_occurrence`` nodes carry
        # whatever reporter is passed here for the rest of the process. Left on
        # ``NULL_REPORTER``, a consumer call that retains such a definition
        # (``CallSiteSugar.expected_definition_ref`` /
        # ``expected_source_call_frame_owner``, #7423) refuses with "producer
        # reporter owns no registration table" -- 25 files on the 2026-09-05
        # board. Same producer roll the prefix door seats.
        from sugar_source_tree.binding_state import (
            ConstructionTestimonyReporterV1,
            SubstitutionTraceBuilderV1,
        )
        from sugar_source_tree.reporter import NULL_REPORTER

        producer_reporter = ConstructionTestimonyReporterV1(
            NULL_REPORTER, SubstitutionTraceBuilderV1(module.source_cid)
        )
        typed = SourceFile(
            (module.source, str(path), module.source_cid), reporter=producer_reporter
        ).root
        runner = get_or_prepare_lexical_import_pass(
            typed,
            root=root,
            path=path,
            source=module.source,
            source_cid=module.source_cid,
            module_identities={},
        )
    session.remember_lexical_pass(module.source_cid, runner)
    return runner


def _session_import_use_receipts(session: SourceResolutionSession, module):
    """Call-door import-use roster once per source body per session."""
    from pathlib import Path
    from types import MappingProxyType

    from sugar_lift_py_tests.import_binding import (
        _LexicalRevalidationSnapshotV1,
        _REVALIDATION_SNAPSHOTS,
        _hash,
        _mint_import_use_receipts,
        _revalidation_cache_key,
    )

    hit = session.import_use_hit(module.source_cid)
    if hit is not None:
        return hit
    runner = _session_lexical_import_runner(session, module)
    root = Path(".")
    path = Path(module.source_seat)
    identities: dict = {}
    cache_key = _revalidation_cache_key(root, path, module.source_cid, identities)
    if cache_key not in _REVALIDATION_SNAPSHOTS:
        _REVALIDATION_SNAPSHOTS[cache_key] = _LexicalRevalidationSnapshotV1(
            row_cids=frozenset(_hash(row) for row in runner.rows),
            outcomes=MappingProxyType(dict(runner.outcomes)),
        )
    receipts = _mint_import_use_receipts(
        runner.rows,
        root=root,
        path=path,
        source=module.source,
        source_cid=module.source_cid,
        module_identities=identities,
    )
    session.remember_import_use(module.source_cid, receipts)
    return receipts


def _session_import_value_receipts(session: SourceResolutionSession, module):
    """Value-door import roster once per source body per session."""
    from pathlib import Path
    from types import MappingProxyType

    from sugar_lift_py_tests.import_binding import (
        _LexicalRevalidationSnapshotV1,
        _VALUE_REVALIDATION_SNAPSHOTS,
        _hash,
        _mint_import_use_receipts,
        _revalidation_cache_key,
    )

    hit = session.import_value_hit(module.source_cid)
    if hit is not None:
        return hit
    runner = _session_lexical_import_runner(session, module)
    root = Path(".")
    path = Path(module.source_seat)
    identities: dict = {}
    cache_key = _revalidation_cache_key(root, path, module.source_cid, identities)
    if cache_key not in _VALUE_REVALIDATION_SNAPSHOTS:
        _VALUE_REVALIDATION_SNAPSHOTS[cache_key] = _LexicalRevalidationSnapshotV1(
            row_cids=frozenset(_hash(row) for row in runner.value_rows),
            outcomes=MappingProxyType(dict(runner.value_outcomes)),
        )
    receipts = _mint_import_use_receipts(
        runner.value_rows,
        root=root,
        path=path,
        source=module.source,
        source_cid=module.source_cid,
        module_identities=identities,
    )
    session.remember_import_value(module.source_cid, receipts)
    return receipts


def _module_level_with_coordinates(source_file) -> frozenset:
    """Use-site coordinates of every ``with`` the module body runs at import.

    A def, lambda or class-method body does not run at import, so its withs
    are not the prefix's.  A class body does run, so its withs are.
    """
    from sugar_lift_py_tests.context_manager_resolution import (
        SourceFragmentCoordinateV1,
    )
    from sugar_source_tree.nodes import AsyncFunctionDef, FunctionDef, Lambda, With

    def span(node):
        box = node.line_col_span()
        return (box.start_line, box.start_col), (box.end_line, box.end_col)

    nodes = tuple(source_file.root.walk())
    unrun = tuple(
        span(node)
        for node in nodes
        if isinstance(node, (FunctionDef, AsyncFunctionDef, Lambda))
    )
    coordinates = set()
    for node in nodes:
        if not isinstance(node, With):
            continue
        start, end = span(node)
        if any(lo <= start and end <= hi for lo, hi in unrun):
            continue
        for item in node.items:
            coordinates.add(
                SourceFragmentCoordinateV1(
                    item.context_expr.unit.source_cid,
                    *item._manager_use_site_span(),
                )
            )
    return frozenset(coordinates)


def _populate_prefix_module_with_managers(module, source_file, *, session) -> None:
    """Derive the managers of the withs a module runs at import.

    The prefix door executes module-level ``with config.config_prefix(...)``
    (pandas io/pytables.py:227) exactly as a module lift does, so it needs the
    same derivation a module lift seats.  Without it, every such with refused
    as "no context-manager derivation" and the export after it became
    ``dynamic-export``.  Population runs once per prefix SourceFile and only
    selects module-level withs.
    """
    from pathlib import Path

    from .manager_summary_derivation import populate_source_derived_resource_refs

    if getattr(source_file, "_prefix_with_managers_populated", False):
        return
    object.__setattr__(source_file, "_prefix_with_managers_populated", True)
    selected = _module_level_with_coordinates(source_file)
    if not selected:
        return
    seat = Path(module.source_seat)
    depth = len(module.module_name.split("."))
    if seat.name == "__init__.py":
        depth += 1
    parents = seat.parents
    root = parents[depth - 1] if depth - 1 < len(parents) else Path(".")
    populate_source_derived_resource_refs(
        source_file,
        root=root,
        path=seat,
        session=session,
        selected_coordinates=selected,
    )


def _module_prefix_outcome(module, locus, *, graph=None, session=None):
    """Execute the authenticated module prefix through its exact definitions."""
    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        reduce_block_to_exitset,
    )
    from sugar_lift_py_tests.sugar.inert_sugar import InertSugar
    from sugar_source_tree.binding_state import (
        ConstructionTestimonyReporterV1,
        SubstitutionTraceBuilderV1,
    )
    from sugar_source_tree.nodes import (
        AsyncFunctionDef,
        Delete,
        FunctionDef,
        Name,
        Subscript,
    )
    from sugar_source_tree.reporter import NULL_REPORTER

    from .canonical import blake3_512_of

    if module.source_cid != blake3_512_of(module.source.encode("utf-8")):
        raise ValueError("module prefix source CID mismatch")
    # Defensive membrane: stdlib must never reach MaterializeModule here.
    # Callers should short-circuit in prefix_has_completed_fallthrough; if they
    # do not, refuse loudly rather than rebuild an unenrolled module.
    if graph is not None and _graph_is_off_population(
        graph, session=session, module_name=getattr(module, "module_name", None)
    ):
        raise RuntimeError(
            "population membrane: _module_prefix_outcome must not MaterializeModule "
            f"off-population seat {module.source_seat!r}; cite via "
            "prefix_has_completed_fallthrough / call-target-off-population"
        )
    session = session_or_new(session)
    # One prefix-door SourceFile per source body per session. Export fallthrough
    # used to rebuild config.py once per export locus (measured 33× SourceFile
    # on one _json open after the frame-door memo). Value is context-bound to
    # this session — never process-global.
    source_file = session.prefix_file_hit(module.source_cid, module.source_seat)
    if source_file is None:
        construction_context = TreeConstructionContextV1.for_source_call_construction()
        producer_reporter = ConstructionTestimonyReporterV1(
            NULL_REPORTER, SubstitutionTraceBuilderV1(module.source_cid)
        )
        source_file = SourceFile(
            (module.source, module.source_seat, module.source_cid),
            reporter=producer_reporter,
            construction_context=construction_context,
        )
        session.remember_prefix_file(module.source_cid, module.source_seat, source_file)
    construction_context = source_file.unit.construction_context
    locus_key = (locus.lineno, locus.col_offset)
    prefix = tuple(
        statement
        for statement in source_file.root.body
        if (
            statement.line_col_span().start_line,
            statement.line_col_span().start_col,
        )
        < locus_key
    )

    # THREAD THE BLOCK BEFORE ANYTHING READS IT -- the same order a function
    # body takes.  ``FunctionDef.source_visible_call_frame`` substitutes its
    # body and only then sugars each statement; this door used to sugar each
    # statement where it stood.  Statement-at-a-time construction cannot see the
    # binding an earlier statement made, so a module-level ``for`` over a
    # module-level constant (``for _dependency in _hard_dependencies:``) met a
    # SYMBOLIC iterable, could not unroll, and fell to ``For.sugar`` --
    # deliberately unwritten, because a SURVIVING ``For`` is the symbolic fold.
    # The dissolution was already written in ``For.substitute``; this door
    # simply never reached it.  Nothing here teaches ``For.sugar`` to guess: an
    # iterable still symbolic after threading keeps the node and stays loud.
    #
    # Threading happens HERE, before base-class seating and import-receipt
    # seating, so every downstream reader sees ONE statement set.  Seating the
    # unsubstituted classes and then sugaring the substituted ones would key
    # ``source_class_bases`` on fragment CIDs the sugared statements no longer
    # carry.
    #
    # ``_substitute_body`` may raise SugarNotWritten/TypeError; the caller
    # (``prefix_has_completed_fallthrough``) already catches exactly those and
    # turns them into named construction-refusal testimony, never a quiet False.
    _populate_prefix_module_with_managers(module, source_file, session=session)

    # A def in the prefix binds a function; its body runs only when called.
    # A refusal inside that body is deferred to the call (see
    # DEFER_DEFINITION_BODY_REFUSAL), never prefix testimony.
    from sugar_source_tree.nodes import DEFER_DEFINITION_BODY_REFUSAL

    prefix, _threaded = source_file.root._substitute_body(
        prefix, {DEFER_DEFINITION_BODY_REFUSAL: True}
    )

    # Base testimony is installed from exact parser-owned module bindings,
    # never from a class-name scan.  Only earlier module ClassDefs can be a
    # source-visible base at this prefix boundary.
    prefix_classes = tuple(item for item in prefix if isinstance(item, ClassDef))
    class_roster = set(prefix_classes)
    for definition in prefix_classes:
        bases = []
        for base in definition.bases:
            if not isinstance(base, Name):
                continue
            bindings = tuple(
                (definition.unit.module_direct_bindings or {}).get(base.id, ())
            )
            if (
                len(bindings) == 1
                and isinstance(bindings[0], ClassDef)
                and bindings[0] in class_roster
                and bindings[0].line_col_span().start_line
                < definition.line_col_span().start_line
            ):
                bases.append(bindings[0].sugar())
        # The table is an all-base positional roster, never a bag of the
        # source bases we happened to recognize.  Installing a partial row for
        # ``class X(Local, dict)`` drops ``dict`` before temporal evaluation.
        if len(bases) == len(definition.bases):
            definition.unit.construction_context.source_class_bases[
                definition.fragment.seal().cid
            ] = tuple(bases)

    dependency_graphs = _bind_dependency_graphs(session, {})
    if graph is not None:
        top = module.module_name.split(".", 1)[0]
        dependency_graphs[top] = graph
        if session.enabled:
            session.dependency_graphs[top] = graph
        for definition in prefix_classes:
            _seat_import_value_use_receipts(
                source_file=source_file,
                module=module,
                target=definition,
                session=session,
                context=construction_context,
                dependency_graphs=dependency_graphs,
            )

    sugars = tuple(
        (
            _ModuleFunctionDefinitionBindingSugar(statement)
            if isinstance(statement, (FunctionDef, AsyncFunctionDef))
            else (
                _ModuleClassDefinitionBindingSugar(
                    statement, source_file.construction_event_receipt_cid
                )
                if isinstance(statement, ClassDef)
                else (
                    _ModuleNameAssignmentBindingSugar(
                        statement, tuple(statement.targets)
                    )
                    if (
                        isinstance(statement, Assign)
                        and statement.targets
                        and all(
                            isinstance(target, Name) for target in statement.targets
                        )
                    )
                    else (
                        _ModuleSubscriptDeleteBindingSugar(
                            statement, statement.targets[0].value
                        )
                        if (
                            isinstance(statement, Delete)
                            and len(statement.targets) == 1
                            and isinstance(statement.targets[0], Subscript)
                            and isinstance(statement.targets[0].value, Name)
                        )
                        else statement.sugar()
                    )
                )
            )
        )
        for statement in prefix
    )
    return reduce_block_to_exitset(sugars)


# Top-level statement kinds that always complete and fall through under Python
# module semantics (bind or no-op; never exit the module body). Used so export
# admit does not run ``_module_prefix_outcome`` (MaterializeModule + ClassDef
# sugar of every earlier definition) when the AST prefix is pure bindings —
# measured residual ~1.9s of prefix_has_completed_fallthrough on tip 63356a636
# for one pandas/io/json/_json.py open after session memos landed.
_STATIC_FALLTHROUGH_STMT_TYPES: frozenset[type] | None = None


def _static_fallthrough_stmt_types() -> frozenset[type]:
    global _STATIC_FALLTHROUGH_STMT_TYPES
    if _STATIC_FALLTHROUGH_STMT_TYPES is not None:
        return _STATIC_FALLTHROUGH_STMT_TYPES
    import ast

    kinds: set[type] = {
        ast.Import,
        ast.ImportFrom,
        ast.FunctionDef,
        ast.AsyncFunctionDef,
        ast.ClassDef,
        ast.Assign,
        ast.AnnAssign,
        ast.Pass,
        ast.Expr,
        ast.Delete,
        ast.Global,
        ast.Nonlocal,
    }
    type_alias = getattr(ast, "TypeAlias", None)
    if type_alias is not None:
        kinds.add(type_alias)
    _STATIC_FALLTHROUGH_STMT_TYPES = frozenset(kinds)
    return _STATIC_FALLTHROUGH_STMT_TYPES


def _ast_stmt_always_falls_through(statement) -> bool:
    """True when this top-level statement cannot prevent later bindings.

    Decorated FunctionDef/ClassDef still bind (incomplete sugar is a Floor gap,
    not a module exit).  Pure-branch Ifs (``if TYPE_CHECKING:`` and any If
    whose every arm always falls through) fall through when both arms do.
    Open control flow (Try/For/While/With/Match/Raise/Return/Assert) needs the
    full prefix producer.
    """
    import ast

    if type(statement) in _static_fallthrough_stmt_types():
        return True
    if isinstance(statement, ast.If):
        body_ok = all(_ast_stmt_always_falls_through(s) for s in statement.body)
        else_ok = all(_ast_stmt_always_falls_through(s) for s in statement.orelse)
        return body_ok and else_ok
    return False


def _static_prefix_always_fallthrough(module, locus) -> bool:
    """AST-only admit: pure-binding prefix needs no MaterializeModule/sugar.

    Parses ``module.source`` once (stdlib ``ast``, not SourceFile).  When every
    statement strictly before ``locus`` always falls through, export resolve
    may admit without ``_module_prefix_outcome``.  That path re-sugared every
    ClassDef before each export locus (prefix_has_completed_fallthrough ~1.9s
    of a ~7s _json open on tip after SourceFile session memos).
    """
    import ast

    from .canonical import blake3_512_of

    if module.source_cid != blake3_512_of(module.source.encode("utf-8")):
        raise ValueError("module prefix source CID mismatch")
    try:
        tree = ast.parse(module.source)
    except SyntaxError:
        return False
    locus_key = (locus.lineno, locus.col_offset)
    for statement in tree.body:
        key = (statement.lineno, statement.col_offset)
        if key >= locus_key:
            break
        if not _ast_stmt_always_falls_through(statement):
            return False
    return True


@dataclass(frozen=True)
class PrefixFallthroughOutcomeV1:
    """Closed testimony for one authenticated module-prefix fallthrough ask.

    The key already identifies the source locus completely.  The former bool
    value did not identify which fact it cached: ordinary non-fallthrough or a
    construction refusal.  One closed outcome keeps those facts distinct.
    """

    kind: Literal[
        "completed", "ordinary-non-fallthrough", "construction-refusal"
    ]
    refusal_kind: Literal["sugar-not-written", "construction-type-error"] | None = (
        None
    )
    observed_event_type: str | None = None
    detail: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in {
            "completed",
            "ordinary-non-fallthrough",
            "construction-refusal",
        }:
            raise ValueError(f"unknown prefix fallthrough outcome {self.kind!r}")
        refusal_fields = (
            self.refusal_kind,
            self.observed_event_type,
            self.detail,
        )
        if self.kind == "construction-refusal":
            if any(value is None for value in refusal_fields):
                raise ValueError("construction refusal requires named testimony")
            if self.refusal_kind not in {
                "sugar-not-written",
                "construction-type-error",
            }:
                raise ValueError(
                    f"unknown prefix construction refusal {self.refusal_kind!r}"
                )
        elif any(value is not None for value in refusal_fields):
            raise ValueError("control-flow outcome cannot carry refusal testimony")


def prefix_has_completed_fallthrough(
    module, locus, *, graph=None, session=None
) -> PrefixFallthroughOutcomeV1:
    """Admit an export when the module prefix normally completes.

    POPULATION MEMBRANE: when ``graph`` is stdlib (off enrolled population),
    never ``MaterializeModule`` the module to prove fallthrough.  Static export
    locus + definition coordinate is enough for a ResolvedPythonObjectV1
    citation; frame projection then cites via ``call-target-off-population``
    instead of rebuilding.  Running the prefix producer here is what turned
    one pandas open into 35× ``SourceFile(enum.py)``.

    STATIC FALLTHROUGH: when the AST prefix is pure bindings (imports, defs,
    classes, assigns, pure-branch Ifs such as TYPE_CHECKING), admit without
    ``_module_prefix_outcome`` / ClassDef.sugar.  Full producer remains the
    authority for open control flow (Try/For/Raise/…).
    """
    from sugar_lift_py_tests.outcome import Completed, true_guard

    session = session_or_new(session)
    if graph is not None and _graph_is_off_population(
        graph, session=session, module_name=getattr(module, "module_name", None)
    ):
        # Cite path: admit static export without off-population construction.
        return PrefixFallthroughOutcomeV1("completed")

    from sugar_source_tree.panic import SugarNotWritten

    fallthrough_key = (
        module.source_cid,
        getattr(locus, "lineno", None),
        getattr(locus, "col_offset", None),
    )
    cached = session.fallthrough_hit(fallthrough_key)
    if cached is not None:
        return cached

    # Cheap door: pure-binding AST prefix always falls through — no sugar.
    if _static_prefix_always_fallthrough(module, locus):
        outcome = PrefixFallthroughOutcomeV1("completed")
        session.remember_fallthrough(fallthrough_key, outcome)
        return outcome

    # Prefix sugar can SNW (e.g. decorated FunctionDef without publication) or
    # TypeError on construction (IfExp/spread require_* costume). Neither is
    # ordinary non-fallthrough: retain named testimony in the session memo so a
    # later caller cannot replay construction refusal as a clean ``False``.
    try:
        exits = _module_prefix_outcome(module, locus, graph=graph, session=session)
    except (SugarNotWritten, TypeError) as exc:
        if isinstance(exc, SugarNotWritten):
            refusal = PrefixFallthroughOutcomeV1(
                kind="construction-refusal",
                refusal_kind="sugar-not-written",
                observed_event_type=f"{type(exc).__module__}.{type(exc).__qualname__}",
                detail=f"{exc.owner}: {exc.observed}",
            )
        else:
            refusal = PrefixFallthroughOutcomeV1(
                kind="construction-refusal",
                refusal_kind="construction-type-error",
                observed_event_type=f"{type(exc).__module__}.{type(exc).__qualname__}",
                detail=str(exc),
            )
        session.remember_fallthrough(fallthrough_key, refusal)
        return refusal
    if len(exits.exits) != 1:
        outcome = PrefixFallthroughOutcomeV1("ordinary-non-fallthrough")
        session.remember_fallthrough(fallthrough_key, outcome)
        return outcome
    face = exits.exits[0]
    ok = (
        isinstance(face, Completed)
        and face.guard == true_guard()
        and bool(getattr(face.value, "can_fall_through", False))
    )
    outcome = PrefixFallthroughOutcomeV1(
        "completed" if ok else "ordinary-non-fallthrough"
    )
    session.remember_fallthrough(fallthrough_key, outcome)
    return outcome


@dataclass(frozen=True)
class ConstructedManagerBehaviorV1:
    resolved_object_cid: str
    manager_construction_cid: str
    receiver_state: ObjectValue | ReceiverStatePartitionValue = field(compare=False)
    receiver_state_cid: str
    formal_actual_bindings: tuple[BindingEntryV1, ...]
    source_call_frame_cid: str
    formal_actual_values: tuple[FloorValue, ...] = field(default=(), compare=False)
    source_call_frame: object | None = field(default=None, compare=False, repr=False)
    factory_prefix: tuple[FloorValue, ...] = field(default=(), compare=False)
    factory_prefix_cids: tuple[str, ...] = ()

    @property
    def preimage(self):
        return {
            "kind": "constructed-manager-behavior",
            "schemaVersion": "1",
            "resolvedObjectCid": self.resolved_object_cid,
            "receiverStateCid": self.receiver_state_cid,
            "formalActualBindings": [
                item.wire() for item in self.formal_actual_bindings
            ],
            "sourceCallFrameCid": self.source_call_frame_cid,
            "factoryPrefixCids": list(self.factory_prefix_cids),
        }

    def __post_init__(self) -> None:
        if self.receiver_state.identity != self.receiver_state_cid:
            raise ValueError("receiver state CID does not match ordinary construction")
        if cid_of_json(self.preimage) != self.manager_construction_cid:
            raise ValueError("manager construction CID does not match its preimage")
        if self.formal_actual_values:
            if len(self.formal_actual_values) != len(self.formal_actual_bindings):
                raise ValueError("formal actual value/binding arity mismatch")
            for value, entry in zip(
                self.formal_actual_values, self.formal_actual_bindings, strict=True
            ):
                testimony = entry.sealed_state.testimony
                if (
                    testimony is None
                    or testimony.semantic_value_cid
                    != _term_content_cid(value.to_term(owner=self.resolved_object_cid))
                ):
                    raise ValueError("formal actual value lacks matching testimony")
        if self.source_call_frame is not None and (
            self.source_call_frame.frame_cid != self.source_call_frame_cid
        ):
            raise ValueError("source call frame CID mismatch")


# The four conditions that ``opaque-call-target`` used to fuse into one name.
#
# ``opaque-call-target`` named a *symptom* -- "construction could not see through
# this call" -- and four structurally different conditions arrived under it, three
# of them carrying a callee spelling as their detail.  Each is decided here by a
# condition construction already evaluates; none reads a name table.
#
# ``call-graph-cycle``
#     Re-entry of a frame already being projected, a returned-callsite cycle, or a
#     fixpoint that stops making progress.  Carries NO symbol.  The fix is a cycle
#     policy.
# ``value-call-target``
#     The callee is bound by the enclosing definition itself -- a parameter or a
#     local -- so it is a runtime VALUE.  Higher-order dispatch.  No export lookup
#     can ever resolve it, because there is nothing to look up.  The fix is a
#     capability, not coverage.
# ``call-target-source-absent``
#     The authenticated export door declined the name: no defining source for it
#     inside this distribution artifact.  An artifact-COVERAGE gap.
# ``call-target-export-unresolved``
#     The export door DID authenticate an object in this artifact, but projecting
#     its frame failed.  A defect in the door, not a coverage gap -- and invisible
#     for as long as it shares a bucket with the other three.
# ``call-target-off-population``
#     The export door authenticated a defining source, but that source is outside
#     the enrolled measurement population (stdlib / off-pin).  Cite via the opaque
#     obligation path; do NOT MaterializeModule / ClassDef.sugar the unenrolled
#     module.  Successful resolution used to be punished with a full rebuild
#     while failure already cited -- the population membrane closes that hole.

@dataclass(frozen=True)
class ManagerConstructionGapV1:
    kind: Literal[
        "artifact-mismatch",
        "definition-missing",
        "call-graph-cycle",
        "value-call-target",
        "call-target-source-absent",
        "call-target-export-unresolved",
        "call-target-off-population",
        "non-manager-result",
        "call-binding",
        "force-floor",
    ]
    resolved_object_cid: str
    detail: str


def _graph_is_off_population(
    graph: "DependencyArtifactGraph | None",
    *,
    session: SourceResolutionSession | None = None,
    module_name: str | None = None,
) -> bool:
    """True when ``graph`` is outside the enrolled measurement population.

    This is the one answer to "is this callee bridged": the lifter has it
    only when an authenticated artifact holds its source AND the population
    enrolls that source.  A graph that holds no source for ``module_name``
    does not have it.  ``graph=None`` means no artifact authenticates
    ``module_name``'s top-level module at all, so the lifter does not have
    it either: it is not bridged, whatever it is implemented in.

    The roster (``session.enrolled_distributions``) is step 2's file list
    (``project_file_roster``): the content CID of every file the lift lists,
    and nothing else. No distribution is enrolled by name and no module by a
    module-scoped entry. A module is enrolled only when the source its
    artifact seats for it is one of those files. An installed module outside
    the file list is not population, even when the opened code imports it:
    an imported call is a coordinate plus an edge, answered by an imported
    proof, and its body is never lifted (#7796). Without ``module_name`` only
    a listed file of the graph admits.
    """
    if session is None:
        raise TypeError(
            "population classification requires an enrolled distribution roster"
        )
    roster = session.enrolled_distributions
    if graph is None:
        return bool(module_name)
    if not module_name:
        return not any(item.content_cid in roster for item in graph.files)
    source_cid = graph.modules.source_cid_of(module_name)
    if source_cid is None:
        # The artifact authenticates, but holds no source for this module
        # (an extension file, or a module it never ships): the lifter does
        # not have it, enrolled or not.
        return True
    return source_cid not in roster


def _absent_module_is_off_population(
    gap, *, session: SourceResolutionSession, dependency_graphs=None
) -> bool:
    """An ``artifact-module-absent`` export gap, asked the one bridged answer.

    The gap names a module the importing artifact does not hold.  The graph
    that would hold it is the module's own top-level artifact (``None`` when
    none authenticates), and :func:`_graph_is_off_population` answers for that
    graph and module.  No other gap kind is asked here: a name an artifact
    holds the source of but cannot resolve statically stays its named gap.
    """
    from .dependency_artifact import DependencyArtifactAuthenticationError

    if getattr(gap, "kind", None) != "artifact-module-absent":
        return False
    module_name = getattr(gap, "module_name", None)
    if not isinstance(module_name, str) or not module_name:
        return False
    try:
        graph = _dependency_graph_for_top(
            module_name.split(".", 1)[0],
            session=session,
            dependency_graphs={} if dependency_graphs is None else dependency_graphs,
        )
    except DependencyArtifactAuthenticationError:
        graph = None
    return _graph_is_off_population(graph, session=session, module_name=module_name)


def _floor_tuple_construct_fields(
    receiver: ObjectValue | ReceiverStatePartitionValue,
    actuals: tuple[FloorValue, ...],
) -> ObjectValue | ReceiverStatePartitionValue:
    """Project bodyless ``tuple(...)`` field stores to TupleValue when decidable.

    RaisesExc writes ``self.expected_exceptions = tuple(_parse_exc(e) for e in ...)``.
    That store may remain a bodyless CallSiteValue or complete as a
    TupleCoordinateValue whose source is the same generator. When the generator
    cannot yet project finite_elements (iterable still a
    branch-result conditional) but the callsite supplied exactly one authenticated
    class actual, the source-visible non-tuple/non-None arm is exactly
    ``(actual,)`` after ``_parse_exc`` identity for BaseException types.

    The same one-class arm is also the else of ``isinstance(..., tuple)`` /
    ``is None`` before that parse, stored as a nested GuardedValue whose
    leaves are the raw class, ``()``, and ``(actual,)``. Floor that field so
    ``not self.expected_exceptions`` / ``len`` / ``[0]`` / exit derivation
    see a TupleValue rather than indexing the empty None arm.
    """
    if isinstance(receiver, ObjectValue):
        return _floor_object_tuple_fields(receiver, actuals)
    from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
    from sugar_lift_py_tests.floor.receiver_state_partition_value import (
        ReceiverStatePartitionValue as RSP,
    )

    faces = []
    changed = False
    for face in receiver.exits.exits:
        if isinstance(face, Completed) and isinstance(
            face.value, (ObjectValue, ReceiverStatePartitionValue)
        ):
            floored = _floor_tuple_construct_fields(face.value, actuals)
            if floored is not face.value:
                changed = True
            faces.append(type(face)(face.guard, floored))
        else:
            faces.append(face)
    if not changed:
        return receiver
    return RSP(ExitSet(tuple(faces)))


def _floor_object_tuple_fields(
    obj: ObjectValue, actuals: tuple[FloorValue, ...]
) -> ObjectValue:
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.floor.class_value import ClassValue
    from sugar_lift_py_tests.floor.comprehension_value import ComprehensionValue
    from sugar_lift_py_tests.floor.none_value import NoneValue
    from sugar_lift_py_tests.floor.object_value import ObjectField
    from sugar_lift_py_tests.floor.tuple_value import TupleValue

    class_actuals = tuple(item for item in actuals if isinstance(item, ClassValue))
    fields_by_name = {field.name: field.value for field in obj.fields}
    changed = False
    for name, value in list(fields_by_name.items()):
        floored = _floor_one_tuple_callsite(value, class_actuals)
        if floored is None:
            floored = _floor_one_guarded_tuple_wrap(value, class_actuals)
        if floored is not None:
            fields_by_name[name] = floored
            changed = True
    # AbstractRaises stores match/check in super().__init__. When that super
    # call remains bodyless, written match=None / check=None still need field
    # testimony so _check_match and NoMessagePattern can floor on the exit face.
    method_names = {method.name for method in obj.methods}
    if "matches" in method_names and "expected_exceptions" in fields_by_name:
        for optional in ("match", "check"):
            if optional not in fields_by_name:
                fields_by_name[optional] = NoneValue()
                changed = True
    if not changed:
        return obj
    return ObjectValue(
        obj.class_name,
        tuple(
            ObjectField(name, fields_by_name[name]) for name in sorted(fields_by_name)
        ),
        obj.methods,
        obj.class_fields,
        obj.identity,
        obj.deferred_helper_fields,
        obj.deleted_instance_fields,
        obj.defining_class,
    )


def _floor_one_guarded_tuple_wrap(
    value: FloorValue, class_actuals: tuple[FloorValue, ...]
) -> FloorValue | None:
    """Select ``(actual,)`` from an isinstance/None wrap stored as GuardedValue.

    For one authenticated class actual the wrap's leaves are the raw class
    (isinstance-true), ``()`` (None), and ``(actual,)`` (else). Indexing the
    joined GuardedValue would halt on the empty None arm; the source-visible
    taken arm is the singleton tuple already present among the leaves.
    """
    from sugar_lift_py_tests.floor.guarded_value import GuardedValue
    from sugar_lift_py_tests.floor.tuple_value import TupleValue

    if len(class_actuals) != 1 or not isinstance(value, GuardedValue):
        return None
    actual = class_actuals[0]
    leaves: list[FloorValue] = []

    def walk(node: FloorValue) -> None:
        if isinstance(node, GuardedValue):
            walk(node.when_true)
            walk(node.when_false)
            return
        leaves.append(node)

    walk(value)
    has_empty = any(
        isinstance(leaf, TupleValue) and leaf.elements == () for leaf in leaves
    )
    singleton = next(
        (
            leaf
            for leaf in leaves
            if isinstance(leaf, TupleValue) and leaf.elements == (actual,)
        ),
        None,
    )
    if has_empty and singleton is not None:
        return singleton
    return None


def _floor_one_tuple_callsite(
    value: FloorValue, class_actuals: tuple[FloorValue, ...]
) -> FloorValue | None:
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.floor.comprehension_value import ComprehensionValue
    from sugar_lift_py_tests.floor.tuple_coordinate_value import TupleCoordinateValue
    from sugar_lift_py_tests.floor.tuple_value import TupleValue

    arg = None
    if isinstance(value, CallSiteValue) and value.target_name == "tuple":
        if len(value.arg_values) != 1:
            return None
        arg = value.arg_values[0]
    elif isinstance(value, TupleCoordinateValue) and value.index is None:
        # Completed ``tuple(iterable)`` testimony carries the same generator
        # as the bodyless CallSiteValue arm, without invented members.
        arg = value.source
    else:
        return None
    if isinstance(arg, ComprehensionValue) and arg.finite_elements is not None:
        return TupleValue(tuple(arg.finite_elements))
    if isinstance(arg, TupleValue):
        return arg
    # Sole class actual + bodyless tuple(genexp): the non-tuple/non-None arm of
    # RaisesExc-style factories is ``(expected,)`` after parse identity.
    if len(class_actuals) == 1 and isinstance(arg, ComprehensionValue):
        return TupleValue(class_actuals)
    return None


def _call_coordinate(call: Call):
    from sugar_lift_py_tests.context_manager_resolution import (
        SourceFragmentCoordinateV1,
    )

    span = call.line_col_span()
    return SourceFragmentCoordinateV1(
        call.unit.source_cid,
        span.start_line,
        span.start_col,
        span.end_line,
        span.end_col,
    )


def _call_callee_coordinate(call: Call):
    from sugar_lift_py_tests.context_manager_resolution import (
        SourceFragmentCoordinateV1,
    )

    span = call.func.line_col_span()
    return SourceFragmentCoordinateV1(
        call.unit.source_cid,
        span.start_line,
        span.start_col,
        span.end_line,
        span.end_col,
    )


def _seat_import_value_use_receipts(
    *,
    source_file,
    module,
    target: Node,
    session: SourceResolutionSession,
    context: TreeConstructionContextV1,
    dependency_graphs: dict[str, DependencyArtifactGraph],
) -> None:
    """Seat authenticated value-use receipts owned by this exact frame target.

    Receipts are minted once via ``authenticated_import_value_use_receipts``
    (source-CID authenticated; dual-door / mismatch raises).  Resolution reads
    the graph of the top named by the receipt's authenticated module identity,
    authenticating it on ask like every other door (never a spelling), so the
    answer does not depend on which tops earlier work happened to seat.
    Seating requires exact unit source_cid + validated span.  A top no
    artifact authenticates, or a non-resolved import, leaves that coordinate
    unseated (consume stays typed-loud); CID/auth defects raise.
    """
    from pathlib import Path

    from sugar_lift_py_tests.context_manager_resolution import (
        SourceFragmentCoordinateV1,
    )
    from sugar_lift_python_source.canonical import blake3_512_of

    unit = source_file.unit
    unit_context = unit.construction_context
    if type(unit_context) is not TreeConstructionContextV1:
        from sugar_source_tree.panic import BackendDefect

        raise BackendDefect(
            blame=unit,
            owner="manager_construction._seat_import_value_use_receipts",
            observed="target SourceUnit has no exact construction context",
            requested="the exact SourceUnit-owned TreeConstructionContextV1",
            fix="construct the target SourceUnit with its manager-owned context",
        )
    # The target SourceUnit owns the context consumed by AttributeSugar.  A
    # caller's distinct context has no authority to receive this unit's rows.
    context = unit_context
    # Path-source law: refuse dual-door / mismatched CID loudly at mint.
    expected_cid = blake3_512_of(module.source.encode("utf-8"))
    if module.source_cid != expected_cid or unit.source_cid != module.source_cid:
        from sugar_source_tree.panic import BackendDefect

        raise BackendDefect(
            blame=module.source_seat,
            owner="manager_construction._seat_import_value_use_receipts",
            observed="source_cid mismatch with blake3(module.source)",
            requested="path_source identity (source, seat, blake3(source))",
            fix="refuse dual-door repair; re-mint module via path_source",
        )
    # No ValueError swallow: authenticated mint refuses tamper/mismatch loud.
    roster_key = (module.module_name, module.source_seat, module.source_cid)
    receipts = context.source_import_value_receipts.get(roster_key)
    if receipts is None:
        minted = _session_import_value_receipts(session, module)
        receipts = _retain_import_value_receipt_roster(context, module, tuple(minted))
    call_receipts = _session_import_use_receipts(session, module)
    calls_by_cid = {}
    for call_receipt in call_receipts:
        cid = call_receipt.use["cid"]
        if cid in calls_by_cid:
            from sugar_source_tree.panic import BackendDefect

            raise BackendDefect(
                blame=module.source_seat,
                owner="manager_construction import call/value receipt subsumption",
                observed="duplicate authenticated call receipt CID",
                requested="one call receipt for each authenticated use CID",
                fix="repair lexical call receipt enrollment uniqueness",
            )
        calls_by_cid[cid] = call_receipt
    owned_spans = [target.line_col_span()]
    owned_spans.extend(
        decorator.line_col_span() for decorator in getattr(target, "decorators", ())
    )
    owned_ranges = tuple(
        (
            (span.start_line, span.start_col),
            (span.end_line, span.end_col),
        )
        for span in owned_spans
    )
    for receipt in receipts:
        if receipt.source_cid != module.source_cid:
            raise ImportValueUseSeatingGap(
                "foreign-source-cid",
                "receipt source CID does not match the frame module",
            )
        site = receipt.use.get("useSite") or {}
        if site.get("sourceCid") != module.source_cid:
            raise ImportValueUseSeatingGap(
                "foreign-use-site-cid",
                "receipt useSite source CID does not match the frame module",
            )
        coordinate = SourceFragmentCoordinateV1(
            module.source_cid,
            site["startLine"],
            site["startCol"],
            site["endLine"],
            site["endCol"],
        )
        span_key = (
            site["startLine"],
            site["startCol"],
            site["endLine"],
            site["endCol"],
        )
        # Session-memoized module SourceFile is shared across definitions
        # (#7064). The first definition that owns a use seats it; later
        # definitions re-enter seating for the same unit. Re-seating a second
        # mint of the same span raises BackendDefect and aborts the whole
        # open — which discarded _json.py's 49-function roster (false zero).
        # Already-seated spans are closed; leave them alone.
        if unit.import_value_use_resolution(span_key) is not None:
            continue
        use_start = (site["startLine"], site["startCol"])
        use_end = (site["endLine"], site["endCol"])
        if not any(
            start <= use_start and use_end <= end for start, end in owned_ranges
        ):
            continue
        receipt.revalidate()
        paired_obligations = []
        for obligation in (
            row
            for roster in context.opaque_source_call_obligations.values()
            for row in roster.obligations
        ):
            relation = obligation.import_call_value_subsumption
            if relation is None or relation.value_use_cid != receipt.use["cid"]:
                continue
            call_receipt = calls_by_cid.get(relation.call_use_cid)
            if call_receipt is None:
                raise ImportValueUseSeatingGap(
                    "missing-call-receipt",
                    "subsumption relation cites no authenticated call receipt",
                )
            call_receipt.revalidate()
            from sugar_lift_python_source.canonical import cid_of_json

            identity = call_receipt.import_binding.value["target"]["moduleIdentity"]
            call_site = call_receipt.use["useSite"]
            value_site = receipt.use["useSite"]
            expected = (
                relation.source_cid == module.source_cid == receipt.source_cid
                and relation.module_identity_cid == cid_of_json(identity)
                and relation.import_binding_cid
                == call_receipt.import_binding.cid
                == receipt.import_binding.cid
                and relation.target_symbol
                == call_receipt.target_symbol
                == receipt.target_symbol
                and relation.exported_member_path
                == tuple(receipt.use["exportedMemberPath"])
                and relation.call_use_cid == call_receipt.use["cid"]
                and relation.value_use_cid == receipt.use["cid"]
                and (
                    relation.call_coordinate.start_line,
                    relation.call_coordinate.start_col,
                    relation.call_coordinate.end_line,
                    relation.call_coordinate.end_col,
                )
                == (
                    call_site["startLine"],
                    call_site["startCol"],
                    call_site["endLine"],
                    call_site["endCol"],
                )
                and relation.callee_coordinate.wire() == value_site
                and relation.callee_coordinate == coordinate
                and relation.call_coordinate == obligation.coordinate
                and relation.resolution_kind == obligation.resolution_kind
                and relation.resolved_object_cid == obligation.resolved_object_cid
            )
            if not expected:
                from sugar_source_tree.panic import BackendDefect

                raise BackendDefect(
                    blame=coordinate,
                    owner="manager_construction import call/value receipt subsumption",
                    observed="parked call/value relation disagrees with authenticated receipts",
                    requested="byte-identical one-to-one imported call/value relation",
                    fix="re-mint the relation from the exact lexical call and value receipts",
                )
            paired_obligations.append(obligation)
        paired_obligations = tuple(paired_obligations)
        # The law is one parked CALL per imported value occurrence. Several
        # authenticated owners may have walked through that one call, and each
        # parks its own obligation there; counting owners as calls would refuse
        # a helper reached from two exports. Count coordinates.
        if len({row.coordinate for row in paired_obligations}) > 1:
            from sugar_source_tree.panic import BackendDefect

            raise BackendDefect(
                blame=coordinate,
                owner="manager_construction import call/value receipt subsumption",
                observed="multiple parked calls claim one imported value occurrence",
                requested="one exact parked call/value receipt relation",
                fix="repair call receipt uniqueness before value seating",
            )

        def exact_parked_callee() -> bool:
            # One coordinate, however many owners parked at it (checked above).
            if not paired_obligations:
                return False
            relation = paired_obligations[0].import_call_value_subsumption
            if relation is None:
                return False
            stack = [target]
            while stack:
                node = stack.pop()
                if (
                    isinstance(node, Call)
                    and _call_coordinate(node) == relation.call_coordinate
                    and _call_callee_coordinate(node) == relation.callee_coordinate
                ):
                    return True
                stack.extend(child for _, _, child in node.children())
            return False

        def seat_receipt() -> None:
            # Already seated on this unit (shared session module product): done.
            if unit.import_value_use_resolution(span_key) is not None:
                return
            transport_key = (
                unit.filename,
                module.source_cid,
                *span_key,
            )
            transported = context.source_import_value_receipts_by_site.get(
                transport_key
            )
            if transported is not None and transported is not receipt:
                from sugar_source_tree.panic import BackendDefect

                raise BackendDefect(
                    blame=coordinate,
                    owner="manager_construction import value receipt transport",
                    observed="conflicting receipt at exact module/use occurrence",
                    requested="one producer-owned receipt object per exact site",
                    fix="preserve receipt identity across parser-owned SourceUnits",
                )
            context.source_import_value_receipts_by_site[transport_key] = receipt
            unit.seat_import_value_use_resolution(
                span_key, receipt, source_cid=module.source_cid
            )

        identity = receipt.import_binding.value["target"]["moduleIdentity"]
        if identity["kind"] == "authenticated-python-module":
            dependency_module = identity["moduleName"]
        elif identity["kind"] == "unavailable-python-module":
            dependency_module = identity["name"]
        else:
            raise ImportValueUseSeatingGap(
                "malformed-module-identity",
                f"unsupported receipt module identity {identity['kind']!r}",
            )
        top_level = dependency_module.split(".", 1)[0]
        # The receipt's authenticated module identity names the top this use
        # needs, and this door authenticates it when it asks, like the call
        # door beside it.  Reading only the tops seated so far made the answer
        # traversal history: ``os`` unseated on a cold open left
        # ``os.environ.get`` a bare receipt, while a walk whose earlier file
        # had seated ``os`` refused the same frame (#7678).
        from .dependency_artifact import DependencyArtifactAuthenticationError

        try:
            dependency_graph = _dependency_graph_for_top(
                top_level, session=session, dependency_graphs=dependency_graphs
            )
        except DependencyArtifactAuthenticationError:
            # No artifact authenticates for this top, on any traversal: an
            # absent graph carries no source authority.  Leave the exact
            # import-use coordinate unseated; any consumer that needs it stays
            # typed-loud at its ordinary resolution door.
            seat_receipt()
            continue
        binding_target = receipt.import_binding.value["target"]
        if (
            binding_target["exportedPath"] == []
            and receipt.use.get("exportedMemberPath") == []
        ):
            # A module-alias value is authenticated import testimony, but it
            # is not a callable definition to seat on this SourceUnit.  Its
            # attributed member carries its own later receipt and exact use
            # coordinate; only that member may become a source call frame.
            seat_receipt()
            continue
        imported = resolve_import_binding(
            receipt, graph=dependency_graph, session=session
        )
        if (
            not isinstance(imported, ResolvedPythonObjectV1)
            and imported.kind == "target-outside-binding"
        ):
            aliased = _resolve_through_module_alias(
                receipt,
                dependency_graph,
                session=session,
                dependency_graphs=dependency_graphs,
            )
            if aliased is not None:
                # The member lives in the alias module's own artifact.
                imported, dependency_graph = aliased
        if not isinstance(imported, ResolvedPythonObjectV1):
            if imported.kind in {
                "dynamic-export",
                "static-export-absent",
                "reexport-cycle",
            }:
                # Honest open-world value exports carry no definition
                # coordinate to seat. Leave the exact use unresolved so its
                # ordinary consumer remains typed-loud if execution reaches
                # it; unrelated construction must not turn that absence into
                # module-wide refusal.
                seat_receipt()
                continue
            if exact_parked_callee():
                # The exact call receipt already owns this callable occurrence
                # and remains parked/loud at the full Call coordinate: the call
                # door cited it opaque under its own resolution kind (an
                # ambiguous export, or ``os.environ.get`` /
                # ``parser_defaults.items`` whose member is reached through a
                # module-level instance, ``target-outside-binding``, cited
                # ``call-target-source-absent``).  The callee's duplicate
                # Attribute value receipt is the same occurrence: it is
                # deliberately unseated and not refused a second time; no
                # candidate definition or runtime branch is selected (#7723).
                continue
            if imported.kind == "ambiguous-static-export":
                # Ambiguity at a non-callee value site cannot borrow a nearby
                # parked Call's refusal.  Preserve the authenticated value row
                # for its own Attribute consumer, which remains responsible
                # for deciding whether that value is usable.
                seat_receipt()
                continue
            # A REAL gap: the authenticated target is not reachable through
            # the binding it claims.  It stays a countable terminal, but
            # receipt seating walks the ENTIRE frame span while the manager's
            # exit CONTRACT only reaches the value-uses on its suppress/raise
            # decision path.  Raising here voids the whole manager even when
            # this unresolved value is reached only on a failure-MESSAGE branch
            # the contract never takes (pytest's ``_config.get_verbosity``
            # inside ``RaisesExc._check_match``).  So DEFER the refusal: record
            # a reachability-scoped marker at the exact use.  Do NOT seat the
            # receipt (the neighbouring ``seat_receipt(); continue`` arms are
            # honest open-world EXPORTS; seating this would let an unresolved
            # value ride as authenticated).  The value-use CONSUMER
            # (AttributeSugar / Attribute._construct_sugar) mints the identical
            # ``ImportValueUseResolutionGap`` if and when the force-floor
            # actually reaches the coordinate; an unreached message-only use is
            # never consumed, so the manager constructs.
            from sugar_source_tree.panic import UnresolvedImportValueUseV1

            marker = UnresolvedImportValueUseV1(
                resolution_kind=imported.kind,
                target_symbol=receipt.target_symbol,
                dependency_module=dependency_module,
            )
            from sugar_lift_python_source.message_only_value_use import (
                frame_value_use_is_message_only,
            )

            if frame_value_use_is_message_only(target, span_key):
                # PROVABLY message-only within this frame: the unresolved value
                # cannot reach the exit contract's suppress/raise decision.
                # Defer -- the consumer mints the countable gap only if the
                # force-floor reaches it, and an unreached message use lets the
                # manager construct.
                unit.defer_unresolved_import_value_use(
                    span_key, marker, source_cid=module.source_cid
                )
                continue
            # Decision-reaching, or not provably message-only: refuse NOW.  This
            # keeps the early abort that bounds construction cost for frames
            # whose unresolved value gates deep materialization (io/json/_json.py),
            # and is the identical countable ImportValueUseResolutionGap.
            raise marker.as_gap(blame=coordinate)
        seat_receipt()
        context.source_import_value_resolutions[coordinate] = imported
        unit.seat_import_value_use_resolution(
            span_key, imported, source_cid=module.source_cid
        )


def _resolve_through_module_alias(
    receipt, dependency_graph, *, session, dependency_graphs
):
    """``import os`` then ``os.path.expanduser``: the member of ``os``'s alias.

    ``os.path`` is no submodule in ``os``'s artifact: ``os`` binds ``path`` by
    ``import posixpath as path`` (on this interpreter; see
    ``module_alias_binding``).  The member is resolved in that module, through
    the one export door, under the receipt's own binding.  Anything else
    returns None and the receipt's gap stands.  Returns the resolved member
    and the artifact graph it was resolved in.
    """
    from .dependency_artifact import (
        module_alias_binding,
        resolve_authenticated_module_export,
    )

    target = receipt.import_binding.value["target"]
    identity = target["moduleIdentity"]
    if target["exportedPath"] != []:
        return None
    if identity.get("kind") == "authenticated-python-module":
        module_name = identity["moduleName"]
    elif identity.get("kind") == "unavailable-python-module":
        module_name = identity["name"]
    else:
        return None
    requested = receipt.target_symbol.removeprefix("python:").split(".")
    base = module_name.split(".")
    path = requested[len(base) :]
    member_path = receipt.use.get("exportedMemberPath")
    if (
        requested[: len(base)] != base
        or len(path) != 2
        or (member_path is not None and list(member_path) != path)
    ):
        return None
    alias = module_alias_binding(dependency_graph, module_name, path[0])
    if alias is None:
        return None
    alias_graph = _dependency_graph_for_top(
        alias.split(".", 1)[0], session=session, dependency_graphs=dependency_graphs
    )
    if alias not in alias_graph.modules:
        return None
    resolved = resolve_authenticated_module_export(
        graph=alias_graph,
        binding_cid=receipt.import_binding.cid,
        module_name=alias,
        exported_name=path[1],
        session=session,
    )
    if not isinstance(resolved, ResolvedPythonObjectV1):
        return None
    return resolved, alias_graph


def _retain_import_value_receipt_roster(
    context: TreeConstructionContextV1,
    module,
    receipts: tuple,
) -> tuple:
    """Retain one producer roster under its exact authenticated module seat."""
    from sugar_lift_py_tests.import_binding import module_name_for_path
    from sugar_source_tree.panic import BackendDefect

    key = (module.module_name, module.source_seat, module.source_cid)
    seen = set()
    identities = []
    for receipt in receipts:
        receipt.revalidate()
        receipt_module = module_name_for_path(receipt.root, receipt.path)
        try:
            receipt_seat = receipt.path.relative_to(receipt.root).as_posix()
        except ValueError:
            receipt_seat = ""
        if (
            receipt.source_cid != module.source_cid
            or receipt.source != module.source
            or receipt_module != module.module_name
            or receipt_seat != module.source_seat
        ):
            raise BackendDefect(
                blame=module.source_seat,
                owner="manager_construction import value receipt roster",
                observed="receipt has foreign authenticated module identity",
                requested="same module name, source seat, source CID, and bytes",
                fix="retain the producer roster only under its own module identity",
            )
        site = receipt.use["useSite"]
        row_key = (
            site["startLine"],
            site["startCol"],
            site["endLine"],
            site["endCol"],
        )
        if row_key in seen:
            raise BackendDefect(
                blame=row_key,
                owner="manager_construction import value receipt roster",
                observed="duplicate exact value-use row",
                requested="one producer receipt per exact occurrence",
                fix="repair lexical receipt enrollment before retaining the roster",
            )
        seen.add(row_key)
        identities.append(
            (
                row_key,
                receipt.target_symbol,
                receipt.import_binding.cid,
                receipt.use["cid"],
                tuple(receipt.use["exportedMemberPath"]),
            )
        )
    existing = context.source_import_value_receipts.get(key)
    if existing is None:
        context.source_import_value_receipts[key] = receipts
        return receipts
    existing_identities = tuple(
        (
            (
                row.use["useSite"]["startLine"],
                row.use["useSite"]["startCol"],
                row.use["useSite"]["endLine"],
                row.use["useSite"]["endCol"],
            ),
            row.target_symbol,
            row.import_binding.cid,
            row.use["cid"],
            tuple(row.use["exportedMemberPath"]),
        )
        for row in existing
    )
    if existing_identities != tuple(identities):
        raise BackendDefect(
            blame=module.source_seat,
            owner="manager_construction import value receipt roster",
            observed="conflicting exact value-use row identities",
            requested="byte-identical target/binding/use/member roster",
            fix="preserve the first producer-owned roster unchanged",
        )
    return existing


def _install_opaque_call_obligation(
    context: TreeConstructionContextV1,
    call: Call,
    obligation: OpaqueSourceCallObligationV1,
) -> None:
    from sugar_source_tree.panic import BackendDefect

    coordinate = _call_coordinate(call)
    if obligation.coordinate != coordinate:
        raise BackendDefect(
            blame=call.fragment,
            owner="manager_construction._install_opaque_call_obligation",
            observed="obligation/call coordinate mismatch",
            requested="exact source-call coordinate testimony",
            fix="mint the obligation from the call being installed",
        )
    if coordinate in context.source_call_frames:
        raise BackendDefect(
            blame=call.fragment,
            owner="manager_construction._install_opaque_call_obligation",
            observed="frame/obligation collision",
            requested="one source-call classification at the exact coordinate",
            fix="keep authenticated frames and opaque obligations disjoint",
        )
    from sugar_lift_py_tests.context_manager_resolution import (
        opaque_source_call_roster_of,
    )

    # One coordinate, many authenticated owners. `resolved_object_cid` names
    # the export whose frame projection walked through this call, not the call
    # — so a second owner reaching the same helper (or the same callee through
    # a second import binding) is an ADDITIONAL seat, never a duplicate. The
    # byte-identity law below is unchanged and applies where it always meant
    # to: one owner may state its testimony exactly once, exactly the same way.
    existing = context.opaque_source_call_obligations.get(coordinate)
    if existing is None:
        context.opaque_source_call_obligations[coordinate] = (
            opaque_source_call_roster_of(obligation)
        )
        _seat_opaque_cited_manager_ref(context, coordinate)
        return
    seated = existing.owner(obligation.resolved_object_cid)
    if seated is not None:
        if seated != obligation:
            raise BackendDefect(
                blame=call.fragment,
                owner="manager_construction._install_opaque_call_obligation",
                observed="conflicting opaque-call obligation",
                requested="byte-identical duplicate testimony",
                fix="resolve the conflicting target or authenticated owner",
            )
        return
    if (existing.target_name, existing.resolution_kind) != (
        obligation.target_name,
        obligation.resolution_kind,
    ):
        # Not a keying artefact: two authenticated owners state DIFFERENT
        # unresolved-callee classifications for one call, and the consumer
        # holds no owner with which to choose. A construction panic is a
        # countable frontier row; a BackendDefect here would void the file.
        from sugar_lift_py_tests.gap import construction_panic_gap

        construction_panic_gap(
            owner="manager_construction._install_opaque_call_obligation",
            blame=call.fragment,
            observed=(
                "authenticated owners disagree about one opaque call: "
                f"{existing.resolution_kind}:{existing.target_name} vs "
                f"{obligation.resolution_kind}:{obligation.target_name}"
            ),
            requested="one opaque-call classification at the exact coordinate",
            fix="resolve the callee for every owner, or name why they differ",
        )
    context.opaque_source_call_obligations[coordinate] = existing.seating(obligation)
    _seat_opaque_cited_manager_ref(context, coordinate)


def _seat_opaque_cited_manager_ref(
    context: TreeConstructionContextV1,
    coordinate,
) -> None:
    """Seat the positive citation for an OFF-POPULATION call, and only that.

    The ``with`` door must never infer opacity from the absence of a contract.
    So the producer that authenticated the callee and classified it
    off-population seats the claim here, positively, at the exact coordinate
    the manager use-site will read.  ``With._prebound_manager_resolution``
    then finds it through the existing ``source_derived_contract_refs`` lookup
    with no consumer-side inference at all.

    ONLY ``call-target-off-population`` is cited.  The sibling kinds are a
    different fact and must not share this spelling:

    - ``call-target-export-unresolved`` -- we FAILED TO LOOK UP the callee.
      That is lookup-failure, and citing it would claim we know which callee
      is opaque when we do not even know which callee it is.
    - ``call-graph-cycle`` -- a construction limit of ours, not a property of
      the target.

    Off-population is the only kind where the callee IS authenticated and the
    only missing thing is its body, by deliberate measurement policy. That is
    the precise condition under which "we authenticate that we do not know"
    is a true statement.
    """
    from sugar_lift_py_tests.context_manager_resolution import (
        OpaqueCitedContextManagerRefV1,
        mint_opaque_cited_context_manager_ref,
    )

    roster = context.opaque_source_call_obligations.get(coordinate)
    if roster is None or roster.resolution_kind != "call-target-off-population":
        return
    seated = context.source_derived_contract_refs.get(coordinate)
    if seated is not None and not isinstance(seated, OpaqueCitedContextManagerRefV1):
        # A real derived contract already stands here. Known beats unknown;
        # never downgrade authenticated enter/exit testimony to a citation.
        return
    context.source_derived_contract_refs[coordinate] = (
        mint_opaque_cited_context_manager_ref(roster=roster)
    )


def _install_source_call_frame(
    context: TreeConstructionContextV1,
    call: Call,
    frame: object,
) -> None:
    from sugar_source_tree.panic import BackendDefect

    coordinate = _call_coordinate(call)
    if coordinate in context.opaque_source_call_obligations:
        raise BackendDefect(
            blame=call.fragment,
            owner="manager_construction._install_source_call_frame",
            observed="frame/obligation collision",
            requested="one source-call classification at the exact coordinate",
            fix="keep authenticated frames and opaque obligations disjoint",
        )
    existing = context.source_call_frames.get(coordinate)
    if existing is not None and existing != frame:
        raise BackendDefect(
            blame=call.fragment,
            owner="manager_construction._install_source_call_frame",
            observed="conflicting source-call frame",
            requested="byte-identical duplicate frame testimony",
            fix="resolve the conflicting authenticated source frame",
        )
    context.source_call_frames[coordinate] = frame
