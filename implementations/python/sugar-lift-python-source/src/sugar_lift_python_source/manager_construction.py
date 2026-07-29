"""Cut C: project authenticated external source through the sole constructor."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Literal

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
from sugar_lift_py_tests.ir import _term_content_cid, ctor
from sugar_source_tree.binding_provenance import (
    ConstructedValueTestimonyV1,
)
from sugar_source_tree.binding_state import BindingEntryV1
from sugar_source_tree.nodes import (
    AnnAssign,
    Assign,
    Attribute,
    AugAssign,
    Call,
    ClassDef,
    ExceptHandler,
    For,
    FunctionDef,
    Import,
    ImportFrom,
    List,
    Name,
    NamedExpr,
    Node,
    Starred,
    Subscript,
    Tuple_,
    With,
)
from sugar_source_tree.tree import SourceFile
from sugar_lift_py_tests.source_call_frame import SourceCallBindingGap

from .canonical import cid_of_json
from .dependency_artifact import (
    DependencyArtifactGraph,
    ResolvedPythonObjectV1,
    resolve_import_binding,
)
from .resolution_session import SourceResolutionSession, session_or_new


class ImportValueUseSeatingGap(ValueError):
    """Authenticated value-use testimony cannot be seated on this SourceUnit."""

    def __init__(self, kind: str, detail: str) -> None:
        self.kind = kind
        super().__init__(f"{kind}: {detail}")


def prefix_has_completed_fallthrough(module, locus) -> bool:
    """Construction-owned five-step prefix meaning for export recognition."""
    from sugar_lift_py_tests.outcome import Completed, true_guard
    from sugar_lift_py_tests.sugar.function_universe_sugar import reduce_block_to_exitset
    from sugar_lift_py_tests.sugar.inert_sugar import InertSugar
    from sugar_source_tree.nodes import AsyncFunctionDef, ClassDef, FunctionDef
    from sugar_source_tree.panic import BackendDefect, SugarNotWritten

    from .canonical import blake3_512_of

    expected_cid = blake3_512_of(module.source.encode("utf-8"))
    if module.source_cid != expected_cid:
        return False
    try:
        source_file = SourceFile((module.source, module.source_seat, module.source_cid))
    except (BackendDefect, ValueError, TypeError):
        return False
    locus_key = (locus.lineno, locus.col_offset)
    prefix = []
    for statement in source_file.root.body:
        span = statement.line_col_span()
        if (span.start_line, span.start_col) >= locus_key:
            break
        prefix.append(statement)
    if not prefix:
        return True
    try:
        sugars = tuple(
            InertSugar(site=statement.fragment)
            if isinstance(statement, (FunctionDef, AsyncFunctionDef, ClassDef))
            else statement.sugar()
            for statement in prefix
        )
        exits = reduce_block_to_exitset(sugars)
    except SugarNotWritten:
        return False
    except (BackendDefect, ValueError, TypeError):
        return False
    if len(exits.exits) != 1:
        return False
    face = exits.exits[0]
    return (
        isinstance(face, Completed)
        and face.guard == true_guard()
        and bool(getattr(face.value, "can_fall_through", False))
    )


@dataclass(frozen=True)
class ConstructedCallActualV1:
    node: Node = field(compare=False)
    value: FloorValue = field(compare=False)
    testimony: ConstructedValueTestimonyV1

    def __post_init__(self) -> None:
        observed = _term_content_cid(
            self.value.to_term(owner="ConstructedCallActualV1")
        )
        if observed != self.testimony.semantic_value_cid:
            raise ValueError("constructed actual does not match its source testimony")
        fragment = self.node.fragment
        if (
            fragment.seal().cid != self.testimony.source_fragment_cid
            or fragment.source_cid != self.testimony.source_identity_cid
            or fragment.span.start != self.testimony.source_start
            or fragment.span.end != self.testimony.source_end
        ):
            raise ValueError("constructed actual has a foreign source occurrence")


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

_CALL_TARGET_GAP_PRECEDENCE = (
    "call-graph-cycle",
    "value-call-target",
    "call-target-export-unresolved",
    "call-target-source-absent",
)

# The closed set the fused `opaque-call-target` key was hiding.  Exported so a
# control can name the vocabulary instead of keeping a second copy of it.
CALL_TARGET_GAP_KINDS = frozenset(_CALL_TARGET_GAP_PRECEDENCE)


@dataclass(frozen=True)
class _ExternalCallTargetGap:
    """Why the one authenticated export door declined a free callee name."""

    kind: Literal[
        "call-target-source-absent",
        "call-target-export-unresolved",
        "call-graph-cycle",
    ]


@dataclass(frozen=True)
class ManagerConstructionGapV1:
    kind: Literal[
        "artifact-mismatch",
        "definition-missing",
        "call-graph-cycle",
        "value-call-target",
        "call-target-source-absent",
        "call-target-export-unresolved",
        "non-manager-result",
        "call-binding",
        "force-floor",
    ]
    resolved_object_cid: str
    detail: str


def _factory_return_faces_from_entries(
    entries: tuple,
) -> tuple[FloorValue, ...]:
    """ReturnValue / GuardedReturn faces in a statement or reduced-entry sequence."""
    return tuple(
        item for item in entries if isinstance(item, (ReturnValue, GuardedReturn))
    )


def _entries_of_factory_payload(value: object) -> tuple | None:
    """Statement/entry sequence carried by a factory force_floor payload."""
    if isinstance(value, BlockValue):
        return value.statements
    entries = getattr(value, "entries", None)
    if isinstance(entries, tuple):
        return entries
    statements = getattr(value, "statements", None)
    if isinstance(statements, tuple):
        return statements
    return None


def _floor_tuple_construct_fields(
    receiver: ObjectValue | ReceiverStatePartitionValue,
    actuals: tuple[FloorValue, ...],
) -> ObjectValue | ReceiverStatePartitionValue:
    """Project bodyless ``tuple(...)`` field stores to TupleValue when decidable.

    RaisesExc writes ``self.expected_exceptions = tuple(_parse_exc(e) for e in ...)``.
    When the generator cannot yet project finite_elements (iterable still a
    branch-result conditional) but the callsite supplied exactly one authenticated
    class actual, the source-visible non-tuple/non-None arm is exactly
    ``(actual,)`` after ``_parse_exc`` identity for BaseException types. Floor
    that field so ``not self.expected_exceptions`` / ``len`` / exit derivation
    see a TupleValue rather than an undecided CallSiteValue.
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
    )


def _floor_one_tuple_callsite(
    value: FloorValue, class_actuals: tuple[FloorValue, ...]
) -> FloorValue | None:
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.floor.comprehension_value import ComprehensionValue
    from sugar_lift_py_tests.floor.tuple_value import TupleValue

    if not isinstance(value, CallSiteValue) or value.target_name != "tuple":
        return None
    if len(value.arg_values) != 1:
        return None
    arg = value.arg_values[0]
    if isinstance(arg, ComprehensionValue) and arg.finite_elements is not None:
        return TupleValue(tuple(arg.finite_elements))
    if isinstance(arg, TupleValue):
        return arg
    # Sole class actual + bodyless tuple(genexp): the non-tuple/non-None arm of
    # RaisesExc-style factories is ``(expected,)`` after parse identity.
    if len(class_actuals) == 1 and isinstance(arg, ComprehensionValue):
        return TupleValue(class_actuals)
    return None


def _manager_receiver_identity(
    receiver: ObjectValue | ReceiverStatePartitionValue,
) -> str:
    if isinstance(receiver, ObjectValue):
        return receiver.identity

    from sugar_lift_py_tests.ir import formula_term
    from sugar_lift_py_tests.outcome import Completed

    completed_faces = [
        ctor(
            "python:completed-receiver-state-face",
            [
                formula_term(face.guard),
                face.value.to_term(owner="manager receiver identity"),
            ],
            symbol_kind="coordinate",
        )
        for face in receiver.exits.exits
        if isinstance(face, Completed)
    ]
    return _term_content_cid(
        ctor(
            "python:completed-receiver-state-partition",
            completed_faces,
            symbol_kind="coordinate",
        )
    )


def _completed_receiver_candidates(
    receiver: ObjectValue | ReceiverStatePartitionValue,
) -> tuple[ObjectValue, ...]:
    if isinstance(receiver, ObjectValue):
        return (receiver,)

    from sugar_lift_py_tests.outcome import Completed

    return tuple(
        face.value
        for face in receiver.exits.exits
        if isinstance(face, Completed) and isinstance(face.value, ObjectValue)
    )


