#!/usr/bin/env python3
"""memento_walker.py -- emit per-node-path memento records for a source file.

Instrument for issue #5940 (STOP-THE-LINE: no enforced membrane around ast).
Not the production membrane. This is a deliberately minimal, stdlib-only
probe: it walks the WHOLE ast tree (every node CPython's `ast` module
produces, not only the subset SourceFragment currently wraps) and for each
node emits a memento record:

    (node_path, kind, start_line, start_col, end_line, end_col, cid)

node_path is a DETERMINISTIC address from the module root: a chain of
"<field_name>" / "<field_name>[<index>]" segments, walked in `node._fields`
order. It does not depend on object identity, dict/set iteration order, or
any cache. Two independent walks of byte-identical source, on any Python
version whose `ast` module exposes the same grammar, must produce the same
node_path for "the same" syntactic node.

cid is NOT sugar's production blake3_512 memento hash (source_fragment.py).
It is sha256 over the exact source segment bytes, computed the same way in
both interpreters, purely so this instrument can run with zero third-party
deps inside stock CPython 3.12.3 and the 3.12.13 container. What is under
test is span/segment STABILITY across interpreter patch versions, not
which hash function production uses -- if the segments are byte-identical,
any hash agrees or disagrees together. Divergence is read off the raw span
fields (start_line/start_col/end_line/end_col) primarily; the cid is a
convenience checksum layered on top, per the #5940 design-review requirement
that raw span components ride alongside the hash so a divergence names
WHICH span component moved.

Columns are UTF-8 byte offsets on the source line, matching CPython's own
`end_col_offset`/`col_offset` semantics (already documented at
source_tables.py:70) -- NOT `ast.get_source_segment`'s character-based
slicing. We re-slice by encoding each line to UTF-8, cutting on byte
offsets, and decoding back, so a divergence in this instrument reflects
CPython's own col_offset semantics, not a defect introduced by using the
stdlib helper.

Emits one JSON object per line (JSONL) to stdout, plus a final summary line
prefixed with "# node_count=".
"""

from __future__ import annotations

import ast
import hashlib
import json
import sys


def _byte_slice_segment(source_lines_bytes: list[bytes], node: ast.AST) -> bytes | None:
    """Extract the source segment for `node` using UTF-8 byte column offsets.

    Mirrors ast.get_source_segment's line/col contract but operates on raw
    bytes so behavior is pinned to CPython's col_offset semantics (bytes),
    not to str-based character slicing.
    """
    if not hasattr(node, "lineno") or not hasattr(node, "end_lineno"):
        return None
    if node.lineno is None or node.end_lineno is None:
        return None
    start_line = node.lineno
    end_line = node.end_lineno
    start_col = node.col_offset
    end_col = node.end_col_offset
    if start_line < 1 or end_line < 1 or end_line > len(source_lines_bytes):
        return None

    if start_line == end_line:
        line = source_lines_bytes[start_line - 1]
        return line[start_col:end_col]

    parts = []
    first_line = source_lines_bytes[start_line - 1]
    parts.append(first_line[start_col:])
    for lineno in range(start_line + 1, end_line):
        parts.append(source_lines_bytes[lineno - 1])
    last_line = source_lines_bytes[end_line - 1]
    parts.append(last_line[:end_col])
    return b"\n".join(parts)


def _walk_with_paths(node: ast.AST, path: str):
    """Yield (path, node) for node and all descendants, in deterministic
    field-and-index order derived from `node._fields` (NOT ast.walk, which
    is BFS over an internal deque and does not expose a stable address)."""
    yield path, node
    for field_name in node._fields:
        value = getattr(node, field_name, None)
        if isinstance(value, list):
            for index, item in enumerate(value):
                if isinstance(item, ast.AST):
                    child_path = f"{path}.{field_name}[{index}]"
                    yield from _walk_with_paths(item, child_path)
        elif isinstance(value, ast.AST):
            child_path = f"{path}.{field_name}"
            yield from _walk_with_paths(value, child_path)


def build_mementos(source: str, filename: str):
    tree = ast.parse(source, filename=filename)
    source_lines_bytes = [
        line.encode("utf-8") for line in source.splitlines(keepends=False)
    ]
    records = []
    for path, node in _walk_with_paths(tree, "module"):
        kind = type(node).__name__
        has_span = hasattr(node, "lineno")
        segment = _byte_slice_segment(source_lines_bytes, node) if has_span else None
        if segment is not None:
            cid = hashlib.sha256(segment).hexdigest()
        else:
            cid = None
        record = {
            "file": filename,
            "node_path": path,
            "kind": kind,
            "start_line": getattr(node, "lineno", None),
            "start_col": getattr(node, "col_offset", None),
            "end_line": getattr(node, "end_lineno", None),
            "end_col": getattr(node, "end_col_offset", None),
            "cid": cid,
        }
        records.append(record)
    return records


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: memento_walker.py <source_file>", file=sys.stderr)
        return 2
    path = argv[1]
    with open(path, "r", encoding="utf-8") as f:
        source = f.read()
    records = build_mementos(source, path)
    for record in records:
        print(json.dumps(record, sort_keys=True))
    print(f"# node_count={len(records)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
