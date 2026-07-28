"""Authenticated ordinary source-call preconstruction.

This phase resolves import occurrences against distribution-recorded source and
installs exact source-call frames.  It never imports or executes modules, and it
never grants semantics from a local or package spelling.
"""

from __future__ import annotations

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
    session=None,
) -> None:
    """Populate exact-use source frames and one closed classification row.

    ``session`` owns every resolution memo for this population.  The default
    opens one bounded to this source file, so no frame projected for one file
    (or one project) can ever answer for another.
    """
    from sugar_lift_py_tests.import_binding import authenticated_import_use_receipts

    from .resolution_session import session_or_new

    session = session_or_new(session)
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
    graphs = {} if artifact_graph_cache is None else artifact_graph_cache
    for receipt in receipts:
        raw = receipt.use["useSite"]
        key = (raw["startLine"], raw["startCol"], raw["endLine"], raw["endCol"])
        call = calls_by_span.get(key) or _call_for_callee_span(calls, key)
        if call is None:
            continue
        coordinate = _coordinate(call)
        top_level = receipt.target_symbol.removeprefix("python:").split(".", 1)[0]
        graph = graphs.get(top_level)
        if graph is None:
            try:
                from .dependency_artifact import authenticate_dependency_top_level

                graph = authenticate_dependency_top_level(
                    top_level, distribution_index=distribution_index
                )
            except DependencyArtifactAuthenticationError as exc:
                context.source_call_resolutions[coordinate] = (
                    SourceCallPreconstructionGapV1(
                        "artifact-resolution", coordinate, str(exc)
                    )
                )
                continue
            graphs[top_level] = graph
        resolved = resolve_import_binding(receipt, graph=graph, session=session)
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
            frame_result = resolve_source_visible_frame(
                resolved, graph=graph, session=session
            )
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
        if isinstance(target, FunctionDef) and target.decorators:
            context.source_call_resolutions[coordinate] = (
                SourceCallPreconstructionGapV1(
                    "decorator-application",
                    coordinate,
                    "authenticated definition has unapplied decorators",
                )
            )
            continue
        _preconstruct_authenticated_attribute_calls(target, graph=graph, session=session)
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


def _preconstruct_authenticated_attribute_calls(
    target, *, graph, session, visited: frozenset[tuple] = frozenset()
) -> None:
    """Install exact frames for attributed callees authenticated in this artifact.

    The outer import receipt authenticates ``target``.  This second lexical
    pass reads receipts from those same retained module bytes and admits only
    exact attributed call coordinates whose targets resolve through the same
    dependency-artifact graph.  No receiver or member spelling is consulted.
    """
    if not isinstance(target, FunctionDef):
        return
    context = target.unit.construction_context
    if context is None:
        return
    target_key = (target.unit.source_cid, _span_key(target))
    if target_key in visited:
        return
    visited = visited | {target_key}

    from sugar_lift_py_tests.import_binding import authenticated_import_use_receipts

    receipts, _ = authenticated_import_use_receipts(
        Path("."),
        Path(target.unit.filename),
        target.unit.source,
        target.unit.source_cid,
        module_identities={},
    )
    calls = tuple(
        node
        for node in target.walk()
        if isinstance(node, Call) and isinstance(node.func, Attribute)
    )
    calls_by_span = {
        span: call
        for call in calls
        for span in (_span_key(call), _span_key(call.func))
    }
    for receipt in receipts:
        raw = receipt.use["useSite"]
        key = (raw["startLine"], raw["startCol"], raw["endLine"], raw["endCol"])
        call = calls_by_span.get(key)
        if call is None:
            continue
        # The lexical pass authenticated this exact attributed use against its
        # import binding. That is sufficient to distinguish it from runtime
        # receiver dispatch; the call's ordinary factory/definition door still
        # owns whether the target can construct a Floor.
        resolved = resolve_import_binding(receipt, graph=graph, session=session)
        if not isinstance(resolved, ResolvedPythonObjectV1):
            continue
        projected = resolve_source_visible_frame(
            resolved, graph=graph, session=session
        )
        if isinstance(projected, ManagerConstructionGapV1):
            continue
        frame, nested_target = projected
        if isinstance(nested_target, FunctionDef) and nested_target.decorators:
            continue
        _preconstruct_authenticated_attribute_calls(
            nested_target, graph=graph, session=session, visited=visited
        )
        context.source_call_frames[_coordinate(call)] = frame


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