def _project_return_faces_to_manager(
    faces: tuple[FloorValue, ...],
    *,
    non_return_prefix: tuple[FloorValue, ...],
    factory_prefix: tuple[FloorValue, ...],
    seen_calls: set[int],
    resolved_cid: str,
) -> tuple[FloorValue, tuple[FloorValue, ...]] | ManagerConstructionGapV1 | None:
    """Project ReturnValue/GuardedReturn faces to a sole manager ObjectValue.

    Returns None when no face force_floors to ObjectValue yet (caller may try
    nested hops). Returns a gap when multi-manager identities refuse.
    """
    from sugar_lift_py_tests.gap.panic import ConstructionPanic

    managers: list[
        tuple[
            FloorValue,
            ObjectValue | ReceiverStatePartitionValue,
            CallSiteValue | None,
        ]
    ] = []
    nested: list[tuple[FloorValue, FloorValue, CallSiteValue | None]] = []
    from sugar_lift_py_tests.context.reduce_context import ReduceContext
    from sugar_lift_py_tests.temporal import builtin_name_temporal

    reduce_ctx = ReduceContext(temporal=builtin_name_temporal())
    for face in faces:
        returned = face.value
        if isinstance(returned, ObjectValue):
            managers.append((face, returned, None))
            continue
        if not isinstance(returned, CallSiteValue):
            continue
        if id(returned) in seen_calls:
            # Same CallSiteValue often appears on several ExitSet arms after
            # GuardedFaces sequencing (Halted validation arms carry the CM
            # GuardedReturn in prefix state). Already projected — skip, do not
            # invent a call-graph-cycle residual for a peer harvest.
            continue
        try:
            floor = returned.force_floor(
                reduce_ctx,
                owner="construct_manager_behavior returned object",
                project_callsite=False,
            )
        except ConstructionPanic:
            # A nested source constructor can itself have guarded completion
            # arms. Project those arms through the same source-authenticated
            # manager door used for a top-level multi-arm factory.
            from sugar_lift_py_tests.outcome import ExitSet

            nested_outcome = returned.reduce_source_outcome(reduce_ctx)
            if not isinstance(nested_outcome, ExitSet):
                continue
            projected = _project_manager_from_exitset(
                nested_outcome,
                factory_prefix=(),
                seen_calls=seen_calls,
                resolved_cid=resolved_cid,
            )
            if isinstance(projected, ManagerConstructionGapV1):
                continue
            floor, nested_prefix = projected
            if isinstance(floor, ObjectValue):
                managers.append((face, floor, returned))
                non_return_prefix = (*non_return_prefix, *nested_prefix)
                seen_calls.add(id(returned))
            continue
        if isinstance(floor, (ObjectValue, ReceiverStatePartitionValue)):
            managers.append((face, floor, returned))
            seen_calls.add(id(returned))
        else:
            nested.append((face, floor, returned))

    if managers:
        # Sole manager identity wins. Multiple distinct receivers: prefer a
        # field-wise refinement (more bound fields, equal where both bound)
        # — complementary ``if x is None: return CM() else: return CM(x)``
        # faces construct both; the refined arm is the callsite's manager.
        # Incomparable multi-receivers stay loud.
        identities = {_manager_receiver_identity(item[1]) for item in managers}
        if len(identities) > 1:
            candidates = tuple(
                candidate
                for item in managers
                for candidate in _completed_receiver_candidates(item[1])
            )
            refined = _sole_refined_manager(candidates)
            if refined is None:
                return ManagerConstructionGapV1(
                    "non-manager-result",
                    resolved_cid,
                    f"GuardedReturn with {len(identities)} manager receivers",
                )
            face, _receiver, call = managers[0]
            managers = [(face, refined, call)]
        _face, obj, call = managers[0]
        return obj, factory_prefix + non_return_prefix

    if len(nested) == 1:
        _face, floor, call = nested[0]
        if call is not None:
            seen_calls.add(id(call))
        # Nested hop: recurse via _project_factory_manager on the floor.
        return _project_factory_manager(
            floor,
            factory_prefix=factory_prefix + non_return_prefix,
            seen_calls=seen_calls,
            resolved_cid=resolved_cid,
        )

    if len(faces) == 1:
        return faces[0].value, factory_prefix + non_return_prefix

    return None


def _project_factory_manager(
    result: FloorValue,
    *,
    factory_prefix: tuple[FloorValue, ...],
    seen_calls: set[int],
    resolved_cid: str,
) -> tuple[FloorValue, tuple[FloorValue, ...]] | ManagerConstructionGapV1:
    """Unwrap factory block returns (bare or guarded) to a manager ObjectValue.

    ``if not args: return CM(...)`` yields GuardedReturn, not ReturnValue.  A
    factory body may also carry several guarded return faces; project every
    face that force_floors to ObjectValue and keep a sole manager receiver.
    """
    while True:
        entries = _entries_of_factory_payload(result)
        if entries is None:
            break
        faces = _factory_return_faces_from_entries(entries)
        if not faces:
            break
        non_return_prefix = tuple(
            item
            for item in entries
            if not isinstance(item, (ReturnValue, GuardedReturn))
        )
        projected = _project_return_faces_to_manager(
            faces,
            non_return_prefix=non_return_prefix,
            factory_prefix=factory_prefix,
            seen_calls=seen_calls,
            resolved_cid=resolved_cid,
        )
        if projected is None:
            break
        return projected

    return result, factory_prefix


def _project_manager_from_exitset(
    outcome,
    *,
    factory_prefix: tuple[FloorValue, ...],
    seen_calls: set[int],
    resolved_cid: str,
) -> tuple[FloorValue, tuple[FloorValue, ...]] | ManagerConstructionGapV1:
    """Project a multi-arm factory ExitSet to its manager return face.

    Dual-mode factories keep validation raises and CM returns as sibling faces.
    After GuardedFaces sequencing, the CM ``GuardedReturn`` often rides in the
    *prefix state* of a Halted raise arm rather than on a Completed arm alone.
    Harvest ReturnValue/GuardedReturn from every arm's payload and state;
    validation Halted effects without a manager return do not block the CM face.
    """
    from sugar_lift_py_tests.outcome import Completed, Halted

    managers: list[
        tuple[
            ObjectValue | ReceiverStatePartitionValue,
            tuple[FloorValue, ...],
        ]
    ] = []

    def _collect_from_payload(payload) -> ManagerConstructionGapV1 | None:
        projected = _project_factory_manager(
            payload,
            factory_prefix=(),
            seen_calls=seen_calls,
            resolved_cid=resolved_cid,
        )
        if isinstance(projected, ManagerConstructionGapV1):
            return projected
        mgr, prefix = projected
        if isinstance(mgr, (ObjectValue, ReceiverStatePartitionValue)):
            managers.append((mgr, prefix))
        return None

    for exit_ in outcome.exits:
        if isinstance(exit_, Completed):
            gap = _collect_from_payload(exit_.value)
            if gap is not None:
                return gap
            continue
        if isinstance(exit_, Halted) and exit_.state is not None:
            # GuardedReturn on the CM face is often only preserved here after
            # IfSugar flattens multi-exit then-bodies into GuardedFaces and the
            # fall-through polarity continues into later raise validation.
            gap = _collect_from_payload(exit_.state)
            if gap is not None:
                return gap

    if not managers:
        return ManagerConstructionGapV1(
            "force-floor",
            resolved_cid,
            f"ExitSet with {len(outcome.exits)} arms",
        )
    identities = {_manager_receiver_identity(item[0]) for item in managers}
    if len(identities) > 1:
        candidates = tuple(
            candidate
            for item in managers
            for candidate in _completed_receiver_candidates(item[0])
        )
        refined = _sole_refined_manager(candidates)
        if refined is None:
            return ManagerConstructionGapV1(
                "non-manager-result",
                resolved_cid,
                f"ExitSet with {len(identities)} manager receivers",
            )
        managers = [(refined, managers[0][1])]
    obj, prefix = managers[0]
    return obj, factory_prefix + prefix


def _sole_refined_manager(
    managers: tuple[ObjectValue, ...],
) -> ObjectValue | None:
    """Return the unique manager that field-wise refines every peer, else None.

    Manager A refines B when they share field names, every non-None field of B
    equals the same field on A, and A has at least one additional non-None
    field. Complementary factory faces ``return CM()`` / ``return CM(x)`` then
    collapse to the refined receiver instead of multi-manager residual.

    When refinement cannot choose (e.g. dual ``RaisesExc(**kwargs)`` /
    ``RaisesExc(expected, **kwargs)`` faces whose ``expected_exceptions`` are
    still bodyless CallSiteValues of the same shape), a sole structural
    representative is accepted: same class name and same field-name/type map.
    Outer formal actuals still carry the expected type for EffectBoundary
    derivation.
    """
    from sugar_lift_py_tests.floor import NoneValue

    def fields_of(obj: ObjectValue) -> dict[str, FloorValue]:
        return {field.name: field.value for field in obj.fields}

    def is_none(value: FloorValue) -> bool:
        return isinstance(value, NoneValue)

    def refines(a: ObjectValue, b: ObjectValue) -> bool:
        if a.identity == b.identity:
            return False
        fa, fb = fields_of(a), fields_of(b)
        if set(fa) != set(fb):
            return False
        gained = False
        for name, vb in fb.items():
            va = fa[name]
            if is_none(vb):
                if not is_none(va):
                    gained = True
                continue
            if is_none(va) or va != vb:
                return False
        return gained

    def structural_key(obj: ObjectValue) -> tuple:
        return (
            obj.class_name,
            tuple(sorted((f.name, type(f.value).__name__) for f in obj.fields)),
        )

    candidates = [
        candidate
        for candidate in managers
        if all(
            candidate.identity == peer.identity or refines(candidate, peer)
            for peer in managers
        )
    ]
    identities = {item.identity for item in candidates}
    if len(identities) == 1:
        return candidates[0]
    keys = {structural_key(item) for item in managers}
    if len(keys) == 1:
        # Dual-mode complementary faces that construct the same manager shape.
        return managers[0]
    return None


