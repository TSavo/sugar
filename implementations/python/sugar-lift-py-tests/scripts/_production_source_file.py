"""The source-derived preconstruction door shared by census floors.

Semantic enumeration in production installs source-derived context-manager
testimony before asking the typed tree for Sugar.  Every census floor must use
that same prepared tree; otherwise a real With construction is reverse-
suppressed into a false loud residual.
"""

from __future__ import annotations

from pathlib import Path


def production_source_file(
    path,
    *,
    root,
    reporter,
    distribution_index=None,
    artifact_graph_cache=None,
):
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_lift_python_source.manager_summary_derivation import (
        populate_source_derived_resource_refs,
    )
    from sugar_lift_python_source.source_call_preconstruction import (
        populate_source_visible_call_frames,
    )
    from sugar_lift_python_source.source_oracle import path_source
    from sugar_source_tree.tree import SourceFile

    context = TreeConstructionContextV1.for_source_call_construction(
        workspace_root=str(root)
    )
    source_file = SourceFile(
        path_source(str(path)), reporter=reporter, construction_context=context
    )
    graphs = {} if artifact_graph_cache is None else artifact_graph_cache
    frames = {}
    populate_source_visible_call_frames(
        source_file,
        root=root,
        path=path,
        distribution_index=distribution_index,
        artifact_graph_cache=graphs,
        source_frame_cache=frames,
    )
    populate_source_derived_resource_refs(
        source_file,
        root=root,
        path=path,
        distribution_index=distribution_index,
        artifact_graph_cache=graphs,
        source_frame_cache=frames,
    )
    _install_unresolved_source_derived_gaps(source_file)
    return source_file


def corpus_root_from_relative(path: Path, relative: str) -> Path:
    """Invert the parent's exact ``path.relative_to(root)`` operation."""
    root = path.resolve()
    for _part in Path(relative).parts:
        root = root.parent
    return root


def _install_unresolved_source_derived_gaps(source_file) -> None:
    """Close the census table without pretending unresolved sites resolved.

    Production's final linker table supplies its own typed unresolved rows.
    Census construction has no linker RPC, so every source-derived use not
    discharged above receives an exact-coordinate ``no-derived-contract`` gap.
    This makes absence loud while preserving derived testimony where it exists.
    """
    from sugar_lift_py_tests.context_manager_resolution import (
        ContextManagerResolutionGapV1,
        SourceFragmentCoordinateV1,
    )
    from sugar_lift_python_source.canonical import cid_of_json
    from sugar_source_tree.nodes import With

    context = source_file.unit.construction_context
    for node in source_file.nodes():
        if not isinstance(node, With):
            continue
        for item in node.items:
            span = item.context_expr.line_col_span()
            coordinate = SourceFragmentCoordinateV1(
                source_file.unit.source_cid,
                span.start_line,
                span.start_col,
                span.end_line,
                span.end_col,
            )
            if coordinate in context.source_derived_contract_refs:
                continue
            demand_cid = cid_of_json(
                {
                    "kind": "source-derived-context-manager-census-demand",
                    "schemaVersion": "1",
                    "useSite": coordinate.wire(),
                }
            )
            context.source_derived_contract_refs[coordinate] = (
                ContextManagerResolutionGapV1(
                    demand_cid, coordinate, None, "no-derived-contract", ()
                )
            )
