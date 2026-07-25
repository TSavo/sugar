#!/usr/bin/env python3
"""Full, UNTRUNCATED four-axis dump.

census.py prints its construction-panic rows `[:40]`. This run found 1074 of
them, so 1034 were invisible on stdout -- the exact truncation hazard the brief
names. This pass re-measures with the SAME DesugarAxis and serializes
`DesugarAxis.row()` in full, so every panic owner, every defect row and every
family count is counted FROM A FILE rather than from a printed excerpt.

It also records, per construction gap, the node kind and site, so the `With`
family can be partitioned by the actual context-manager expression at the site
(assertion membrane vs protocol resource) instead of reported as one number.
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
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
    desugar = DesugarAxis()
    construction_gaps: list[dict] = []
    crashes: Counter = Counter()
    file_panics: list[dict] = []
    total_fns = 0
    clean_fns = 0
    clean_files = 0
    t0 = time.time()

    for i, f in enumerate(files):
        rel = str(f.relative_to(root))

        def _measure_file(_f=f, _rel=rel):
            nonlocal total_fns, clean_fns, clean_files
            reporter = CollectingReporter()
            sf = SourceFile.from_path(str(_f), reporter=reporter)
            for fn in sf.functions():
                total_fns += 1
                try:
                    span = fn.line_col_span()
                    where = f"{_rel}:{span.start_line}:{span.start_col}"
                except Exception:  # noqa: BLE001
                    where = f"{_rel}:?"
                try:
                    sugar = fn.sugar()
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
                    construction_gaps.append(
                        {
                            "kind": node.kind,
                            "file": _rel,
                            "line": lc.start_line,
                            "col": lc.start_col,
                        }
                    )
            if not reporter.gaps:
                clean_files += 1
            return len(reporter.gaps)

        try:
            _, panic_row = collect_construction_panic(rel, _measure_file)
        except Exception as e:  # noqa: BLE001
            crashes[type(e).__name__] += 1
            continue
        if panic_row is not None:
            info = panic_row.info if isinstance(panic_row.info, dict) else {}
            file_panics.append({"file": rel, "owner": info.get("owner")})
            continue
        if (i + 1) % 100 == 0:
            print(f"[{i + 1}/{len(files)}] {time.time() - t0:.0f}s", flush=True)

    row = desugar.row()
    # The occurrence keys themselves, not just their counts. Without these the
    # bounded replay at current head has nothing to target and would have to
    # re-census the whole corpus -- which is exactly what the projection exists
    # to avoid. `_seen` is the authenticated (owner, occurrence) row identity.
    occurrences = sorted(f"{owner}\t{occ}" for owner, occ in desugar._seen)
    payload = {
        "desugarOccurrences": occurrences,
        "root": str(root),
        "wallSeconds": round(time.time() - t0, 1),
        "files": len(files),
        "cleanFiles": clean_files,
        "totalFunctions": total_fns,
        "constructCleanFunctions": clean_fns,
        "R_construction": len(construction_gaps),
        "constructionFamilies": Counter(g["kind"] for g in construction_gaps).most_common(),
        "constructionGaps": construction_gaps,
        "R_desugar": row["R_desugar"],
        "desugarFamilies": row["desugarFamilies"],
        "desugarConstructionPanics": row["desugarConstructionPanics"],
        "desugarConstructionPanicOwners": Counter(
            p.get("owner") for p in row["desugarConstructionPanics"]
        ).most_common(),
        "desugarDefects": row["desugarDefects"],
        "desugarDefectKinds": Counter(
            f"{d['kind']}:{d['detail']}" for d in row["desugarDefects"]
        ).most_common(),
        "fileLevelCrashes": crashes.most_common(),
        "fileLevelPanics": file_panics,
    }
    out.write_text(json.dumps(payload))
    print(
        f"R_construction={payload['R_construction']} "
        f"R_desugar={payload['R_desugar']} "
        f"panics={len(row['desugarConstructionPanics'])} "
        f"defects={len(row['desugarDefects'])} "
        f"in {payload['wallSeconds']}s",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