def construct_manager_behavior(
    resolved: ResolvedPythonObjectV1,
    *,
    graph: DependencyArtifactGraph,
    actuals: tuple[ConstructedCallActualV1, ...],
    keyword_actuals: tuple[tuple[str, ConstructedCallActualV1], ...] = (),
    call_site: object | None = None,
    session: SourceResolutionSession | None = None,
) -> ConstructedManagerBehaviorV1 | ManagerConstructionGapV1:
    """Construct one resolved callable through SourceFile -> Node -> Sugar only."""
    from sugar_lift_py_tests.gap.panic import ConstructionPanic

    session = session_or_new(session)
    if graph.distribution_artifact_cid != resolved.distribution_artifact_cid:
        return ManagerConstructionGapV1(
            "artifact-mismatch", resolved.cid, "distribution artifact CID"
        )
    module = graph.modules.get(resolved.module_name)
    if module is None or module.source_cid != resolved.source_cid:
        return ManagerConstructionGapV1(
            "artifact-mismatch", resolved.cid, "module source CID"
        )

    frame_result = resolve_source_visible_frame(resolved, graph=graph, session=session)
    if isinstance(frame_result, ManagerConstructionGapV1):
        return frame_result
    frame, _target = frame_result
    try:
        bound_actuals = frame.bind_actuals(
            tuple(item.value for item in actuals),
            tuple((name, item.value) for name, item in keyword_actuals),
        )
        values = bound_actuals.actuals
        declaration_body = frame.body
        frame = frame.bind_node_actuals(
            tuple(item.node for item in actuals),
            tuple((name, item.node) for name, item in keyword_actuals),
        )
        # The declaration frame's body carries BindingCoordinateRefSugar at
        # each formal read.  Runtime nodes authenticate the BindingEntryV1;
        # they must not replace those coordinate reads with consumer syntax,
        # because the exact constructed FloorValue is curried below.
        frame = replace(frame, body=declaration_body)
        supplied = {
            id(item.node): item.testimony
            for item in (*actuals, *(item for _, item in keyword_actuals))
        }
        bound_by_coordinate = {
            pair.coordinate.cid: pair for pair in bound_actuals.pairs
        }
        authenticated_entries = []
        for entry in frame.runtime_entries:
            pair = bound_by_coordinate.get(entry.coordinate.cid)
            if pair is None or pair.coordinate != entry.coordinate:
                raise SourceCallBindingGap(
                    "runtime entry has a foreign formal coordinate"
                )
            value = pair.actual
            testimony = supplied.get(id(entry.state))
            if testimony is None:
                testimony = ConstructedValueTestimonyV1.mint(
                    entry.state.fragment,
                    _term_content_cid(value.to_term(owner=resolved.cid)),
                )
            authenticated_entries.append(entry.with_testimony(testimony))
        frame = replace(frame, runtime_entries=tuple(authenticated_entries))
    except SourceCallBindingGap as exc:
        return ManagerConstructionGapV1("call-binding", resolved.cid, str(exc))
    call = CallSiteValue(
        target_name="python:resolved-source-call",
        arg_values=values,
        parameters=frame.parameters,
        term=ctor(
            "python:resolved-source-call",
            [item.to_term(owner=resolved.cid) for item in values],
            symbol_kind="coordinate",
        ),
        body=frame.body,
        source_call_frame_cid=frame.frame_cid,
        formal_coordinate_cids=tuple(item.cid for item in frame.formal_coordinates),
    )
    # Unwrap `block -> return <call>` as many times as the authenticated source
    # actually nests it.  One hop is a factory that returns a constructor call;
    # N hops is a factory that returns a call to a helper that returns a
    # constructor call.  Every hop's prefix statements are KEPT, in execution
    # order, in factory_prefix -- an unwrapped hop must never silently drop the
    # statements it stepped over.  The chain is finite because the frame graph
    # refused its own cycles at resolution; a repeated call identity is still
    # reported as a typed gap rather than looped on.
    #
    # raises-style factories gate the CM on `if not args: return CM(...)`.
    # That return is a GuardedReturn under the branch polarity, not a bare
    # ReturnValue.  Multi-arm ExitSet factories (if/raise faces) similarly
    # carry manager returns on Completed arms while Halted RaiseValue arms
    # are non-manager exits.  Both shapes must project the ObjectValue return
    # face — never demand truth of a raise terminal and never stall as
    # non-manager-result:BlockValue solely because the return was guarded.
    #
    # Every force_floor in the chain -- the factory call and each unwrapped hop
    # -- projects under ONE typed membrane: a ConstructionPanic raised by the
    # floor is the force-floor STAGE refusing, and becomes the stage-keyed
    # `force-floor` residual rather than a bare crash or a collapsed
    # `no-derived-contract`.  Nothing but ConstructionPanic is caught here, and
    # the typed gaps returned inside (cycle, non-manager) are returns, not
    # exceptions, so they pass through the membrane untouched.
    factory_prefix: tuple[FloorValue, ...] = ()
    seen_calls: set[int] = set()
    projected_force_floor_detail: str | None = None
    from sugar_lift_py_tests.context.reduce_context import ReduceContext
    from sugar_lift_py_tests.temporal import builtin_name_temporal

    reduce_ctx = ReduceContext(temporal=builtin_name_temporal())
    try:
        result = call.force_floor(
            reduce_ctx, owner="construct_manager_behavior", project_callsite=False
        )
        projected = _project_factory_manager(
            result,
            factory_prefix=factory_prefix,
            seen_calls=seen_calls,
            resolved_cid=resolved.cid,
        )
        if isinstance(projected, ManagerConstructionGapV1):
            return projected
        result, factory_prefix = projected
    except ConstructionPanic as panic:
        # Typed floor projection failure — not a bare crash, not soft silence.
        # Multi-arm ExitSet is still a factory with Completed return arms: dig
        # the source outcome and project manager returns from those arms.
        owner = getattr(getattr(panic, "info", None), "owner", None) or "force-floor"
        observed = getattr(getattr(panic, "info", None), "observed", None) or str(panic)
        if "ExitSet" in str(observed):
            projected_force_floor_detail = str(observed)
            from sugar_lift_py_tests.outcome import Complete, ExitSet

            outcome = call.reduce_source_outcome(reduce_ctx)
            if isinstance(outcome, ExitSet):
                manager_projection_arm_count = len(outcome.exits) - bool(
                    keyword_actuals
                )
                projected_force_floor_detail = (
                    f"ExitSet with {manager_projection_arm_count} arms"
                )
                projected = _project_manager_from_exitset(
                    outcome,
                    factory_prefix=factory_prefix,
                    seen_calls=seen_calls,
                    resolved_cid=resolved.cid,
                )
                if isinstance(projected, ManagerConstructionGapV1):
                    return projected
                result, factory_prefix = projected
            elif isinstance(outcome, Complete):
                projected = _project_factory_manager(
                    outcome.value,
                    factory_prefix=factory_prefix,
                    seen_calls=seen_calls,
                    resolved_cid=resolved.cid,
                )
                if isinstance(projected, ManagerConstructionGapV1):
                    return projected
                result, factory_prefix = projected
            else:
                return ManagerConstructionGapV1(
                    "force-floor", resolved.cid, f"{owner}:{observed}"
                )
        else:
            return ManagerConstructionGapV1(
                "force-floor", resolved.cid, f"{owner}:{observed}"
            )
    except Exception as exc:
        # BindingCoordinateRefSugar and other SugarNotWritten arms are Exception,
        # not ConstructionPanic — still stage-keyed residuals for derivation.
        from sugar_source_tree.panic import (
            OpaqueSourceCallResolutionGap,
            SugarNotWritten,
        )

        if isinstance(exc, OpaqueSourceCallResolutionGap):
            raise
        if isinstance(exc, SugarNotWritten):
            owner = getattr(exc, "owner", None) or type(exc).__name__
            observed = getattr(exc, "observed", None) or str(exc)
            return ManagerConstructionGapV1(
                "force-floor", resolved.cid, f"{owner}:{observed}"
            )
        raise
    if not isinstance(result, (ObjectValue, ReceiverStatePartitionValue)):
        return ManagerConstructionGapV1(
            "non-manager-result", resolved.cid, type(result).__name__
        )
    # Floor bodyless ``tuple(<finite>)`` field stores (RaisesExc.expected_exceptions)
    # so exit-face truth of the field can decide. Without this, ``not self.expected_exceptions``
    # refuses at unary_operation_exception_floor:CallSiteValue not.
    result = _floor_tuple_construct_fields(result, values)
    if isinstance(result, ObjectValue):
        helper_fields = result.helper_receiver_field_names()
        if helper_fields and (len(actuals) != 1 or keyword_actuals):
            return ManagerConstructionGapV1(
                "force-floor",
                resolved.cid,
                projected_force_floor_detail
                or "helper receiver-field projection requires one positional actual",
            )
        if helper_fields:
            result = result.with_deferred_helper_fields()
    bindings = frame.runtime_entries
    # BranchResultAuthentication / other control-metadata faces ride in the
    # linearized if-block but are not term-projectable factory prefix work.
    # Keep only prefix entries that mint a content CID; never panic the door.
    prefix_cids_list: list[str] = []
    kept_prefix: list[FloorValue] = []
    for item in factory_prefix:
        try:
            prefix_cids_list.append(_term_content_cid(item.to_term(owner=resolved.cid)))
            kept_prefix.append(item)
        except ConstructionPanic:
            continue
    factory_prefix = tuple(kept_prefix)
    prefix_cids = tuple(prefix_cids_list)
    preimage = {
        "kind": "constructed-manager-behavior",
        "schemaVersion": "1",
        "resolvedObjectCid": resolved.cid,
        "receiverStateCid": result.identity,
        "formalActualBindings": [item.wire() for item in bindings],
        "sourceCallFrameCid": frame.frame_cid,
        "factoryPrefixCids": list(prefix_cids),
    }
    return ConstructedManagerBehaviorV1(
        resolved_object_cid=resolved.cid,
        manager_construction_cid=cid_of_json(preimage),
        receiver_state=result,
        receiver_state_cid=result.identity,
        formal_actual_bindings=bindings,
        source_call_frame_cid=frame.frame_cid,
        formal_actual_values=values,
        source_call_frame=frame,
        factory_prefix=factory_prefix,
        factory_prefix_cids=prefix_cids,
    )


