"""Golden corpus: mementos emitted from OUR spans.

One record per node, addressed by ``(file, node_path)`` where ``node_path``
is the deterministic field path from the module root (``$``, then
``.field`` / ``.field[i]`` in declared grammar order). No reliance on
object identity or iteration order: field order is the class declaration,
file order is sorted, record order is DFS.

Record fields:
    file, path, kind, start, end (codepoint offsets),
    start_line, start_col, end_line, end_col (1-based lines,
    0-based codepoint cols), cid.

``cid`` is ``sha256:`` over the UTF-8 encoding of the source segment
selected by OUR span — a pure function of (source, span), never of the
provider. (sha256, not production's blake3_512, so the corpus runs
stdlib-only; the span components ride alongside so a change names
which coordinate moved, not just that a hash changed. Precedent: the
#5940.)

This artifact is the instrument that admits or rejects a future provider:
parse the same sources through another adapter, emit, diff. A provider
that diverges is not debugged — it is uninstalled.

Failures are LOUD: a MembranePanic or provider SyntaxError on any file is
recorded, reported, and fails the run. A MISSING never becomes silence.

CLI:
    python -m sugar_node_membrane.corpus --out corpus.jsonl PATH [PATH ...]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

from .construct import Membrane
from .nodes import SourceFragment
from .panic import MembranePanic


def node_paths(root: SourceFragment) -> Iterator[tuple[str, SourceFragment]]:
    """Deterministic (path, node) pairs, DFS pre-order, iterative."""
    stack: list[tuple[str, SourceFragment]] = [("$", root)]
    while stack:
        path, node = stack.pop()
        yield path, node
        entries = []
        for name, index, child in node.children():
            step = f".{name}" if index is None else f".{name}[{index}]"
            entries.append((path + step, child))
        stack.extend(reversed(entries))


def records_for_source(
    membrane: Membrane, source: str, rel_file: str
) -> list[dict[str, object]]:
    root = membrane.parse(source, filename=rel_file)
    table = root.unit.line_table
    out: list[dict[str, object]] = []
    for path, node in node_paths(root):
        lc = table.project(node.span)
        segment_cid = hashlib.sha256(node.segment().encode("utf-8")).hexdigest()
        out.append(
            {
                "file": rel_file,
                "path": path,
                "kind": node.kind,
                "start": node.span.start,
                "end": node.span.end,
                "start_line": lc.start_line,
                "start_col": lc.start_col,
                "end_line": lc.end_line,
                "end_col": lc.end_col,
                "cid": f"sha256:{segment_cid}",
            }
        )
    return out


@dataclass
class CorpusResult:
    files: int
    nodes: int
    kind_counts: dict[str, int]
    failures: list[tuple[str, str, str]]  # (file, failure_class, message)
    manifest_cid: str


def emit_corpus(
    paths: list[Path], out_path: Optional[Path], base: Optional[Path] = None
) -> CorpusResult:
    files: list[Path] = []
    for p in paths:
        if p.is_dir():
            files.extend(sorted(p.rglob("*.py")))
        else:
            files.append(p)
    files.sort()

    membrane = Membrane()
    manifest = hashlib.sha256()
    kind_counts: dict[str, int] = {}
    failures: list[tuple[str, str, str]] = []
    nodes = 0
    parsed = 0

    sink = out_path.open("w", encoding="utf-8") if out_path is not None else None
    try:
        for path in files:
            rel = str(path.relative_to(base)) if base is not None else str(path)
            try:
                source = path.read_text(encoding="utf-8")
            except UnicodeDecodeError as err:
                failures.append((rel, "undecodable", str(err)))
                continue
            try:
                recs = records_for_source(membrane, source, rel)
            except SyntaxError as err:
                # The PROVIDER refused the file (not valid input for it).
                # Recorded loudly; distinct from a membrane MISSING.
                failures.append((rel, "provider_syntax_error", str(err)))
                continue
            except MembranePanic as err:
                # A membrane MISSING: a shape with no class. THE finding.
                failures.append((rel, "membrane_panic", str(err)))
                continue
            parsed += 1
            for rec in recs:
                nodes += 1
                kind_counts[rec["kind"]] = kind_counts.get(rec["kind"], 0) + 1
                line = json.dumps(rec, sort_keys=True, ensure_ascii=True)
                manifest.update(line.encode("utf-8"))
                manifest.update(b"\n")
                if sink is not None:
                    sink.write(line)
                    sink.write("\n")
    finally:
        if sink is not None:
            sink.close()

    return CorpusResult(
        files=parsed,
        nodes=nodes,
        kind_counts=kind_counts,
        failures=failures,
        manifest_cid=f"sha256:{manifest.hexdigest()}",
    )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--base", type=Path, default=None)
    args = parser.parse_args(argv)

    result = emit_corpus(args.paths, args.out, args.base)
    print(f"files:    {result.files}")
    print(f"nodes:    {result.nodes}")
    print(f"kinds:    {len(result.kind_counts)}")
    print(f"manifest: {result.manifest_cid}")
    membrane_missing = [f for f in result.failures if f[1] == "membrane_panic"]
    other = [f for f in result.failures if f[1] != "membrane_panic"]
    for rel, failure_class, message in result.failures:
        print(f"FAIL[{failure_class}] {rel}: {message.splitlines()[0]}")
    print(f"membrane panics: {len(membrane_missing)}")
    print(f"provider refusals / undecodable: {len(other)}")
    return 1 if result.failures else 0


if __name__ == "__main__":
    sys.exit(main())
