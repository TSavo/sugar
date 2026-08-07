"""Is numpy.errstate's dynamic-export decidable, or does it bottom out off-population?

Diagnostic only.

``numpy/__init__.py`` binds ``errstate`` inside the else arm of

    try:
        __NUMPY_SETUP__          # noqa: B018
    except NameError:
        __NUMPY_SETUP__ = False

    if __NUMPY_SETUP__:
        sys.stderr.write(...)
    else:
        ...
        from ._core import (... errstate ...)

The export recognizer joins both arms on raw ``ast`` and, because one arm binds
and the other does not, returns ``("dynamic", locus)``. But the test is not
obviously symbolic: the ``try/except NameError`` above it binds
``__NUMPY_SETUP__ = False`` on the ordinary import path, so a THREADED prefix
might decide the ``If`` outright -- in which case the repair is the #7393 shape
(one entrance threads, the other reads raw AST) and NOT a guard-lifter.

Threading the prefix means materializing ``numpy``. This probe asks the one
question that decides which repair is even available:

    is the numpy graph OFF-POPULATION for the session the census uses?

If it is, the prefix cannot be threaded, the ``If`` cannot be decided, and
``errstate`` bottoms out at off-population like the rest -- a finding, not a
repair.
"""

from __future__ import annotations

import sys


def main() -> int:
    from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
    from sugar_lift_python_source.dependency_artifact import (
        authenticate_dependency_top_level,
    )
    from sugar_lift_python_source.manager_construction import (
        _graph_is_off_population,
        prefix_has_completed_fallthrough,
    )
    from sugar_lift_python_source.resolution_session import walk_session_for

    corpus = authenticated_pandas_corpus()
    print(f"CORPUS {corpus.distribution} {corpus.version} files={corpus.file_count}")

    # The roster the census installs: one enrolled distribution.
    session = walk_session_for(
        corpus.root, enrolled_distributions=frozenset({"pandas"})
    )
    print(f"SESSION enrolled_distributions = {sorted(session.enrolled_distributions)}")

    for top in ("numpy", "pandas", "contextlib"):
        graph = authenticate_dependency_top_level(top)
        off = _graph_is_off_population(graph, session=session)
        print(
            f"  {top:<12} artifactKind={graph.artifact_kind!r:<14} "
            f"OFF-POPULATION={off}"
        )

    # And what the prefix door therefore answers for numpy's export locus.
    import ast

    from sugar_lift_python_source.dependency_export_adapter import (
        _export_block_with_locus,
    )
    from sugar_lift_python_source.source_tables import parsed_tree

    graph = authenticate_dependency_top_level("numpy")
    module = graph.modules.get("numpy")
    tree = parsed_tree(module.source, module.source_seat)
    _binding, locus = _export_block_with_locus(tree.body, "errstate", None)
    print(f"\nEXPORT LOCUS for numpy.errstate: line {locus.lineno} {type(locus).__name__}")
    outcome = prefix_has_completed_fallthrough(
        module, locus, graph=graph, session=session
    )
    print(f"  prefix_has_completed_fallthrough -> kind={outcome.kind!r}")
    print(
        "  NOTE: 'completed' here may be the off-population SHORT-CIRCUIT, not a\n"
        "  threaded result. Read it together with OFF-POPULATION above."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