def resolve_source_visible_frame(
    resolved: ResolvedPythonObjectV1,
    *,
    graph: DependencyArtifactGraph,
    dependency_graphs: dict[str, DependencyArtifactGraph] | None = None,
    session: SourceResolutionSession | None = None,
) -> tuple[object, Node] | ManagerConstructionGapV1:
    """Resolve one authenticated definition into the ordinary source frame.

    This is orchestration over typed Nodes.  Function/Class bodies still
    construct only through their existing ``source_visible_*_frame`` arms.

    The projection is memoized on ``session``: the same authenticated
    definition is projected once per repeated call-site receipt in pandas
    megamodules, and re-materializing SourceFile + class base sugar each time
    was the residual wall after export/revalidation amortization.

    The memo may NOT be process-global even though its key is a content
    address.  ``_resolve_source_visible_frame_uncached`` mints a fresh
    ``TreeConstructionContextV1`` and WRITES into its mutable
    ``source_class_bases`` / ``source_call_frames`` tables; the returned
    ``frame``/``target`` Nodes are bound to that context.  Serving them to a
    later construction hands it another session's live context, so a warm
    answer from one project would silently become another project's answer.
    ``session`` is the boundary that makes that unrepresentable.
    """
    session = session_or_new(session)
    if graph.distribution_artifact_cid != resolved.distribution_artifact_cid:
        return ManagerConstructionGapV1(
            "artifact-mismatch", resolved.cid, "distribution artifact CID"
        )
    module = graph.modules.get(resolved.module_name)
    if module is None or module.source_cid != resolved.source_cid:
        return ManagerConstructionGapV1(
            "artifact-mismatch", resolved.cid, "module source CID"
        )
    definition = resolved.definition
    cache_key = (
        graph.distribution_artifact_cid,
        tuple(
            sorted(
                (name, dependency.distribution_artifact_cid)
                for name, dependency in (dependency_graphs or {}).items()
            )
        ),
        resolved.source_cid,
        definition.name,
        definition.kind,
        definition.start_line,
        definition.start_col,
        definition.end_line,
        definition.end_col,
    )
    hit = session.frame_hit(cache_key)
    if hit is not None:
        return hit
    if cache_key in session.frame_active:
        # Re-entered while its own frame is still being projected.  Not
        # memoized: the cycle is a property of this traversal, not of this
        # definition.
        return ManagerConstructionGapV1(
            "call-graph-cycle", resolved.cid, "recursive source call graph"
        )

    session.frame_active.add(cache_key)
    try:
        result = _resolve_source_visible_frame_uncached(
            resolved,
            graph=graph,
            module=module,
            dependency_graphs=dependency_graphs,
            session=session,
        )
    finally:
        session.frame_active.discard(cache_key)
    if isinstance(result, tuple) and len(result) == 3:
        frame, target, source_file = result
        # Hold the SourceFile that owns target/frame node identity.
        session.remember_frame(cache_key, (frame, target), hold=source_file)
        return frame, target
    assert not isinstance(result, tuple)
    session.remember_frame(cache_key, result)
    return result


