"""Cut C: project authenticated external source through the sole constructor."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Literal

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import (
    BlockValue,
    CallSiteValue,
    FloorValue,
    ObjectValue,
    ReturnValue,
)
from sugar_lift_py_tests.ir import _term_content_cid, ctor
from sugar_source_tree.binding_provenance import (
    ConstructedValueTestimonyV1,
)
from sugar_source_tree.binding_state import BindingEntryV1
from sugar_source_tree.nodes import Call, ClassDef, FunctionDef, Name, Node
from sugar_source_tree.tree import SourceFile
from sugar_lift_py_tests.source_call_frame import SourceCallBindingGap

from .canonical import cid_of_json
from .dependency_artifact import DependencyArtifactGraph, ResolvedPythonObjectV1


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


@dataclass(frozen=True)
class ManagerConstructionGapV1:
    kind: Literal[
        "artifact-mismatch",
        "definition-missing",
        "opaque-call-target",
        "non-manager-result",
        "call-binding",
    ]
    resolved_object_cid: str
    detail: str


def construct_manager_behavior(
    resolved: ResolvedPythonObjectV1,
    *,
    graph: DependencyArtifactGraph,
    actuals: tuple[ConstructedCallActualV1, ...],
    keyword_actuals: tuple[tuple[str, ConstructedCallActualV1], ...] = (),
    call_site: object | None = None,
    source_frame_cache: dict | None = None,
) -> ConstructedManagerBehaviorV1 | ManagerConstructionGapV1:
    """Construct one resolved callable through SourceFile -> Node -> Sugar only."""
    if graph.distribution_artifact_cid != resolved.distribution_artifact_cid:
        return ManagerConstructionGapV1(
            "artifact-mismatch", resolved.cid, "distribution artifact CID"
        )
    module = graph.modules.get(resolved.module_name)
    if module is None or module.source_cid != resolved.source_cid:
        return ManagerConstructionGapV1(
            "artifact-mismatch", resolved.cid, "module source CID"
        )

    frame_result = resolve_source_visible_frame(
        resolved, graph=graph, frame_cache=source_frame_cache
    )
    if isinstance(frame_result, ManagerConstructionGapV1):
        return frame_result
    frame, _target = frame_result
    try:
        values = frame.bind_actuals(
            tuple(item.value for item in actuals),
            tuple((name, item.value) for name, item in keyword_actuals),
        )
        frame = frame.bind_node_actuals(
            tuple(item.node for item in actuals),
            tuple((name, item.node) for name, item in keyword_actuals),
        )
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
    )
    result = call.force_floor(
        None, owner="construct_manager_behavior", project_callsite=False
    )
    factory_prefix: tuple[FloorValue, ...] = ()
    if (
        isinstance(result, BlockValue)
        and result.statements
        and isinstance(result.statements[-1], ReturnValue)
    ):
        factory_prefix = result.statements[:-1]
        returned = result.statements[-1].value
        if isinstance(returned, CallSiteValue):
            result = returned.force_floor(
                None, owner="construct_manager_behavior returned object"
            )
        else:
            result = returned
    if not isinstance(result, ObjectValue):
        return ManagerConstructionGapV1(
            "non-manager-result", resolved.cid, type(result).__name__
        )
    bindings = frame.runtime_entries
    prefix_cids = tuple(
        _term_content_cid(item.to_term(owner=resolved.cid)) for item in factory_prefix
    )
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


@dataclass(frozen=True)
class _SourceDefinitionGraphV1:
    context: object = field(compare=False)
    definitions: tuple[Node, ...] = field(compare=False)
    frames: dict[str, object] = field(default_factory=dict, compare=False)
    gaps: dict[str, tuple[str, str]] = field(default_factory=dict, compare=False)


def resolve_source_visible_frame(
    resolved: ResolvedPythonObjectV1,
    *,
    graph: DependencyArtifactGraph,
    frame_cache: dict | None = None,
) -> tuple[object, Node] | ManagerConstructionGapV1:
    """Resolve one authenticated definition into the ordinary source frame.

    This is orchestration over typed Nodes.  Function/Class bodies still
    construct only through their existing ``source_visible_*_frame`` arms.
    """
    if graph.distribution_artifact_cid != resolved.distribution_artifact_cid:
        return ManagerConstructionGapV1(
            "artifact-mismatch", resolved.cid, "distribution artifact CID"
        )
    module = graph.modules.get(resolved.module_name)
    if module is None or module.source_cid != resolved.source_cid:
        return ManagerConstructionGapV1(
            "artifact-mismatch", resolved.cid, "module source CID"
        )
    if frame_cache is not None and resolved.cid in frame_cache:
        return frame_cache[resolved.cid]
    definition_key = (
        "source-definition-graph-v1",
        graph.distribution_artifact_cid,
        resolved.module_name,
        module.source_cid,
    )
    definition_graph = None if frame_cache is None else frame_cache.get(definition_key)
    if definition_graph is None:
        definition_graph = _construct_source_definition_graph(module)
        if frame_cache is not None:
            frame_cache[definition_key] = definition_graph
    definitions = definition_graph.definitions
    target = next(
        (item for item in definitions if _matches_definition(item, resolved)), None
    )
    if target is None:
        return _remember_frame_result(
            frame_cache,
            resolved.cid,
            ManagerConstructionGapV1(
                "definition-missing", resolved.cid, "resolved definition coordinate"
            ),
        )

    definition_names = {item.name for item in definitions}
    if isinstance(target, FunctionDef):
        opaque = tuple(
            call.func.id
            for call in _local_named_calls(target)
            if call.func.id not in definition_names
        )
        if opaque:
            return _remember_frame_result(
                frame_cache,
                resolved.cid,
                ManagerConstructionGapV1(
                    "opaque-call-target", resolved.cid, opaque[0]
                ),
            )
    frame_result = _construct_source_target_frame(definition_graph, target)
    if isinstance(frame_result, tuple) and frame_result[0] == "gap":
        _tag, kind, detail = frame_result
        return _remember_frame_result(
            frame_cache,
            resolved.cid,
            ManagerConstructionGapV1(kind, resolved.cid, detail),
        )
    frame = frame_result
    result = (frame, target)
    if frame_cache is not None:
        frame_cache[resolved.cid] = result
    return result


def _construct_source_definition_graph(module) -> _SourceDefinitionGraphV1:
    """Materialize one authenticated module's direct definitions once."""
    context = TreeConstructionContextV1.for_source_call_construction()
    source_file = SourceFile(
        (module.source, module.source_seat, module.source_cid),
        construction_context=context,
    )
    definitions = tuple(
        item
        for item in source_file.root.body
        if isinstance(item, (FunctionDef, ClassDef))
    )
    return _SourceDefinitionGraphV1(context, definitions)


