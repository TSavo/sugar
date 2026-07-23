"""Authenticated ordinary source-call preconstruction.

This phase resolves import occurrences against distribution-recorded source and
installs exact source-call frames.  It never imports or executes modules, and it
never grants semantics from a local or package spelling.
"""

from __future__ import annotations

import importlib.metadata
from pathlib import Path

from sugar_lift_py_tests.context_manager_resolution import (
    SourceFragmentCoordinateV1,
)
from sugar_lift_py_tests.source_call_resolution import (
    SourceCallPreconstructionGapV1,
    SourceCallPreconstructionRefV1,
)
from sugar_source_tree.nodes import Attribute, Call, ClassDef, FunctionDef, Name

from .dependency_artifact import (
    DependencyArtifactAuthenticationError,
    DependencyArtifactGraph,
    PythonObjectResolutionGapV1,
    ResolvedPythonObjectV1,
    resolve_import_binding,
)
from .manager_construction import (
    ManagerConstructionGapV1,
    resolve_source_visible_frame,
)


def populate_source_visible_call_frames(
    source_file,
    *,
    root: Path,
    path: Path,
    distribution_index=None,
    artifact_graph_cache: dict | None = None,
) -> None:
    """Populate exact-use source frames and one closed classification row."""
    from sugar_lift_py_tests.import_binding import authenticated_import_use_receipts

    context = source_file.unit.construction_context
    if context is None:
        return
    receipts, _outcomes = authenticated_import_use_receipts(
        Path(root),
        Path(path),
        source_file.unit.source,
        source_file.unit.source_cid,
        module_identities={},
    )
    calls = tuple(node for node in source_file.nodes() if isinstance(node, Call))
    calls_by_span = {_span_key(node): node for node in calls}
    constructor_targets = {}
    packages = (
        importlib.metadata.packages_distributions()
        if distribution_index is None
        else {name: (name,) for name in distribution_index}
    )
    graphs = {} if artifact_graph_cache is None else artifact_graph_cache
    for receipt in receipts:
        raw = receipt.use["useSite"]
        key = (raw["startLine"], raw["startCol"], raw["endLine"], raw["endCol"])
        call = calls_by_span.get(key) or _call_for_callee_span(calls, key)
        if call is None:
            continue
        coordinate = _coordinate(call)
        top_level = receipt.target_symbol.removeprefix("python:").split(".", 1)[0]
        distributions = tuple(packages.get(top_level, ()))
        if len(distributions) != 1:
            kind = "no-distribution" if not distributions else "ambiguous-distribution"
            context.source_call_resolutions[coordinate] = (
                SourceCallPreconstructionGapV1(kind, coordinate, top_level)
            )
            continue
        distribution = (
            importlib.metadata.distribution(distributions[0])
            if distribution_index is None
            else distribution_index[top_level]
        )
        graph = graphs.get(top_level)
        if graph is None:
            try:
                graph = DependencyArtifactGraph.authenticate(distribution)
            except DependencyArtifactAuthenticationError as exc:
                context.source_call_resolutions[coordinate] = (
                    SourceCallPreconstructionGapV1(
                        "artifact-resolution", coordinate, str(exc)
                    )
                )
                continue
            graphs[top_level] = graph
        resolved = resolve_import_binding(receipt, graph=graph)
        if isinstance(resolved, PythonObjectResolutionGapV1):
            context.source_call_resolutions[coordinate] = (
                SourceCallPreconstructionGapV1(
                    "artifact-resolution", coordinate, resolved.kind
                )
            )
            continue
        if not isinstance(resolved, ResolvedPythonObjectV1):
            context.source_call_resolutions[coordinate] = (
                SourceCallPreconstructionGapV1(
                    "artifact-resolution", coordinate, type(resolved).__name__
                )
            )
            continue
        from sugar_source_tree.panic import SugarNotWritten

        try:
            frame_result = resolve_source_visible_frame(resolved, graph=graph)
        except SugarNotWritten as exc:
            context.source_call_resolutions[coordinate] = (
                SourceCallPreconstructionGapV1("source-body-gap", coordinate, str(exc))
            )
            continue
        if isinstance(frame_result, ManagerConstructionGapV1):
            context.source_call_resolutions[coordinate] = (
                SourceCallPreconstructionGapV1(
                    frame_result.kind, coordinate, frame_result.detail
                )
            )
            continue
        frame, target = frame_result
        opaque = _unsupported_call(target)
        if opaque is not None:
            context.source_call_resolutions[coordinate] = (
                SourceCallPreconstructionGapV1(
                    "dynamic-call-target", coordinate, opaque
                )
            )
            continue
        from sugar_lift_py_tests.source_call_frame import SourceCallBindingGap

        try:
            frame = frame.bind_node_actuals(
                call.args,
                tuple(
                    (keyword.arg, keyword.value)
                    for keyword in call.keywords
                    if keyword.arg is not None
                ),
            )
        except SourceCallBindingGap as exc:
            context.source_call_resolutions[coordinate] = (
                SourceCallPreconstructionGapV1("call-binding", coordinate, str(exc))
            )
            continue
        context.source_call_frames[coordinate] = frame
        dispatch_kind = "constructor" if isinstance(target, ClassDef) else "function"
        if isinstance(target, ClassDef):
            constructor_targets[coordinate] = target
        context.source_call_resolutions[coordinate] = SourceCallPreconstructionRefV1(
            coordinate,
            resolved.cid,
            graph.distribution_artifact_cid,
            frame.frame_cid,
            dispatch_kind,
        )

    for call in calls:
        if not isinstance(call.func, Attribute) or not isinstance(
            call.func.value, Call
        ):
            continue
        receiver_coordinate = _coordinate(call.func.value)
        target = constructor_targets.get(receiver_coordinate)
        if target is None:
            continue
        coordinate = _coordinate(call)
        frame = _source_method_frame(target, call.func.attr)
        if frame is None:
            context.source_call_resolutions[coordinate] = (
                SourceCallPreconstructionGapV1(
                    "dynamic-call-target",
                    coordinate,
                    "authenticated class has no source method",
                )
            )
            continue
        context.source_call_frames[coordinate] = frame
        constructor_ref = context.source_call_resolutions[receiver_coordinate]
        context.source_call_resolutions[coordinate] = SourceCallPreconstructionRefV1(
            coordinate,
            constructor_ref.resolved_object_cid,
            constructor_ref.distribution_artifact_cid,
            frame.frame_cid,
            "method",
        )


