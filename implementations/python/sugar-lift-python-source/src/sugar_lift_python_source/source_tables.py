"""The one API for reading source text through line tables: table-backed, idempotent.

Every consumer that needs a node's source segment or a module's line table goes
through these functions. Each is an idempotent recompute keyed by the source
CONTENT, so behind the scenes it is a build-once in-memory table and an O(1)
lookup on every subsequent request -- callers never know different.
Keying by content (never by path) preserves drift semantics exactly: changed
source is a new key and recomputes; identical source never re-derives.

Stdlib parse / foreign AST currency does NOT live here. Residual dual-body
consumers that still need a content-keyed ``ast.Module`` enter through
``source_tables_adapter.parsed_tree``. Production construction enters through
``SourceFile`` / typed Nodes. Parent maps, locus indexes, and symtable caches
that had no production callers were deleted rather than rewritten.

Process-lifetime bound: tables use a finite LRU (SOURCE_TABLE_CAPACITY), not
`maxsize=None`. A resident lift generation walks many modules; unbounded
content-keyed caches retained every distinct body until the hosted runner
killed the kit. Eviction recomputes — same semantics, finite ownership.
See tools/resident_ownership_census.py and
docs/analysis/ci-whack-a-mole-course-2026-07-15.md.
"""

from __future__ import annotations

import functools
import re
from typing import Any, Protocol

# Re-export residual dual parse for callers that still pin it; the adapter
# owns the foreign ``ast`` import so this module stays construction-clean.
from .source_tables_adapter import SOURCE_TABLE_CAPACITY, parsed_tree

__all__ = [
    "SOURCE_TABLE_CAPACITY",
    "parsed_tree",
    "source_lines",
    "source_segment",
    "source_splitlines",
]


# Mirror of CPython ``ast._splitlines_no_ff``: form feeds do not break lines,
# so offsets agree with parser node positions. Kept local so this module never
# imports foreign ``ast`` currency.
_LINE_PATTERN = re.compile(r"(.*?(?:\r\n|\n|\r|$))")


class _Positioned(Protocol):
    """Duck shape for source-segment lookup — typed Node or residual dual AST."""

    lineno: int
    col_offset: int
    end_lineno: int | None
    end_col_offset: int | None


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

    Mirrors the parser's own line splitting (form feeds do not break lines),
    so offsets agree with node positions.
    """
    lines: list[str] = []
    for match in _LINE_PATTERN.finditer(source):
        lines.append(match[0])
    return tuple(lines)


def source_segment(source: str, node: Any) -> str | None:
    """`ast.get_source_segment` semantics as a lookup against the line table.

    Returns None when position information is missing, exactly as the stdlib
    does. Column offsets are byte offsets into the UTF-8 encoding of each line.
    Accepts any positioned node (typed Node attrs or residual dual AST).
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
