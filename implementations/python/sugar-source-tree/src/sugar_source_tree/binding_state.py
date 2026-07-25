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
            owner="CollectingReporter.present_construction",
            observed=(
                f"{canonicalized} of {type(value).__name__} at "
                f"{_testimony_blame(node)} does not canonicalize: "
                f"{type(cause).__name__}: {cause}"
            ),
            requested="content-addressable constructed-value testimony",
            fix=(
                "teach canonicalization the general value category "
                "(_canonical_constructed_value) or keep the coordinate loud"
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
            value = {"leaf": _canonical_constructed_value(slot.value)}
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


def _constructed_preimage(value: object) -> dict[str, Any]:
    return {
        "kind": "constructed-semantic-value",
        "schemaVersion": "1",
        "value": _canonical_constructed_value(value),
    }


# Canonicalization is content-addressed WORK over a shared value DAG that the
# recursion below walks as a TREE. Measured on pandas
# ``core/indexes/base.py::_join_level``: 758,852 calls over 1,544 distinct value
# objects -- 491x recomputation, and the cost the silent testimony skip used to
# hide by aborting canonicalization early. Same ruling as the static
# ``_SHAPE_CIDS`` registry: the work is content-addressed, so it is done once at
# its coordinate and read thereafter. Never skip testimony to buy speed.
#
# THE KEY IS THE COORDINATE, NOT THE ADDRESS. The key must cover every input
# that determines the canonical output, so a row is written only for value
# categories whose canonicalization this module can NAME the inputs of:
#
#   Node             -> keyed by the AUTHENTICATED construction-shape CID, with
#                       no identity component at all. The Node arm's output is
#                       exactly ``{"nodeShape": node_construction_shape_cid(v)}``,
#                       a pure function of that CID: two different node views of
#                       the same content are the same coordinate and must share
#                       the answer.
#   frozen dataclass -> keyed by (type, live object). The output is the type's
#                       module/qualname plus the canonicalization of each field,
#                       and ``frozen=True`` is what makes the field tuple a
#                       function of the object. Type is IN the key because it is
#                       IN the output; identity is a component, never the whole.
#   Enum             -> keyed by (type, member). The output is the enum type's
#                       module/qualname plus its canonicalized ``.value``; the
#                       member is the coordinate and members are singletons.
#
# Everything else is deliberately NOT memoized, because its canonical output is
# NOT a function of the value object alone (or is too cheap to be worth a row):
#
#   list / dict / set / non-frozen dataclass -- MUTABLE. The same object can
#       canonicalize two ways over its lifetime, so identity is not a
#       coordinate. (These are also the arms that cannot be weakref'd.)
#   objects canonicalized via ``.wire()`` -- ``wire()`` is a method call that
#       may read state beyond the value; this module cannot enumerate its
#       inputs, so it does not claim a coordinate for it.
#   tuple -- immutable, but its answer is exactly its elements' answers, which
#       ARE memoized individually; a row would buy the walk of one tuple.
#   None / bool / int / float / str / bytes -- the answer is a constant-time
#       spelling of the value; a row costs more than it saves.
#   SourceFragment / SourceMemento -- delegated to ``seal()`` / ``to_dict()``,
#       which own their own authentication; not this module's coordinate.
#
# The id-reuse hazard (#6212) is closed by construction wherever identity IS a
# key component: the row holds a WEAK reference to the object it keyed and a hit
# is honored only when that weakref still resolves to the SAME object, so a
# recycled address misses instead of reading a dead value's JSON. The weakref
# callback drops the row, bounding the table by LIVE values rather than pinning
# every constructed value for the life of a corpus census.
_CANONICAL_VALUES: dict[Any, tuple[Any, Any]] = {}

_NO_COORDINATE = object()


def _canonicalization_coordinate(value: object) -> Any:
    """This value's canonical-testimony coordinate, or ``_NO_COORDINATE``."""
    from sugar_source_tree.nodes import Node

    if isinstance(value, Node):
        return ("node-shape", node_construction_shape_cid(value))
    if isinstance(value, Enum):
        return ("enum", type(value), value)
    if (
        is_dataclass(value)
        and not isinstance(value, type)
        and getattr(value, "__dataclass_params__", None) is not None
        and value.__dataclass_params__.frozen
    ):
        return ("frozen-dataclass", type(value), id(value))
    return _NO_COORDINATE


def _canonical_constructed_value(value: object) -> Any:
    """The value's canonical JSON: computed once per coordinate, read after."""
    coordinate = _canonicalization_coordinate(value)
    if coordinate is _NO_COORDINATE:
        return _compute_canonical_constructed_value(value)

    remembered = _CANONICAL_VALUES.get(coordinate)
    if remembered is not None:
        keyed, canonical = remembered
        # An identity-bearing key is honored only while the object it named is
        # alive and the SAME object; a content coordinate carries no identity to
        # check (``keyed`` is None) and is honored unconditionally.
        if keyed is None or keyed() is value:
            return canonical

    canonical = _compute_canonical_constructed_value(value)
    _memoize_canonical(coordinate, value, canonical)
    return canonical


def _memoize_canonical(coordinate: Any, value: object, canonical: Any) -> None:
    if coordinate[0] == "node-shape":
        # Pure content coordinate: no address, nothing to outlive.
        _CANONICAL_VALUES[coordinate] = (None, canonical)
        return
    try:

        def _forget(_dead: Any, coordinate: Any = coordinate) -> None:
            _CANONICAL_VALUES.pop(coordinate, None)

        reference = weakref.ref(value, _forget)
    except TypeError:
        # Cannot hold the live identity its key names -> no row, rather than a
        # row a recycled address could read.
        return
    _CANONICAL_VALUES[coordinate] = (reference, canonical)


def _compute_canonical_constructed_value(value: object) -> Any:
    from sugar_source_tree.fragment import SourceFragment, SourceMemento

    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        from decimal import Decimal

        # The one canonical float spelling the system already uses (see
        # term_value.to_term / ir.real_lit): a fixed-point decimal string, never
        # a Python float text form. str(float) is the shortest exact decimal
        # that reparses to the same double; non-finite becomes Infinity / NaN.
        return {"float": format(Decimal(str(value)), "f")}
    if isinstance(value, bytes):
        # Bytes canonicalize by hex, matching bytes_value / sequence_repetition.
        return {"bytes": value.hex()}
    if isinstance(value, Enum):
        return {
            "enumType": f"{type(value).__module__}.{type(value).__qualname__}",
            "value": _canonical_constructed_value(value.value),
        }
    if isinstance(value, SourceFragment):
        return {"sourceFragment": value.seal().to_dict()}
    if isinstance(value, SourceMemento):
        return {"sourceMemento": value.to_dict()}
    from sugar_source_tree.nodes import Node

    if isinstance(value, Node):
        # A Node is a tree VIEW, not content. Its content identity is its
        # construction-shape CID (fragment + subtree preimage); its unit/span
        # are positional infrastructure that must never enter a content CID.
        # A constructed value can legitimately carry a Node (e.g. a
        # SourceVisibleCallFrameV1 holding the Lambda it will construct when
        # called), but field-walking it drags in unit -> SourceUnit ->
        # LineTable and fails to serialize (core/groupby/generic.value_counts).
        # Represent the node by its content key, like every other node view.
        return {"nodeShape": node_construction_shape_cid(value)}
    if isinstance(value, (tuple, list)):
        return [_canonical_constructed_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        items = [_canonical_constructed_value(item) for item in value]
        return sorted(items, key=lambda item: cid_of_json(item))
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("constructed testimony dictionaries require string keys")
        return {
            key: _canonical_constructed_value(item)
            for key, item in sorted(value.items())
        }
    if is_dataclass(value) and not isinstance(value, type):
        return {
            "constructedType": f"{type(value).__module__}.{type(value).__qualname__}",
            "fields": {
                field.name: _canonical_constructed_value(getattr(value, field.name))
                for field in fields(value)
            },
        }
    wire = getattr(value, "wire", None)
    if callable(wire):
        return {
            "wireType": f"{type(value).__module__}.{type(value).__qualname__}",
            "wire": _canonical_constructed_value(wire()),
        }
    raise TypeError(f"unserializable constructed value {type(value).__name__}")


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
    from sugar_source_tree.nodes import Node

    if when_true is when_false or when_true == when_false:
        return when_true
    when_true = unwrap_binding_state(when_true)
    when_false = unwrap_binding_state(when_false)
    if isinstance(when_true, Node) and isinstance(when_false, Node):
        return make_ifexp(slot, when_true, when_false)
    if isinstance(when_true, UnboundBinding) and isinstance(when_false, UnboundBinding):
        return UnboundBinding(name=when_true.name, cause=when_true.cause)
    return GuardedBinding(slot=slot, when_true=when_true, when_false=when_false)
