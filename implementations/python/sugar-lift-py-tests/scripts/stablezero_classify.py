#!/usr/bin/env python3
"""The `stableZero` rig: classify every function of one file, in isolation.

    stableZero = completed_denominator  > 0
               ∧ R(timeout)             == 0
               ∧ R(construction_panics)  == 0
               ∧ R(factoring_gaps)       == 0
               ∧ R(unnamed_exceptions)   == 0

WHY THIS SCRIPT EXISTS AT ALL. The `stableZero-classify-isolated-v1` ledgers in
`docs/ledgers/` were produced by a rig that lived in one agent's temp directory
and did not survive the session — its own frames record `module: "__main__"`.
A measurement nobody else can re-take is not an instrument; it is a claim. This
is the same rig, committed, so the number can be re-taken by anyone at any
commit. The schema string is unchanged so old and new ledgers compare directly.

WHAT "ISOLATED" MEANS. The file is copied ALONE into an empty temp directory
and opened from there. There is no workspace contract-ref table, so a function's
classification depends on nothing but that function, and 223 rows are 223
independent verdicts rather than one entangled one. It also makes the rig cheap
enough to run beside a heavy corpus job without contending for the measurement
lease.

THE STATUSES ARE THE POINT.

  `clean`                 the tower reduced the function. Nothing else.
  `ConstructionPanic`     an owner reached its `None` arm — a Floor law that
                          does not exist yet. The panic IS the worklist row,
                          and its `ConstructionGap` carries owner / blame /
                          observed / requested / fix.
  `ExitSetFactoringGap`   a completed face that a first-match-wins guarded
                          chain cannot faithfully carry.
  `timeout`               the per-function wall deadline. Recorded separately
                          and never folded into the others, because a timeout
                          ABSORBS every panic and gap row the function would
                          have produced — that is exactly how three pandas
                          files hid their rows behind the 300s deadline (#6324).
  `raised:<Type>`         an UNNAMED gap: the tower stopped on a bare exception
                          that names no owner, no observed shape and no fix.

`R(unnamed_exceptions)` is a term of `stableZero` here, and that is a deliberate
addition to the milestone as first written. A rig that gates only on panics
reads GREEN the moment a gap stops naming itself — close three panics, let the
carrier travel one seat further, hit a bare `raise TypeError(type(outcome))`,
and the panic axis is zero while a function still does not lift. That is a
false green bought by misclassification, and it is exactly the failure mode the
whole ladder exists to prevent. A gap is a gap; wearing a bare exception
instead of a `ConstructionGap` makes it WORSE, not absent, because it names
neither its owner nor its replacement architecture.

Every residual carries its full testimony: the gap's own `info` dict, the
message, and the frame list with the innermost frame named. A row that cannot
say who owns it cannot be worked.
"""

from __future__ import annotations

import argparse
import faulthandler
import json
import shutil
import signal
import sys
import tempfile
import time
import traceback
from collections import Counter
from pathlib import Path

SCHEMA = "stableZero-classify-isolated-v1"


class FunctionTimeout(BaseException):
    """Per-function wall deadline. A BaseException so no `except Exception`
    inside the tower can swallow the deadline and report a false `clean`."""


def _alarm(signum, frame):
    raise FunctionTimeout("function wall budget")


def _frames(error: BaseException) -> list[dict]:
    return [
        {
            "module": frame.f_globals.get("__name__"),
            "qualname": frame.f_code.co_qualname,
            "line": lineno,
        }
        for frame, lineno in traceback.walk_tb(error.__traceback__)
    ]


def _testimony(error: BaseException) -> dict:
    """Full testimony for one residual. Never a summary — the row IS the fix."""
    frames = _frames(error)
    info = getattr(error, "info", None)
    payload = {
        "type": type(error).__name__,
        "message": str(error),
        "frames": frames,
        "innermost": frames[-1] if frames else None,
    }
    if info is not None:
        payload["info"] = {
            "owner": getattr(info, "owner", None),
            "blame": getattr(info, "blame", None),
            "observed": getattr(info, "observed", None),
            "requested": getattr(info, "requested", None),
            "fix": getattr(info, "fix", None),
            "gap_kind": getattr(getattr(info, "gap_kind", None), "name", None),
            "gap_locus": getattr(getattr(info, "gap_locus", None), "name", None),
        }
    return payload


