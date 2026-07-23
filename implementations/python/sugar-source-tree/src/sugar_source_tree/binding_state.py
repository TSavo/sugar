from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass, replace
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, TypeAlias

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
    return BindingCoordinateV1.mint(
        scope_owner_cid, binding_site, projection_path
    )


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
            raise BindingStateWireGap(
                "loop projected binding requires completed faces"
            )
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
            raise BindingStateWireGap(
                "binding state is not a constructed bound value"
            )
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

    __slots__ = ("_delegate", "_by_node_shape", "_trace_builder")

    def __init__(
        self, delegate: object, trace_builder: SubstitutionTraceBuilderV1
    ) -> None:
        self._delegate = delegate
        self._by_node_shape: dict[str, ConstructedValueTestimonyV1] = {}
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
            semantic_value_cid = cid_of_json(_constructed_preimage(value))
            node_shape_cid = node_construction_shape_cid(node)
        except (TypeError, ValueError):
            return
        self._by_node_shape[node_shape_cid] = mint_constructed_value_testimony_v1(
            source_fragment=node.fragment,
            semantic_value_cid=semantic_value_cid,
        )

    def testimony_for(self, node: Node) -> ConstructedValueTestimonyV1 | None:
        try:
            return self._by_node_shape.get(node_construction_shape_cid(node))
        except (TypeError, ValueError):
            return None

    def seal_snapshot(
        self, snapshot: tuple[tuple[str, BindingEntryV1], ...]
    ) -> tuple[tuple[str, BindingEntryV1], ...]:
        return _seal_snapshot(snapshot, self)

    def projected_snapshots_for(self, statement: Node):
        return self._trace_builder.projected_snapshots_for(statement, self)


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
        (name, SealedBindingEntryV1.decode(entry.wire()))
        for name, entry in testified
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
    return cid_of_json(
        {
            "kind": "constructed-node-shape",
            "schemaVersion": "1",
            "source": node.fragment.seal().to_dict(),
            "node": _backend_node_preimage(node.ref),
        }
    )


def _backend_node_preimage(ref: object) -> dict[str, Any]:
    from sugar_source_tree.backend import (
        Child,
        Children,
        Leaf,
        MaybeChild,
        OpLeaf,
        OpsLeaf,
    )

    desc = ref.describe()
    slots = []
    for name, slot in desc.slots:
        if isinstance(slot, Child):
            value = {"child": _backend_node_preimage(slot.handle)}
        elif isinstance(slot, MaybeChild):
            value = {
                "maybeChild": None
                if slot.handle is None
                else _backend_node_preimage(slot.handle)
            }
        elif isinstance(slot, Children):
            value = {
                "children": [_backend_node_preimage(handle) for handle in slot.handles]
            }
        elif isinstance(slot, Leaf):
            value = {"leaf": _canonical_constructed_value(slot.value)}
        elif isinstance(slot, OpLeaf):
            value = {"operator": slot.op.kind}
        elif isinstance(slot, OpsLeaf):
            value = {"operators": [operator.kind for operator in slot.ops]}
        else:
            raise TypeError(f"unknown backend slot {type(slot).__name__}")
        slots.append({"name": name, "value": value})
    return {"kind": desc.kind, "slots": slots}


def _constructed_preimage(value: object) -> dict[str, Any]:
    return {
        "kind": "constructed-semantic-value",
        "schemaVersion": "1",
        "value": _canonical_constructed_value(value),
    }


def _canonical_constructed_value(value: object) -> Any:
    from sugar_source_tree.fragment import SourceFragment, SourceMemento

    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, Enum):
        return {
            "enumType": f"{type(value).__module__}.{type(value).__qualname__}",
            "value": _canonical_constructed_value(value.value),
        }
    if isinstance(value, SourceFragment):
        return {"sourceFragment": value.seal().to_dict()}
    if isinstance(value, SourceMemento):
        return {"sourceMemento": value.to_dict()}
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
    snapshot: tuple[tuple[str, BindingEntryV1], ...]
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
        del_names.append(
            {"bindingCoordinateCid": entry.coordinate.cid, "cell": cell}
        )
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
                raise BindingStateWireGap(
                    "constructed-value testimony CID mismatch"
                )
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