def _construct_source_target_frame(definition_graph, target):
    """Construct only the selected definition's authenticated local call closure."""
    context = definition_graph.context
    definitions = definition_graph.definitions
    by_name = {item.name: item for item in definitions}

    def ensure(item, active: frozenset[str]):
        cached = definition_graph.frames.get(item.name)
        if cached is not None:
            return cached
        gap = definition_graph.gaps.get(item.name)
        if gap is not None:
            return ("gap", *gap)
        if item.name in active:
            result = ("opaque-call-target", "recursive source call graph")
            definition_graph.gaps[item.name] = result
            return ("gap", *result)
        active = active | {item.name}
        if isinstance(item, ClassDef):
            local_bases = []
            for base in item.bases:
                base_definition = by_name.get(base.id) if isinstance(base, Name) else None
                if not isinstance(base_definition, ClassDef):
                    local_bases = []
                    break
                base_result = ensure(base_definition, active)
                if isinstance(base_result, tuple) and base_result[0] == "gap":
                    return base_result
                local_bases.append(base_definition.sugar())
            if local_bases and len(local_bases) == len(item.bases):
                context.source_class_bases[item.fragment.seal().cid] = tuple(local_bases)
            frame = item.source_visible_constructor_frame()
            definition_graph.frames[item.name] = frame
            return frame
        local_calls = tuple(_local_named_calls(item))
        for call in local_calls:
            dependency = by_name.get(call.func.id)
            if dependency is None:
                result = ("opaque-call-target", call.func.id)
                definition_graph.gaps[item.name] = result
                return ("gap", *result)
            nested = ensure(dependency, active)
            if isinstance(nested, tuple) and nested[0] == "gap":
                return nested
            context.source_call_frames[_call_coordinate(call)] = nested
        frame = item.source_visible_call_frame()
        definition_graph.frames[item.name] = frame
        return frame

    return ensure(target, frozenset())


def _remember_frame_result(frame_cache, resolved_cid, result):
    if frame_cache is not None:
        frame_cache[resolved_cid] = result
    return result


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