def _resolve_source_visible_frame_uncached(
    resolved: ResolvedPythonObjectV1,
    *,
    graph: DependencyArtifactGraph,
    module,
    dependency_graphs: dict[str, DependencyArtifactGraph] | None,
    session: SourceResolutionSession,
) -> tuple[object, Node, object] | ManagerConstructionGapV1:
    # frame_projection: dual-mode factories may nest With only on non-CM
    # branches; soft-require those so call-frame projection can complete.
    context = TreeConstructionContextV1.for_source_call_construction(
        frame_projection=True
    )
    source_file = SourceFile(
        (module.source, module.source_seat, module.source_cid),
        construction_context=context,
    )
    from sugar_lift_python_source.value_pins import scan_module_value_pins
    from sugar_lift_py_tests.source_call_frame import MutableGlobalBindingV1

    pin_scan = scan_module_value_pins(
        source_file.root, source=module.source, source_path=module.source_seat
    )
    mutable_global_bindings = tuple(
        MutableGlobalBindingV1(
            source_cid=pin.source_cid,
            binding_occurrence=pin.binding_occurrence,
            name=pin.name,
            kind=pin.kind,
            term=pin.term,
            line=pin.line,
            col=pin.col,
        )
        for pin in pin_scan.mutable_global_pins
    )

    def with_mutable_globals(frame):
        return replace(frame, mutable_global_bindings=mutable_global_bindings)
    dependency_graphs = dict(dependency_graphs or {})
    dependency_graphs[resolved.module_name.split(".", 1)[0]] = graph
    definitions = tuple(
        item
        for item in source_file.root.body
        if isinstance(item, (FunctionDef, ClassDef))
    )
    target = next(
        (item for item in definitions if _matches_definition(item, resolved)), None
    )
    # Callable-instance exports resolve to a nested ``Class.__call__`` method.
    # Top-level definition scan cannot see those coordinates; methods of
    # module-level classes are the sole additional surface.
    if target is None:
        for item in definitions:
            if not isinstance(item, ClassDef):
                continue
            method = next(
                (
                    member
                    for member in item.body
                    if isinstance(member, FunctionDef)
                    and _matches_definition(member, resolved)
                ),
                None,
            )
            if method is not None:
                target = method
                break
    if target is None:
        return ManagerConstructionGapV1(
            "definition-missing", resolved.cid, "resolved definition coordinate"
        )
    # Seat final-checked import value-use receipts owned by THIS resolved
    # definition before constructing its frame. Identity operands bind via
    # authenticated coordinates on this unit; unrelated sibling definitions
    # never acquire authority merely by sharing the module source.
    _seat_import_value_use_receipts(
        source_file=source_file,
        module=module,
        target=target,
        session=session,
        context=context,
        dependency_graphs=dependency_graphs,
    )
    # Nested method export: project its ordinary frame without requiring the
    # enclosing class to be the export target. Leading ``self`` is the bound
    # instance for ``name = Class()`` callables and is not supplied by the
    # free-name call site.
    if (
        isinstance(target, FunctionDef)
        and target not in definitions
        and resolved.definition.name == "__call__"
    ):
        frame = with_mutable_globals(target.source_visible_call_frame())
        if frame.parameters and frame.parameters[0] == "self":
            frame = replace(
                frame,
                parameters=frame.parameters[1:],
                formal_coordinates=frame.formal_coordinates[1:],
                parameter_kinds=frame.parameter_kinds[1:],
                default_sugars=frame.default_sugars[1:],
                default_nodes=frame.default_nodes[1:],
                default_fragments=frame.default_fragments[1:],
                default_fragment_cids=frame.default_fragment_cids[1:],
            )
        return frame, target, source_file

    definitions_by_name = {item.name: item for item in definitions}

    def _local_class_base_name(base: Node) -> str | None:
        """The local class named by ``Base`` or the native generic ``Base[T]``.

        Subscription supplies type arguments; it does not change which class
        owns inherited runtime methods. Computed and attributed bases remain
        loud because neither shape authenticates a local class coordinate.
        """
        if isinstance(base, Name):
            return base.id
        if isinstance(base, Subscript) and isinstance(base.value, Name):
            return base.value.id
        return None

    # REACHABLE-ONLY definition graph. Frame projection constructs only the
    # authenticated target and definitions it references by authenticated
    # local edges (bases + named calls in the target's own frame surface).
    # Unrelated module-level classes are never constructor-sugared just because
    # they share a source file — their panics stay loud only if this target
    # actually reaches them.
    reachable_names = _reachable_local_definition_names(target, definitions_by_name)
    definitions = tuple(item for item in definitions if item.name in reachable_names)

    # Imported Attribute calls inside an authenticated reachable definition are
    # ordinary source calls too.  Candidate discovery deliberately knows only
    # that the callee is an Attribute: the exact call-contract receipt at that
    # same source span is the sole authority that it is imported and names its
    # dependency.  This includes both function-local and module-level imports
    # without reconstructing either binding from the callee spelling.
    from pathlib import Path

    from sugar_lift_py_tests.import_binding import (
        authenticated_import_use_receipts,
        authenticated_import_value_use_receipts,
    )

    reachable_calls = {
        (
            call.line_col_span().start_line,
            call.line_col_span().start_col,
            call.line_col_span().end_line,
            call.line_col_span().end_col,
        ): call
        for definition in definitions
        for function in _scanned_definitions(definition)
        for call in _reachable_attribute_calls(function)
    }
    if reachable_calls:
        module_path = Path(module.source_seat)
        import_receipts, _ = authenticated_import_use_receipts(
            Path("."),
            module_path,
            module.source,
            module.source_cid,
            module_identities={},
        )
        value_receipts, _ = authenticated_import_value_use_receipts(
            Path("."),
            module_path,
            module.source,
            module.source_cid,
            module_identities={},
        )
        value_receipts = _cache_import_value_receipts(
            context,
            module,
            dependency_graphs,
            value_receipts,
        )
    else:
        import_receipts = ()
        value_receipts = ()
    for receipt in import_receipts:
        raw_site = receipt.use["useSite"]
        call = reachable_calls.get(
            (
                raw_site["startLine"],
                raw_site["startCol"],
                raw_site["endLine"],
                raw_site["endCol"],
            )
        )
        if call is None:
            continue
        receipt.revalidate()
        callee_coordinate = _call_callee_coordinate(call)
        matching_values = tuple(
            value
            for value in value_receipts
            if value.source_cid == receipt.source_cid
            and value.target_symbol == receipt.target_symbol
            and value.import_binding.cid == receipt.import_binding.cid
            and value.use["useSite"]
            == {
                "sourceCid": callee_coordinate.source_cid,
                "startLine": callee_coordinate.start_line,
                "startCol": callee_coordinate.start_col,
                "endLine": callee_coordinate.end_line,
                "endCol": callee_coordinate.end_col,
            }
        )
        if len(matching_values) > 1:
            from sugar_source_tree.panic import BackendDefect

            raise BackendDefect(
                blame=call.fragment,
                owner="manager_construction imported call receipt pairing",
                observed="multiple value-use receipts claim one imported callee",
                requested="one exact call/value receipt pair",
                fix="repair lexical import-use enrollment uniqueness",
            )
        if matching_values:
            matching_values[0].revalidate()
        def obligation(relation_kind: str) -> OpaqueSourceCallObligationV1:
            subsumption = None
            if matching_values:
                from sugar_lift_py_tests.context_manager_resolution import (
                    _mint_import_call_value_subsumption,
                )

                subsumption = _mint_import_call_value_subsumption(
                    call_receipt=receipt,
                    value_receipt=matching_values[0],
                    call_coordinate=_call_coordinate(call),
                    callee_coordinate=callee_coordinate,
                    resolution_kind=relation_kind,
                    resolved_object_cid=resolved.cid,
                )
            return OpaqueSourceCallObligationV1(
                _call_coordinate(call),
                receipt.target_symbol,
                resolved.cid,
                resolution_kind=relation_kind,
                import_call_value_subsumption=subsumption,
            )
        top_level = receipt.target_symbol.removeprefix("python:").split(".", 1)[0]
        dependency_graph = dependency_graphs.get(top_level)
        if dependency_graph is None:
            from .dependency_artifact import (
                DependencyArtifactAuthenticationError,
                authenticate_dependency_top_level,
            )

            try:
                dependency_graph = authenticate_dependency_top_level(top_level)
            except DependencyArtifactAuthenticationError:
                _install_opaque_call_obligation(
                    context,
                    call,
                    obligation("call-target-source-absent"),
                )
                continue
            dependency_graphs[top_level] = dependency_graph
        imported = resolve_import_binding(
            receipt, graph=dependency_graph, session=session
        )
        if not isinstance(imported, ResolvedPythonObjectV1):
            _install_opaque_call_obligation(
                context,
                call,
                obligation("call-target-source-absent"),
            )
            continue
        from sugar_source_tree.panic import SugarNotWritten

        try:
            projected = resolve_source_visible_frame(
                imported,
                graph=dependency_graph,
                dependency_graphs=dependency_graphs,
                session=session,
            )
        except SugarNotWritten as exc:
            # Imported callee body is incomplete: park the obligation, do not
            # erase the outer authenticated target frame.
            _install_opaque_call_obligation(
                context,
                call,
                obligation("call-target-export-unresolved"),
            )
            del exc
            continue
        if isinstance(projected, ManagerConstructionGapV1):
            kind = (
                "call-graph-cycle"
                if projected.kind == "call-graph-cycle"
                else "call-target-export-unresolved"
            )
            _install_opaque_call_obligation(
                context,
                call,
                obligation(kind),
            )
            continue
        imported_frame, _ = projected
        _install_source_call_frame(context, call, imported_frame)

    definition_names = {item.name for item in definitions}
    from sugar_lift_py_tests.temporal.builtin_name_bindings import builtin_name_temporal

    builtin_floor = builtin_name_temporal()

    # Non-local call targets, resolved through the ONE authenticated export
    # door.  Demand (a name called in this module and neither locally defined
    # nor a semantic builtin) maps bijectively onto resolution: exactly one
    # entry per demanded name, in `external_frames` when the defining source is
    # authenticated in this artifact, otherwise in `external_opaque`.
    external_frames: dict[str, object] = {}
    external_opaque: dict[str, str] = {}

    def _parked_call_targets(
        function: FunctionDef,
    ) -> tuple[tuple[Call, str, str], ...]:
        """Return exact unresolved callees with their landed typed kind.

        Frame preparation classifies every named call through main's closed
        call-target vocabulary, but it does not decide reachability.  Each
        unresolved call is parked at its own coordinate; ordinary Sugar
        control flow selects which obligation, if any, becomes a refusal.
        """
        binders = _frame_bound_names(function)
        blocked: list[tuple[Call, str, str]] = []
        for call in _local_named_calls(function):
            name = call.func.id
            if name in external_frames:
                continue
            classification = _classify_named_call_target(
                name, definition_names, builtin_floor, frame_binders=binders
            )
            if classification in ("local-definition", "builtin"):
                continue
            if classification == "frame-bound-value":
                # Bound HERE: a value, not a symbol.  The export door is never
                # asked, because there is nothing for it to look up.
                blocked.append((call, name, "value-call-target"))
                continue
            declined = external_opaque.get(name)
            if declined is None:
                outcome = _resolve_external_call_frame(
                    name, resolved=resolved, graph=graph, session=session
                )
                if not isinstance(outcome, _ExternalCallTargetGap):
                    external_frames[name] = outcome
                    continue
                declined = outcome.kind
                if declined != "call-graph-cycle":
                    # A cycle is a property of THIS traversal, not of the
                    # callee; memoizing it against the name would serve a
                    # traversal verdict to an unrelated one.
                    external_opaque[name] = declined
            blocked.append((call, name, declined))
        # Dual-mode EffectBoundary factories return a concrete manager
        # (``return RaisesExc(...)``) without requiring every frame-bound
        # callee on the function-form branch (``func = args[0]; func(...)``).
        # Only drop value-call-target when some return is NOT higher-order
        # ``return helper()`` — pure higher-order sole returns and methods
        # with no return (``self.x = helper()``) still block (see twins).
        if _has_non_higher_order_return(function, binders):
            blocked = [
                obligation
                for obligation in blocked
                if obligation[2] != "value-call-target"
            ]
        return tuple(blocked)

    # Every reachable definition is scanned, whether it is written as a
    # module-level function or as a method of a reachable class.
    #
    # The class arm used to be absent, and its absence was not a reporting gap:
    # a method calling a name with no authenticated defining source CONSTRUCTED.
    # The unresolvable call was carried into the receiver as a `CallSiteValue`
    # with `body=None`, `source_call_frame_cid=None` and
    # `authenticated_target_symbol=None`, and that value was then content-addressed
    # into `receiver_state.identity` and `manager_construction_cid` -- a
    # manager-construction CID asserting an authenticated receiver over a call
    # the system could not see through.  `_resolve_external_call_frame` promises
    # it "never yields a fabricated contract"; that promise held only on the
    # function path.  The same source written as a module-level function refused
    # loudly, so the two faces disagreed and the silent one was wrong.
    for definition in (target,) + tuple(definitions):
        for scanned in _scanned_definitions(definition):
            for call, name, kind in _parked_call_targets(scanned):
                coordinate = _call_coordinate(call)
                _install_opaque_call_obligation(
                    context,
                    call,
                    OpaqueSourceCallObligationV1(
                        coordinate,
                        name,
                        resolved.cid,
                        resolution_kind=kind,
                    ),
                )

    frames: dict[str, object] = {}
    reaching_classes: dict[str, ClassDef] = {}
    from sugar_source_tree.panic import SugarNotWritten

    # Only reachable ClassDefs (see filter above). Never constructor-sugar an
    # unrelated module-level class just because it shares this source file.
    for item in definitions:
        if not isinstance(item, ClassDef):
            continue
        local_bases = []
        for base in item.bases:
            base_name = _local_class_base_name(base)
            if base_name is None or base_name not in reaching_classes:
                local_bases = []
                break
            try:
                local_bases.append(reaching_classes[base_name].sugar())
            except SugarNotWritten as exc:
                owner = getattr(exc, "owner", None) or type(exc).__name__
                observed = getattr(exc, "observed", None) or str(exc)
                return ManagerConstructionGapV1(
                    "force-floor", resolved.cid, f"{owner}:{observed}"
                )
        if local_bases and len(local_bases) == len(item.bases):
            context.source_class_bases[item.fragment.seal().cid] = tuple(local_bases)
        reaching_classes[item.name] = item
    for item in definitions:
        if not isinstance(item, ClassDef):
            continue
        # Target class (or a local class the target actually reaches): panics
        # stay loud. There is no soft-green for a reached broken definition.
        # Seat its exact imported member coordinates before constructor-frame
        # construction can cache an AttributeSugar for a class-body field.
        _seat_import_value_use_receipts(
            source_file=source_file,
            module=module,
            target=item,
            session=session,
            context=context,
            dependency_graphs=dependency_graphs,
        )
        frames[item.name] = item.source_visible_constructor_frame()

    pending = [item for item in definitions if isinstance(item, FunctionDef)]
    while pending:
        progressed = False
        for function in tuple(pending):
            local_calls = tuple(_local_named_calls(function))
            frame_binders = _frame_bound_names(function)
            for call, name, kind in _parked_call_targets(function):
                coordinate = _call_coordinate(call)
                _install_opaque_call_obligation(
                    context,
                    call,
                    OpaqueSourceCallObligationV1(
                        coordinate,
                        name,
                        resolved.cid,
                        resolution_kind=kind,
                    ),
                )
            unresolved = tuple(
                call.func.id
                for call in local_calls
                if call.func.id in definition_names and call.func.id not in frames
            )
            if unresolved:
                continue
            for call in local_calls:
                if call.func.id in frame_binders:
                    # A parameter/local shadows any module-level definition
                    # with the same spelling.  Its parked value-call-target
                    # obligation is the sole classification at this site.
                    continue
                nested = frames.get(call.func.id)
                if nested is None:
                    nested = external_frames.get(call.func.id)
                if nested is not None:
                    _install_source_call_frame(context, call, nested)
            if function is not target:
                _seat_import_value_use_receipts(
                    source_file=source_file,
                    module=module,
                    target=function,
                    session=session,
                    context=context,
                    dependency_graphs=dependency_graphs,
                )
            frames[function.name] = with_mutable_globals(
                function.source_visible_call_frame()
            )
            pending.remove(function)
            progressed = True
        if not progressed:
            return ManagerConstructionGapV1(
                "call-graph-cycle", resolved.cid, "recursive source call graph"
            )
    frame = frames.get(target.name)
    if frame is None:
        return ManagerConstructionGapV1(
            "definition-missing", resolved.cid, "ordinary source call frame"
        )
    decorated_class_bindings = _construct_reachable_decorated_class_bindings(
        source_file=source_file,
        module=module,
        target=target,
        module_definitions=tuple(source_file.root.body),
        reachable_definitions=definitions,
        frames=frames,
        session=session,
        context=context,
        dependency_graphs=dependency_graphs,
    )
    if decorated_class_bindings:
        frame = replace(frame, decorated_class_bindings=decorated_class_bindings)
    return frame, target, source_file


