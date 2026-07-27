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
    Tuple_,
    With,
)
from sugar_source_tree.tree import SourceFile
from sugar_lift_py_tests.source_call_frame import SourceCallBindingGap

from .canonical import cid_of_json
from .dependency_artifact import DependencyArtifactGraph, ResolvedPythonObjectV1
from .resolution_session import SourceResolutionSession, session_or_new


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


@dataclass(frozen=True)
class ConstructedManagerBehaviorV1:
    resolved_object_cid: str
    manager_construction_cid: str
    receiver_state: ObjectValue = field(compare=False)
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

    managers: list[tuple[FloorValue, ObjectValue, CallSiteValue | None]] = []
    nested: list[tuple[FloorValue, FloorValue, CallSiteValue | None]] = []
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
                None,
                owner="construct_manager_behavior returned object",
            )
        except ConstructionPanic:
            # Missing body / later-stage force-floor on this face — try peers.
            continue
        if isinstance(floor, ObjectValue):
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
        identities = {item[1].identity for item in managers}
        if len(identities) > 1:
            refined = _sole_refined_manager(tuple(item[1] for item in managers))
            if refined is None:
                return ManagerConstructionGapV1(
                    "non-manager-result",
                    resolved_cid,
                    f"GuardedReturn with {len(identities)} manager receivers",
                )
            managers = [
                item for item in managers if item[1].identity == refined.identity
            ]
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

    managers: list[tuple[ObjectValue, tuple[FloorValue, ...]]] = []

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
        if isinstance(mgr, ObjectValue):
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
    identities = {item[0].identity for item in managers}
    if len(identities) > 1:
        refined = _sole_refined_manager(tuple(item[0] for item in managers))
        if refined is None:
            return ManagerConstructionGapV1(
                "non-manager-result",
                resolved_cid,
                f"ExitSet with {len(identities)} manager receivers",
            )
        managers = [item for item in managers if item[0].identity == refined.identity]
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

    candidates = [
        candidate
        for candidate in managers
        if all(
            candidate.identity == peer.identity or refines(candidate, peer)
            for peer in managers
        )
    ]
    identities = {item.identity for item in candidates}
    if len(identities) != 1:
        return None
    return candidates[0]


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
        values = frame.bind_actuals(
            tuple(item.value for item in actuals),
            tuple((name, item.value) for name, item in keyword_actuals),
        )
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
        authenticated_entries = []
        for entry, value in zip(frame.runtime_entries, values, strict=True):
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
    try:
        result = call.force_floor(
            None, owner="construct_manager_behavior", project_callsite=False
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
            from sugar_lift_py_tests.outcome import Complete, ExitSet

            outcome = call.reduce_source_outcome(None)
            if isinstance(outcome, ExitSet):
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
    if not isinstance(result, ObjectValue):
        return ManagerConstructionGapV1(
            "non-manager-result", resolved.cid, type(result).__name__
        )
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
            resolved, graph=graph, module=module, session=session
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
    definitions = tuple(
        item
        for item in source_file.root.body
        if isinstance(item, (FunctionDef, ClassDef))
    )
    target = next(
        (item for item in definitions if _matches_definition(item, resolved)), None
    )
    if target is None:
        return ManagerConstructionGapV1(
            "definition-missing", resolved.cid, "resolved definition coordinate"
        )

    definitions_by_name = {item.name: item for item in definitions}
    reachable_names = {target.name}
    pending_names = [target.name]
    while pending_names:
        current = definitions_by_name[pending_names.pop()]
        dependencies = []
        if isinstance(current, ClassDef):
            dependencies.extend(
                base.id for base in current.bases if isinstance(base, Name)
            )
            functions = tuple(
                item for item in current.body if isinstance(item, FunctionDef)
            )
        else:
            functions = (current,)
        dependencies.extend(
            call.func.id
            for function in functions
            for call in _local_named_calls(function)
        )
        for name in dependencies:
            if name in definitions_by_name and name not in reachable_names:
                reachable_names.add(name)
                pending_names.append(name)
    definitions = tuple(item for item in definitions if item.name in reachable_names)

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
    for item in definitions:
        if not isinstance(item, ClassDef):
            continue
        local_bases = []
        for base in item.bases:
            if not isinstance(base, Name) or base.id not in reaching_classes:
                local_bases = []
                break
            local_bases.append(reaching_classes[base.id].sugar())
        if local_bases and len(local_bases) == len(item.bases):
            context.source_class_bases[item.fragment.seal().cid] = tuple(local_bases)
        reaching_classes[item.name] = item
    for item in definitions:
        if isinstance(item, ClassDef):
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
            frames[function.name] = function.source_visible_call_frame()
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
    return frame, target, source_file


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
    projected = resolve_source_visible_frame(callee, graph=graph, session=session)
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


def _install_opaque_call_obligation(
    context: TreeConstructionContextV1,
    call: Call,
    obligation: OpaqueSourceCallObligationV1,
) -> None:
    from sugar_source_tree.panic import BackendDefect

    coordinate = _call_coordinate(call)
    if obligation.coordinate != coordinate:
        raise BackendDefect(
            owner="manager_construction._install_opaque_call_obligation",
            observed="obligation/call coordinate mismatch",
            requested="exact source-call coordinate testimony",
            fix="mint the obligation from the call being installed",
        )
    if coordinate in context.source_call_frames:
        raise BackendDefect(
            owner="manager_construction._install_opaque_call_obligation",
            observed="frame/obligation collision",
            requested="one source-call classification at the exact coordinate",
            fix="keep authenticated frames and opaque obligations disjoint",
        )
    existing = context.opaque_source_call_obligations.get(coordinate)
    if existing is not None and existing != obligation:
        raise BackendDefect(
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
            owner="manager_construction._install_source_call_frame",
            observed="frame/obligation collision",
            requested="one source-call classification at the exact coordinate",
            fix="keep authenticated frames and opaque obligations disjoint",
        )
    existing = context.source_call_frames.get(coordinate)
    if existing is not None and existing != frame:
        raise BackendDefect(
            owner="manager_construction._install_source_call_frame",
            observed="conflicting source-call frame",
            requested="byte-identical duplicate frame testimony",
            fix="resolve the conflicting authenticated source frame",
        )
    context.source_call_frames[coordinate] = frame
