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
from sugar_source_tree.nodes import Call, FunctionDef, Name

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
    calls = {
        _span_key(node): node for node in source_file.nodes() if isinstance(node, Call)
    }
    packages = (
        importlib.metadata.packages_distributions()
        if distribution_index is None
        else {name: (name,) for name in distribution_index}
    )
    graphs = {} if artifact_graph_cache is None else artifact_graph_cache
    for receipt in receipts:
        raw = receipt.use["useSite"]
        key = (raw["startLine"], raw["startCol"], raw["endLine"], raw["endCol"])
        call = calls.get(key)
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
        context.source_call_resolutions[coordinate] = SourceCallPreconstructionRefV1(
            coordinate,
            resolved.cid,
            graph.distribution_artifact_cid,
            frame.frame_cid,
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


def _coordinate(node) -> SourceFragmentCoordinateV1:
    start_line, start_col, end_line, end_col = _span_key(node)
    return SourceFragmentCoordinateV1(
        node.unit.source_cid, start_line, start_col, end_line, end_col
    )
