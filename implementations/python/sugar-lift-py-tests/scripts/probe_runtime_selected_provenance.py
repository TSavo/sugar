"""Which door painted the runtime-selected rows: the join miss, or no context?

Diagnostic only -- reports, never repairs.

Two mechanisms are known to involve the words "runtime selected":

  DOOR A -- the demand-table join. `lift_rpc._preconstruction_demand_rows` sets
    `gapKind = "runtime-selected"` when `calls_by_site.get(site)` misses. A
    context IS seated; `With._prebound_manager_resolution` reaches
    `contract_refs.require(coordinate)`, gets a typed
    `ContextManagerResolutionGapV1` whose `kind` carries that string, and
    `_raise_resolution_gap` raises `ContextManagerResolutionConstructionGap`
    with owner `With._construct_sugar`.

  DOOR B -- the bare construction door. `R_bare_construction_door` says
    `SourceFile.from_path` yields a tree with NO construction context, and that
    "without a context every `with` paints RuntimeSelectedContextManager
    regardless of resolvability". There `_prebound_manager_resolution` returns
    None at `if context is None`, and `With.sugar` raises the separate
    `RuntimeSelectedContextManager` panic.

If both doors produce the same artifact, they are one defect at two altitudes
and repairing the join would leave the other minting identical rows. If they
produce different artifacts, they are two independent bugs sharing a word, and
the owner/observed text on the sealed rows says which one painted them.

WARNING -- this probe DELIBERATELY drives `.sugar()` over a bare
`SourceFile.from_path` tree in `door_b`. That is exactly what
`R_bare_construction_door` forbids, and it is the point: the probe exists to
exhibit the forbidden door's output next to the production door's. If that law
is mounted, this file is a KNOWN offender and should be allowlisted or deleted,
never silently "fixed" -- fixing it would delete the measurement.

usage:
  python probe_runtime_selected_provenance.py [seat ...]
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

DEFAULT_SEATS = [
    "tests/io/parser/test_compression.py",
    "tests/test_register_accessor.py",
]


def _panic_fields(panic) -> None:
    print(f"    class    = {type(panic).__name__}")
    for field in ("owner", "observed", "requested", "resolution_kind", "target_symbol"):
        if hasattr(panic, field):
            print(f"    {field:<9}= {getattr(panic, field)!r}")


def door_a(seat: str) -> None:
    """The census entrance, with the context the production path seats."""
    import importlib.util

    from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
    from sugar_lift_py_tests.repo_root import sugar_lift_py_tests_package_root
    from sugar_lift_python_source.source_oracle import install_root_for

    scripts = sugar_lift_py_tests_package_root() / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    spec = importlib.util.spec_from_file_location(
        "recensus_enumerate_consumer", scripts / "recensus_enumerate_consumer.py"
    )
    consumer = importlib.util.module_from_spec(spec)
    sys.modules["recensus_enumerate_consumer"] = consumer
    spec.loader.exec_module(consumer)

    corpus = authenticated_pandas_corpus().root
    target = corpus.joinpath(*seat.split("/"))
    installed = install_root_for(str(target))
    locus_root = corpus if installed is None else Path(installed)
    row = consumer.measure_file_via_enumerate(
        workspace_root=corpus,
        file_rel=seat,
        distribution="pandas",
        source_workspace_root=locus_root,
    )
    failure = (row.get("instrumentFailure") or {}).get("message")
    print(f"  terminalKind      = {row.get('terminalKind')!r}")
    print(f"  instrumentFailure = {failure!r}")
    panics = [p for p in (row.get("constructionPanics") or []) if isinstance(p, dict)]
    selected = [
        p for p in panics if "runtime-selected" in str(p.get("observed"))
    ]
    print(f"  panics={len(panics)}  naming runtime-selected={len(selected)}")
    for panic in selected[:4]:
        print("    ---")
        for key in ("owner", "coordinate", "observed", "resolutionKind", "targetSymbol"):
            if key in panic:
                print(f"    {key:<14}= {str(panic[key])[:160]!r}")


def door_b(seat: str) -> None:
    """The bare door the law names: no construction context, driven anyway."""
    from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
    from sugar_source_tree.nodes import With
    from sugar_source_tree.tree import SourceFile

    corpus = authenticated_pandas_corpus().root
    target = corpus.joinpath(*seat.split("/"))
    source_file = SourceFile.from_path(str(target))
    context = source_file.unit.construction_context
    print(f"  construction_context = {context!r}")
    withs = [node for node in source_file.root.walk() if isinstance(node, With)]
    print(f"  With statements = {len(withs)}")
    for node in withs[:1]:
        try:
            node.sugar()
            print("    constructed WITHOUT a context (no refusal at all)")
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            _panic_fields(exc)


def door_a_context(seat: str) -> None:
    """Affirmative check: is a TreeConstructionContextV1 seated on the production door?"""
    from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_lift_py_tests.lift_rpc import provisional_contract_refs_from_demands
    from sugar_source_tree.tree import SourceFile

    corpus = authenticated_pandas_corpus().root
    target = corpus.joinpath(*seat.split("/"))
    refs = provisional_contract_refs_from_demands(corpus)
    context = TreeConstructionContextV1(contract_refs=refs)
    source_file = SourceFile.from_path(str(target), construction_context=context)
    seated = source_file.unit.construction_context
    print(f"  seated context type = {type(seated).__name__}")
    print(
        f"  is TreeConstructionContextV1 = "
        f"{isinstance(seated, TreeConstructionContextV1)}"
    )


def main(argv: list[str]) -> int:
    seats = argv or DEFAULT_SEATS
    from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus

    corpus = authenticated_pandas_corpus()
    print(f"CORPUS {corpus.distribution} {corpus.version} files={corpus.file_count}")
    for seat in seats:
        print(f"\n=== {seat}")
        print("DOOR A -- census entrance (context seated)")
        try:
            door_a(seat)
        except BaseException:
            traceback.print_exc()
        print("DOOR B -- bare SourceFile.from_path (no context), driven anyway")
        try:
            door_b(seat)
        except BaseException:
            traceback.print_exc()
        print("CONTEXT CHECK -- production door seats what?")
        try:
            door_a_context(seat)
        except BaseException:
            traceback.print_exc()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
