#!/usr/bin/env python3
"""Single-file construction latency bisection for pandas recensus.

Phases:
  1. production_source_file (preconstruction + SourceFile materialize)
  2. With inventory walk
  3. per-function function.sugar()

Engine log (JSONL) is optional via SUGAR_ENGINE_LOG / --engine-log.
After run, prints top spans by elapsed_ms from the JSONL.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from _production_source_file import production_source_file  # noqa: E402


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
    # Nested child time is double-counted if we sum all exits; also report
    # root-ish sugars of interest.
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
        help="only measure production_source_file + inventory",
    )
    parser.add_argument(
        "--phase-preconstruction",
        action="store_true",
        help="time SourceFile vs populate_* separately",
    )
    parser.add_argument("--json", type=Path, default=None)
    parser.add_argument("--top-spans", type=int, default=20)
    args = parser.parse_args()

    if args.engine_log is not None:
        args.engine_log.parent.mkdir(parents=True, exist_ok=True)
        if args.engine_log.exists():
            args.engine_log.unlink()
        os.environ["SUGAR_ENGINE_LOG"] = str(args.engine_log.resolve())
        # Re-configure after env is set (module may have already run configure).
        from sugar_lift_py_tests import engine_log

        engine_log._LIVE_HANDLER = None  # type: ignore[attr-defined]
        engine_log.configure_live_log(str(args.engine_log.resolve()))

    from sugar_source_tree.nodes import With
    from sugar_source_tree.panic import SourceTreePanic, SugarNotWritten
    from sugar_source_tree.reporter import CollectingReporter

    if args.corpus is None:
        import pandas

        args.corpus = Path(pandas.__file__).resolve().parent

    path = (args.corpus / args.file).resolve()
    if not path.is_file():
        print(f"missing file: {path}", file=sys.stderr)
        return 2

    package_distributions = importlib.metadata.packages_distributions()
    distribution_index = {
        package: importlib.metadata.distribution(distributions[0])
        for package, distributions in package_distributions.items()
        if len(distributions) == 1
    }
    artifact_graph_cache: dict = {}

    phases: dict[str, float] = {}
    t0 = time.perf_counter()

    if args.phase_preconstruction:
        from sugar_lift_py_tests.context_manager_resolution import (
            TreeConstructionContextV1,
        )
        from sugar_lift_python_source.manager_summary_derivation import (
            populate_source_derived_resource_refs,
        )
        from sugar_lift_python_source.source_call_preconstruction import (
            populate_source_visible_call_frames,
        )
        from sugar_lift_python_source.source_oracle import path_source
        from sugar_source_tree.tree import SourceFile
        from _production_source_file import _install_unresolved_source_derived_gaps

        reporter = CollectingReporter()
        t = time.perf_counter()
        context = TreeConstructionContextV1.for_source_call_construction(
            workspace_root=str(args.corpus)
        )
        source_file = SourceFile(
            path_source(str(path)), reporter=reporter, construction_context=context
        )
        phases["source_file_materialize_s"] = time.perf_counter() - t

        t = time.perf_counter()
        populate_source_visible_call_frames(
            source_file,
            root=args.corpus,
            path=path,
            distribution_index=distribution_index,
            artifact_graph_cache=artifact_graph_cache,
        )
        phases["populate_source_visible_call_frames_s"] = time.perf_counter() - t

        t = time.perf_counter()
        populate_source_derived_resource_refs(
            source_file,
            root=args.corpus,
            path=path,
            distribution_index=distribution_index,
            artifact_graph_cache=artifact_graph_cache,
        )
        phases["populate_source_derived_resource_refs_s"] = time.perf_counter() - t

        t = time.perf_counter()
        _install_unresolved_source_derived_gaps(source_file)
        phases["install_unresolved_gaps_s"] = time.perf_counter() - t
        phases["production_source_file_s"] = time.perf_counter() - t0
    else:
        reporter = CollectingReporter()
        source_file = production_source_file(
            path,
            root=args.corpus,
            reporter=reporter,
            distribution_index=distribution_index,
            artifact_graph_cache=artifact_graph_cache,
        )
        phases["production_source_file_s"] = time.perf_counter() - t0

    t = time.perf_counter()
    with_items = 0
    for node in source_file.nodes():
        if isinstance(node, With):
            with_items += sum(1 for _ in node.items)
    phases["with_inventory_s"] = time.perf_counter() - t

    # Cache contents after first file
    cache_keys = sorted(str(k) for k in artifact_graph_cache.keys())

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
            except SourceTreePanic as panic:
                panics += 1
                status = type(panic).__name__
            except Exception as exc:  # noqa: BLE001
                panics += 1
                status = type(exc).__name__
            fn_times.append(
                {
                    "name": name,
                    "line": lc.start_line,
                    "elapsed_ms": round((time.perf_counter() - tf) * 1000, 3),
                    "status": status,
                }
            )
        phases["all_function_sugar_s"] = time.perf_counter() - t_all

    phases["total_s"] = time.perf_counter() - t0
    fn_times_sorted = sorted(fn_times, key=lambda r: r["elapsed_ms"], reverse=True)

    result = {
        "kind": "pandas-recensus-latency-probe-v1",
        "file": args.file,
        "path": str(path),
        "phasesSeconds": {k: round(v, 4) for k, v in phases.items()},
        "withItems": with_items,
        "functionsTotal": len(functions),
        "functionsClean": clean,
        "functionsNotWritten": not_written,
        "functionsPanic": panics,
        "reporterGaps": len(reporter.gaps),
        "artifactGraphCacheKeys": cache_keys,
        "topFunctionsByMs": fn_times_sorted[:30],
        "functionMsSum": round(sum(r["elapsed_ms"] for r in fn_times), 3),
        "functionMsMax": fn_times_sorted[0]["elapsed_ms"] if fn_times_sorted else 0,
        "functionMsMedian": (
            sorted(r["elapsed_ms"] for r in fn_times)[len(fn_times) // 2]
            if fn_times
            else 0
        ),
        "engineLog": None,
    }

    if args.engine_log is not None and args.engine_log.exists():
        result["engineLog"] = _analyze_engine_log(args.engine_log, args.top_spans)
        result["engineLogBytes"] = args.engine_log.stat().st_size

    rendered = json.dumps(result, indent=2, sort_keys=True)
    print(rendered, flush=True)
    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(rendered + "\n", encoding="utf-8")
        print(f"wrote {args.json}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
