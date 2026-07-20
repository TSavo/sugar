"""Backend bench harness (#5940, #5932): correctness first, speed second.

Three independent passes, never conflated:

1. CORRECTNESS — enumerate a SourceTree: every file becomes a SourceFile,
   every SourceFile enumerates its nodes. Record backend refusals
   (BackendRefused), panics (VocabularyMissing / BackendDefect), and any
   other crash verbatim. Not load sensitive; safe to run on a busy host.

2. RSS — same enumeration, printing ru_maxrss at file-count checkpoints.
   Because nothing retains a SourceFile after the loop lets go of it,
   peak RSS must plateau: it is bounded by the largest file, not the
   corpus. A curve that keeps climbing is a retention bug.

3. THROUGHPUT — files/second for the full enumerate-every-node pass.
   Load-sensitive: only trust numbers taken with the host quiet
   (``--require-quiet``).

CLI::

    python -m sugar_source_tree.bench_backends PATH [PATH ...] \\
        --backend cpython-ast|libcst|parso|tree-sitter-python \\
        [--mode correctness|rss|throughput] [--require-quiet 5]
"""

from __future__ import annotations

import argparse
import resource
import sys
import time
from pathlib import Path
from typing import Optional

from sugar_lift_python_source.source_oracle import SourceOracleRefusal, path_source

from .backend import BackendRefused
from .corpus import make_backend
from .panic import SourceTreePanic
from .tree import SourceFile, SourceTree


def _load1() -> Optional[float]:
    try:
        with open("/proc/loadavg") as f:
            return float(f.read().split()[0])
    except Exception:
        return None


def _maxrss_mib() -> float:
    ru = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # Linux reports KiB, macOS bytes.
    return ru / 1024 if sys.platform.startswith("linux") else ru / (1024 * 1024)


def run_correctness(backend_name: str, root: Path, rss: bool = False) -> int:
    tree = SourceTree(root, backend=make_backend(backend_name))
    parsed = 0
    node_count = 0
    refused: list[tuple[str, str]] = []
    panics: list[tuple[str, str]] = []
    crashes: list[tuple[str, str]] = []
    checkpoint = 0
    total = 0
    for path in tree.paths():
        total += 1
        rel = str(path)
        try:
            identity = path_source(rel)
        except SourceOracleRefusal as err:
            refused.append((rel, f"oracle refused: {err}"))
            continue
        try:
            file = SourceFile(identity, backend=tree.backend)
            for _node in file.nodes():
                node_count += 1
            parsed += 1
        except BackendRefused as err:
            refused.append((rel, str(err).splitlines()[0]))
        except SourceTreePanic as err:
            panics.append((rel, " | ".join(str(err).splitlines())))
        except Exception as err:  # noqa: BLE001 - a crash IS a result here
            crashes.append((rel, f"{type(err).__name__}: {err}"))
        if rss and total - checkpoint >= 200:
            checkpoint = total
            print(f"  rss after {total:5d} files: {_maxrss_mib():8.1f} MiB")

    print(f"backend:          {backend_name}")
    print(f"files:            {total}")
    print(f"constructed:      {parsed}")
    print(f"nodes enumerated: {node_count}")
    print(f"backend refusals: {len(refused)}")
    for rel, msg in refused:
        print(f"  REFUSED  {rel}: {msg}")
    print(f"panics:           {len(panics)}")
    for rel, msg in panics:
        print(f"  PANIC    {rel}: {msg}")
    print(f"other crashes:    {len(crashes)}")
    for rel, msg in crashes:
        print(f"  CRASH    {rel}: {msg}")
    if rss:
        print(f"peak rss:         {_maxrss_mib():.1f} MiB")
    return 1 if (crashes or panics) else 0


def _require_quiet(threshold: float) -> None:
    load = _load1()
    if load is None:
        return
    waited = False
    while load is not None and load >= threshold:
        waited = True
        time.sleep(30)
        load = _load1()
    tag = "(waited)" if waited else "(already quiet)"
    print(f"host 1-min load at start: {load} {tag}")


def run_throughput(backend_name: str, root: Path, limit: Optional[int]) -> None:
    tree = SourceTree(root, backend=make_backend(backend_name))
    paths = list(tree.paths())
    if limit is not None:
        paths = paths[:limit]
    identities: list[tuple[str, str, str]] = []
    for path in paths:
        try:
            identities.append(path_source(str(path)))
        except SourceOracleRefusal:
            continue

    load_start = _load1()
    t0 = time.perf_counter()
    constructed = 0
    nodes = 0
    for identity in identities:
        try:
            file = SourceFile(identity, backend=tree.backend)
            for _n in file.nodes():
                nodes += 1
            constructed += 1
        except Exception:
            continue
    dt = time.perf_counter() - t0
    load_end = _load1()

    n = len(identities)
    print(f"backend:                {backend_name}")
    print(f"files timed:            {n}")
    print(f"host load (1min) start: {load_start}")
    print(f"host load (1min) end:   {load_end}")
    print(
        f"construct+enumerate:    {dt:.3f}s  "
        f"({n / dt if dt else float('inf'):.1f} files/s)  "
        f"[{constructed} ok, {nodes} nodes]"
    )


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("path", type=Path)
    ap.add_argument("--backend", required=True)
    ap.add_argument(
        "--mode", choices=["correctness", "rss", "throughput"], default="correctness"
    )
    ap.add_argument("--require-quiet", type=float, default=None)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args(argv)

    if args.mode in ("correctness", "rss"):
        return run_correctness(args.backend, args.path, rss=args.mode == "rss")
    if args.require_quiet is not None:
        _require_quiet(args.require_quiet)
    run_throughput(args.backend, args.path, args.limit)
    return 0

if __name__ == "__main__":
    sys.exit(main())
