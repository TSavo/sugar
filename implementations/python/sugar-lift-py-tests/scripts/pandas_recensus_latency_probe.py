#!/usr/bin/env python3
"""Single-file construction latency bisection for pandas recensus.

Enum path only:

    path_source → SourceFile → functions() → function.sugar()

Engine log (JSONL) is optional via SUGAR_ENGINE_LOG / --engine-log.
After run, prints top spans by elapsed_ms from the JSONL.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _analyze_engine_log(path: Path, top_n: int = 20) -> dict:
    """Summarize exit events by sugar/role and list top elapsed spans."""
    by_sugar: Counter[str] = Counter()
    by_role: Counter[str] = Counter()
    by_sugar_role: Counter[str] = Counter()
    event_counts: Counter[str] = Counter()
    exits: list[dict] = []
    heartbeats = 0
    errors = 0
    total_exit_ms = 0.0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        event = row.get("event")
        event_counts[event] += 1
        if event == "heartbeat":
            heartbeats += 1
            continue
        if event == "error":
            errors += 1
        if event not in {"exit", "error", "propagate"}:
            continue
        elapsed = float(row.get("elapsed_ms") or 0.0)
        sugar = row.get("sugar") or "?"
        role = row.get("role") or "?"
        by_sugar[sugar] += elapsed
        by_role[role] += elapsed
        by_sugar_role[f"{sugar}|{role}"] += elapsed
        total_exit_ms += elapsed
        exits.append(
            {
                "elapsed_ms": elapsed,
                "sugar": sugar,
                "role": role,
                "site": row.get("site"),
                "event": event,
                "error_type": row.get("error_type"),
            }
        )
    exits.sort(key=lambda r: r["elapsed_ms"], reverse=True)
    return {
        "logPath": str(path),
        "eventCounts": dict(event_counts.most_common()),
        "heartbeats": heartbeats,
        "errors": errors,
        "sumExitElapsedMs": round(total_exit_ms, 3),
        "note": "sumExitElapsedMs double-counts nested spans",
        "bySugarMs": {k: round(v, 3) for k, v in by_sugar.most_common(30)},
        "byRoleMs": {k: round(v, 3) for k, v in by_role.most_common(20)},
        "bySugarRoleMs": {
            k: round(v, 3) for k, v in by_sugar_role.most_common(30)
        },
        "topSpans": exits[:top_n],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--file",
        required=True,
        help="relative path under pandas root, e.g. core/arrays/categorical.py",
    )
    parser.add_argument("--corpus", type=Path, default=None)
    parser.add_argument(
        "--engine-log",
        type=Path,
        default=None,
        help="JSONL path (also sets SUGAR_ENGINE_LOG before imports that log)",
    )
    parser.add_argument(
        "--limit-functions",
        type=int,
        default=0,
        help="if >0, only first N functions",
    )
    parser.add_argument(
        "--skip-sugar",
        action="store_true",
        help="only measure SourceFile materialize + inventory",
    )
    parser.add_argument("--json", type=Path, default=None)
    parser.add_argument("--top-spans", type=int, default=20)
    args = parser.parse_args()

    if args.engine_log is not None:
        args.engine_log.parent.mkdir(parents=True, exist_ok=True)
        if args.engine_log.exists():
            args.engine_log.unlink()
        os.environ["SUGAR_ENGINE_LOG"] = str(args.engine_log.resolve())
        from sugar_lift_py_tests import engine_log

        engine_log._LIVE_HANDLER = None  # type: ignore[attr-defined]
        engine_log.configure_live_log(str(args.engine_log.resolve()))

    from sugar_lift_python_source.source_oracle import path_source
    from sugar_source_tree.nodes import With
    from sugar_source_tree.panic import SourceTreePanic, SugarNotWritten
    from sugar_source_tree.reporter import CollectingReporter
    from sugar_source_tree.tree import SourceFile

    if args.corpus is None:
        import pandas

        args.corpus = Path(pandas.__file__).resolve().parent

    path = (args.corpus / args.file).resolve()
    if not path.is_file():
        print(f"missing file: {path}", file=sys.stderr)
        return 2

    phases: dict[str, float] = {}
    t0 = time.perf_counter()
    reporter = CollectingReporter()
    source_file = SourceFile(path_source(str(path)), reporter=reporter)
    phases["source_file_s"] = time.perf_counter() - t0

    t = time.perf_counter()
    with_items = 0
    for node in source_file.nodes():
        if isinstance(node, With):
            with_items += sum(1 for _ in node.items)
    phases["with_inventory_s"] = time.perf_counter() - t

    fn_times: list[dict] = []
    clean = 0
    panics = 0
    not_written = 0
    functions = list(source_file.functions())
    if args.limit_functions > 0:
        functions = functions[: args.limit_functions]

    if not args.skip_sugar:
        t_all = time.perf_counter()
        for function in functions:
            name = getattr(function, "name", "?")
            lc = function.line_col_span()
            tf = time.perf_counter()
            status = "clean"
            try:
                function.sugar()
                clean += 1
            except SugarNotWritten:
                not_written += 1
                status = "SugarNotWritten"
            except SourceTreePanic:
                panics += 1
                status = "SourceTreePanic"
            except Exception as exc:  # noqa: BLE001 -- latency probe
                panics += 1
                status = type(exc).__name__
            fn_times.append(
                {
                    "name": name,
                    "line": lc.start_line,
                    "elapsed_s": round(time.perf_counter() - tf, 6),
                    "status": status,
                }
            )
        phases["all_functions_sugar_s"] = time.perf_counter() - t_all

    report = {
        "file": args.file,
        "path": str(path),
        "phases": {k: round(v, 6) for k, v in phases.items()},
        "withItems": with_items,
        "functionCount": len(functions),
        "clean": clean,
        "notWritten": not_written,
        "panics": panics,
        "functions": sorted(fn_times, key=lambda r: r["elapsed_s"], reverse=True)[
            : args.top_spans
        ],
    }
    if args.engine_log is not None and args.engine_log.is_file():
        report["engineLog"] = _analyze_engine_log(args.engine_log, args.top_spans)

    text = json.dumps(report, indent=2)
    print(text)
    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
