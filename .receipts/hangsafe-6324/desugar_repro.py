#!/usr/bin/env python3
"""Bounded four-axis pandas reproducer: construct AND desugar, per-file SIGALRM.

Same per-file body as the census's `full_dump.py` (open for construction ->
`fn.sugar()` -> `DesugarAxis.measure`) and the same shared contract-ref table,
so the measured path is the census's path. The one addition is the census's
missing piece: a hard per-file wall deadline, so the first file that crosses is
NAMED with its live stack instead of taking the whole run down.

The desugar half is load-bearing. The #6293/#6296 floor arms only execute
during `DesugarAxis.measure`; a construction-only sweep cannot see them and
will report a false zero.

Counters come from `profile_child.install_counters` so wall time is never the
sole evidence: equality/richcompare counts, contains counts, unique
authenticated operand pairs, node construction and intern counts all travel
with every timing.
"""

from __future__ import annotations

import argparse
import faulthandler
import json
import signal
import sys
import time
import traceback
from collections import Counter
from pathlib import Path


class FileTimeout(BaseException):
    pass


# The stack must be captured IN the handler, from the interrupted frame. Taking
# it in the `except` block reports the unwound handler frame and names nothing.
ALARM_STACK: list[str] = []


def _alarm(signum, frame):
    ALARM_STACK.clear()
    ALARM_STACK.append("".join(traceback.format_stack(frame)))
    raise FileTimeout("file wall budget")


def measure_file(root: Path, rel: str, shared_refs) -> dict:
    from sugar_lift_py_tests.desugar_axis import DesugarAxis
    from sugar_lift_py_tests.lift_rpc import (
        open_source_file_for_construction,
        tree_construction_context_for_workspace,
    )
    from sugar_source_tree.panic import SugarNotWritten
    from sugar_source_tree.reporter import CollectingReporter

    desugar = DesugarAxis()
    reporter = CollectingReporter()
    sf = open_source_file_for_construction(
        root / rel,
        root=root,
        reporter=reporter,
        construction_context=tree_construction_context_for_workspace(
            root, contract_refs=shared_refs
        ),
        populate_derived=True,
    )
    live = {"function": None, "phase": "open"}
    for fn in sf.functions():
        try:
            span = fn.line_col_span()
            where = f"{rel}:{span.start_line}:{span.start_col}"
        except Exception:
            where = f"{rel}:?"
        live["function"] = where
        live["phase"] = "construct"
        try:
            sugar = fn.sugar()
        except SugarNotWritten:
            sugar = None
        if sugar is not None:
            live["phase"] = "desugar"
            desugar.measure(sugar, where=where)
    row = desugar.row()
    families: Counter = Counter()
    seen = set()
    for node, _p in reporter.gaps:
        lc = node.line_col_span()
        key = (node.kind, lc.start_line, lc.start_col)
        if key not in seen:
            seen.add(key)
            families[node.kind] += 1
    return {
        "R_construction": sum(families.values()),
        "R_desugar": row["R_desugar"],
        "panics": len(row["desugarConstructionPanics"]),
        "defects": len(row["desugarDefects"]),
    }


# The live locus is written into this module-level dict by `measure_file`'s
# closure so the SIGALRM handler's report can name the function under the axe.
LIVE: dict = {}


