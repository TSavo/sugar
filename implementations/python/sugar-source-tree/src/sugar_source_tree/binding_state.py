from __future__ import annotations

import weakref
from dataclasses import dataclass, fields, is_dataclass, replace
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, NoReturn, TypeAlias

from sugar_lift_python_source.canonical import cid_of_json

from .binding_provenance import (
    BindingCoordinateV1,
    BindingEntryV1 as SealedBindingEntryV1,
    BindingProvenanceGap,
    BindingStateV1 as SealedBindingStateV1,
    BoundBindingStateV1,
    ConstructedValueTestimonyV1,
    GuardedBindingStateV1,
    SubstitutionTraceRecordV1 as SealedSubstitutionTraceRecordV1,
    SubstitutionTraceV1 as SealedSubstitutionTraceV1,
    UnboundBindingStateV1,
)

if TYPE_CHECKING:
    from sugar_source_tree.fragment import SourceFragment
    from sugar_source_tree.nodes import Node


class BindingStateWireGap(BindingProvenanceGap):
    """A required binding/state testimony cannot enter the closed wire."""


RuntimeBindingEntryGap = BindingStateWireGap


def mint_binding_coordinate_v1(
    *,
    scope_owner_cid: str,
    binding_site: SourceFragment,
    projection_path: tuple[str | int, ...],
) -> BindingCoordinateV1:
    return BindingCoordinateV1.mint(scope_owner_cid, binding_site, projection_path)


def mint_constructed_value_testimony_v1(
    *, source_fragment: SourceFragment, semantic_value_cid: str
) -> ConstructedValueTestimonyV1:
    return ConstructedValueTestimonyV1.mint(source_fragment, semantic_value_cid)


@dataclass(frozen=True)
class UnboundBinding:
    name: str
    cause: SourceFragment


@dataclass(frozen=True)
class BranchResultSlot:
    slot_id: str


def branch_result_slot(test: Node) -> BranchResultSlot:
    memento = test.fragment.seal()
    address = f"{memento.source_cid}@{memento.start}:{memento.end}#{memento.cid}"
    return BranchResultSlot(f"branch-result:{address}")


@dataclass(frozen=True)
class GuardedBinding:
    slot: BranchResultSlot
    when_true: BindingState
    when_false: BindingState


