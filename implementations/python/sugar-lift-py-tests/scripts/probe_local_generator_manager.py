"""Does the generator-CM derivation reach a SAME-MODULE @contextmanager?

Diagnostic only -- reports, never repairs. Opens through
``open_source_file_for_construction``, never the bare door.

Two halves are written and the diagonal between them is not:

  * ``_populate_same_module_class_manager_uses`` resolves a same-module manager
    -- "when Call.func Name binds to exactly one module **ClassDef**".
  * ``_populate_generator_resource_ref`` derives a generator-backed CM protocol
    -- reached only from an **import receipt**.

A same-module ``@contextlib.contextmanager`` generator (``ensure_removed`` in
``tests/test_register_accessor.py``, ``set_locale`` in
``_config/localization.py``) is neither, so it falls through to the demand
table and is painted ``runtime-selected``.

Before relying on the diagonal being cheap, this probe checks the ONE step that
might not survive the move off the import road: the decorator step.
``_protocol_coords_from_generator_decorators`` must produce native enter/exit
coordinates for ``contextlib.contextmanager`` when the decorated function is
LOCAL and there is no receipt and no ``graph``. It being true on the import road
does not make it true here.

  ARM LOCAL   -- local FunctionDef, graph=None
  ARM IMPORT  -- an import-backed @contextmanager, its own graph (control)

usage:
  python probe_local_generator_manager.py
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

LOCAL_TARGETS = [
    ("tests/test_register_accessor.py", "ensure_removed"),
    ("_config/localization.py", "set_locale"),
]
IMPORT_CONTROL = ("pandas._testing", "assert_produces_warning")


def _report_decorator_bindings(decorators, session, graph=None) -> None:
    """Which step of the decorator road declines: the binding, or the class?"""
    from sugar_lift_python_source.manager_summary_derivation import (
        _construct_decorator_function,
        _decorator_module_export_binding,
        _enter_exit_sites_from_class_def,
        _sole_returned_manager_class,
    )

    for decorator in decorators:
        spelling = getattr(decorator, "id", None) or getattr(decorator, "attr", None)
        binding = _decorator_module_export_binding(decorator)
        print(
            f"      decorator {type(decorator).__name__} {spelling!r} "
            f"-> module_export_binding = {binding!r}"
        )
        if binding is not None:
            _trace_decorator_export(binding, decorator, session)
        fn = _construct_decorator_function(decorator, session=session, graph=graph)
        print(f"        _construct_decorator_function -> {type(fn).__name__ if fn is not None else None}")
        if fn is None:
            continue
        returned = _sole_returned_manager_class(fn)
        print(f"        _sole_returned_manager_class -> {type(returned).__name__ if returned is not None else None}")
        if returned is None:
            continue
        print(f"        _enter_exit_sites_from_class_def -> {_enter_exit_sites_from_class_def(returned) is not None}")


def _trace_decorator_export(binding, decorator, session) -> None:
    """Replicate the tail of _construct_decorator_function, naming each step.

    "declines because contextlib is not in the graph" and "declines at the
    population membrane" are different facts and want different repairs.
    """
    from sugar_lift_python_source.dependency_artifact import (
        DependencyArtifactAuthenticationError,
        ResolvedPythonObjectV1,
        authenticate_dependency_top_level,
        resolve_authenticated_module_export,
    )
    from sugar_lift_python_source.manager_construction import (
        resolve_source_visible_frame,
    )

    module_name, exported_name = binding
    top_level = module_name.split(".", 1)[0]
    try:
        graph = authenticate_dependency_top_level(top_level)
    except DependencyArtifactAuthenticationError as exc:
        print(f"        authenticate_dependency_top_level({top_level!r}) -> REFUSED {exc}")
        return
    print(
        f"        authenticate_dependency_top_level({top_level!r}) -> "
        f"artifactKind={getattr(graph, 'artifact_kind', None)!r} "
        f"module_present={module_name in graph.modules}"
    )
    resolved = resolve_authenticated_module_export(
        graph=graph,
        binding_cid=decorator.fragment.seal().cid,
        module_name=module_name,
        exported_name=exported_name,
        session=session,
    )
    print(f"        resolve_authenticated_module_export -> {type(resolved).__name__}")
    if not isinstance(resolved, ResolvedPythonObjectV1):
        print(f"          {resolved}")
        return
    frame_result = resolve_source_visible_frame(resolved, graph=graph, session=session)
    if isinstance(frame_result, tuple):
        _frame, target = frame_result
        print(f"        resolve_source_visible_frame -> {type(target).__name__}")
    else:
        print(
            f"        resolve_source_visible_frame -> GAP "
            f"kind={getattr(frame_result, 'kind', None)!r} "
            f"detail={getattr(frame_result, 'detail', None)!r}"
        )


def _describe_coords(label: str, coords) -> None:
    if coords is None:
        print(f"    {label}: coords = None  (decorator step DID NOT produce them)")
        return
    enter, exit_ = coords
    print(f"    {label}: coords OK")
    for name, coord in (("enter", enter), ("exit", exit_)):
        print(f"      {name}: {coord}")


def arm_local(corpus, session) -> None:
    from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
    from sugar_lift_python_source.manager_summary_derivation import (
        _protocol_coords_from_generator_decorators,
    )
    from sugar_source_tree.nodes import FunctionDef

    for seat, name in LOCAL_TARGETS:
        print(f"\n  --- {seat}::{name}")
        from sugar_lift_python_source.source_oracle import install_root_for

        path = corpus.joinpath(*seat.split("/"))
        installed = install_root_for(str(path))
        # An installed file's address is the seat its distribution recorded;
        # open it against the install root, not the package root.
        locus_root = corpus if installed is None else Path(installed)
        # root = the enrolled corpus (what the demand table is built over);
        # source_workspace_root = the install root (what the seat address is
        # recorded against). Passing the install root as `root` walks all of
        # site-packages to mint a demand table.
        source_file = open_source_file_for_construction(
            path,
            root=corpus,
            source_workspace_root=locus_root,
            distribution="pandas",
        )
        binds = (source_file.unit.module_direct_bindings or {}).get(name, ())
        print(f"    module_direct_bindings[{name!r}] -> {len(binds)} binding(s)")
        target = None
        for bound in binds:
            print(f"      {type(bound).__name__}")
            if isinstance(bound, FunctionDef):
                target = bound
        if target is None:
            print("    no FunctionDef binding; nothing for the generator road to take")
            continue
        decorators = getattr(target, "decorators", ()) or ()
        print(f"    decorators = {[type(d).__name__ for d in decorators]}")
        _report_decorator_bindings(decorators, session)
        try:
            coords = _protocol_coords_from_generator_decorators(
                target, session=session, graph=None
            )
        except BaseException:
            print("    decorator step RAISED:")
            traceback.print_exc()
            continue
        _describe_coords("LOCAL (graph=None)", coords)

        # Does anything publish a derived ref for this file's With uses today?
        context = source_file.unit.construction_context
        derived = getattr(context, "source_derived_contract_refs", {}) or {}
        print(f"    source_derived_contract_refs on this open: {len(derived)}")
        for coordinate, ref in list(derived.items())[:4]:
            print(f"      {type(ref).__name__} at {coordinate}")


def arm_import(corpus, session) -> None:
    from sugar_lift_python_source.dependency_artifact import (
        authenticate_dependency_top_level,
    )
    from sugar_lift_python_source.dependency_export_adapter import resolve_export
    from sugar_lift_python_source.manager_construction import (
        resolve_source_visible_frame,
    )
    from sugar_lift_python_source.manager_summary_derivation import (
        _protocol_coords_from_generator_decorators,
    )

    module_name, exported = IMPORT_CONTROL
    print(f"\n  --- CONTROL {module_name}.{exported} (import-backed)")
    graph = authenticate_dependency_top_level("pandas")
    resolved = resolve_export(
        graph, "probe", module_name, exported, (), frozenset(), session=session
    )
    print(f"    resolve_export -> {type(resolved).__name__}")
    frame_result = resolve_source_visible_frame(resolved, graph=graph, session=session)
    if not isinstance(frame_result, tuple):
        print(f"    frame gap: {frame_result}")
        return
    _frame, target = frame_result
    decorators = getattr(target, "decorators", ()) or ()
    print(f"    target = {type(target).__name__} {getattr(target, 'name', None)!r}")
    print(f"    decorators = {[type(d).__name__ for d in decorators]}")
    _report_decorator_bindings(decorators, session, graph=graph)
    coords = _protocol_coords_from_generator_decorators(
        target, session=session, graph=graph
    )
    _describe_coords("IMPORT (its own graph)", coords)


def main() -> int:
    from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
    from sugar_lift_python_source.resolution_session import walk_session_for

    corpus_handle = authenticated_pandas_corpus()
    corpus = corpus_handle.root
    print(
        f"CORPUS {corpus_handle.distribution} {corpus_handle.version} "
        f"files={corpus_handle.file_count}"
    )
    session = walk_session_for(corpus, enrolled_distributions=frozenset({"pandas"}))

    print("\nARM LOCAL -- same-module @contextmanager, no receipt, graph=None")
    try:
        arm_local(corpus, session)
    except BaseException:
        traceback.print_exc()

    print("\nARM IMPORT -- control, the road that already works")
    try:
        arm_import(corpus, session)
    except BaseException:
        traceback.print_exc()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
