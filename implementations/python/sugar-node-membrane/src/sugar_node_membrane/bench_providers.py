"""Provider bench harness (#5940, #5932): correctness first, speed second.

Two independent passes, never conflated:

1. CORRECTNESS — parse + construct every file in the corpus. Record parse
   failures (provider refused: SyntaxError), membrane panics (a shape with
   no class: MembranePanic), and any other crash verbatim. Not load
   sensitive; safe to run on a busy host.

2. THROUGHPUT — pure parse time and parse+construct time, files/second.
   Load-sensitive: the caller is responsible for only trusting numbers
   taken with the host quiet (see the ``--require-quiet`` flag, which
   blocks until 1-minute load average is under the given threshold and
   prints load before and after the timed run).

No cross-provider CID comparison here — that instrument is
``differential.py`` and is explicitly out of scope for this harness
(different parsers build different trees; matching CIDs across providers
is not a criterion, per #5940/#5932).

CLI::

    python -m sugar_node_membrane.bench_providers PATH [PATH ...] \\
        --provider cpython-ast|libcst|parso|tree-sitter-python \\
        [--require-quiet 5] [--limit N]
"""

from __future__ import annotations

import argparse
import sys
import time
import traceback
from pathlib import Path
from typing import Optional

from .construct import Membrane
from .panic import MembranePanic


def _load1() -> Optional[float]:
    try:
        with open("/proc/loadavg") as f:
            return float(f.read().split()[0])
    except Exception:
        return None


def _provider(name: str):
    if name == "cpython-ast":
        from .cpython_adapter import CPythonAstProvider
        return CPythonAstProvider()
    if name == "libcst":
        from .libcst_adapter import LibCSTProvider
        return LibCSTProvider()
    if name == "parso":
        from .parso_adapter import ParsoProvider
        return ParsoProvider()
    if name == "tree-sitter-python":
        from .tree_sitter_python_adapter import TreeSitterPythonProvider
        return TreeSitterPythonProvider()
    raise SystemExit(f"unknown provider {name!r}")


def collect_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for p in paths:
        if p.is_dir():
            files.extend(sorted(p.rglob("*.py")))
        else:
            files.append(p)
    files.sort()
    return files


def run_correctness(provider_name: str, files: list[Path], base: Optional[Path]) -> int:
    provider = _provider(provider_name)
    membrane = Membrane(provider)
    parsed = 0
    parse_failures: list[tuple[str, str]] = []
    panics: list[tuple[str, str]] = []
    crashes: list[tuple[str, str]] = []
    for path in files:
        rel = str(path.relative_to(base)) if base is not None else str(path)
        try:
            source = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as err:
            parse_failures.append((rel, f"undecodable: {err}"))
            continue
        try:
            membrane.parse(source, filename=rel)
            parsed += 1
        except SyntaxError as err:
            parse_failures.append((rel, str(err).splitlines()[0]))
        except MembranePanic as err:
            panics.append((rel, " | ".join(str(err).splitlines())))
        except Exception as err:  # noqa: BLE001 - a crash IS a result here
            crashes.append((rel, f"{type(err).__name__}: {err}"))

    print(f"provider:        {provider_name}")
    print(f"files:           {len(files)}")
    print(f"constructed:     {parsed}")
    print(f"parse failures:  {len(parse_failures)}")
    for rel, msg in parse_failures:
        print(f"  PARSE_FAIL  {rel}: {msg}")
    print(f"membrane panics: {len(panics)}")
    for rel, msg in panics:
        print(f"  PANIC       {rel}: {msg}")
    print(f"other crashes:   {len(crashes)}")
    for rel, msg in crashes:
        print(f"  CRASH       {rel}: {msg}")
    return 1 if crashes else 0


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


def run_throughput(provider_name: str, files: list[Path], limit: Optional[int]) -> None:
    if limit is not None:
        files = files[:limit]
    provider = _provider(provider_name)

    sources: list[tuple[Path, str]] = []
    for path in files:
        try:
            sources.append((path, path.read_text(encoding="utf-8")))
        except UnicodeDecodeError:
            continue

    load_start = _load1()
    t0 = time.perf_counter()
    parsed_handles = 0
    for _, source in sources:
        try:
            provider.parse.__self__  # no-op; keeps provider warm
        except Exception:
            pass
    for _, source in sources:
        try:
            from .nodes import SourceUnit
            unit = SourceUnit(filename="<bench>", source=source)
            provider.parse(unit)
            parsed_handles += 1
        except Exception:
            continue
    t_parse = time.perf_counter() - t0

    membrane = Membrane(_provider(provider_name))
    t1 = time.perf_counter()
    constructed = 0
    for path, source in sources:
        try:
            membrane.parse(source, filename=str(path))
            constructed += 1
        except Exception:
            continue
    t_construct_total = time.perf_counter() - t1
    load_end = _load1()

    n = len(sources)
    print(f"provider:              {provider_name}")
    print(f"files timed:           {n}")
    print(f"host load (1min) start: {load_start}")
    print(f"host load (1min) end:   {load_end}")
    print(f"pure parse:            {t_parse:.3f}s  ({n / t_parse if t_parse else float('inf'):.1f} files/s)  [{parsed_handles} ok]")
    print(f"parse+construct:       {t_construct_total:.3f}s  ({n / t_construct_total if t_construct_total else float('inf'):.1f} files/s)  [{constructed} ok]")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("paths", nargs="+", type=Path)
    ap.add_argument("--provider", required=True)
    ap.add_argument("--base", type=Path, default=None)
    ap.add_argument("--mode", choices=["correctness", "throughput"], default="correctness")
    ap.add_argument("--require-quiet", type=float, default=None)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args(argv)

    files = collect_files(args.paths)
    if args.mode == "correctness":
        return run_correctness(args.provider, files, args.base)
    if args.require_quiet is not None:
        _require_quiet(args.require_quiet)
    run_throughput(args.provider, files, args.limit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