def _construct_reachable_decorated_class_bindings(
    *,
    source_file,
    module,
    target,
    module_definitions,
    reachable_definitions,
    frames,
    session,
    context,
    dependency_graphs,
):
    """Execute exact decorated classes reached by the selected frame."""
    from dataclasses import dataclass

    from sugar_lift_py_tests.callable_application import CallableApplication
    from sugar_lift_py_tests.context import ReduceContext
    from sugar_lift_py_tests.floor import FloorValue
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.floor.decorated_class_value import (
        DecoratedClassPublicationV1,
        DecoratedClassValue,
        DecoratorApplicationPublicationV1,
    )
    from sugar_lift_py_tests.ir import ctor, str_const
    from sugar_lift_py_tests.outcome import Complete
    from sugar_lift_py_tests.source_call_frame import DecoratedClassBindingV1
    from sugar_lift_py_tests.temporal import TemporalContext
    from sugar_source_tree.panic import SugarNotWritten

    @dataclass(frozen=True)
    class _SourceFrameCallableV1(FloorValue):
        definition: FunctionDef
        frame: object

        def to_term(self, *, owner):
            del owner
            return ctor(
                "python:source-frame-callable",
                [str_const(self.frame.frame_cid)],
                symbol_kind="coordinate",
            )

        def callable_application_with(self, operation, ctx):
            keywords = tuple(zip(operation.keyword_names, (), strict=True))
            bound = self.frame.bind_actuals(operation.arguments, keywords, ctx)
            call = CallSiteValue(
                self.definition.name,
                bound.actuals,
                self.frame.parameters,
                ctor(
                    "call:source-frame",
                    [
                        self.to_term(owner=self.definition.name),
                        *(
                            item.to_term(owner=self.definition.name)
                            for item in bound.actuals
                        ),
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
            produced = call.producer_outcome(ctx)
            if not isinstance(produced, Complete) or type(produced.value) is not CallSiteValue:
                raise SugarNotWritten(
                    owner="manager_construction decorated class application",
                    blame=operation.site,
                    observed="decorator source call produced a nonlinear outcome",
                    requested="one completed retained source-call coordinate",
                    fix="sequence the decorator's effects before module publication",
                )
            projected = produced.value.project_operation_receiver_outcome(
                ctx, owner="manager_construction decorated class application"
            )
            if not isinstance(projected, Complete):
                raise SugarNotWritten(
                    owner="manager_construction decorated class application",
                    blame=operation.site,
                    observed="decorator source return projected nonlinearly",
                    requested="one completed decorator result Floor",
                    fix="sequence the decorator's effects before module publication",
                )
            return projected

    if not isinstance(target, FunctionDef):
        return ()

    def owned_lexical_load_occurrences(function):
        from sugar_source_tree.nodes import AsyncFunctionDef, Lambda

        def visit(node):
            if isinstance(node, (FunctionDef, AsyncFunctionDef)):
                for field_name in ("decorators", "type_params", "params", "returns"):
                    value = getattr(node, field_name)
                    if value is None:
                        continue
                    items = (value,) if isinstance(value, Node) else tuple(value)
                    for item in items:
                        yield from visit(item)
                return
            if isinstance(node, ClassDef):
                for field_name in ("decorators", "type_params", "bases", "keywords"):
                    for item in tuple(getattr(node, field_name)):
                        yield from visit(item)
                return
            if isinstance(node, Lambda):
                for parameter in node.params:
                    yield from visit(parameter)
                return
            if isinstance(node, Name):
                yield node
                return
            for field_name, _, child in node.children():
                if field_name in {"target", "targets", "optional_vars"}:
                    continue
                yield from visit(child)

        for statement in function.body:
            yield from visit(statement)

    module_classes = tuple(
        item for item in module_definitions if isinstance(item, ClassDef)
    )
    reached = []
    for function in reachable_definitions:
        if not isinstance(function, FunctionDef):
            continue
        table = function.unit.function_symtable(
            function.name, function.line_col_span().start_line
        )
        for node in owned_lexical_load_occurrences(function):
            bindings = tuple(
                (function.unit.module_direct_bindings or {}).get(node.id, ())
            )
            if len(bindings) != 1 or not isinstance(bindings[0], ClassDef):
                continue
            candidate = bindings[0]
            if not any(candidate is item for item in module_classes):
                continue
            if not candidate.decorators:
                continue
            try:
                symbol = table.lookup(node.id)
            except KeyError:
                continue
            if not symbol.is_global() or not symbol.is_referenced():
                continue
            if candidate not in reached:
                reached.append(candidate)
    if not reached:
        return ()

    decorator_functions = set()
    for definition in reached:
        for decorator in definition.decorators:
            if isinstance(decorator, Name):
                bindings = tuple(
                    (definition.unit.module_direct_bindings or {}).get(decorator.id, ())
                )
                if len(bindings) == 1 and isinstance(bindings[0], FunctionDef):
                    decorator_functions.add(bindings[0])
    temporal = TemporalContext.empty()
    for definition in decorator_functions:
        frame = frames.get(definition.name)
        if frame is None:
            frame = definition.source_visible_call_frame()
        elif frame.owner is not definition:
            from sugar_source_tree.panic import BackendDefect

            raise BackendDefect(
                owner="manager_construction decorated callable frame",
                blame=definition.fragment,
                observed="name-keyed frame does not belong to bound decorator definition",
                requested="the exact module-direct-binding FunctionDef frame",
                fix="preserve definition identity when indexing source call frames",
            )
        temporal = temporal.bind_value(
            definition.name, _SourceFrameCallableV1(definition, frame)
        )

    ctx = ReduceContext.root(owner="manager decorated class publication")
    class_dependencies = set()
    for function in decorator_functions:
        function_table = function.unit.function_symtable(
            function.name, function.line_col_span().start_line
        )
        for node in owned_lexical_load_occurrences(function):
            bindings = tuple((function.unit.module_direct_bindings or {}).get(node.id, ()))
            if len(bindings) != 1 or not isinstance(bindings[0], ClassDef):
                continue
            candidate = bindings[0]
            if not any(candidate is item for item in module_classes):
                continue
            try:
                symbol = function_table.lookup(node.id)
            except KeyError:
                continue
            if not symbol.is_global() or not symbol.is_referenced():
                continue
            class_dependencies.add(candidate)
    for definition in module_definitions:
        if definition not in class_dependencies:
            continue
        outcome = definition.sugar().desugar(ctx)
        if not isinstance(outcome, Complete):
            raise SugarNotWritten(
                owner="manager_construction decorated class dependency",
                blame=definition.fragment,
                observed="decorator class dependency reduced nonlinearly",
                requested="one completed source class Floor",
                fix="sequence module definition effects before decorator execution",
            )
        temporal = temporal.bind_value(definition.name, outcome.value)
    ctx = replace(ctx, temporal=temporal, module_temporal=temporal)

    result = []
    for definition in reached:
        sugar = definition.sugar()
        raw_outcome = sugar.desugar(ctx)
        if not isinstance(raw_outcome, Complete):
            raise SugarNotWritten(
                owner="manager_construction decorated raw class",
                blame=definition.fragment,
                observed="raw class reduced nonlinearly",
                requested="one completed raw ClassDefinitionValue",
                fix="sequence module definition effects before decorator execution",
            )
        decorator_floors = []
        for decorator_sugar in sugar.decorator_sugars:
            outcome = decorator_sugar.desugar(ctx)
            if not isinstance(outcome, Complete):
                raise SugarNotWritten(
                    owner="manager_construction decorated callable",
                    blame=definition.fragment,
                    observed="decorator expression reduced nonlinearly",
                    requested="one completed decorator callable Floor",
                    fix="sequence decorator expression effects before application",
                )
            decorator_floors.append(outcome.value)
        current = raw_outcome.value
        applications = []
        for callable_floor, occurrence in reversed(
            tuple(zip(decorator_floors, sugar.decorator_occurrences, strict=True))
        ):
            before = current
            outcome = CallableApplication(
                (before,),
                (),
                occurrence,
                owner="manager decorated class application",
                call_occurrence=occurrence,
            ).apply(callable_floor, ctx)
            if not isinstance(outcome, Complete):
                raise SugarNotWritten(
                    owner="manager_construction decorated class application",
                    blame=occurrence,
                    observed="decorator application reduced nonlinearly",
                    requested="one completed decorator result Floor",
                    fix="sequence decorator application effects before publication",
                )
            current = outcome.value
            applications.append(
                DecoratorApplicationPublicationV1.mint(
                    occurrence=occurrence,
                    callable_floor=callable_floor,
                    input_floor=before,
                    output_floor=current,
                )
            )
        publication = DecoratedClassPublicationV1.mint(
            source_cid=source_file.unit.source_cid,
            definition=_call_coordinate(definition),
            binding_occurrence=sugar.binding_target_occurrence,
            raw_class=raw_outcome.value,
            decorator_applications=tuple(applications),
            final_class=current,
            module_construction_receipt_cid=(
                source_file.construction_event_receipt_cid
            ),
        )
        result.append(
            DecoratedClassBindingV1(
                definition.name,
                publication,
                DecoratedClassValue(publication),
            )
        )
    return tuple(result)


def _resolve_external_call_frame(
    name: str,
    *,
    resolved: ResolvedPythonObjectV1,
    graph: DependencyArtifactGraph,
    session: SourceResolutionSession,
) -> object | _ExternalCallTargetGap:
    """Project one non-local call target through the authenticated export door.

    A name called inside an authenticated module but not defined there is bound
    by that module's own top-level import -- which IS a static export of that
    module.  So the callee is resolved by the SAME static export/re-export
    resolver that authenticated the outer callable (`resolve_export`), against
    the SAME artifact graph, and is then projected by the same
    `resolve_source_visible_frame` door.  There is no second resolver, no
    executed import, and no name arm: the only question asked is whether the
    defining source is authenticated inside this artifact.

    Returns the ordinary source frame, or a typed ``_ExternalCallTargetGap``
    naming WHICH of the two declines happened.  Both used to be a bare ``None``
    and were reported under one kind, which is why an in-artifact symbol the
    door failed on was indistinguishable from a stdlib symbol the artifact does
    not contain:

    - ``call-target-source-absent`` -- the export door itself declined: no
      authenticated defining source for this name in this artifact
      (native/builtin callables, modules outside the distribution manifest,
      dynamic or ambiguous exports, free names).  Artifact COVERAGE.
    - ``call-target-export-unresolved`` -- the door DID authenticate an object
      in this artifact and projecting its frame still failed.  A DEFECT.

    Either way the call site stays typed-loud; it never yields a fabricated
    contract.
    """
    from .dependency_artifact import ResolvedPythonObjectV1 as _Resolved

    callee = _resolve_export(
        graph,
        resolved.import_binding_cid,
        resolved.module_name,
        name,
        (),
        frozenset(),
        session=session,
    )
    if not isinstance(callee, _Resolved):
        return _ExternalCallTargetGap("call-target-source-absent")
    from sugar_source_tree.panic import SugarNotWritten

    try:
        projected = resolve_source_visible_frame(callee, graph=graph, session=session)
    except SugarNotWritten:
        # Callee body is incomplete (e.g. Compare leg gap inside a method of a
        # class this target only *names*).  Park the free-name obligation; do
        # not erase the outer authenticated target frame.  When that broken
        # definition IS the outer target, resolve_source_visible_frame is the
        # entry door and the panic stays loud there.
        return _ExternalCallTargetGap("call-target-export-unresolved")
    if isinstance(projected, ManagerConstructionGapV1):
        # A cycle reached through a re-export hop is still a cycle.  Read the
        # callee's OWN authenticated gap kind rather than restating the hop as a
        # door defect -- otherwise every cross-module recursion would be
        # reported as a bug in the export door.
        if projected.kind == "call-graph-cycle":
            return _ExternalCallTargetGap("call-graph-cycle")
        return _ExternalCallTargetGap("call-target-export-unresolved")
    frame, _target = projected
    return frame


def _resolve_export(*args, **kwargs):
    from .dependency_artifact import _resolve_export as _door

    return _door(*args, **kwargs)


def _reachable_local_definition_names(
    target: Node, definitions_by_name: dict[str, Node]
) -> set[str]:
    """Local definitions the authenticated target reaches by reference.

    Edges are authenticated structure only:

    * Class bases named as local ``Name`` / ``Name[T]`` (not attributed/computed)
    * Named local calls inside the target function, or — for a ClassDef target —
      inside ``__init__`` and class-level field RHS only (not every method body)

    Method bodies of a class are NOT scanned when expanding the graph for a
    sibling or for a function target that never names the class.  That keeps
    unrelated module classes (and panics inside their methods) from aborting a
    target that does not reach them.  When the target *is* that class, its
    constructor frame still sugars the full definition and method panics stay
    loud at the target door.
    """
    if not isinstance(target, (FunctionDef, ClassDef)):
        return set()
    # Method targets are not module-level definitions_by_name keys; their
    # enclosing class is not automatically enrolled.  Only __call__ early-exit
    # handles method frames.  Module-level targets start at their own name.
    if target.name not in definitions_by_name:
        return {target.name} if isinstance(target, FunctionDef) else set()

    reachable: set[str] = {target.name}
    pending = [target.name]

    def _local_class_base_name(base: Node) -> str | None:
        if isinstance(base, Name):
            return base.id
        if isinstance(base, Subscript) and isinstance(base.value, Name):
            return base.value.id
        return None

    while pending:
        current = definitions_by_name[pending.pop()]
        dependencies: list[str] = []
        if isinstance(current, ClassDef):
            dependencies.extend(
                name
                for base in current.bases
                if (name := _local_class_base_name(base)) is not None
            )
            # Constructor surface only: __init__ + class-body field values.
            # Do not name-scan every method — that is the "every class in the
            # module" residual when one class's method mentions another.
            functions = tuple(
                item
                for item in current.body
                if isinstance(item, FunctionDef) and item.name == "__init__"
            )
            for item in current.body:
                if isinstance(item, Assign):
                    # field = LocalClass(...) edges are real construction refs.
                    for call in _named_calls_under(item.value):
                        dependencies.append(call.func.id)
                elif (
                    isinstance(item, AnnAssign)
                    and item.value is not None
                ):
                    for call in _named_calls_under(item.value):
                        dependencies.append(call.func.id)
        else:
            functions = (current,)
        dependencies.extend(
            call.func.id
            for function in functions
            for call in _local_named_calls(function)
        )
        for name in dependencies:
            if name in definitions_by_name and name not in reachable:
                reachable.add(name)
                pending.append(name)
    return reachable


def _named_calls_under(node: Node):
    """Named ``Call`` nodes under one expression (authenticated AST walk)."""
    stack = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, Call) and isinstance(current.func, Name):
            yield current
        children = [child for _, _, child in current.children()]
        stack.extend(children)


def _matches_definition(node: Node, resolved: ResolvedPythonObjectV1) -> bool:
    span = node.line_col_span()
    definition = resolved.definition
    return (
        (
            (isinstance(node, FunctionDef) and definition.kind == "function")
            or (isinstance(node, ClassDef) and definition.kind == "class")
        )
        and node.fragment.seal().cid == definition.fragment_cid
        and node.unit.source_cid == definition.source_cid
        and span.start_line == definition.start_line
        and span.start_col == definition.start_col
        and span.end_line == definition.end_line
        and span.end_col == definition.end_col
    )


def _classify_named_call_target(
    name: str,
    definition_names: set[str],
    builtin_floor,
    *,
    frame_binders: frozenset[str],
) -> Literal["frame-bound-value", "local-definition", "builtin", "free-name"]:
    """What binds a named callee, read off the enclosing frame and the module.

    This supersedes the old ``_named_call_is_source_opaque`` predicate, which
    answered only "is this a local definition or a builtin" and therefore
    classified a callee that is a bound PARAMETER identically to a missing
    import.  Those are different conditions with different fixes: a parameter
    callee is higher-order dispatch that no export door can ever resolve, and a
    missing import is artifact coverage.  A predicate cannot say that; a
    classification can.

    Precedence is Python's own scoping order, which is also why checking the
    frame first is a correctness fix and not only a reporting one: a local
    binding SHADOWS both a module-level definition of the same name and a
    builtin, so a definition with a parameter named ``len`` does not call the
    builtin ``len``.

    Frame resolution used to treat only ``BuiltinSemanticCallable`` (issubclass,
    set) as non-opaque, so ordinary builtins like ``len`` / ``sorted`` /
    ``isinstance`` aborted manager construction before force_floor. That
    over-classified residual for every source-derived manager family --
    including assertion EffectBoundary factories.  A name bound in the builtin
    temporal is not source-opaque; construction may still refuse at force_floor
    when the builtin is not yet reducible, and that is a later, stage-keyed gap.

    ``free-name`` is the LOCAL question's only remaining answer, and it is not
    yet a gap: the name is offered to the one authenticated export door
    (``_blocking_call_targets`` -> ``_resolve_external_call_frame``) and is
    reported only when that door also declines, under the kind naming WHICH
    decline it was.
    """
    if name in frame_binders:
        return "frame-bound-value"
    if name in definition_names:
        return "local-definition"
    if builtin_floor.value_if_bound(name) is not None:
        return "builtin"
    return "free-name"


def _scanned_definitions(definition: Node) -> tuple[FunctionDef, ...]:
    """The frames a definition contributes to the call-target scan.

    A function contributes itself.  A class contributes its methods -- each is
    an ordinary frame with its own parameters and locals, and a called name
    inside one is exactly as opaque as the same call written at module level.
    Whether a body is spelled as a function or as a method is syntax; it must
    not decide whether construction authenticates its callees.
    """
    if isinstance(definition, FunctionDef):
        return (definition,)
    if isinstance(definition, ClassDef):
        return tuple(item for item in definition.body if isinstance(item, FunctionDef))
    return ()


def _frame_bound_names(function: FunctionDef) -> frozenset[str]:
    """Every name the enclosing definition binds itself: parameters and locals.

    A callee bound HERE is a runtime value, not a symbol.  The set is read off
    the definition's own binding syntax -- parameters, assignment / for / with /
    except targets, function-local imports, walrus, nested definitions -- and
    never off a spelling.  There is no name table and nothing vendor-specific:
    the same walk answers the same question for any Python definition.

    Comprehension targets are deliberately ABSENT.  They bind in their own
    scope, so a callee spelled like one is still a free name in this frame and
    still goes to the export door -- exactly as before this classification
    existed.  Reporting it as frame-bound would be a claim this walk cannot
    authenticate.
    """
    names: set[str] = {param.name for param in function.params}

    def _bind_target(node) -> None:
        if isinstance(node, Name):
            names.add(node.id)
        elif isinstance(node, (Tuple_, List)):
            for element in node.elts:
                _bind_target(element)
        elif isinstance(node, Starred):
            _bind_target(node.value)

    stack = list(function.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (FunctionDef, ClassDef)):
            # A nested definition binds its own name here and opens its own
            # scope; its body's binders are not this frame's.
            names.add(node.name)
            continue
        if isinstance(node, Assign):
            for target in node.targets:
                _bind_target(target)
        elif isinstance(node, (AnnAssign, AugAssign, For, NamedExpr)):
            _bind_target(node.target)
        elif isinstance(node, With):
            for item in node.items:
                if item.optional_vars is not None:
                    _bind_target(item.optional_vars)
        elif isinstance(node, ExceptHandler):
            if node.name:
                names.add(node.name)
        elif isinstance(node, (Import, ImportFrom)):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".", 1)[0])
        stack.extend(child for _, _, child in node.children())
    return frozenset(names)