def classify(path: Path, deadline: float) -> dict:
    from sugar_lift_py_tests.gap.panic import ConstructionPanic
    from sugar_lift_py_tests.outcome.exit_set import ExitSetFactoringGap
    from sugar_lift_python_source.source_oracle import path_source
    from sugar_source_tree.panic import SugarNotWritten
    from sugar_source_tree.tree import SourceFile

    wall_started = time.time()
    functions = list(SourceFile(path_source(str(path))).functions())

    rows: list[dict] = []
    desugar_seconds = 0.0
    signal.signal(signal.SIGALRM, _alarm)

    for function in functions:
        try:
            span = function.line_col_span()
            line = span.start_line
        except Exception:
            line = None
        try:
            name = function.name()
        except Exception:
            name = None

        row: dict = {"name": name, "line": line}
        started = time.time()
        signal.setitimer(signal.ITIMER_REAL, deadline)
        try:
            sugar = function.sugar()
            if sugar is None:
                row["status"] = "clean"
            else:
                sugar.desugar(None)
                row["status"] = "clean"
        except SugarNotWritten:
            # The TREE door, not a Floor law. It is a construction gap on the
            # recognition axis and is counted on its own name, never folded
            # into the Floor panic term this rig gates on.
            row["status"] = "SugarNotWritten"
        except FunctionTimeout:
            row["status"] = "timeout"
        except ExitSetFactoringGap as gap:
            row["status"] = "ExitSetFactoringGap"
            row["testimony"] = _testimony(gap)
            # #6356: the term is not a scalar. Each refusal says whether a
            # producer failed to testify (possibly closable) or no exclusion
            # was available to this prover (correct output). Read off the arms
            # the refusal carries, never re-derived from its message.
            classification = gap.classification()
            if classification is not None:
                row["factoringGap"] = classification.row()
        except ConstructionPanic as panic:
            row["status"] = "ConstructionPanic"
            row["testimony"] = _testimony(panic)
        except BaseException as error:  # noqa: BLE001 — measured, never hidden
            row["status"] = f"raised:{type(error).__name__}"
            row["testimony"] = _testimony(error)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
        row["seconds"] = round(time.time() - started, 4)
        desugar_seconds += row["seconds"]
        rows.append(row)

    statuses = Counter(row["status"] for row in rows)
    r_timeout = statuses["timeout"]
    r_panics = statuses["ConstructionPanic"]
    r_gaps = statuses["ExitSetFactoringGap"]
    r_unnamed = sum(
        count for status, count in statuses.items() if status.startswith("raised:")
    )
    gap_rows = [row.get("factoringGap") for row in rows if row.get("factoringGap")]
    gap_split = Counter(row["kind"] for row in gap_rows)
    gap_work = sum(1 for row in gap_rows if row["isRemainingWork"])
    completed = len(rows) - r_timeout

    return {
        "schema": SCHEMA,
        "n_functions": len(rows),
        "statuses": dict(sorted(statuses.items())),
        "R(timeout)": r_timeout,
        "R(construction_panics)": r_panics,
        "R(factoring_gaps)": r_gaps,
        "R(unnamed_exceptions)": r_unnamed,
        # The (a)/(b) split. `R(factoring_gaps)` counts every refusal;
        # `R(factoring_gaps_remaining_work)` counts only those a producer could
        # plausibly close by testifying. The rest are the gate working, and a
        # term that mixes them overstates the board.
        "R(factoring_gaps_remaining_work)": gap_work,
        "factoring_gap_split": dict(sorted(gap_split.items())),
        "factoring_gap_rows": gap_rows,
        "completed_denominator": completed,
        "stableZero": bool(
            completed > 0
            and r_timeout == 0
            and r_panics == 0
            and r_gaps == 0
            and r_unnamed == 0
        ),
        "desugar_s": round(desugar_seconds, 2),
        "wall_s": round(time.time() - wall_started, 2),
        "residuals": [row for row in rows if row["status"] != "clean"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", help="path to the single file to classify")
    parser.add_argument("--out", required=True)
    parser.add_argument("--deadline", type=float, default=120.0)
    parser.add_argument("--label", default="")
    args = parser.parse_args()

    faulthandler.enable()
    sys.setrecursionlimit(100000)

    source = Path(args.source).resolve()
    isolated = Path(tempfile.mkdtemp(prefix="sz-iso-"))
    try:
        copied = isolated / source.name
        shutil.copy2(source, copied)
        payload = classify(copied, args.deadline)
    finally:
        shutil.rmtree(isolated, ignore_errors=True)

    payload["file"] = str(source)
    payload["label"] = args.label
    payload["deadline_seconds"] = args.deadline
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")

    print(
        f"stableZero={payload['stableZero']} "
        f"denominator={payload['completed_denominator']} "
        f"timeouts={payload['R(timeout)']} "
        f"construction_panics={payload['R(construction_panics)']} "
        f"factoring_gaps={payload['R(factoring_gaps)']} "
        f"(remaining_work={payload['R(factoring_gaps_remaining_work)']} "
        f"split={payload['factoring_gap_split']}) "
        f"unnamed_exceptions={payload['R(unnamed_exceptions)']} "
        f"statuses={payload['statuses']} out={args.out}",
        flush=True,
    )
    # Red while any term is nonzero. The exit code is the gate; never read a
    # verdict off a pipeline's last stage.
    return 0 if payload["stableZero"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
