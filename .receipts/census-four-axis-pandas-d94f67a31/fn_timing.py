#!/usr/bin/env python3
"""Per-function timing probe for the pandas census.

Mirrors sugar_lift_py_tests.census.census() exactly at the per-function door
(fn.sugar() construction + DesugarAxis.measure), but records wall time per
function so the census's per-file line can be resolved into a distribution.

It does NOT re-implement the axis membrane: it imports the SAME DesugarAxis and
the SAME collect_construction_panic used by census.py, so the two cannot drift.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path


def main() -> int:
    root = Path(sys.argv[1])
    out = Path(sys.argv[2])

    from sugar_lift_py_tests.audit_only.collect_construction_gaps import (
        collect_construction_panic,
    )
    from sugar_lift_py_tests.desugar_axis import DesugarAxis
    from sugar_source_tree.panic import SugarNotWritten
    from sugar_source_tree.reporter import CollectingReporter
    from sugar_source_tree.tree import SourceFile

    sys.setrecursionlimit(100000)

    files = sorted(root.rglob("*.py"))
    rows: list[dict] = []
    file_rows: list[dict] = []
    desugar = DesugarAxis()
    t0 = time.time()

    for i, f in enumerate(files):
        rel = str(f.relative_to(root))
        ft = time.time()

        def _measure_file(_f=f, _rel=rel):
            reporter = CollectingReporter()
            sf = SourceFile.from_path(str(_f), reporter=reporter)
            for fn in sf.functions():
                try:
                    span = fn.line_col_span()
                    where = f"{_rel}:{span.start_line}:{span.start_col}"
                except Exception:  # noqa: BLE001
                    where = f"{_rel}:?"
                name = getattr(fn, "name", None) or "<unnamed>"
                t_c = time.time()
                try:
                    sugar = fn.sugar()
                    constructed = True
                except SugarNotWritten:
                    sugar = None
                    constructed = False
                c_dt = time.time() - t_c
                t_d = time.time()
                if sugar is not None:
                    desugar.measure(sugar, where=where)
                d_dt = time.time() - t_d
                rows.append(
                    {
                        "name": name,
                        "where": where,
                        "constructed": constructed,
                        "construct_s": round(c_dt, 6),
                        "desugar_s": round(d_dt, 6),
                        "total_s": round(c_dt + d_dt, 6),
                    }
                )
            return len(reporter.gaps)

        status = "ok"
        try:
            _, panic_row = collect_construction_panic(rel, _measure_file)
            if panic_row is not None:
                status = "construction-panic"
        except Exception as e:  # noqa: BLE001
            status = f"crash:{type(e).__name__}"
        file_rows.append(
            {"file": rel, "elapsed_s": round(time.time() - ft, 6), "status": status}
        )
        print(f"[{i + 1}/{len(files)}] {time.time() - ft:5.1f}s {rel}", flush=True)

    out.write_text(
        json.dumps(
            {
                "root": str(root),
                "wall_s": round(time.time() - t0, 3),
                "functions": rows,
                "files": file_rows,
            }
        )
    )
    print(f"wrote {len(rows)} function rows to {out} in {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
