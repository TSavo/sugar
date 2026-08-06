"""Name, for one authenticated symbol, WHY With has no contract ref.

Diagnostic only -- reports, never repairs. Answers two questions the sealed
board cannot, because the board records the fused gap kind and not the
producer testimony behind it:

  * export resolution: what does ``resolve_export`` return, and when it
    returns ``dynamic-export``, which arm of ``PrefixFallthroughOutcomeV1``
    actually produced it -- ``ordinary-non-fallthrough`` or a named
    ``construction-refusal``?
  * frame projection: when ``resolve_source_visible_frame`` raises
    ``SugarNotWritten``, what construct, at which coordinate, refused?

usage:
  python probe_with_gaps.py python:pandas.option_context [more symbols...]
"""

from __future__ import annotations

import sys
import traceback


def _print_outcome(label: str, value: object) -> None:
    print(f"  {label}: {type(value).__name__}")
    for field in (
        "kind",
        "refusal_kind",
        "observed_event_type",
        "detail",
        "module_name",
        "exported_name",
        "target_symbol",
    ):
        if hasattr(value, field):
            print(f"    .{field} = {getattr(value, field)!r}")


def probe(symbol: str, corpus_root) -> None:
    import ast

    from sugar_lift_python_source.dependency_artifact import (
        ResolvedPythonObjectV1,
        authenticate_dependency_top_level,
    )
    from sugar_lift_python_source.dependency_export_adapter import (
        _export_block_with_locus,
        resolve_export,
    )
    from sugar_lift_python_source.manager_construction import (
        prefix_has_completed_fallthrough,
        resolve_source_visible_frame,
    )
    from sugar_lift_python_source.resolution_session import walk_session_for
    from sugar_lift_python_source.source_tables import parsed_tree

    print(f"=== {symbol}")
    dotted = symbol.removeprefix("python:")
    module_name, _, exported_name = dotted.rpartition(".")
    top_level = dotted.split(".", 1)[0]
    session = walk_session_for(
        corpus_root, enrolled_distributions=frozenset({"pandas"})
    )
    graph = authenticate_dependency_top_level(top_level)
    print(f"  graph.distributionArtifactCid = {graph.distribution_artifact_cid}")
    print(f"  module {module_name!r} exported {exported_name!r}")

    module = graph.modules.get(module_name)
    if module is None:
        print("  MODULE ABSENT from graph")
        return
    print(f"  module.source_seat = {module.source_seat}")

    # The prefix arm, read straight from the producer -- this is the fact the
    # adapter fuses into an untyped ``dynamic-export``.
    tree = parsed_tree(module.source, module.source_seat)
    _binding, locus = _export_block_with_locus(tree.body, exported_name, None)
    if locus is None:
        print("  no export-binding locus for this name in this module")
    else:
        print(f"  export locus: line {locus.lineno} col {locus.col_offset} "
              f"{type(locus).__name__} :: {ast.unparse(locus)[:160]!r}")
        outcome = prefix_has_completed_fallthrough(
            module, locus, graph=graph, session=session
        )
        _print_outcome("prefix fallthrough", outcome)
        # Which prefix statements are NOT statically fall-through: the exact
        # reason the cheap door declined and the producer had to run.
        from sugar_lift_python_source.manager_construction import (
            _ast_stmt_always_falls_through,
        )

        locus_key = (locus.lineno, locus.col_offset)
        for statement in tree.body:
            if (statement.lineno, statement.col_offset) >= locus_key:
                break
            if not _ast_stmt_always_falls_through(statement):
                print(
                    f"    non-static-fallthrough prefix stmt "
                    f"line {statement.lineno} {type(statement).__name__}: "
                    f"{ast.unparse(statement)[:200]!r}"
                )

    resolved = resolve_export(
        graph, "probe", module_name, exported_name, (), frozenset(), session=session
    )
    _print_outcome("resolve_export", resolved)
    if not isinstance(resolved, ResolvedPythonObjectV1):
        return

    from sugar_source_tree.panic import SugarNotWritten

    try:
        frame_result = resolve_source_visible_frame(
            resolved, graph=graph, session=session
        )
    except SugarNotWritten as exc:
        print("  resolve_source_visible_frame RAISED SugarNotWritten")
        for field in ("owner", "observed", "requested", "fix", "blame"):
            print(f"    .{field} = {getattr(exc, field, None)!r}")
        traceback.print_exc()
        return
    except TypeError:
        print("  resolve_source_visible_frame RAISED TypeError")
        traceback.print_exc()
        return
    if isinstance(frame_result, tuple):
        frame, target = frame_result
        print(f"  FRAME OK: target={type(target).__name__} {target.name!r}")
    else:
        _print_outcome("frame gap", frame_result)


def main(argv: list[str]) -> int:
    from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus

    corpus = authenticated_pandas_corpus()
    print(f"CORPUS {corpus.distribution} {corpus.version} "
          f"files={corpus.file_count} manifest={corpus.manifest_cid}")
    for symbol in argv:
        try:
            probe(symbol, corpus.root)
        except BaseException:  # a probe is diagnostic: never hide its own death
            traceback.print_exc()
        print(flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
