"""Discriminator: does the module-prefix door reach the block-threading construct?

Diagnostic only -- reports, never repairs.

Two doors construct a statement sequence in this codebase:

  A. ``FunctionDef.source_visible_call_frame`` (nodes.py:3814)
         substituted_body, _ = self._substitute_body(filtered_body, formal_scope)
         ... self._sugar_body_statement(statement) for statement in substituted_body
     SUBSTITUTE the block, THEN sugar each statement.

  B. ``manager_construction._module_prefix_outcome`` (:1002)
         sugars = tuple(... statement.sugar() ... for statement in prefix)
         return reduce_block_to_exitset(sugars)
     Sugar each statement. Never substitute.

``_substitute_body_tracked`` is what threads a statement's binding into the
rest of the block, and it is what splices a ``for`` that dissolved over a
concrete iterable (``_Splice``). Door B never calls it, so a module-level
``for`` over a module-level constant cannot dissolve and falls to
``For.sugar``, which is deliberately unwritten because a SURVIVING ``For`` is
the symbolic fold.

This probe runs BOTH arms over the SAME authenticated prefix statements and
reports what each produces. It writes nothing and repairs nothing.

usage:
  python probe_prefix_threading.py pandas pandas 34
      <top-level> <module> <export-locus-line>
"""

from __future__ import annotations

import sys
import traceback


def main(argv: list[str]) -> int:
    from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
    from sugar_lift_python_source.dependency_artifact import (
        authenticate_dependency_top_level,
    )
    from sugar_lift_python_source.resolution_session import walk_session_for
    from sugar_source_tree.panic import SugarNotWritten
    from sugar_source_tree.tree import SourceFile

    top_level, module_name, locus_line = argv[0], argv[1], int(argv[2])
    corpus = authenticated_pandas_corpus()
    print(f"CORPUS {corpus.distribution} {corpus.version} files={corpus.file_count}")
    session = walk_session_for(
        corpus.root, enrolled_distributions=frozenset({"pandas"})
    )
    graph = authenticate_dependency_top_level(top_level)
    module = graph.modules[module_name]
    print(f"MODULE {module_name} seat={module.source_seat}")

    from sugar_lift_python_source.manager_construction import (
        TreeConstructionContextV1,
    )
    from sugar_source_tree.binding_state import (
        ConstructionTestimonyReporterV1,
        SubstitutionTraceBuilderV1,
    )
    from sugar_source_tree.reporter import NULL_REPORTER

    def fresh_prefix():
        """A cold prefix: door A and door B must not share a construction memo."""
        source_file = SourceFile(
            (module.source, module.source_seat, module.source_cid),
            reporter=ConstructionTestimonyReporterV1(
                NULL_REPORTER, SubstitutionTraceBuilderV1(module.source_cid)
            ),
            construction_context=(
                TreeConstructionContextV1.for_source_call_construction()
            ),
        )
        prefix = tuple(
            statement
            for statement in source_file.root.body
            if statement.line_col_span().start_line < locus_line
        )
        return source_file, prefix

    source_file, prefix = fresh_prefix()
    print(f"PREFIX {len(prefix)} statements before line {locus_line}")
    for statement in prefix:
        span = statement.line_col_span()
        print(f"  line {span.start_line:>4} {statement.kind}")

    # ---- DOOR B (what _module_prefix_outcome does today) --------------------
    print("\nDOOR B -- sugar each statement, no substitute (current prefix door)")
    for statement in prefix:
        span = statement.line_col_span()
        if statement.kind not in ("For", "While", "Try"):
            continue
        try:
            statement.sugar()
            print(f"  line {span.start_line} {statement.kind}: sugar OK")
        except SugarNotWritten as exc:
            print(
                f"  line {span.start_line} {statement.kind}: "
                f"SugarNotWritten [{exc.owner}] {exc.observed}"
            )
        except BaseException as exc:  # a probe names its own death
            print(f"  line {span.start_line} {statement.kind}: {type(exc).__name__}: {exc}")

    # ---- DOOR A (block-substitute first, exactly as a function body does) ---
    print("\nDOOR A -- _substitute_body over the SAME prefix, then sugar")
    source_file, prefix = fresh_prefix()
    root = source_file.root
    try:
        substituted, changed = root._substitute_body(prefix, {})
    except SugarNotWritten as exc:
        print(f"  _substitute_body RAISED SugarNotWritten [{exc.owner}] {exc.observed}")
        return 0
    except BaseException:
        print("  _substitute_body RAISED:")
        traceback.print_exc()
        return 0
    print(f"  changed={changed}  {len(prefix)} statements -> {len(substituted)}")
    kinds_before = [s.kind for s in prefix]
    kinds_after = [s.kind for s in substituted]
    print(f"  kinds before: {kinds_before}")
    print(f"  kinds after : {kinds_after}")
    print(f"  For survived substitution: {'For' in kinds_after}")
    for statement in substituted:
        span = statement.line_col_span()
        if statement.kind not in ("For", "While", "Try"):
            continue
        try:
            statement.sugar()
            print(f"  line {span.start_line} {statement.kind}: sugar OK")
        except SugarNotWritten as exc:
            print(
                f"  line {span.start_line} {statement.kind}: "
                f"SugarNotWritten [{exc.owner}] {exc.observed}"
            )
        except BaseException as exc:
            print(f"  line {span.start_line} {statement.kind}: {type(exc).__name__}: {exc}")

    # ---- The SECOND gate: even a dissolved For must leave ONE Completed face
    # `prefix_has_completed_fallthrough` requires len(exits.exits) == 1 with a
    # true guard. Report the face count so a reader cannot mistake "the For
    # dissolved" for "the export is now admissible".
    print("\nEXIT FACES of the substituted prefix (the second gate)")
    try:
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            reduce_block_to_exitset,
        )

        sugars = []
        for statement in substituted:
            try:
                sugars.append(statement.sugar())
            except SugarNotWritten as exc:
                print(f"  cannot reduce: [{exc.owner}] {exc.observed}")
                return 0
        exits = reduce_block_to_exitset(tuple(sugars))
        print(f"  exit face count = {len(exits.exits)}")
        for face in exits.exits:
            print(
                f"    {type(face).__name__} guard={getattr(face, 'guard', None)!r} "
                f"can_fall_through="
                f"{getattr(getattr(face, 'value', None), 'can_fall_through', None)!r}"
            )
    except BaseException:
        traceback.print_exc()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
