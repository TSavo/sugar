"""The corpus census: construct every function once, rank the frontier.

    python -m sugar_lift_py_tests.census <package-root> [--engine-log PATH]

One construction per function; the reporter witnesses every gap DURING that
construction (linear -- never a per-node re-ask). Per-file progress on stdout;
the ranked gap-family table at the end. The engine log (configure_live_log) is
the bisection instrument: every function construction enters a reduction_span,
so the heartbeat names the exact function a slow lift is inside -- macro
progress tells you THAT it is slow, the span log tells you WHERE to cut next.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from pathlib import Path


def census(root: Path) -> int:
    from sugar_source_tree.panic import SugarNotWritten
    from sugar_source_tree.reporter import CollectingReporter
    from sugar_source_tree.tree import SourceFile

    files = sorted(root.rglob("*.py"))
    families: Counter = Counter()
    crashes: Counter = Counter()
    clean_files = 0
    total_fns = 0
    clean_fns = 0
    t0 = time.time()
    for i, f in enumerate(files):
        ft = time.time()
        rel = f.relative_to(root)
        try:
            reporter = CollectingReporter()
            sf = SourceFile.from_path(str(f), reporter=reporter)
            for fn in sf.functions():
                total_fns += 1
                try:
                    fn.sugar()  # ONE construction; nested gaps self-report
                    clean_fns += 1
                except SugarNotWritten:
                    pass
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
                f"gaps={len(reporter.gaps):5d} {rel}",
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
    print("--- gap families (top 40, deduped by source site) ---")
    for kind, n in families.most_common(40):
        print(f"{n:8d}  {kind}")
    print("--- crashes (defects, not gaps) ---")
    for k, n in crashes.most_common():
        print(f"{n:8d}  {k}")
    # A construction crash is a backend defect, not census residue.  Printing
    # the row is testimony, but a successful process status would let callers
    # bank a partial denominator as a complete census.  Keep ordinary
    # SugarNotWritten gaps measurable while making every defect row red.
    return 1 if crashes else 0


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
