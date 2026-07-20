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
backend. (sha256, not production's blake3_512, so the corpus runs
stdlib-only; the span components ride alongside so a change names
which coordinate moved, not just that a hash changed. Precedent: #5940.)

This artifact is the instrument that admits or rejects a future backend:
enumerate the same tree through another adapter, emit, diff. A backend
that diverges is not debugged — it is uninstalled.

Failures are LOUD: a VocabularyMissing (our vocabulary is incomplete for
a shape the backend legitimately produced), a BackendDefect (the backend
or its adapter produced something structurally invalid), or a backend
refusal (BackendRefused, backend.py — the backend's own "not valid input
for me", never its native exception type) on any file is recorded,
reported, and fails the run. None of the three ever becomes silence.

The backend is a parameter, not a source edit: default is CPython's
``ast`` (CPythonAstBackend), but any Backend can be threaded through from
the CLI (--backend) or from code, so a benchmark can run the same corpus
through more than one adapter without monkeypatching this module.

CLI:
    python -m sugar_source_tree.corpus --out corpus.jsonl PATH [PATH ...]
    python -m sugar_source_tree.corpus --backend libcst PATH [PATH ...]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

from sugar_lift_python_source.source_oracle import SourceOracleRefusal, path_source

from .backend import Backend, BackendRefused
from .nodes import Node
from .panic import BackendDefect, VocabularyMissing
from .tree import SourceFile


def node_paths(root: Node) -> Iterator[tuple[str, Node]]:
    """Deterministic (path, node) pairs, DFS pre-order, iterative."""
    stack: list[tuple[str, Node]] = [("$", root)]
    while stack:
        path, node = stack.pop()
        yield path, node
        entries = []
        for name, index, child in node.children():
            step = f".{name}" if index is None else f".{name}[{index}]"
            entries.append((path + step, child))
        stack.extend(reversed(entries))


def records_for_file(
    file: SourceFile, display: Optional[str] = None
) -> list[dict[str, object]]:
    """``display`` is the record's ``file`` label (root-relative in a corpus
    run); the unit's own filename is the oracle's address and stays on the
    unit."""
    file_label = display if display is not None else file.filename
    table = file.unit.line_table
    out: list[dict[str, object]] = []
    for path, node in node_paths(file.root):
        lc = table.project(node.span)
        segment_cid = hashlib.sha256(node.segment().encode("utf-8")).hexdigest()
        out.append(
            {
                "file": file_label,
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
    paths: list[Path],
    out_path: Optional[Path],
    base: Optional[Path] = None,
    backend: Optional[Backend] = None,
) -> CorpusResult:
    """Enumerate every file, one SourceFile at a time — built, recorded,
    dropped. Nothing retains parsed files across iterations, so peak RSS is
    bounded by the largest file, not the corpus. The backend is the ONLY
    thing that should ever change which parser a corpus run measures —
    never a monkeypatch."""
    files: list[Path] = []
    for p in paths:
        if p.is_dir():
            files.extend(sorted(p.rglob("*.py")))
        else:
            files.append(p)
    files.sort()

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
                identity = path_source(str(path))
            except SourceOracleRefusal as err:
                # The ORACLE refused to mint an identity (unreadable or
                # undecodable). Text enters only through the oracle, so
                # this is where a bad file surfaces — recorded, never
                # swallowed.
                failures.append((rel, "oracle_refused", str(err)))
                continue
            try:
                file = SourceFile(identity, backend=backend)
                recs = records_for_file(file, display=rel)
            except BackendRefused as err:
                # The BACKEND refused the file (not valid input for it).
                # Recorded loudly; distinct from a vocabulary MISSING. Never
                # the backend's native exception type (#5946) — the tree's
                # own contract type, so this catch works identically no
                # matter which backend is installed.
                failures.append((rel, "backend_refused", str(err)))
                continue
            except VocabularyMissing as err:
                # OUR vocabulary is incomplete for a shape the backend
                # legitimately produced. THE finding this instrument exists
                # to surface.
                failures.append((rel, "vocabulary_missing", str(err)))
                continue
            except BackendDefect as err:
                # The backend (or its adapter) produced something
                # structurally invalid. Distinct from vocabulary_missing:
                # this is never fixed by adding vocabulary.
                failures.append((rel, "backend_defect", str(err)))
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


_BACKENDS = ("cpython-ast", "libcst", "parso", "tree-sitter-python")


def make_backend(name: Optional[str]) -> Optional[Backend]:
    """None / "cpython-ast" -> the default (CPython's ast). Otherwise
    construct the named backend by importing its adapter module lazily, so
    installing libcst is never a condition of running the corpus with the
    default backend."""
    if name is None or name == "cpython-ast":
        return None
    if name == "libcst":
        from .libcst_adapter import LibCSTBackend

        return LibCSTBackend()
    if name == "parso":
        from .parso_adapter import ParsoBackend

        return ParsoBackend()
    if name == "tree-sitter-python":
        from .tree_sitter_python_adapter import TreeSitterPythonBackend

        return TreeSitterPythonBackend()
    raise SystemExit(f"unknown --backend {name!r}; choices: {list(_BACKENDS)}")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--base", type=Path, default=None)
    parser.add_argument(
        "--backend",
        choices=list(_BACKENDS),
        default="cpython-ast",
        help="which Backend to run the corpus through (default: cpython-ast).",
    )
    args = parser.parse_args(argv)

    result = emit_corpus(
        args.paths, args.out, args.base, backend=make_backend(args.backend)
    )
    print(f"backend:  {args.backend}")
    print(f"files:    {result.files}")
    print(f"nodes:    {result.nodes}")
    print(f"kinds:    {len(result.kind_counts)}")
    print(f"manifest: {result.manifest_cid}")
    missing = [f for f in result.failures if f[1] == "vocabulary_missing"]
    defects = [f for f in result.failures if f[1] == "backend_defect"]
    other = [
        f
        for f in result.failures
        if f[1] not in ("vocabulary_missing", "backend_defect")
    ]
    for rel, failure_class, message in result.failures:
        print(f"FAIL[{failure_class}] {rel}: {message.splitlines()[0]}")
    print(f"vocabulary missing (our gaps): {len(missing)}")
    print(f"backend defects: {len(defects)}")
    print(f"backend refusals / undecodable: {len(other)}")
    return 1 if result.failures else 0


if __name__ == "__main__":
    sys.exit(main())
