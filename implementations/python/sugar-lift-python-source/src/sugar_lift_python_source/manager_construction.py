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
    target = next(
        (item for item in definitions if _matches_definition(item, resolved)), None
    )
    if target is None:
        return ManagerConstructionGapV1(
            "definition-missing", resolved.cid, "resolved definition coordinate"
        )

    definition_names = {item.name for item in definitions}
    if isinstance(target, FunctionDef):
        opaque = tuple(
            call.func.id
            for call in _local_named_calls(target)
            if call.func.id not in definition_names
        )
        if opaque:
            return ManagerConstructionGapV1(
                "opaque-call-target", resolved.cid, opaque[0]
            )

    frames: dict[str, object] = {}
    for item in definitions:
        if isinstance(item, ClassDef):
            frames[item.name] = item.source_visible_constructor_frame()

    pending = [item for item in definitions if isinstance(item, FunctionDef)]
    while pending:
        progressed = False
        for function in tuple(pending):
            local_calls = tuple(_local_named_calls(function))
            unresolved = tuple(
                call.func.id
                for call in local_calls
                if call.func.id in definition_names and call.func.id not in frames
            )
            if unresolved:
                continue
            for call in local_calls:
                frame = frames.get(call.func.id)
                if frame is not None:
                    context.source_call_frames[_call_coordinate(call)] = frame
            frames[function.name] = function.source_visible_call_frame()
            pending.remove(function)
            progressed = True
        if not progressed:
            return ManagerConstructionGapV1(
                "opaque-call-target", resolved.cid, "recursive source call graph"
            )

    frame = frames.get(target.name)
    if frame is None:
        return ManagerConstructionGapV1(
            "definition-missing", resolved.cid, "ordinary source call frame"
        )
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
    if isinstance(result, BlockValue) and result.statements and isinstance(
        result.statements[-1], ReturnValue
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
        _term_content_cid(item.to_term(owner=resolved.cid))
        for item in factory_prefix
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
        resolved.cid,
        cid_of_json(preimage),
        result,
        result.identity,
        bindings,
        frame.frame_cid,
        factory_prefix,
        prefix_cids,
    )


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
