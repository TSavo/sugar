#!/usr/bin/env python3
"""Sole-construction floor enrollment — completeness by roll call, not sum of R.

T: serializing floors on a multi-runner fleet is pure insanity. Each process
axis is its own CI job; wall clock is max(axis), not sum(axes). Completeness
is enrollment: a missing axis is UNMEASURED, never a smaller green set.

Process axes (expensive, parallel matrix — one job each):
  silent | native-crash | bare-exception | timeout

Static laws (cheap AST / discrimination): one parallel job that does not wait
on the process matrix.

Each job writes an identity-bound floor-axis-report.json. Attendance checks
the enrolled roster; residual red is the axis job's own exit code.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

SCOREBOARD_AUTHORITY = False

REPORT_KIND = "sole-construction-floor-axis-report"
REPORT_FILENAME = "floor-axis-report.json"
CAMPAIGN_CLASS = "python-sole-construction-floors"
CAMPAIGN_BODY = "floor-measurement.json"


@dataclass(frozen=True, slots=True)
class FloorAxis:
    axis_id: str
    display: str
    kind: str  # process | static
    script: str | None = None  # process floors only


PROCESS_AXES: tuple[FloorAxis, ...] = (
    FloorAxis("silent", "R_silent", "process", "silent_zero_tolerance.py"),
    FloorAxis(
        "native-crash", "R_native_crashes", "process", "native_crash_zero_tolerance.py"
    ),
    FloorAxis(
        "bare-exception",
        "R_bare_exceptions",
        "process",
        "bare_exception_zero_tolerance.py",
    ),
    FloorAxis("timeout", "R_timeouts", "process", "timeout_zero_tolerance.py"),
)

# One enrollment slot for the cheap static job (ownership, side doors, …).
STATIC_AXIS = FloorAxis("static-laws", "R_static_sole_construction", "static")

ENROLLED: tuple[FloorAxis, ...] = PROCESS_AXES + (STATIC_AXIS,)


def enrolled_ids() -> tuple[str, ...]:
    return tuple(a.axis_id for a in ENROLLED)


def emit_process_matrix_json() -> str:
    include = [
        {
            "axis": a.axis_id,
            "display": a.display,
            "script": a.script,
        }
        for a in PROCESS_AXES
    ]
    return json.dumps({"include": include})


def mint_axis_report(
    *,
    axis_id: str,
    display: str,
    commit_sha: str,
    exit_code: int,
    kind: str,
) -> dict:
    if axis_id not in enrolled_ids():
        raise ValueError(f"axis_id {axis_id!r} is not enrolled")
    return {
        "schemaVersion": 1,
        "kind": REPORT_KIND,
        "axisId": axis_id,
        "display": display,
        "axisKind": kind,
        "measurementClass": CAMPAIGN_CLASS,
        "measuredCommit": commit_sha,
        "status": "completed",
        "exitCode": int(exit_code),
        "identityResolved": True,
        "measured": True,
        "floorExitGreen": int(exit_code) == 0,
        "totals": {"failed": 0 if int(exit_code) == 0 else 1},
    }


def check_attendance(directory: Path, *, require_commit: str) -> tuple[int, dict]:
    """Enrollment roll call. Missing axis ⇒ UNMEASURED (exit 1).

    Residual-red axes still attend; campaign residual is separate from attendance.
    """
    require_commit = require_commit.strip()
    if not require_commit:
        raise ValueError("require_commit must be non-empty")

    by_id: dict[str, list[dict]] = {i: [] for i in enrolled_ids()}
    for path in sorted(directory.rglob(REPORT_FILENAME)):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict) or data.get("kind") != REPORT_KIND:
            continue
        aid = data.get("axisId")
        if aid in by_id:
            data["_path"] = str(path)
            by_id[aid].append(data)

    missing: list[str] = []
    unresolved: list[str] = []
    wrong_commit: list[str] = []
    residual_red: list[str] = []
    attended: list[str] = []

    for axis in ENROLLED:
        rows = by_id[axis.axis_id]
        if not rows:
            missing.append(axis.axis_id)
            continue
        row = rows[0]
        if not row.get("identityResolved") or not row.get("measured"):
            unresolved.append(axis.axis_id)
            continue
        if str(row.get("measuredCommit", "")).strip() != require_commit:
            wrong_commit.append(axis.axis_id)
            continue
        attended.append(axis.axis_id)
        if int(row.get("exitCode", 1)) != 0:
            residual_red.append(axis.axis_id)

    complete = not missing and not unresolved and not wrong_commit
    summary = {
        "kind": "sole-construction-floor-attendance",
        "ok": complete,
        "requireCommit": require_commit,
        "enrolled": list(enrolled_ids()),
        "attended": attended,
        "missing": missing,
        "unresolved": unresolved,
        "wrongCommit": wrong_commit,
        "residualRed": residual_red,
        "status": "complete" if complete else "UNMEASURED",
        "measurementClass": CAMPAIGN_CLASS,
    }
    return (0 if complete else 1), summary


def mint_campaign_body(attendance: dict, *, commit_sha: str) -> dict:
    """Identity-bound campaign body for heavy-measurement attendance roll call."""
    residual = list(attendance.get("residualRed") or [])
    unmeasured = attendance.get("status") != "complete"
    return {
        "schemaVersion": 1,
        "measurementClass": CAMPAIGN_CLASS,
        "measuredCommit": commit_sha,
        "status": "unmeasured" if unmeasured else "completed",
        "enrollment": attendance,
        "exitCode": 1 if unmeasured or residual else 0,
        "totals": {
            "failed": 0 if not residual and not unmeasured else 1,
            "enrolledAxes": len(enrolled_ids()),
            "attendedAxes": len(attendance.get("attended") or []),
            "residualRedAxes": len(residual),
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emit-process-matrix-json", action="store_true")
    parser.add_argument("--emit-roster-json", action="store_true")
    parser.add_argument("--mint-report", type=Path)
    parser.add_argument("--axis-id", default="")
    parser.add_argument("--display", default="")
    parser.add_argument("--kind", default="process")
    parser.add_argument("--commit-sha", default="")
    parser.add_argument("--exit-code", type=int, default=0)
    parser.add_argument("--check-attendance", type=Path)
    parser.add_argument("--require-commit", default="")
    parser.add_argument("--write-campaign-body", type=Path)
    args = parser.parse_args(argv)

    if args.emit_process_matrix_json:
        print(emit_process_matrix_json())
        return 0
    if args.emit_roster_json:
        print(
            json.dumps(
                {
                    "kind": "sole-construction-floor-roster",
                    "enrolled": [
                        {"axisId": a.axis_id, "display": a.display, "kind": a.kind}
                        for a in ENROLLED
                    ],
                    "count": len(ENROLLED),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.mint_report is not None:
        report = mint_axis_report(
            axis_id=args.axis_id,
            display=args.display,
            commit_sha=args.commit_sha,
            exit_code=args.exit_code,
            kind=args.kind,
        )
        args.mint_report.parent.mkdir(parents=True, exist_ok=True)
        args.mint_report.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(json.dumps(report, sort_keys=True))
        return 0
    if args.check_attendance is not None:
        code, summary = check_attendance(
            args.check_attendance, require_commit=args.require_commit
        )
        print(json.dumps(summary, indent=2, sort_keys=True))
        if args.write_campaign_body is not None:
            body = mint_campaign_body(summary, commit_sha=args.require_commit)
            args.write_campaign_body.write_text(
                json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        if code != 0:
            print(
                f"FLOOR ENROLLMENT RED: status={summary['status']} "
                f"missing={summary['missing']} unresolved={summary['unresolved']} "
                f"wrongCommit={summary['wrongCommit']}",
                file=sys.stderr,
            )
        else:
            print(
                f"FLOOR ENROLLMENT GREEN: all {len(ENROLLED)} axes attended "
                f"(residualRed={summary['residualRed']})",
                file=sys.stderr,
            )
        return code
    parser.error("pick an action")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
