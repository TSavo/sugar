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

Failures are LOUD: a MembraneMissing (our vocabulary is incomplete for a
shape the provider legitimately produced), a MembraneProviderDefect (the
provider or its adapter produced something structurally invalid), or a
provider refusal (ProviderRefused, backend.py — the provider's own
two-arm outcome, never its native exception type) on any file is
recorded, reported, and fails the run. None of the three ever becomes
silence.

The provider is a parameter, not a source edit: default is today's
behaviour (CPythonAstProvider), but any Provider — including LibCST's
— can be threaded through from the CLI (--provider) or from code,
so a benchmark can run the same corpus through more than one adapter
without monkeypatching this module.

CLI:
    python -m sugar_node_membrane.corpus --out corpus.jsonl PATH [PATH ...]
    python -m sugar_node_membrane.corpus --provider libcst PATH [PATH ...]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

from .backend import Provider, ProviderRefused
from .construct import Membrane
from .nodes import SourceFragment
from .panic import MembraneMissing, MembraneProviderDefect


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
    paths: list[Path],
    out_path: Optional[Path],
    base: Optional[Path] = None,
    provider: Optional[Provider] = None,
) -> CorpusResult:
    """provider defaults to Membrane()'s own default
    (CPythonAstProvider) — today's behaviour, unchanged. Pass any other
    Provider (e.g. LibCSTProvider() from libcst_adapter.py) to
    run the same corpus through it; this is the ONLY thing that should ever
    change which provider a corpus run measures — never a monkeypatch."""
    files: list[Path] = []
    for p in paths:
        if p.is_dir():
            files.extend(sorted(p.rglob("*.py")))
        else:
            files.append(p)
    files.sort()

    membrane = Membrane(provider)
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
            except ProviderRefused as err:
                # The PROVIDER refused the file (not valid input for it).
                # Recorded loudly; distinct from a membrane MISSING. Never
                # the provider's native exception type (#5946) — the
                # membrane's own contract type, so this catch works
                # identically no matter which provider is installed.
                failures.append((rel, "provider_refused", str(err)))
                continue
            except MembraneMissing as err:
                # OUR vocabulary is incomplete for a shape the provider
                # legitimately produced. THE finding this instrument exists
                # to surface.
                failures.append((rel, "membrane_missing", str(err)))
                continue
            except MembraneProviderDefect as err:
                # The provider (or its adapter) produced something
                # structurally invalid. Distinct from membrane_missing:
                # this is never fixed by adding vocabulary.
                failures.append((rel, "membrane_provider_defect", str(err)))
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


_PROVIDERS: dict[str, str] = {
    "cpython": "CPythonAstProvider",
    "libcst": "LibCSTProvider",
}


def _make_provider(name: Optional[str]) -> Optional[Provider]:
    """None -> Membrane()'s own default (today's behaviour,
    unchanged). Otherwise construct the named provider by importing its
    adapter module lazily, so installing libcst is never a condition of
    running the corpus with the default provider."""
    if name is None or name == "cpython":
        return None
    if name == "libcst":
        from .libcst_adapter import LibCSTProvider

        return LibCSTProvider()
    raise SystemExit(
        f"unknown --provider {name!r}; choices: {sorted(_PROVIDERS)}"
    )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--base", type=Path, default=None)
    parser.add_argument(
        "--provider",
        choices=sorted(_PROVIDERS),
        default="cpython",
        help="which Provider to run the corpus through (default: cpython, "
        "today's unchanged behaviour). 'libcst' requires the libcst "
        "extra installed.",
    )
    args = parser.parse_args(argv)

    result = emit_corpus(
        args.paths, args.out, args.base, provider=_make_provider(args.provider)
    )
    print(f"provider: {args.provider}")
    print(f"files:    {result.files}")
    print(f"nodes:    {result.nodes}")
    print(f"kinds:    {len(result.kind_counts)}")
    print(f"manifest: {result.manifest_cid}")
    membrane_missing = [f for f in result.failures if f[1] == "membrane_missing"]
    provider_defects = [
        f for f in result.failures if f[1] == "membrane_provider_defect"
    ]
    other = [
        f
        for f in result.failures
        if f[1] not in ("membrane_missing", "membrane_provider_defect")
    ]
    for rel, failure_class, message in result.failures:
        print(f"FAIL[{failure_class}] {rel}: {message.splitlines()[0]}")
    print(f"membrane missing (vocabulary gaps): {len(membrane_missing)}")
    print(f"membrane provider defects: {len(provider_defects)}")
    print(f"provider refusals / undecodable: {len(other)}")
    return 1 if result.failures else 0


if __name__ == "__main__":
    sys.exit(main())