def _require_runtime_cid(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.startswith("blake3-512:"):
        raise BindingStateWireGap(f"{field} must be an authenticated CID")


@dataclass(frozen=True)
class LoopProjectedCompletedFace:
    """One exact completed face retained by a loop post-binding projection."""

    target_cid: str
    completion_kind: str
    guard_formula_cid: str
    state: BindingState
    guard_formula: object | None = None
    exit_partition_arity: int | None = None
    """How many exit routes the PRODUCER declared for this loop occurrence.

    ``None`` is a face from a producer that never stated a family size. Such a
    face can still be read; it simply cannot carry completeness downstream, in
    the same way ``PartitionFace.arity is None`` cannot.
    """

    def __post_init__(self) -> None:
        _require_runtime_cid(self.target_cid, "targetCid")
        _require_runtime_cid(self.guard_formula_cid, "guardFormulaCid")
        if self.completion_kind not in {
            "BodyFallthrough",
            "BreakExit",
            "NormalExhaustion",
        }:
            raise BindingStateWireGap("unknown loop completion kind")
        from sugar_source_tree.nodes import Node

        if not isinstance(
            self.state,
            (Node, UnboundBinding, GuardedBinding, LoopProjectedBinding),
        ):
            raise BindingStateWireGap(
                "loop completed face requires an exact runtime binding state"
            )


@dataclass(frozen=True)
class LoopProjectedBinding:
    """Guarded completed post-state for one authenticated loop target.

    This is a runtime state of the sole ``BindingEntryV1`` carrier. CIDs remain
    identities/testimony; the live face states are what downstream substitution
    consumes.
    """

    target_cid: str
    completed_faces: tuple[LoopProjectedCompletedFace, ...]

    def __post_init__(self) -> None:
        _require_runtime_cid(self.target_cid, "targetCid")
        if not self.completed_faces:
            raise BindingStateWireGap("loop projected binding requires completed faces")
        if any(face.target_cid != self.target_cid for face in self.completed_faces):
            raise BindingStateWireGap("loop projected binding target mismatch")


BindingState: TypeAlias = (
    "Node | UnboundBinding | GuardedBinding | LoopProjectedBinding"
)


@dataclass(frozen=True)
class BindingEntryV1:
    """The sole runtime temporal binding entry.

    ``state`` is the live AST-local value consumed by substitution.  The
    closed ``sealed_state`` is only its authenticated transport projection;
    no live node enters ``wire()``.
    """

    coordinate: BindingCoordinateV1
    state: BindingState
    sealed_state: SealedBindingStateV1 | None

    @property
    def constructed_value_testimony(self) -> ConstructedValueTestimonyV1 | None:
        if isinstance(self.sealed_state, BoundBindingStateV1):
            return self.sealed_state.testimony
        return None

    def with_testimony(
        self, testimony: ConstructedValueTestimonyV1
    ) -> "BindingEntryV1":
        return replace(self, sealed_state=BoundBindingStateV1(testimony))

    def require_constructed_value_testimony(self) -> ConstructedValueTestimonyV1:
        from sugar_source_tree.nodes import Node

        if not isinstance(self.state, Node):
            raise BindingStateWireGap("binding state is not a constructed bound value")
        if self.constructed_value_testimony is None:
            raise BindingStateWireGap("constructed-value testimony unavailable")
        return self.constructed_value_testimony

    def wire(self) -> dict[str, Any]:
        if self.sealed_state is None:
            if isinstance(self.state, LoopProjectedBinding):
                raise BindingStateWireGap(
                    "loop projected binding requires authenticated face projection"
                )
            raise BindingStateWireGap(
                "runtime binding state has no authenticated sealed projection"
            )
        if (
            isinstance(self.sealed_state, BoundBindingStateV1)
            and self.sealed_state.testimony is None
        ):
            raise RuntimeBindingEntryGap("constructed-value testimony unavailable")
        return SealedBindingEntryV1.decode(
            SealedBindingEntryV1(self.coordinate, self.sealed_state).wire()
        ).wire()


BindingMap: TypeAlias = dict[str, "BindingEntryV1 | object"]


class RuntimeBindingEntryFactoryV1:
    """Compatibility-facing occurrence minter over the one runtime carrier."""

    def __init__(self, scope_owner_cid: str) -> None:
        self.scope_owner_cid = scope_owner_cid
        self._ordinal = 0

    def mint_entry(
        self,
        *,
        binding_site: SourceFragment,
        projection_path: tuple[str | int, ...],
        state: BindingState,
    ) -> BindingEntryV1:
        ordinal = self._ordinal
        self._ordinal += 1
        return BindingEntryV1(
            coordinate=mint_binding_coordinate_v1(
                scope_owner_cid=self.scope_owner_cid,
                binding_site=binding_site,
                projection_path=("occurrence", ordinal, *projection_path),
            ),
            state=state,
            sealed_state=_initial_sealed_state(state),
        )


@dataclass(frozen=True)
class RuntimeSubstitutionTraceRecordV1:
    statement_source: dict[str, Any]
    pre_bindings: tuple[tuple[str, BindingEntryV1], ...]
    post_bindings: tuple[tuple[str, BindingEntryV1], ...]
    cid: str


@dataclass(frozen=True)
class RuntimeSubstitutionTraceV1:
    scope_owner_cid: str
    records: tuple[RuntimeSubstitutionTraceRecordV1, ...]

    def project(self) -> SealedSubstitutionTraceV1:
        records = tuple(_seal_trace_record(record, None) for record in self.records)
        return SealedSubstitutionTraceV1.mint(self.scope_owner_cid, records)

    def wire(self) -> dict[str, Any]:
        return self.project().wire()


class SubstitutionTraceBuilderV1:
    """Mutable only during substitution; ``freeze`` publishes immutable wire."""

    def __init__(self, scope_owner_cid: str) -> None:
        self.scope_owner_cid = scope_owner_cid
        self._records: list[RuntimeSubstitutionTraceRecordV1] = []
        self._frozen = False
        self._binding_ordinal = 0

    def mint_entry(
        self,
        *,
        binding_site: SourceFragment,
        local_projection_path: tuple[str | int, ...],
        state: BindingState,
    ) -> BindingEntryV1:
        if self._frozen:
            raise ValueError("SubstitutionTraceBuilderV1 is frozen")
        ordinal = self._binding_ordinal
        self._binding_ordinal += 1
        coordinate = mint_binding_coordinate_v1(
            scope_owner_cid=self.scope_owner_cid,
            binding_site=binding_site,
            projection_path=("occurrence", ordinal, *local_projection_path),
        )
        return BindingEntryV1(
            coordinate=coordinate,
            state=state,
            sealed_state=_initial_sealed_state(state),
        )

    def record(self, statement: Node, pre: BindingMap, post: BindingMap) -> None:
        if self._frozen:
            raise ValueError("SubstitutionTraceBuilderV1 is frozen")
        pre_snapshot = _snapshot(pre)
        post_snapshot = _snapshot(post)
        statement_source = statement.fragment.seal().to_dict()
        preimage = {
            "kind": "substitution-trace-record",
            "schemaVersion": "1",
            "statementSource": statement_source,
            "preBindings": _snapshot_preimage(pre_snapshot),
            "postBindings": _snapshot_preimage(post_snapshot),
        }
        self._records.append(
            RuntimeSubstitutionTraceRecordV1(
                statement_source,
                pre_snapshot,
                post_snapshot,
                cid_of_json(preimage),
            )
        )

    def freeze(
        self, testimony_source: "ConstructionTestimonyReporterV1 | None" = None
    ) -> SealedSubstitutionTraceV1 | RuntimeSubstitutionTraceV1:
        """Publish the substitution trace.

        Without a testimony reporter (no loop consumer), keep the runtime
        trace and skip sealing/hashing every binding — measured exclusive
        cost of unconditional project() was ~1.2s on pandas asserters for
        functions that never need sealed wire. Sealed projections run only
        when a loop testimony reporter is provided.
        """
        if self._frozen:
            raise ValueError("SubstitutionTraceBuilderV1 is frozen")
        self._frozen = True
        runtime = RuntimeSubstitutionTraceV1(
            self.scope_owner_cid,
            tuple(
                _testify_trace_record(record, testimony_source)
                for record in self._records
            ),
        )
        if testimony_source is None:
            return runtime
        try:
            return runtime.project()
        except BindingProvenanceGap:
            return runtime

    def projected_snapshots_for(
        self,
        statement: Node,
        testimony_source: "ConstructionTestimonyReporterV1",
    ) -> tuple[tuple[SealedBindingEntryV1, ...], tuple[SealedBindingEntryV1, ...]]:
        """Project the unique authenticated trace record owned by a statement."""
        fragment_cid = statement.fragment.seal().cid
        matches = [
            record
            for record in self._records
            if record.statement_source.get("cid") == fragment_cid
        ]
        if len(matches) != 1:
            raise BindingStateWireGap(
                f"expected one substitution trace record for {fragment_cid}, got {len(matches)}"
            )
        record = matches[0]
        pre = _seal_snapshot(record.pre_bindings, testimony_source)
        post = _seal_snapshot(record.post_bindings, testimony_source)
        return (
            tuple(entry for _name, entry in pre),
            tuple(entry for _name, entry in post),
        )


class ConstructionTestimonyReporterV1:
    """Explicit one-traversal testimony projection layered over the roll call.

    It never constructs a value. ``Node.sugar`` hands it the value that the
    ordinary construction door already produced, and it seals that answer by
    the structural identity of the exact source/shadow node that produced it.
    """

    __slots__ = (
        "_delegate",
        "_by_node_shape",
        "_failed_by_node_shape",
        "_trace_builder",
    )

    def __init__(
        self, delegate: object, trace_builder: SubstitutionTraceBuilderV1
    ) -> None:
        self._delegate = delegate
        self._by_node_shape: dict[str, ConstructedValueTestimonyV1] = {}
        # Both outcomes are remembered at the same coordinate. A shape that
        # could not be testified re-raises the SAME typed panic, and re-raising
        # adds no roll-call mass: the gap was testified once, when it happened.
        self._failed_by_node_shape: dict[str, BaseException] = {}
        self._trace_builder = trace_builder

    def register(self, node: Node) -> None:
        self._delegate.register(node)

    def present_fact(self, node: Node) -> None:
        self._delegate.present_fact(node)

    def present_inert(self, node: Node) -> None:
        self._delegate.present_inert(node)

    def report_gap(self, node: Node, panic: object) -> None:
        self._delegate.report_gap(node, panic)

    def present_construction(self, node: Node, value: object) -> None:
        try:
            node_shape_cid = node_construction_shape_cid(node)
        except (TypeError, ValueError) as cause:
            self._testimony_gap(node, value, "node construction shape", cause)
        remembered_failure = self._failed_by_node_shape.get(node_shape_cid)
        if remembered_failure is not None:
            raise remembered_failure
        # Same content, same testimony: a node view is presented in every
        # snapshot it survives (asof: 2,277 presentations, 187 distinct shapes
        # -- 12x). The shape CID is the content key; once it is recorded, the
        # semantic-value CID and the testimony mint are pure recomputation.
        # Do the work once per shape.
        if node_shape_cid in self._by_node_shape:
            return
        try:
            semantic_value_cid = cid_of_json(_constructed_preimage(value))
        except (TypeError, ValueError) as cause:
            self._testimony_gap(
                node, value, "constructed value", cause, shape=node_shape_cid
            )
        self._by_node_shape[node_shape_cid] = mint_constructed_value_testimony_v1(
            source_fragment=node.fragment,
            semantic_value_cid=semantic_value_cid,
        )

    def _testimony_gap(
        self,
        node: Node,
        value: object,
        canonicalized: str,
        cause: Exception,
        shape: str | None = None,
    ) -> NoReturn:
        """The ONE typed door for a failed constructed-value testimony.

        Conservation is atomic: the gap is testified through the SAME roll call
        the census reads (``report_gap``, delegated to the collecting reporter)
        BEFORE the panic is raised, and ``Node.sugar`` raises before it records
        the present answer. So the coordinate carries exactly one discharge --
        the loud absent one -- never a present testimony it does not have and
        never no discharge at all.
        """
        from sugar_source_tree.panic import ConstructedValueTestimonyNotWritten

        panic = ConstructedValueTestimonyNotWritten(
            blame=node.fragment,
            owner="CollectingReporter.present_construction",
            observed=(
                f"{canonicalized} of {type(value).__name__} at "
                f"{_testimony_blame(node)} does not canonicalize: "
                f"{type(cause).__name__}: {cause}"
            ),
            requested="content-addressable constructed-value testimony",
            fix=(
                "teach canonicalization the general value category "
                "(_cv2_leaf / _cv2_entries) or keep the coordinate loud"
            ),
        )
        if shape is not None:
            self._failed_by_node_shape[shape] = panic
        self.report_gap(node, panic)
        raise panic

    def testimony_for(self, node: Node) -> ConstructedValueTestimonyV1 | None:
        # A miss is an honest None (this node was never presented); a
        # canonicalization FAILURE is not, and never returns quietly.
        try:
            node_shape_cid = node_construction_shape_cid(node)
        except (TypeError, ValueError) as cause:
            self._testimony_gap(node, node, "node construction shape", cause)
        return self._by_node_shape.get(node_shape_cid)

    def seal_snapshot(
        self, snapshot: tuple[tuple[str, BindingEntryV1], ...]
    ) -> tuple[tuple[str, BindingEntryV1], ...]:
        return _seal_snapshot(snapshot, self)

    def projected_snapshots_for(self, statement: Node):
        return self._trace_builder.projected_snapshots_for(statement, self)


def _testimony_blame(node: object) -> str:
    """The node's site, by the same projection ``Node.sugar`` uses."""
    from sugar_source_tree.panic import SourceTreePanic

    unit = getattr(node, "unit", None)
    where = getattr(unit, "filename", None)
    if not isinstance(where, str):
        return str(type(node).__name__)
    try:
        lc = node.line_col_span()
    except SourceTreePanic:
        return where
    return f"{where}:{lc.start_line}:{lc.start_col}"


def _seal_trace_record(
    record: RuntimeSubstitutionTraceRecordV1,
    testimony_source: ConstructionTestimonyReporterV1 | None,
) -> SealedSubstitutionTraceRecordV1:
    pre = _seal_snapshot(record.pre_bindings, testimony_source)
    post = _seal_snapshot(record.post_bindings, testimony_source)
    return SealedSubstitutionTraceRecordV1.mint(
        _ResolvedSourceFragment(record.statement_source),
        tuple(entry for _name, entry in pre),
        tuple(entry for _name, entry in post),
    )


def _testify_trace_record(
    record: RuntimeSubstitutionTraceRecordV1,
    testimony_source: ConstructionTestimonyReporterV1 | None,
) -> RuntimeSubstitutionTraceRecordV1:
    return RuntimeSubstitutionTraceRecordV1(
        record.statement_source,
        _testify_snapshot(record.pre_bindings, testimony_source),
        _testify_snapshot(record.post_bindings, testimony_source),
        record.cid,
    )


def _seal_snapshot(
    snapshot: tuple[tuple[str, BindingEntryV1], ...],
    testimony_source: ConstructionTestimonyReporterV1 | None,
) -> tuple[tuple[str, SealedBindingEntryV1], ...]:
    testified = _testify_snapshot(snapshot, testimony_source)
    return tuple(
        (name, SealedBindingEntryV1.decode(entry.wire())) for name, entry in testified
    )


def _testify_snapshot(
    snapshot: tuple[tuple[str, BindingEntryV1], ...],
    testimony_source: ConstructionTestimonyReporterV1 | None,
) -> tuple[tuple[str, BindingEntryV1], ...]:
    if testimony_source is None:
        return snapshot
    testified: list[tuple[str, BindingEntryV1]] = []
    for name, entry in snapshot:
        testimony = entry.constructed_value_testimony
        if testimony is None:
            from sugar_source_tree.nodes import Node

            if isinstance(entry.state, Node):
                testimony = testimony_source.testimony_for(entry.state)
        runtime = entry if testimony is None else entry.with_testimony(testimony)
        testified.append((name, runtime))
    return tuple(testified)


class _ResolvedSourceFragment:
    """Already-authenticated source memento adapter used only for re-sealing."""

    def __init__(self, source: dict[str, Any]) -> None:
        self._source = source

    def seal(self):
        class _Memento:
            def __init__(self, source):
                self._source = source

            def to_dict(self):
                return self._source

        return _Memento(self._source)


def _initial_sealed_state(state: BindingState) -> SealedBindingStateV1:
    from sugar_source_tree.nodes import Node

    if isinstance(state, Node):
        return BoundBindingStateV1(None)
    if isinstance(state, UnboundBinding):
        return UnboundBindingStateV1(state.cause.seal().cid)
    if isinstance(state, GuardedBinding):
        return None
    if isinstance(state, LoopProjectedBinding):
        return None
    raise BindingStateWireGap(f"unknown runtime binding state {type(state).__name__}")


def node_construction_shape_cid(node: Node) -> str:
    # The shape CID is a CATEGORY of content-addressed work: a pure function of
    # the backend ref (fragment + subtree preimage), which the ref determines
    # (verified: no ref maps to two shape CIDs). The tree holds many node views
    # over one ref -- a binding live across N statements is testified in every
    # pre/post snapshot it survives -- so canonicalizing the full subtree from
    # scratch each time is the dominant construction cost (core/generic._where:
    # 91,516 recomputations, 180s). Memoize it in the STATIC category registry:
    # new does the work once, every view thereafter sees it done.
    from .construction_cache import remember_shape_cid, shape_cid_for

    ref = node.ref
    cached = shape_cid_for(ref)
    if cached is not None:
        return cached
    result = cid_of_json(
        {
            "kind": "constructed-node-shape",
            "schemaVersion": "2",
            "shapeSchema": NODE_SHAPE_V2_SCHEMA,
            "source": node.fragment.seal().to_dict(),
            "nodeShape": backend_node_shape_cid_v2(ref),
        }
    )
    remember_shape_cid(ref, result)
    return result


# ---------------------------------------------------------------------------
# NodeShapeV2 -- the Merkle shape preimage.
#
# V1 embedded each child's FULL subtree preimage inside its parent, so the same
# descendant content was authenticated once for every ancestor path above it:
# total encoding work was the sum of all subtree sizes, i.e. quadratic in depth.
# Measured consequence: 624s cumulative in ``canonical_json_bytes`` over only
# 1,318 CID calls on pandas ``core/reshape/pivot.py::__internal_pivot_table``.
#
# V2 is the content-addressed form the graph always wanted: a node authenticates
# its own IMMEDIATE structure plus the authenticated IDENTITIES (CIDs) of its
# children. Each node's preimage is O(its own arity); the whole tree is O(n).
#
# Domain separation is explicit and total:
#   * the child-CID algorithm is NAMED in every preimage
#     (``childCidAlgorithm``), so a child slot's string can never be mistaken
#     for an opaque leaf or for a CID minted by some other schema;
#   * the schema tag ``NodeShapeV2`` and the outer ``schemaVersion: "2"`` put
#     V2 in a different identity namespace from V1 -- no V1 preimage can ever
#     encode to a V2 preimage, so no V1 CID is ever reinterpretable as V2.
#
# This migration DOES change every shape CID. That is sanctioned and pinned
# deliberately: shape CIDs are REPRESENTATION identity, never meaning. The
# constructed meaning (formulas, bindings, effects, gaps, ExitSets, corpus
# classification) is unchanged, and is what the equivalence proof measures --
# a fingerprint built from shape CIDs would be circular here.
# ---------------------------------------------------------------------------

NODE_SHAPE_V2_SCHEMA = "NodeShapeV2"
NODE_SHAPE_V2_DOMAIN = "sugar/construction/node-shape/v2"
# The child slot carries a CID, and THIS names the algorithm that minted it:
# the same NodeShapeV2 preimage under the repository canonical JSON CID.
NODE_SHAPE_V2_CHILD_CID_ALGORITHM = "sugar/construction/node-shape/v2+cid_of_json"


def _child_handles(desc: object) -> list[object]:
    """Every child handle of ``desc``, in slot order then position order."""
    from sugar_source_tree.backend import Child, Children, MaybeChild

    handles: list[object] = []
    for _name, slot in desc.slots:  # type: ignore[attr-defined]
        if isinstance(slot, Child):
            handles.append(slot.handle)
        elif isinstance(slot, MaybeChild):
            if slot.handle is not None:
                handles.append(slot.handle)
        elif isinstance(slot, Children):
            handles.extend(slot.handles)
    return handles


def _node_shape_v2_preimage(ref: object, child_cid: "dict[int, str]") -> dict[str, Any]:
    """The V2 preimage of ONE node: its kind, its local authenticated fields,
    and its ordered slots carrying CHILD CIDS -- never child subtrees.

    Every slot kind keeps its own wrapper key, so the six kinds stay mutually
    distinguishable and none can collide with another:

      Child(x)          -> {"child": cid}
      MaybeChild(x)     -> {"maybeChild": cid}
      MaybeChild(None)  -> {"maybeChild": None}   (present-but-empty)
      Children([x])     -> {"children": [cid]}    (never a bare child)
      Children([])      -> {"children": []}       (present-but-empty)
      Leaf(v)           -> {"leaf": <canonical value>}
      OpLeaf(op)        -> {"operator": kind}
      OpsLeaf(ops)      -> {"operators": [kind, ...]}

    An ABSENT slot emits no entry at all, and every entry carries its NAME, so
    ``MaybeChild(None)`` (an entry whose value is ``{"maybeChild": null}``)
    can never collide with the absence of that slot. Positions are a JSON
    ARRAY in the backend's declared order: reordering, duplicating or omitting
    children changes the encoding, hence the CID.
    """
    from sugar_source_tree.backend import (
        Child,
        Children,
        Leaf,
        MaybeChild,
        OpLeaf,
        OpsLeaf,
    )

    desc = ref.describe()  # type: ignore[attr-defined]
    slots = []
    for name, slot in desc.slots:
        if isinstance(slot, Child):
            value = {"child": child_cid[id(slot.handle)]}
        elif isinstance(slot, MaybeChild):
            value = {
                "maybeChild": (
                    None if slot.handle is None else child_cid[id(slot.handle)]
                )
            }
        elif isinstance(slot, Children):
            value = {"children": [child_cid[id(h)] for h in slot.handles]}
        elif isinstance(slot, Leaf):
            value = {"leaf": constructed_value_slot_v2(slot.value)}
        elif isinstance(slot, OpLeaf):
            value = {"operator": slot.op.kind}
        elif isinstance(slot, OpsLeaf):
            value = {"operators": [operator.kind for operator in slot.ops]}
        else:
            # NEVER a fallback to subtree embedding: an unknown slot kind is a
            # gap in the schema, reported loudly, not inlined behind our backs.
            raise TypeError(f"unknown backend slot {type(slot).__name__}")
        slots.append({"name": name, "value": value})
    return {
        "domain": NODE_SHAPE_V2_DOMAIN,
        "schema": NODE_SHAPE_V2_SCHEMA,
        "childCidAlgorithm": NODE_SHAPE_V2_CHILD_CID_ALGORITHM,
        "kind": desc.kind,
        "slots": slots,
    }


def backend_node_shape_cid_v2(ref: object) -> str:
    """The NodeShapeV2 CID of ``ref``, built STRICTLY BOTTOM-UP.

    Explicit post-order over an iterative stack -- no recursion, no recursive
    subtree embedding, and no Python recursion limit on deep trees. Each
    distinct ref encodes exactly ONE preimage of its own arity, memoized in the
    static category registry, so a shared child (substitution shares node
    objects; the constructed graph is a DAG) is encoded once, not once per
    incoming path.

    Two structurally identical subtrees under two DISTINCT refs get the SAME
    CID -- that is content identity, and it is the point. They remain distinct
    OCCURRENCES: the memo is keyed by ref (two live refs, two rows, one value),
    and the parent carries them at distinct ordered slot positions, so anything
    keyed by occurrence still sees two.
    """
    from .construction_cache import (
        remember_shape_cid_v2,
        shape_cid_v2_for,
    )

    cached = shape_cid_v2_for(ref)
    if cached is not None:
        return cached

    child_cid: dict[int, str] = {}
    # ``child_cid`` is keyed by id(); pin every keyed handle for the duration so
    # a dead handle's address can never be recycled onto another's row.
    pinned: list[object] = []
    # (ref, expanded?) -- expanded means its children are already resolved.
    stack: list[tuple[object, bool]] = [(ref, False)]
    while stack:
        current, expanded = stack.pop()
        if id(current) in child_cid:
            continue
        known = shape_cid_v2_for(current)
        if known is not None:
            child_cid[id(current)] = known
            pinned.append(current)
            continue
        if not expanded:
            stack.append((current, True))
            for handle in _child_handles(current.describe()):  # type: ignore[attr-defined]
                if id(handle) not in child_cid:
                    stack.append((handle, False))
            continue
        cid = cid_of_json(_node_shape_v2_preimage(current, child_cid))
        child_cid[id(current)] = cid
        pinned.append(current)
        remember_shape_cid_v2(current, cid)
    result = child_cid[id(ref)]
    del pinned
    return result


# ---------------------------------------------------------------------------
# ConstructedValueV2 -- the Merkle preimage of a CONSTRUCTED SEMANTIC VALUE.
#
# THE DEFECT V2 CLOSES. V1 built one JSON document per presented value by
# recursively INLINING every child value's full canonical form. The constructed
# graph is a DAG (substitution shares sugar objects), and V1 walked it as a
# TREE, so the same descendant content was encoded once for every ancestor path
# above it: total encoded work was the sum of all subtree sizes. Measured
# consequence after NodeShapeV2 (#6253) had already fixed the node layer:
# ``cid_of_json`` 2,736s cumulative over only 1,482 calls out of
# ``present_construction`` -- ~39,100 JSON nodes per call -- on pandas
# ``core/reshape/pivot.py::__internal_pivot_table``. Same disease as #6253, one
# layer up.
#
# T'S CHILD IDENTITY LAW. A child constructed semantic value is referenced by a
# DOMAIN-SEPARATED CID of that child's immutable semantic content. Its
# OCCURRENCE identity remains separate and is never inferred from the content
# CID. Two identities stay explicit and are never collapsed into one:
#
#     semantic content CID    answers "what value?"
#     construction occurrence answers "which construction/site produced it?"
#
# Equal immutable values MAY share the semantic CID -- that is what makes the
# form linear. They must NOT merge roll-call seats, effect occurrences,
# bindings, or source sites, and they do not: occurrence identity is carried by
# BindingCoordinateV1, by the node shape CID keyed presentation registry, and by
# the ordered ``at`` coordinate a child occupies inside its parent -- never by
# this content CID.
#
# THE FORM.
#
#     ConstructedValueV2 {
#         domain, schema, childCidAlgorithm,   -- total domain separation
#         semanticType,                        -- stable semantic type tag
#         arity,                               -- authenticated slot count
#         localFields: [ {at, leaf}, ... ],    -- authenticated scalar leaves
#         children:    [ {at, childConstructedValueCid}, ... ],
#     }
#
# Each value encodes a preimage of its OWN arity; the whole DAG is O(n) and each
# distinct content coordinate is hashed exactly once.
#
# CLASSIFICATION IS EXHAUSTIVE AND CLOSED. Every category is NAMED. There is no
# generic reflective fallback and no generic ``.wire()`` call: a value whose
# category this schema cannot name is a TYPED TESTIMONY GAP
# (``ConstructedValueCategoryGap``), reported loudly through the one testimony
# gap door, never an invented preimage.
#
# V1 AND V2 NEVER SHARE AN IDENTITY NAMESPACE. The outer envelope carries
# ``schemaVersion: "2"`` plus ``valueSchema``/``childCidAlgorithm``, which no V1
# preimage ever carried, so no V1 CID is reinterpretable as V2 and vice versa.
#
# This migration DOES change every constructed-value CID, deliberately and
# pinned. Constructed-value CIDs are REPRESENTATION identity, never meaning: the
# formulas, bindings, effects, gaps, ExitSets and terminal fingerprints the
# census reads are CID-INDEPENDENT and are what the equivalence proof measures.
# ---------------------------------------------------------------------------

CONSTRUCTED_VALUE_V2_SCHEMA = "ConstructedValueV2"
CONSTRUCTED_VALUE_V2_DOMAIN = "sugar/construction/constructed-value/v2"
# The child slot carries a CID, and THIS names the algorithm that minted it: the
# same ConstructedValueV2 preimage under the repository canonical JSON CID. A
# child slot's string can therefore never be read as an opaque leaf, nor as a
# CID minted by NodeShapeV2 or by any other schema.
CONSTRUCTED_VALUE_V2_CHILD_CID_ALGORITHM = (
    "sugar/construction/constructed-value/v2+cid_of_json"
)


class ConstructedValueCategoryGap(TypeError):
    """A value category ConstructedValueV2 will NOT invent a preimage for.

    A ``TypeError`` subclass so it travels the SAME typed door every other
    canonicalization failure travels (``present_construction`` catches
    ``(TypeError, ValueError)`` and mints the loud
    ``ConstructedValueTestimonyNotWritten`` gap). Raising it is the schema
    saying "I cannot NAME this value's category", which is testimony, not a
    reason to reach for reflection.
    """


def _cv2_type_tag(value: object) -> str:
    """The stable semantic type tag of ``value``'s class."""
    cls = type(value)
    return f"{cls.__module__}.{cls.__qualname__}"


_NOT_A_LEAF = object()

# (type, cid) pairs whose ``cid_of_json(preimage) == cid`` has been checked once.
# Validation is the whole warrant for the native-CID arm, so it is CHECKED, not
# trusted -- but it is a pure function of the pair, so it is checked once.
_VALIDATED_NATIVE_CIDS: set[tuple[type, str]] = set()


def _validated_native_cid(value: object) -> str | None:
    """``value``'s own CID, iff that CID already authenticates its content.

    T's rule: reference an existing wire/CID-owning value's validated native CID
    *where that CID already authenticates the complete semantic content*. The
    warrant is checkable and is CHECKED here -- ``cid_of_json(value.preimage)``
    must reproduce ``value.cid``, exactly the admission test
    ``seal_binding_state_v1`` applies. A value that merely *has* a ``.cid``
    attribute earns nothing.

    This is deliberately NOT ``.wire()``: ``wire()`` is an arbitrary method call
    whose inputs this module cannot enumerate. ``preimage``/``cid`` is a
    self-authenticating pair, and its failure mode is a miss, never a guess.
    """
    cid = getattr(value, "cid", None)
    if not isinstance(cid, str):
        return None
    key = (type(value), cid)
    if key in _VALIDATED_NATIVE_CIDS:
        return cid
    try:
        preimage = value.preimage  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 -- an unreadable preimage authenticates nothing
        return None
    if not isinstance(preimage, (dict, list)):
        return None
    try:
        recomputed = cid_of_json(preimage)
    except (TypeError, ValueError):
        return None
    if recomputed != cid:
        return None
    _VALIDATED_NATIVE_CIDS.add(key)
    return cid


def _cv2_leaf(value: object) -> Any:
    """``value``'s INLINE leaf encoding, or ``_NOT_A_LEAF``.

    A leaf is a value whose complete semantic content is already authenticated
    by a bounded, non-recursive spelling. Every leaf carries its own category
    key, so a leaf can never be confused with another leaf category and a leaf
    string can never be read as a child CID (children live under a different
    key entirely).

    ``Enum`` is tested BEFORE ``int``: an ``IntEnum`` member IS an ``int``, and
    V1's arm order encoded it as a bare integer, losing the member. V2 keeps the
    enum type and member tags and never recurses into ``.value``.
    """
    from sugar_source_tree.fragment import SourceFragment, SourceMemento

    if value is None:
        return {"null": None}
    if isinstance(value, Enum):
        # Stable enum type + MEMBER tags. Never the member's payload: two
        # members can carry equal payloads, and the member is the meaning.
        return {"enum": {"enumType": _cv2_type_tag(value), "member": value.name}}
    if isinstance(value, bool):
        return {"bool": value}
    if isinstance(value, int):
        return {"int": value}
    if isinstance(value, str):
        return {"str": value}
    if isinstance(value, float):
        from decimal import Decimal

        # The one canonical float spelling the system already uses (see
        # term_value.to_term / ir.real_lit): a fixed-point decimal string, never
        # a Python float text form.
        return {"float": format(Decimal(str(value)), "f")}
    if isinstance(value, bytes):
        return {"bytes": value.hex()}
    if isinstance(value, SourceFragment):
        # Reference its EXISTING authenticated identity, unreinterpreted. The
        # sealed memento is five flat fields -- bounded, never a subtree.
        return {"sourceFragment": value.seal().to_dict()}
    if isinstance(value, SourceMemento):
        return {"sourceMemento": value.to_dict()}
    from sugar_source_tree.nodes import Node

    if isinstance(value, Node):
        # A Node is a tree VIEW, not content. Its content identity is its
        # NodeShapeV2 construction-shape CID; its unit/span are the positional
        # OCCURRENCE coordinate and must never enter a content CID.
        return {"nodeShapeCid": node_construction_shape_cid(value)}
    native = _validated_native_cid(value)
    if native is not None:
        return {"authenticatedValueCid": {"type": _cv2_type_tag(value), "cid": native}}
    return _NOT_A_LEAF


def _cv2_entries(value: object) -> tuple[str, list[tuple[Any, object]]]:
    """``value``'s semantic type tag and its ordered ``(at, child)`` slots.

    Called only for values ``_cv2_leaf`` declined. Every arm is NAMED; the final
    arm is a typed gap, never reflection over ``__dict__`` and never
    ``.wire()``.
    """
    if isinstance(value, tuple):
        # Length and position are authenticated: ``at`` is the index, and
        # ``arity`` is encoded, so reordering, duplicating or omitting a child
        # changes the preimage.
        return ("tuple", [(index, item) for index, item in enumerate(value)])
    if isinstance(value, frozenset):
        # An unordered frozen collection: ``at`` is deliberately absent and the
        # entries are sorted by their own encoding at emit time, so the CID is a
        # function of the MEMBERSHIP, never of Python's hash iteration order.
        return ("frozenset", [(None, item) for item in value])
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise ConstructedValueCategoryGap(
                "constructed testimony mappings require string keys; "
                f"{_cv2_type_tag(value)} carries "
                f"{sorted({type(k).__name__ for k in value})}"
            )
        # Key/value PAIRING is authenticated (``at`` is the key, carried beside
        # its own value) under a deterministic (sorted) order.
        return ("mapping", [(key, value[key]) for key in sorted(value)])
    if is_dataclass(value) and not isinstance(value, type):
        params = getattr(value, "__dataclass_params__", None)
        if params is not None and params.frozen:
            return (
                _cv2_type_tag(value),
                [(field.name, getattr(value, field.name)) for field in fields(value)],
            )
        raise ConstructedValueCategoryGap(
            f"{_cv2_type_tag(value)} is a MUTABLE dataclass: its content can "
            "change after testimony, so it has no content coordinate. Make the "
            "semantic value frozen, or keep the coordinate loud."
        )
    if isinstance(value, (list, set, bytearray)):
        raise ConstructedValueCategoryGap(
            f"{_cv2_type_tag(value)} is a MUTABLE container: snapshotting it "
            "would authenticate a moment, not a value. Carry a tuple/frozenset "
            "semantic value, or keep the coordinate loud."
        )
    raise ConstructedValueCategoryGap(
        f"unclassified constructed value category {_cv2_type_tag(value)}: "
        "ConstructedValueV2 names its categories and will not invent a preimage "
        "by reflection. Name the category, or keep the coordinate loud."
    )


def _cv2_classify(
    value: object,
) -> tuple[str, int, list[dict[str, Any]], list[tuple[Any, object]]]:
    """``value``'s semantic type, arity, inline leaves and child values.

    Classification happens exactly ONCE per value: ``_cv2_leaf`` is not free
    (a ``SourceFragment`` leaf seals its segment, which hashes text), so the
    bottom-up loop caches this and never re-asks a slot's category.
    """
    semantic_type, entries = _cv2_entries(value)
    local_fields: list[dict[str, Any]] = []
    children: list[tuple[Any, object]] = []
    for at, child in entries:
        leaf = _cv2_leaf(child)
        if leaf is _NOT_A_LEAF:
            children.append((at, child))
        else:
            local_fields.append({"at": at, "leaf": leaf})
    return semantic_type, len(entries), local_fields, children


def _cv2_preimage(
    semantic_type: str,
    arity: int,
    local_fields: list[dict[str, Any]],
    children: list[tuple[Any, object]],
    child_cid: dict[int, str],
) -> dict[str, Any]:
    """ONE value's V2 preimage: its own arity, never a child's subtree."""
    child_entries = [
        {"at": at, "childConstructedValueCid": child_cid[id(child)]}
        for at, child in children
    ]
    if semantic_type == "frozenset":
        # Membership, not iteration order. Sorting by the entry's own canonical
        # encoding is total and deterministic.
        local_fields = sorted(local_fields, key=cid_of_json)
        child_entries.sort(key=lambda entry: entry["childConstructedValueCid"])
    return {
        "domain": CONSTRUCTED_VALUE_V2_DOMAIN,
        "schema": CONSTRUCTED_VALUE_V2_SCHEMA,
        "childCidAlgorithm": CONSTRUCTED_VALUE_V2_CHILD_CID_ALGORITHM,
        "semanticType": semantic_type,
        "arity": arity,
        "localFields": local_fields,
        "children": child_entries,
    }


def constructed_value_cid_v2(value: object) -> str:
    """The ConstructedValueV2 content CID of ``value``, built BOTTOM-UP.

    Explicit post-order over an iterative stack: no recursion, no recursive
    embedding of a child's preimage, and no Python recursion limit on deep
    constructed graphs. Each distinct content coordinate encodes exactly ONE
    preimage of its own arity, so a shared DAG child is hashed once per content
    coordinate rather than once per incoming path.

    A value reached while it is still being expanded is a CYCLE: a typed gap,
    loudly, never a truncation or a placeholder.
    """
    from .construction_cache import (
        constructed_value_cid_v2_for,
        remember_constructed_value_cid_v2,
    )

    cached = constructed_value_cid_v2_for(value)
    if cached is not None:
        return cached

    child_cid: dict[int, str] = {}
    classified: dict[int, tuple[str, int, list[dict[str, Any]], list[Any]]] = {}
    # ``child_cid`` and ``classified`` are keyed by id(); pin every keyed
    # value for the duration so a dead value's address can never be recycled
    # onto another's row.
    pinned: list[object] = []
    # Values whose expansion has begun and not finished -- the DFS "gray" set,
    # which is exactly the cycle predicate.
    expanding: dict[int, object] = {}
    stack: list[tuple[object, bool]] = [(value, False)]
    while stack:
        current, expanded = stack.pop()
        if id(current) in child_cid:
            continue
        known = constructed_value_cid_v2_for(current)
        if known is not None:
            child_cid[id(current)] = known
            pinned.append(current)
            continue
        row = classified.get(id(current))
        if row is None:
            row = _cv2_classify(current)
            classified[id(current)] = row
        semantic_type, arity, local_fields, children = row
        pinned.append(current)
        if not expanded:
            expanding[id(current)] = current
            stack.append((current, True))
            for _at, child in children:
                if id(child) in child_cid:
                    continue
                if id(child) in expanding:
                    raise ConstructedValueCategoryGap(
                        "constructed value graph is CYCLIC through "
                        f"{_cv2_type_tag(child)}: a cycle has no content "
                        "coordinate. Keep the coordinate loud."
                    )
                stack.append((child, False))
            continue
        expanding.pop(id(current), None)
        cid = cid_of_json(
            _cv2_preimage(semantic_type, arity, local_fields, children, child_cid)
        )
        child_cid[id(current)] = cid
        remember_constructed_value_cid_v2(current, cid)
    result = child_cid[id(value)]
    del pinned
    return result


def constructed_value_slot_v2(value: object) -> dict[str, Any]:
    """One value as it appears in a slot: an inline leaf, or a child CID.

    The two forms live under DIFFERENT keys, so a leaf string can never be read
    as a child CID and a child CID can never be read as a leaf.
    """
    leaf = _cv2_leaf(value)
    if leaf is not _NOT_A_LEAF:
        return {"leaf": leaf}
    return {"constructedValueCid": constructed_value_cid_v2(value)}


def _constructed_preimage(value: object) -> dict[str, Any]:
    """The envelope a presented construction's semantic-value CID is taken of.

    ``schemaVersion: "2"`` plus the named value schema and child-CID algorithm
    put V2 in an identity namespace disjoint from V1's.
    """
    return {
        "kind": "constructed-semantic-value",
        "schemaVersion": "2",
        "valueSchema": CONSTRUCTED_VALUE_V2_SCHEMA,
        "childCidAlgorithm": CONSTRUCTED_VALUE_V2_CHILD_CID_ALGORITHM,
        "value": constructed_value_slot_v2(value),
    }


def _snapshot(scope: BindingMap) -> tuple[tuple[str, BindingEntryV1], ...]:
    return tuple(
        sorted(
            (
                (name, entry)
                for name, entry in scope.items()
                if isinstance(name, str) and isinstance(entry, BindingEntryV1)
            ),
            key=lambda item: item[1].coordinate.cid,
        )
    )


def _snapshot_preimage(
    snapshot: tuple[tuple[str, BindingEntryV1], ...],
) -> list[dict[str, Any]]:
    del_names = []
    for _name, entry in snapshot:
        state = entry.state
        if entry.constructed_value_testimony is not None:
            cell = {
                "kind": "bound-value",
                "constructedValueTestimonyCid": entry.constructed_value_testimony.cid,
            }
        elif isinstance(state, UnboundBinding):
            cell = {"kind": "unbound", "causeFragmentCid": state.cause.seal().cid}
        else:
            # Guarded and pending bound states have no serializable testimony
            # yet. They remain present in the in-memory snapshot but cannot mint
            # a state CID; callers that need wire admission must stay loud.
            cell = {"kind": "unserializable"}
        del_names.append({"bindingCoordinateCid": entry.coordinate.cid, "cell": cell})
    return del_names


def seal_binding_state_v1(
    snapshot: tuple[tuple[str, BindingEntryV1], ...],
) -> dict[str, Any]:
    """Seal one testified lexical snapshot into the shared BindingState wire.

    Lexical names are deliberately ignored. Entry ordering and identity come
    only from BindingCoordinateV1; a bound cell without construction testimony
    cannot be serialized and therefore stays loud at its consumer.
    """

    entries = []
    for _name, entry in sorted(snapshot, key=lambda item: item[1].coordinate.cid):
        if cid_of_json(entry.coordinate.preimage) != entry.coordinate.cid:
            raise BindingStateWireGap("binding coordinate CID mismatch")
        if isinstance(entry.sealed_state, BoundBindingStateV1):
            testimony = entry.require_constructed_value_testimony()
            if cid_of_json(testimony.preimage) != testimony.cid:
                raise BindingStateWireGap("constructed-value testimony CID mismatch")
        entries.append(entry.wire())
    from sugar_lift_py_tests.loop_construction import seal_binding_state_v1 as seal

    return seal(tuple(entries))


def unwrap_binding_state(value):
    return value.state if isinstance(value, BindingEntryV1) else value


def binding_state_read_node(
    state: BindingState,
    *,
    make_read: Callable[[UnboundBinding | GuardedBinding], Node],
) -> Node:
    """Project binding availability into the tree's ordinary Node currency.

    Binding-state witnesses are deliberately not AST nodes.  A consumer that
    reads a binding must project an unbound/guarded state into the explicit
    read node owned by the read site before placing it in a shadow child slot.
    """
    from sugar_source_tree.nodes import Node

    state = unwrap_binding_state(state)

    if isinstance(state, Node):
        return state
    if isinstance(state, (UnboundBinding, GuardedBinding)):
        return make_read(state)
    if isinstance(state, LoopProjectedBinding):
        # A single completion face is the TOTAL post-value (a no-break loop
        # exits only by NormalExhaustion), so read straight through it. A
        # multi-face join stays loud rather than silently pick one arm.
        if len(state.completed_faces) == 1:
            return binding_state_read_node(
                state.completed_faces[0].state, make_read=make_read
            )
        raise TypeError(type(state))
    raise TypeError(type(state))


def join_binding_state(
    *,
    slot: BranchResultSlot,
    when_true: BindingState,
    when_false: BindingState,
    make_ifexp,
) -> BindingState:
    """Join the two branch faces of one binding into a single state.

    THE ``IfExp`` COLLAPSE BELOW IS LOAD-BEARING, NOT A CONVENIENCE. It reads
    like an optimisation -- both sides are plain values, so express the join as
    an if-expression instead of a guarded binding -- and it is the single thing
    keeping the commonest conditional-binding shape in real code away from a
    source-keyed partition.

    ``GuardedBinding`` is what later mints
    ``partition(("binding.projection", slot.slot_id))``, and ``slot_id`` is
    keyed on ``(source_cid, span, fragment_cid)`` with NO execution component
    (``branch_result_slot``). ``_faces_exclusive`` then proves two arms
    exclusive from their carried faces alone and never reads their guards. So
    two arms from DIFFERENT executions that shared one slot would be declared
    mutually exclusive and collapsed into a single guarded value -- the second
    execution's value re-attributed to the negation of the first's guard.

    That conflation is not reachable today, and this arm is one of three
    reasons why. The other two are that ordinary call sites stay opaque (one
    callee is not reduced twice into one ``ExitSet``) and that loops route
    through ``LoopGuardedProjection`` instead.

    THE MINT NEEDS ALL THREE OF: a name bound in exactly ONE branch, with NO
    PRIOR BINDING of that name, then read afterwards. Measured::

        if p: x = 1 else: x = 2 ; return x   ->  no mint   (this arm)
        x = 0 ; if p: x = 1 ; return x       ->  no mint
        if p: x = 1 ; return x               ->  MINTS

    The prior binding kills it for the same reason this arm does: ``x = 0``
    leaves the else-face bound too, so the join has a plain Node on both sides
    and collapses here. **Initializing the name first is the more natural way
    to write that code**, which is why the mint is harder to reach than "bound
    in one branch, then read" suggests -- one of twelve probed shapes reaches
    it. Anyone checking this docstring against a shape with a prior
    initialization will see no mint and should not conclude the docstring is
    wrong.

    **Making this symmetric -- returning a ``GuardedBinding`` here for
    consistency with the arms below -- would hand a source-keyed partition to
    the most common shape in the corpus.** Do not do it without giving the slot
    an execution component first.

    Pinned by ``tests/test_binding_partition_execution_conflation.py``
    (``test_tripwire_a_two_branch_binding_never_mints``), which fails if this
    arm stops collapsing, and by the tripwires beside it for the other two
    properties.
    """
    from sugar_source_tree.nodes import Node

    if when_true is when_false or when_true == when_false:
        return when_true
    when_true = unwrap_binding_state(when_true)
    when_false = unwrap_binding_state(when_false)
    if isinstance(when_true, Node) and isinstance(when_false, Node):
        # Both sides are plain values: the join is an if-expression, and NO
        # partition is minted. See the docstring -- this is the property that
        # keeps ordinary conditional bindings off the source-keyed partition.
        return make_ifexp(slot, when_true, when_false)
    if isinstance(when_true, UnboundBinding) and isinstance(when_false, UnboundBinding):
        return UnboundBinding(name=when_true.name, cause=when_true.cause)
    return GuardedBinding(slot=slot, when_true=when_true, when_false=when_false)
