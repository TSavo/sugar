"""The corpus census: construction axis + desugar-layer axis (#6243).

    python -m sugar_lift_py_tests.census <package-root> [--engine-log PATH]

Two named quantities (never merged into one R):

1. **Construction** — ``fn.sugar()`` gaps, deduped by (node.kind, line, col).
2. **Desugar** — ``sugar.desugar(None)`` refusals (owner-keyed) and typed red
   effects at desugar, deduped by (owner, file, line).

Yield/YieldFrom construct then refuse at desugar: construction-total, still
on the board under R_desugar.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from pathlib import Path


def _desugar_owner_key(gap: BaseException) -> str:
    owner = getattr(gap, "owner", None)
    if isinstance(owner, str) and owner:
        return owner
    return type(gap).__name__


def _typed_red_owners(outcome: object) -> list[str]:
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.floor.universe_value import UniverseValue
    from sugar_lift_py_tests.outcome import (
        Complete,
        Completed,
        ExitSet,
        Halted,
        Incomplete,
    )

    owners: list[str] = []

    def visit(obj: object, depth: int = 0) -> None:
        if depth > 24 or obj is None:
            return
        if isinstance(obj, Incomplete):
            owners.append(type(obj.effect).__name__)
            return
        if isinstance(obj, Complete):
            visit(obj.value, depth + 1)
            return
        if isinstance(obj, ExitSet):
            for exit_ in getattr(obj, "exits", ()):
                if isinstance(exit_, Halted):
                    owners.append(type(exit_.effect).__name__)
                elif isinstance(exit_, Completed):
                    visit(exit_.value, depth + 1)
            return
        if isinstance(obj, UniverseValue):
            visit(obj.record, depth + 1)
            return
        if isinstance(obj, BlockValue):
            for entry in getattr(obj, "statements", ()):
                visit(entry, depth + 1)

    visit(outcome)
    return owners


def census(root: Path) -> int:
    from sugar_source_tree.panic import SugarNotWritten
    from sugar_source_tree.reporter import CollectingReporter
    from sugar_source_tree.tree import SourceFile

    files = sorted(root.rglob("*.py"))
    families: Counter = Counter()
    desugar_families: Counter = Counter()
    desugar_seen: set[tuple[str, str, object]] = set()
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
                    line = fn.line_col_span().start_line
                except Exception:  # noqa: BLE001
                    line = "?"
                try:
                    sugar = fn.sugar()  # ONE construction; nested gaps self-report
                    clean_fns += 1
                except SugarNotWritten:
                    sugar = None
                if sugar is not None:

                    def tally(owner: str, line_key: object = line) -> None:
                        key = (owner, rel, line_key)
                        if key in desugar_seen:
                            return
                        desugar_seen.add(key)
                        desugar_families[owner] += 1

                    try:
                        outcome = sugar.desugar(None)
                    except SugarNotWritten as gap:
                        tally(_desugar_owner_key(gap))
                    except Exception as exc:  # noqa: BLE001
                        tally(f"desugar-crash:{type(exc).__name__}")
                    else:
                        for owner in _typed_red_owners(outcome):
                            tally(owner)
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
                f"desugar={sum(desugar_families.values()):5d} {rel}",
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
    print("--- desugar-layer families (top 40, deduped by owner+file+line) ---")
    print(f"R_desugar = {sum(desugar_families.values())}")
    for kind, n in desugar_families.most_common(40):
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
