#!/usr/bin/env python3
"""#6320 probe: time the OPEN phase separately from construction and desugar.

#6318's author reported that
`open_source_file_for_construction(populate_derived=True)` still TIMES OUT at
300s in the OPEN phase on `pandas/core/generic.py`, before `normalize` is
entered. If that reproduces under the census door, #6315 fixed the
arm-population wall and a separate open-phase wall remains — and a full sweep
would burn into a known hang at index 121.

`populate_derived` is a PARAMETER, so the two doors may be measuring different
work. This probe times both doors on the same file:

  A. census door      SourceFile.from_path(...)  -- what census.py actually calls
  B. reproducer door  open_source_file_for_construction(populate_derived=True)

then, through the census door only, `fn.sugar()` construction and
`DesugarAxis.measure` desugar, separately.

Each phase is bounded by its own alarm so a hang is reported as a phase, not as
a dead probe.
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import time


class PhaseTimeout(Exception):
    pass


def _bounded(seconds: int):
    def handler(signum, frame):
        raise PhaseTimeout()

    signal.signal(signal.SIGALRM, handler)
    signal.alarm(seconds)


def _clear():
    signal.alarm(0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--root", required=True)
    ap.add_argument("--bound", type=int, default=300)
    args = ap.parse_args()
    sys.setrecursionlimit(100000)

    from sugar_lift_py_tests.desugar_axis import DesugarAxis
    from sugar_source_tree.panic import SugarNotWritten
    from sugar_source_tree.reporter import CollectingReporter
    from sugar_source_tree.tree import SourceFile

    out: dict = {"file": args.path, "bound": args.bound}

    # ---- A. the CENSUS open door ----------------------------------------
    t = time.time()
    try:
        _bounded(args.bound)
        reporter = CollectingReporter()
        sf = SourceFile.from_path(args.path, reporter=reporter)
        _clear()
        out["openCensusDoor"] = {"status": "completed", "seconds": round(time.time() - t, 2)}
    except PhaseTimeout:
        out["openCensusDoor"] = {"status": "TIMEOUT", "seconds": args.bound}
        print(json.dumps(out))
        return 1
    except Exception as exc:  # noqa: BLE001
        _clear()
        out["openCensusDoor"] = {"status": "error", "detail": f"{type(exc).__name__}: {exc}"}
        print(json.dumps(out))
        return 1

    # ---- B. the REPRODUCER open door ------------------------------------
    t = time.time()
    try:
        from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction

        _bounded(args.bound)
        from pathlib import Path as _P
        open_source_file_for_construction(
            _P(args.path), root=_P(args.root), populate_derived=True
        )
        _clear()
        out["openReproducerDoor"] = {
            "status": "completed",
            "seconds": round(time.time() - t, 2),
            "populate_derived": True,
        }
    except PhaseTimeout:
        _clear()
        out["openReproducerDoor"] = {"status": "TIMEOUT", "seconds": args.bound,
                                     "populate_derived": True}
    except Exception as exc:  # noqa: BLE001
        _clear()
        out["openReproducerDoor"] = {"status": "error",
                                     "detail": f"{type(exc).__name__}: {exc}"}

    # ---- construction and desugar, through the census door --------------
    axis = DesugarAxis()
    total = clean = 0
    con_t = des_t = 0.0
    try:
        _bounded(args.bound)
        for fn in sf.functions():
            total += 1
            try:
                span = fn.line_col_span()
                where = f"{args.path}:{span.start_line}:{span.start_col}"
            except Exception:  # noqa: BLE001
                where = f"{args.path}:?"
            t = time.time()
            try:
                sugar = fn.sugar()
                clean += 1
            except SugarNotWritten:
                sugar = None
            con_t += time.time() - t
            if sugar is not None:
                t = time.time()
                axis.measure(sugar, where=where)
                des_t += time.time() - t
        _clear()
        out["construction"] = {"status": "completed", "seconds": round(con_t, 2),
                               "functions": total, "clean": clean,
                               "gaps": len(reporter.gaps)}
        out["desugar"] = {"status": "completed", "seconds": round(des_t, 2),
                          "pairs": len(axis._seen),
                          "panics": len(axis.construction_panics),
                          "defects": len(axis.defects)}
    except PhaseTimeout:
        _clear()
        out["construction"] = {"status": "partial", "seconds": round(con_t, 2),
                               "functionsReached": total}
        out["desugar"] = {"status": "TIMEOUT", "seconds": round(des_t, 2)}
        print(json.dumps(out))
        return 1

    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
