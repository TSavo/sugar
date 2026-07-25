#!/usr/bin/env python3
"""Re-measure the top-N worst functions and test whether RANK survived the load.

The corpus timing run happened under oscillating load (11..75). Absolute
seconds are therefore void. Rank MIGHT survive, because fast oscillation
averages out -- but "might" is not evidence. This replays only the top-N
functions, in a different order, and reports Spearman rank correlation between
the two independent measurements plus the load profile of each.

If rho is high the ranking is reportable AS A RANKING. If it is not, the timing
axis is UNMEASURED and will be reported as such -- never as "slow".
"""

from __future__ import annotations

import json
import random
import subprocess
import sys
import time
from pathlib import Path


def load1() -> float:
    try:
        import os

        return os.getloadavg()[0]
    except Exception:  # noqa: BLE001
        return float("nan")


def main() -> int:
    timing = json.loads(Path(sys.argv[1]).read_text())
    out = Path(sys.argv[2])
    topn = int(sys.argv[3]) if len(sys.argv) > 3 else 40

    from sugar_source_tree.panic import SugarNotWritten
    from sugar_source_tree.reporter import CollectingReporter
    from sugar_source_tree.tree import SourceFile
    from sugar_lift_py_tests.desugar_axis import DesugarAxis

    sys.setrecursionlimit(100000)
    root = Path(timing["root"])

    worst = sorted(timing["functions"], key=lambda r: -r["total_s"])[:topn]
    # Different visitation order: rank must not depend on sweep position.
    order = list(worst)
    random.Random(20260725).shuffle(order)

    # Group by file so each file is parsed once, but keep the shuffled order of
    # first appearance so we are not silently re-imposing alphabetical order.
    want: dict[str, set[str]] = {}
    for r in order:
        want.setdefault(r["where"].rsplit(":", 2)[0], set()).add(r["where"])

    remeasured: dict[str, float] = {}
    loads: list[float] = []
    t0 = time.time()
    for rel, wheres in want.items():
        reporter = CollectingReporter()
        sf = SourceFile.from_path(str(root / rel), reporter=reporter)
        for fn in sf.functions():
            try:
                span = fn.line_col_span()
                where = f"{rel}:{span.start_line}:{span.start_col}"
            except Exception:  # noqa: BLE001
                continue
            if where not in wheres:
                continue
            axis = DesugarAxis()
            loads.append(load1())
            t = time.time()
            try:
                sugar = fn.sugar()
            except SugarNotWritten:
                sugar = None
            if sugar is not None:
                axis.measure(sugar, where=where)
            remeasured[where] = time.time() - t
        print(f"{rel}: {len(remeasured)}/{topn} load={load1():.1f}", flush=True)

    paired = [
        (r["where"], r["name"], r["total_s"], remeasured[r["where"]])
        for r in worst
        if r["where"] in remeasured
    ]

    def spearman(a: list[float], b: list[float]) -> float:
        def ranks(v: list[float]) -> list[float]:
            order_ = sorted(range(len(v)), key=lambda i: v[i])
            rk = [0.0] * len(v)
            for pos, i in enumerate(order_):
                rk[i] = float(pos)
            return rk

        ra, rb = ranks(a), ranks(b)
        n = len(ra)
        if n < 3:
            return float("nan")
        ma, mb = sum(ra) / n, sum(rb) / n
        num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
        da = sum((x - ma) ** 2 for x in ra) ** 0.5
        db = sum((y - mb) ** 2 for y in rb) ** 0.5
        return num / (da * db) if da and db else float("nan")

    rho = spearman([p[2] for p in paired], [p[3] for p in paired])
    payload = {
        "topN": topn,
        "paired": len(paired),
        "spearmanRho": round(rho, 4),
        "wallSeconds": round(time.time() - t0, 1),
        "loadMin": round(min(loads), 2) if loads else None,
        "loadMax": round(max(loads), 2) if loads else None,
        "loadMean": round(sum(loads) / len(loads), 2) if loads else None,
        "rows": [
            {
                "name": n,
                "where": w,
                "run1_s": round(a, 4),
                "replay_s": round(b, 4),
                "ratio": round(b / a, 3) if a else None,
            }
            for w, n, a, b in paired
        ],
    }
    out.write_text(json.dumps(payload, indent=2))
    print(json.dumps({k: v for k, v in payload.items() if k != "rows"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