def _local_named_calls(function: FunctionDef):
    stack = list(reversed(function.body))
    while stack:
        node = stack.pop()
        if isinstance(node, (FunctionDef, ClassDef)):
            continue
        if isinstance(node, Call) and isinstance(node.func, Name):
            yield node
        children = [child for _, _, child in node.children()]
        stack.extend(reversed(children))


def _reachable_attribute_calls(function: FunctionDef):
    """Attribute-call candidates owned by one reachable definition.

    This walk grants no import or target authority.  The caller admits a
    candidate only when the lexical pass returns one exact call-contract
    receipt for the candidate's full source span.
    """
    stack = list(reversed(function.body))
    calls: list[Call] = []
    while stack:
        node = stack.pop()
        if isinstance(node, (FunctionDef, ClassDef)):
            continue
        if (
            isinstance(node, Call)
            and isinstance(node.func, Attribute)
        ):
            calls.append(node)
        children = [child for _, _, child in node.children()]
        stack.extend(reversed(children))
    return tuple(calls)


def _has_non_higher_order_return(
    function: FunctionDef, binders: frozenset[str]
) -> bool:
    """True when some ``return`` is not ``return <frame-bound-name>(...)``.

    Dual-mode EffectBoundary factories return a free/local constructor on the
    CM path (``return RaisesExc(...)``) while the function-form branch may call
    a formal. Pure higher-order (``return helper()`` only) and methods with no
    return statement keep value-call-target blocked.
    """
    from sugar_source_tree.nodes import Return

    returns: list = []
    stack = list(reversed(function.body))
    while stack:
        node = stack.pop()
        if isinstance(node, (FunctionDef, ClassDef)):
            continue
        if isinstance(node, Return):
            returns.append(node)
            continue
        children = [child for _, _, child in node.children()]
        stack.extend(reversed(children))
    if not returns:
        return False
    for ret in returns:
        value = ret.value
        if not (
            isinstance(value, Call)
            and isinstance(value.func, Name)
            and value.func.id in binders
        ):
            return True
    return False


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


