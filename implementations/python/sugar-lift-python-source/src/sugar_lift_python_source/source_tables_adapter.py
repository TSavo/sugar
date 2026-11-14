"""Stdlib-AST parse adapter for residual dual-body consumers.

Production sole path enters through ``SourceFile`` / typed Nodes. The only
remaining dual-body pin of a content-keyed stdlib ``ast.Module`` is
``dependency_artifact`` export scan — foreign ``ast`` currency lives HERE
(the ``*_adapter*`` boundary) and nowhere in the public line-table module.
"""

from __future__ import annotations

import ast
import functools

# Align with install-source / public source_tables capacity: hot working set
# of modules in one generation, not the whole corpus forever.
SOURCE_TABLE_CAPACITY = 64


@functools.lru_cache(maxsize=SOURCE_TABLE_CAPACITY)
def _parsed(source: str, filename: str) -> ast.Module:
    return ast.parse(source, filename=filename)


def parsed_tree(source: str, filename: str = "<unknown>") -> ast.Module:
    """Content-keyed stdlib parse for residual dual-body consumers only.

    Raises SyntaxError exactly as ``ast.parse`` does (the raise recurs on every
    call for the same source; failures are not cached). Production construction
    must not take this door — ``SourceFile`` is the sole parse gate.
    """
    return _parsed(source, filename)