def timeout_residual(rows: list[dict]) -> int:
    """Count files whose authenticated reproducer outcome is timeout."""
    return sum(row.get("outcome") == "timeout" for row in rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="/usr/local/lib/python3.14/site-packages/pandas")
    ap.add_argument("--out", required=True)
    ap.add_argument("--deadline", type=float, default=180.0)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", default=None)
    ap.add_argument("--counters", action="store_true")
    ap.add_argument("--profile", action="store_true",
                    help="cProfile each measured file (mechanism pass only)")
    ap.add_argument("--hot-counters", action="store_true",
                    help="also wrap the innermost IR seats (slow; mechanism pass only)")
    ap.add_argument("--stop-on-first-hang", action=argparse.BooleanOptionalAction, default=True)
    ap.add_argument("--label", default="")
    args = ap.parse_args()

    faulthandler.enable()
    sys.setrecursionlimit(100000)
    sys.path.insert(0, str(Path(__file__).resolve().parent))

    counts = pair_content = None
    if args.counters:
        import profile_child

        profile_child.install_counters(hot=args.hot_counters)
        counts = profile_child.COUNTS
        pair_content = profile_child.PAIR_CONTENT

    root = Path(args.root)
    files = sorted(str(p.relative_to(root)) for p in root.rglob("*.py"))
    from sugar_lift_py_tests.lift_rpc import tree_construction_context_for_workspace

    t_table = time.time()
    print(f"shared contract-ref table over {len(files)} files…", flush=True)
    shared_refs = tree_construction_context_for_workspace(root).contract_refs
    table_seconds = time.time() - t_table
    print(f"shared table ready in {table_seconds:.0f}s", flush=True)

    if args.only:
        selected = [(files.index(one), one) for one in args.only.split(",")]
    else:
        selected = list(enumerate(files))[args.start:]
        if args.limit:
            selected = selected[: args.limit]

    def snapshot() -> dict:
        if counts is None:
            return {}
        eq = sum(
            counts.get(f"ir._{kind}.__eq__", 0)
            for kind in ("Atomic", "Connective", "Quantifier")
        )
        hsh = sum(
            counts.get(f"ir._{kind}.__hash__", 0)
            for kind in ("Atomic", "Connective", "Quantifier")
        )
        return {
            "formula_eq": eq,
            "formula_hash": hsh,
            "formula_content_key": counts.get("ir._formula_content_key", 0),
            "formula_intern_key": counts.get("ir._formula_intern_key", 0),
            "term_content_cid": counts.get("ir._term_content_cid", 0),
            "intern_term": counts.get("ir._intern_term", 0),
            "atomic": counts.get("ir.atomic", 0),
            "contains": counts.get("contains.total", 0),
            "guarded_built": counts.get("GuardedValue.__init__", 0),
            "guarded_max_depth": counts.get("GuardedValue.max_depth", 0),
            "guarded_map": counts.get("GuardedValue._map", 0),
            "guarded_predicate": counts.get("GuardedValue._predicate", 0),
            "guarded_attribute": counts.get("GuardedValue.attribute", 0),
            "exitset_normalize_calls": counts.get("exitset.normalize_calls", 0),
            "exitset_arms_in_sum": counts.get("exitset.arms_in_sum", 0),
            "exitset_arms_in_max": counts.get("exitset.arms_in_max", 0),
            "exitset_arms_out_sum": counts.get("exitset.arms_out_sum", 0),
            "exitset_arms_out_max": counts.get("exitset.arms_out_max", 0),
            "exitset_pairwise_upper_bound": counts.get("exitset.pairwise_upper_bound", 0),
            "distinct_formula_objects": len(
                profile_child.DISTINCT.get("formula_content_key", ())
            ),
            "unique_operand_pairs_by_content": len(pair_content),
        }

    profiler = None
    if args.profile:
        import cProfile

        profiler = cProfile.Profile()

    rows: list[dict] = []
    hung: list[str] = []
    signal.signal(signal.SIGALRM, _alarm)
    t0 = time.time()
    for index, rel in selected:
        before = snapshot()
        started = time.time()
        signal.setitimer(signal.ITIMER_REAL, args.deadline)
        row: dict = {"index": index, "file": rel}
        try:
            if profiler is not None:
                profiler.enable()
            row.update(measure_file(root, rel, shared_refs))
            row["outcome"] = "measured"
        except FileTimeout:
            row["outcome"] = "timeout"
            row["stack"] = (ALARM_STACK[0] if ALARM_STACK else "")[-16000:]
        except BaseException as error:
            row["outcome"] = f"raised:{type(error).__name__}"
            row["error"] = str(error)[:800]
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            if profiler is not None:
                profiler.disable()
        row["wall_seconds"] = round(time.time() - started, 3)
        if profiler is not None:
            import pstats
            from io import StringIO

            buffer = StringIO()
            stats = pstats.Stats(profiler, stream=buffer)
            stats.sort_stats("tottime").print_stats(30)
            buffer.write("\n===== CALLERS OF THE HOT SEATS =====\n")
            stats.print_callers("_formula_content_key|_term_content_cid|__eq__|__hash__")
            row["profile"] = buffer.getvalue()
            profiler.clear()
        after = snapshot()
        row["counters_delta"] = {
            key: after[key] - before[key] for key in after
        }
        row["counters_total"] = after
        rows.append(row)
        print(
            f"[{index:5d}] {row['wall_seconds']:8.2f}s {row['outcome']:>12} {rel} "
            + json.dumps(row.get("counters_delta", {})),
            flush=True,
        )
        if row["outcome"] == "timeout":
            hung.append(rel)
            print(f"FIRST TIMEOUT index={index} file={rel} deadline={args.deadline}s", flush=True)
            print(row["stack"][-4000:], flush=True)
            if args.stop_on_first_hang:
                break

    r_timeout = timeout_residual(rows)
    payload = {
        "R(timeout)": r_timeout,
        "arm_histogram": (
            {k: v for k, v in sorted(counts.items()) if k.startswith("exitset.band_")}
            if counts is not None
            else {}
        ),
        "arm_construction_sites": (
            profile_child.ARM_STACKS if args.counters else []
        ),
        "label": args.label,
        "root": str(root),
        "deadline_seconds": args.deadline,
        "shared_table_seconds": round(table_seconds, 1),
        "wall_seconds": round(time.time() - t0, 1),
        "files_measured": len(rows),
        "hung_files": hung,
        "rows": rows,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(
        f"DONE R(timeout)={r_timeout} measured={len(rows)} out={args.out}",
        flush=True,
    )
    return 1 if r_timeout else 0


if __name__ == "__main__":
    raise SystemExit(main())
