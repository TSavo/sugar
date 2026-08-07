"""What does the generator road need from an off-population decorator?

Diagnostic only -- reports, never repairs.

The question that decides whether the citation route is even possible:

  If the road needs enter/exit SEMANTICS it can only get by constructing an
  off-population body, a citation cannot feed it and the road needs a different
  shape. If it needs an IDENTITY -- a coordinate -- a citation can carry that,
  and the repair is to cite instead of construct.

ARM A -- what the road does today.
  ``_enter_exit_sites_from_class_def`` calls ``source_visible_call_frame()`` on
  ``_GeneratorContextManager.__enter__``/``__exit__`` -- which substitutes and
  sugars the whole method body -- and then keeps ONLY ``frame.definition_site``.
  Everything else it built is discarded. Reaching that requires materializing
  ``contextlib``, which the population membrane refuses, correctly.

ARM B -- what a citation could supply.
  ``resolve_authenticated_module_export`` already succeeds for off-population
  ``contextlib`` (measured: it returns ``ResolvedPythonObjectV1``). This arm
  asks whether the enter/exit coordinates are obtainable from the authenticated
  artifact WITHOUT materializing: resolve the class, then locate the methods
  inside the authenticated class span by parsing the authenticated source --
  the same stdlib-``ast`` reading ``_export_block_with_locus`` already performs
  on off-population modules for export resolution.

Also reported: what ``construct_generator_backed_protocol`` actually consumes.
Its own docstring says "Coordinates alone cannot construct this protocol -- the
generator frame is load-bearing", and the frame in question is the DECORATED
function's, which is in-population.

usage:
  python probe_decorator_citation_shape.py
"""

from __future__ import annotations

import ast
import sys
import traceback

TARGET_MODULE = "contextlib"
DECORATOR = "contextmanager"
MANAGER_CLASS = "_GeneratorContextManager"


def main() -> int:
    from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
    from sugar_lift_python_source.dependency_artifact import (
        ResolvedPythonObjectV1,
        authenticate_dependency_top_level,
        resolve_authenticated_module_export,
    )
    from sugar_lift_python_source.manager_construction import (
        resolve_source_visible_frame,
    )
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_lift_python_source.resolution_session import walk_session_for

    # The provider binding cid must be a real content address, not a label.
    probe_cid = blake3_512_of(b"probe-decorator-citation-shape")

    corpus = authenticated_pandas_corpus()
    print(f"CORPUS {corpus.distribution} {corpus.version} files={corpus.file_count}")
    session = walk_session_for(
        corpus.root, enrolled_distributions=frozenset({"pandas"})
    )
    graph = authenticate_dependency_top_level(TARGET_MODULE)
    print(f"GRAPH {TARGET_MODULE}: artifactKind={graph.artifact_kind!r}")
    module = graph.modules.get(TARGET_MODULE)
    print(f"  module present={module is not None} source_cid={getattr(module, 'source_cid', None)}")

    # ---- ARM A: the road as it stands -------------------------------------
    print("\nARM A -- construct the decorator, as the road does today")
    resolved = resolve_authenticated_module_export(
        graph=graph,
        binding_cid=probe_cid,
        module_name=TARGET_MODULE,
        exported_name=DECORATOR,
        session=session,
    )
    print(f"  resolve_authenticated_module_export({DECORATOR!r}) -> {type(resolved).__name__}")
    if isinstance(resolved, ResolvedPythonObjectV1):
        print(f"    definition kind={resolved.definition.kind!r} name={resolved.definition.name!r}")
        frame_result = resolve_source_visible_frame(
            resolved, graph=graph, session=session
        )
        if isinstance(frame_result, tuple):
            print("    resolve_source_visible_frame -> CONSTRUCTED")
        else:
            print(
                f"    resolve_source_visible_frame -> GAP "
                f"kind={getattr(frame_result, 'kind', None)!r}"
            )
            print(f"      detail={getattr(frame_result, 'detail', None)!r}")

    # ---- ARM B: is the identity obtainable without constructing? -----------
    print("\nARM B -- cite the identity from the authenticated artifact")
    resolved_class = resolve_authenticated_module_export(
        graph=graph,
        binding_cid=probe_cid,
        module_name=TARGET_MODULE,
        exported_name=MANAGER_CLASS,
        session=session,
    )
    print(f"  resolve_authenticated_module_export({MANAGER_CLASS!r}) -> {type(resolved_class).__name__}")
    if not isinstance(resolved_class, ResolvedPythonObjectV1):
        print(f"    {resolved_class}")
        return 0
    definition = resolved_class.definition
    print(
        f"    AUTHENTICATED definition: kind={definition.kind!r} "
        f"name={definition.name!r} "
        f"span={definition.start_line}:{definition.start_col}"
        f"-{definition.end_line}:{definition.end_col}"
    )
    print(f"    source_cid={definition.source_cid}")
    print(f"    matches module source_cid: {definition.source_cid == module.source_cid}")

    # Locate the protocol methods INSIDE the authenticated class span, by
    # reading the authenticated source with stdlib ast -- no SourceFile, no
    # MaterializeModule, no sugar.
    tree = ast.parse(module.source)
    found = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != MANAGER_CLASS:
            continue
        inside = (
            node.lineno >= definition.start_line
            and node.end_lineno <= definition.end_line
        )
        print(f"    ast ClassDef {node.name} at {node.lineno}-{node.end_lineno} within authenticated span: {inside}")
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name in (
                "__enter__",
                "__exit__",
            ):
                found[item.name] = (
                    item.lineno,
                    item.col_offset,
                    item.end_lineno,
                    item.end_col_offset,
                )
    for name in ("__enter__", "__exit__"):
        print(f"    {name}: {found.get(name)}")
    print(
        f"    both present and distinct: "
        f"{len(found) == 2 and found.get('__enter__') != found.get('__exit__')}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException:
        traceback.print_exc()
        raise SystemExit(1)