def _unsupported_call(target) -> str | None:
    """Keep method/computed dispatch loud until receiver identity is authenticated."""
    if not isinstance(target, FunctionDef):
        return None
    stack = list(reversed(target.body))
    while stack:
        node = stack.pop()
        if isinstance(node, FunctionDef):
            continue
        if isinstance(node, Call) and not isinstance(node.func, Name):
            return node.func.kind
        stack.extend(reversed([child for _, _, child in node.children()]))
    return None


def _span_key(node):
    span = node.line_col_span()
    return span.start_line, span.start_col, span.end_line, span.end_col


def _call_for_callee_span(calls, key):
    """Project an authenticated imported callee occurrence to its exact Call."""
    candidates = tuple(call for call in calls if _span_key(call.func) == key)
    return candidates[0] if len(candidates) == 1 else None


def _source_method_frame(target: ClassDef, name: str):
    """Project the exact method frame from the sole-door class construction."""
    from sugar_lift_py_tests.floor import ClassDefinitionValue
    from sugar_lift_py_tests.outcome import Complete

    outcome = target.sugar().desugar()
    if not isinstance(outcome, Complete) or not isinstance(
        outcome.value, ClassDefinitionValue
    ):
        return None
    matches = tuple(
        method
        for method in outcome.value._object_methods()
        if method.name == name and method.source_call_frame is not None
    )
    return matches[-1].source_call_frame if matches else None


def _coordinate(node) -> SourceFragmentCoordinateV1:
    start_line, start_col, end_line, end_col = _span_key(node)
    return SourceFragmentCoordinateV1(
        node.unit.source_cid, start_line, start_col, end_line, end_col
    )