def _source_import_value_receipt_cache_key(module, dependency_graphs):
    """Closed cache identity for one authenticated module source roster."""
    from sugar_source_tree.panic import BackendDefect

    graph = dependency_graphs.get(module.module_name.split(".", 1)[0])
    if graph is None or graph.modules.get(module.module_name) is not module:
        raise BackendDefect(
            blame=module.source_seat,
            owner="manager_construction import value receipt cache",
            observed="module source is not owned by the carried dependency graph",
            requested="exact module name/source/seat/artifact identity",
            fix="carry the authenticated graph that minted this module source",
        )
    return (
        module.module_name,
        module.source_cid,
        module.source_seat,
        graph.distribution_artifact_cid,
    )


def _validated_import_value_receipt_roster(module, receipts):
    """Validate and retain one exact immutable receipt roster."""
    from sugar_lift_py_tests.import_binding import AuthenticatedImportUseV1
    from sugar_source_tree.panic import BackendDefect

    roster = tuple(receipts)
    exact_rows = {}
    uses = {}
    for receipt in roster:
        if type(receipt) is not AuthenticatedImportUseV1:
            raise BackendDefect(
                blame=module.source_seat,
                owner="manager_construction import value receipt cache",
                observed="receipt roster contains an unadmitted product",
                requested="exact AuthenticatedImportUseV1 rows",
                fix="cache only lexical-pass value-use receipts",
            )
        receipt.revalidate()
        exported = tuple(receipt.use.get("exportedMemberPath") or ())
        row_key = (
            receipt.source_cid,
            receipt.import_binding.cid,
            receipt.use["cid"],
            exported,
        )
        if receipt.source_cid != module.source_cid:
            raise BackendDefect(
                blame=module.source_seat,
                owner="manager_construction import value receipt cache",
                observed="receipt roster contains a foreign source CID",
                requested="same-module authenticated value-use rows",
                fix="partition receipt rosters by authenticated module identity",
            )
        if row_key in exact_rows:
            raise BackendDefect(
                blame=module.source_seat,
                owner="manager_construction import value receipt cache",
                observed="duplicate exact import value receipt row",
                requested="one row per source/binding/use/path identity",
                fix="repair lexical receipt enrollment uniqueness",
            )
        prior = uses.get(receipt.use["cid"])
        if prior is not None and prior != row_key:
            raise BackendDefect(
                blame=module.source_seat,
                owner="manager_construction import value receipt cache",
                observed="conflicting import value receipt use CID",
                requested="one exact row identity for each use CID",
                fix="repair cross-wired receipt preimages before caching",
            )
        exact_rows[row_key] = receipt
        uses[receipt.use["cid"]] = row_key
    return roster


def _cache_import_value_receipts(context, module, dependency_graphs, minted):
    key = _source_import_value_receipt_cache_key(module, dependency_graphs)
    candidate = _validated_import_value_receipt_roster(module, minted)
    existing = context.source_import_value_receipts.get(key)
    if existing is None:
        context.source_import_value_receipts[key] = candidate
        return candidate
    existing_keys = tuple(
        (
            row.source_cid,
            row.import_binding.cid,
            row.use["cid"],
            tuple(row.use.get("exportedMemberPath") or ()),
        )
        for row in existing
    )
    candidate_keys = tuple(
        (
            row.source_cid,
            row.import_binding.cid,
            row.use["cid"],
            tuple(row.use.get("exportedMemberPath") or ()),
        )
        for row in candidate
    )
    if existing_keys != candidate_keys:
        from sugar_source_tree.panic import BackendDefect

        raise BackendDefect(
            blame=module.source_seat,
            owner="manager_construction import value receipt cache",
            observed="conflicting roster for authenticated module identity",
            requested="byte-identical ordered receipt row identities",
            fix="keep module receipt enrollment deterministic",
        )
    return existing


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
    (source-CID authenticated; dual-door / mismatch raises).  Resolution uses
    only pre-authenticated ``dependency_graphs`` already carried for this frame
    — never spelling-derived ambient dependency authentication.  Seating
    requires exact unit source_cid + validated span.  Missing graph /
    non-resolved import leaves that coordinate unseated (consume stays
    typed-loud); CID/auth defects raise.
    """
    from pathlib import Path

    from sugar_lift_py_tests.context_manager_resolution import (
        SourceFragmentCoordinateV1,
    )
    from sugar_lift_py_tests.import_binding import (
        authenticated_import_value_use_receipts,
    )
    from sugar_lift_python_source.canonical import blake3_512_of

    unit = source_file.unit
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
    cache_key = _source_import_value_receipt_cache_key(module, dependency_graphs)
    receipts = context.source_import_value_receipts.get(cache_key)
    if receipts is None:
        minted, _ = authenticated_import_value_use_receipts(
            Path("."),
            Path(module.source_seat),
            module.source,
            module.source_cid,
            module_identities={},
        )
        receipts = _cache_import_value_receipts(
            context, module, dependency_graphs, minted
        )
    from sugar_lift_py_tests.import_binding import authenticated_import_use_receipts

    call_receipts, _ = authenticated_import_use_receipts(
        Path("."),
        Path(module.source_seat),
        module.source,
        module.source_cid,
        module_identities={},
    )
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
        decorator.line_col_span()
        for decorator in getattr(target, "decorators", ())
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
        use_start = (site["startLine"], site["startCol"])
        use_end = (site["endLine"], site["endCol"])
        if not any(
            start <= use_start and use_end <= end for start, end in owned_ranges
        ):
            continue
        receipt.revalidate()
        paired_obligations = []
        for obligation in context.opaque_source_call_obligations.values():
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
        if len(paired_obligations) > 1:
            from sugar_source_tree.panic import BackendDefect

            raise BackendDefect(
                blame=coordinate,
                owner="manager_construction import call/value receipt subsumption",
                observed="multiple parked calls claim one imported value occurrence",
                requested="one exact parked call/value receipt relation",
                fix="repair call receipt uniqueness before value seating",
            )

        def seat_receipt() -> None:
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
        # Only the receipt's authenticated module identity selects among the
        # pre-authenticated graphs carried by this publication.
        dependency_graph = dependency_graphs.get(top_level)
        if dependency_graph is None:
            # An absent graph carries no source authority.  Leave the exact
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
            if imported.kind == "ambiguous-static-export" and len(
                paired_obligations
            ) == 1:
                # The exact call receipt already owns this callable occurrence
                # and remains parked/loud at the full Call coordinate.  Its
                # duplicate Attribute value receipt is deliberately unseated;
                # no candidate definition or runtime branch is selected.
                continue
            raise ImportValueUseSeatingGap(
                f"resolution-{imported.kind}",
                "authenticated value-use receipt did not resolve",
            )
        seat_receipt()
        context.source_import_value_resolutions[coordinate] = imported
        unit.seat_import_value_use_resolution(
            span_key, imported, source_cid=module.source_cid
        )


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
    existing = context.opaque_source_call_obligations.get(coordinate)
    if existing is not None and existing != obligation:
        raise BackendDefect(
            blame=call.fragment,
            owner="manager_construction._install_opaque_call_obligation",
            observed="conflicting opaque-call obligation",
            requested="byte-identical duplicate testimony",
            fix="resolve the conflicting target or authenticated owner",
        )
    context.opaque_source_call_obligations[coordinate] = obligation


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
