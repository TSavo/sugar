"""The corpus census: construction axis + desugar-layer axis (#6243).

    python -m sugar_lift_py_tests.census <package-root> [--engine-log PATH]

Two named axes (never merged into one R):

1. **Construction** — ``fn.sugar()`` gaps, deduped by (node.kind, line, col).
2. **Desugar** — ``sugar.desugar(None)`` refusals and typed red effects,
   deduped by (owner, authenticated effect-occurrence coordinate).

Yield/YieldFrom construct then refuse at desugar: construction-total, still
on the board under R_desugar.

Behind the desugar door, ``ConstructionPanic`` (a ``BaseException``) and
ordinary exceptions are counted SEPARATELY from semantic R and make the run
red — see :mod:`sugar_lift_py_tests.desugar_axis`, which owns the membrane for
this module and for ``scripts/control_effect_recensus.py`` alike.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from pathlib import Path


def census(root: Path) -> int:
    from sugar_lift_py_tests.desugar_axis import DesugarAxis
    from sugar_lift_py_tests.gap.panic import ConstructionPanic
    from sugar_source_tree.panic import SugarNotWritten
    from sugar_source_tree.reporter import CollectingReporter
    from sugar_source_tree.tree import SourceFile

    files = sorted(root.rglob("*.py"))
    families: Counter = Counter()
    desugar = DesugarAxis()
    crashes: Counter = Counter()
    clean_files = 0
    total_fns = 0
    clean_fns = 0
    t0 = time.time()
    for i, f in enumerate(files):
        ft = time.time()
        rel = str(f.relative_to(root))
        try:
            reporter = CollectingReporter()
            sf = SourceFile.from_path(str(f), reporter=reporter)
            for fn in sf.functions():
                total_fns += 1
                try:
                    span = fn.line_col_span()
                    where = f"{rel}:{span.start_line}:{span.start_col}"
                except Exception:  # noqa: BLE001
                    where = f"{rel}:?"
                try:
                    sugar = fn.sugar()  # ONE construction; nested gaps self-report
                    clean_fns += 1
                except SugarNotWritten:
                    sugar = None
                if sugar is not None:
                    desugar.measure(sugar, where=where)
            seen = set()
            for node, _p in reporter.gaps:
                lc = node.line_col_span()
                key = (node.kind, lc.start_line, lc.start_col)
                if key not in seen:
                    seen.add(key)
                    families[node.kind] += 1
            if not reporter.gaps:
                clean_files += 1
            print(
                f"[{i + 1}/{len(files)}] {time.time() - ft:5.1f}s "
                f"gaps={len(reporter.gaps):5d} "
                f"desugar={sum(desugar.families.values()):5d} {rel}",
                flush=True,
            )
        except ConstructionPanic as panic:
            # A BaseException: `except Exception` below cannot see it, and an
            # uncaught one aborts the whole run. Named arm, red row, keep going.
            crashes[f"ConstructionPanic:{panic.info.owner}"] += 1
            print(
                f"[{i + 1}/{len(files)}]  CONSTRUCTION PANIC "
                f"{panic.info.owner} {rel}",
                flush=True,
            )
        except Exception as e:  # a crash is a DEFECT row, never silence
            crashes[type(e).__name__] += 1
            print(
                f"[{i + 1}/{len(files)}]  CRASH {type(e).__name__} {rel}",
                flush=True,
            )

    print(
        f"\n=== census: {len(files)} files ({clean_files} clean), "
        f"{total_fns} functions ({clean_fns} construct clean), "
        f"{time.time() - t0:.0f}s ===",
        flush=True,
    )
    print("--- construction gap families (top 40, deduped by source site) ---")
    print(f"R_construction = {sum(families.values())}")
    for kind, n in families.most_common(40):
        print(f"{n:8d}  {kind}")
    print("--- desugar families (top 40, deduped by owner+effect occurrence) ---")
    print(f"R_desugar = {sum(desugar.families.values())}")
    for kind, n in desugar.families.most_common(40):
        print(f"{n:8d}  {kind}")
    print("--- desugar construction panics (construction law, NOT R_desugar) ---")
    print(f"desugarConstructionPanics = {len(desugar.construction_panics)}")
    for panic in desugar.construction_panics[:40]:
        print(f"          {panic['owner']}  @{panic['where']}")
    print("--- desugar defects (implementation/audit, NOT R_desugar) ---")
    print(f"desugarDefects = {len(desugar.defects)}")
    for kind, n in Counter(
        f"{row['kind']}:{row['detail']}" for row in desugar.defects
    ).most_common(40):
        print(f"{n:8d}  {kind}")
    print("--- crashes (defects, not gaps) ---")
    for k, n in crashes.most_common():
        print(f"{n:8d}  {k}")
    # A construction crash is a backend defect, not census residue.  Printing
    # the row is testimony, but a successful process status would let callers
    # bank a partial denominator as a complete census.  Keep ordinary
    # SugarNotWritten gaps measurable while making every defect row red.
    # Desugar-layer panics and defects are red for the same reason: a
    # construction-law gap or an instrument defect must never let a caller bank
    # a partial denominator as a complete census. R_desugar itself is a
    # measured frontier, not a failure — it does not colour the exit.
    return 1 if crashes or desugar.red else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="package root to census")
    parser.add_argument(
        "--engine-log",
        default=None,
        help="JSONL span/heartbeat sink (or set SUGAR_ENGINE_LOG)",
    )
    args = parser.parse_args()

    from sugar_lift_py_tests.engine_log import configure_live_log

    configure_live_log(args.engine_log)
    sys.setrecursionlimit(100000)
    return census(args.root)


if __name__ == "__main__":
    raise SystemExit(main())
