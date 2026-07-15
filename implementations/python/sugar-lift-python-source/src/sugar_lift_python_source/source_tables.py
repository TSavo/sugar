"""The one API for reading source text through the AST: table-backed, idempotent.

Every consumer that needs a node's source segment, a module's line table, or a
parsed tree goes through these functions. Each is an idempotent recompute keyed
by the source CONTENT, so behind the scenes it is a build-once in-memory table
and an O(1) lookup on every subsequent request -- callers never know different.
Keying by content (never by path) preserves drift semantics exactly: changed
source is a new key and recomputes; identical source never re-derives.

`ast.get_source_segment` re-splits the entire source on every call and callers
that re-`ast.parse` per query are quadratic across a module's nodes; these
tables are why neither ever appears outside this module.

Process-lifetime bound: tables use a finite LRU (SOURCE_TABLE_CAPACITY), not
`maxsize=None`. A resident lift generation walks many modules; unbounded
content-keyed caches retained every distinct body until the hosted runner
killed the kit. Eviction recomputes — same semantics, finite ownership.
See tools/resident_ownership_census.py and
docs/analysis/ci-whack-a-mole-course-2026-07-15.md.
"""

from __future__ import annotations

import ast
import functools

from sugar_lift_python_source.big_stack import parse_on_big_stack

__all__ = [
    "SOURCE_TABLE_CAPACITY",
    "parsed_parents",
    "parsed_tree",
    "source_lines",
    "source_segment",
    "source_splitlines",
]

# Align with install-source index capacity (install_source_dig): hot working
# set of modules in one generation, not the whole corpus forever.
SOURCE_TABLE_CAPACITY = 64


@functools.lru_cache(maxsize=SOURCE_TABLE_CAPACITY)
def source_splitlines(source: str) -> tuple[str, ...]:
    """`str.splitlines(keepends=True)` split once per source.

    Distinct from `source_lines`: str.splitlines DOES break on form feeds and
    other line-boundary characters the parser ignores. Consumers whose pinned
    CIDs were minted over str.splitlines line lists must keep these semantics.
    """
    return tuple(source.splitlines(keepends=True))


@functools.lru_cache(maxsize=SOURCE_TABLE_CAPACITY)
def source_lines(source: str) -> tuple[str, ...]:
    """The module's line table (line ends kept), split once per source.

    Mirrors the parser's own line splitting (`ast._splitlines_no_ff`): form
    feeds do not break lines, so offsets agree with node positions.
    """
    return tuple(ast._splitlines_no_ff(source))


def source_segment(source: str, node: ast.AST) -> str | None:
    """`ast.get_source_segment` semantics as a lookup against the line table.

    Returns None when position information is missing, exactly as the stdlib
    does. Column offsets are byte offsets into the UTF-8 encoding of each line.
    """
    try:
        if node.end_lineno is None or node.end_col_offset is None:
            return None
        lineno = node.lineno - 1
        end_lineno = node.end_lineno - 1
        col_offset = node.col_offset
        end_col_offset = node.end_col_offset
    except AttributeError:
        return None
    lines = source_lines(source)
    if end_lineno == lineno:
        return lines[lineno].encode()[col_offset:end_col_offset].decode()
    first = lines[lineno].encode()[col_offset:].decode()
    last = lines[end_lineno].encode()[:end_col_offset].decode()
    return "".join((first, *lines[lineno + 1 : end_lineno], last))


@functools.lru_cache(maxsize=SOURCE_TABLE_CAPACITY)
def _parsed(source: str, filename: str) -> ast.Module:
    return parse_on_big_stack(source, filename)


def parsed_tree(source: str, filename: str = "<unknown>") -> ast.Module:
    """The parsed module, one parse per (source, filename).

    Raises SyntaxError exactly as `ast.parse` does (the raise recurs on every
    call for the same source; failures are not cached).
    """
    return _parsed(source, filename)


@functools.lru_cache(maxsize=SOURCE_TABLE_CAPACITY)
def parsed_parents(source: str) -> "tuple[ast.Module, dict[ast.AST, ast.AST]] | None":
    """The parsed tree plus its child->parent map, or None on a syntax error.

    One parse and one walk per source; every ancestor query over the same
    module shares the same table.
    """
    try:
        tree = parsed_tree(source)
    except SyntaxError:
        return None
    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    return tree, parents
