#!/usr/bin/env python3
"""Heavy-measurement roll call: silence must not read as a clean floor.

Attendance is the presence of an identity-bound RESULT BODY for a roster
class — not a lease mutex grab. A class attended if its measurement body is
present under receipts-dir (measurementClass field, or path/content hints).

    R_attendance = |roster \\ attended|

Usage::

    python3 tools/heavy_measurement_attendance.py --commit "$GITHUB_SHA"
    python3 tools/heavy_measurement_attendance.py --commit SHA --receipts-dir runs/
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

PER_COMMIT = "per-commit"
NIGHTLY_WINDOW = "nightly-window"

# Workflow `name:` strings matched by gh run list / API.
HEAVY_ROSTER = {
    "python-package-suite": "Python package suite (authoritative)",
    "python-sole-construction-floors": "Python sole-construction floors (R>0 red)",
    "numpy-wall": "NumPy Wall Ratchet",
    "pandas-wall": "Pandas Wall Ratchet",
    "restored-suite-scoreboard": "Restored Suite Scoreboard",
    "control-effect-recensus": "Control-effect recensus (authoritative scoreboard)",
}

HEAVY_CADENCE = {
    "python-package-suite": PER_COMMIT,
    "python-sole-construction-floors": PER_COMMIT,
    "numpy-wall": NIGHTLY_WINDOW,
    "pandas-wall": NIGHTLY_WINDOW,
    "restored-suite-scoreboard": NIGHTLY_WINDOW,
    "control-effect-recensus": NIGHTLY_WINDOW,
}

# Path fragments that identify a class's measurement body when measurementClass
# is not set on the JSON.
PATH_HINTS = {
    "python-package-suite": ("suite-report.json", "python-package-suite"),
    "python-sole-construction-floors": (
        "floor-measurement.json",
        "python-sole-construction-floors",
    ),
    "numpy-wall": ("numpy-wall", "frontier.json"),
    "pandas-wall": ("pandas-wall", "frontier.json"),
    "restored-suite-scoreboard": ("restored-suite",),
    "control-effect-recensus": ("pandas-control-effect", "control-effect-recensus"),
}


def owed(cadence):
    return [c for c in HEAVY_ROSTER if HEAVY_CADENCE[c] == cadence]


def _class_from_payload(path: Path, payload: dict) -> str | None:
    mc = payload.get("measurementClass")
    if isinstance(mc, str) and mc in HEAVY_ROSTER:
        return mc
    # Identity-bound body markers (suite report, etc.)
    identity_bound = bool(
        payload.get("measuredCommit")
        or payload.get("environmentIdentityHash")
        or payload.get("bodyCid")
        or payload.get("failedNodeIds") is not None
        or payload.get("totals") is not None
    )
    if not identity_bound and "frontier" not in path.name:
        # frontier.json is a wall body even without those keys
        if path.name not in ("frontier.json", "suite-report.json", "floor-measurement.json"):
            return None
    text = str(path).replace("\\", "/")
    for cls, hints in PATH_HINTS.items():
        if any(h in text for h in hints):
            return cls
    return None


def receipts_attendance(receipts_dir):
    """Which classes produced an identity-bound measurement body."""
    attended, testimony = {}, []
    for path in sorted(Path(receipts_dir).rglob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        # Skip pure lease records if any linger in old artifacts
        if payload.get("leaseClass") and "acquired" in payload and "measurementClass" not in payload:
            if "failedNodeIds" not in payload and "totals" not in payload:
                continue
        cls = _class_from_payload(path, payload)
        if cls is None:
            continue
        testimony.append((cls, str(path), True))
        attended.setdefault(cls, str(path))
    return attended, testimony


def workflow_runs(commit, repo=None):
    slug = repo or "${GITHUB_REPOSITORY}"
    argv = [
        "gh",
        "api",
        f"repos/{slug}/actions/runs?head_sha={commit}&per_page=100",
        "--paginate",
        "--jq",
        ".workflow_runs[]?|{name,status,conclusion,databaseId:.id,workflowName:.name}",
    ]
    try:
        completed = subprocess.run(argv, capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(
            f"heavy-measurement-attendance: GitHub API unavailable: {exc}",
            file=sys.stderr,
        )
        return None
    runs = []
    for line in completed.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            runs.append(json.loads(line))
        except ValueError:
            print(
                "heavy-measurement-attendance: unparseable run row; "
                "treating the run list as unavailable rather than empty",
                file=sys.stderr,
            )
            return None
    return runs


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--receipts-dir", default=None)
    parser.add_argument("--repo", default=None)
    parser.add_argument("--advisory", action="store_true")
    parser.add_argument(
        "--cadence",
        choices=(PER_COMMIT, NIGHTLY_WINDOW),
        default=PER_COMMIT,
    )
    args = parser.parse_args(argv)

    attended, testimony = ({}, [])
    if args.receipts_dir:
        attended, testimony = receipts_attendance(args.receipts_dir)

    runs = workflow_runs(args.commit, args.repo) if not attended else None
    run_state = {}
    if runs:
        for run in runs:
            name = run.get("workflowName") or run.get("name")
            for cls, workflow_name in HEAVY_ROSTER.items():
                if name == workflow_name:
                    run_state.setdefault(cls, []).append(
                        f"{run.get('status')}/{run.get('conclusion')} (#{run.get('databaseId')})"
                    )

    obliged = owed(args.cadence)
    minority = [c for c in obliged if c not in attended]

    print(f"### heavy-measurement attendance ({args.cadence}) for `{args.commit}`")
    print()
    print("| heavy class | spoke | testimony |")
    print("| --- | --- | --- |")
    for cls in obliged:
        if cls in attended:
            detail = f"measurement body `{attended[cls]}`"
            spoke = "yes"
        else:
            states = run_state.get(cls)
            spoke = "NO"
            if states:
                detail = "; ".join(states) + " — no measurement body"
            elif runs is not None:
                detail = "no run at all for this commit"
            else:
                detail = "no measurement body (and no run list available)"
        print(f"| `{cls}` | {spoke} | {detail} |")
    print()

    axis = (
        "R_attendance_commit"
        if args.cadence == PER_COMMIT
        else "R_attendance_nightly"
    )
    print(f"**{axis} = {len(minority)}**")
    not_asked = [c for c in HEAVY_ROSTER if c not in obliged]
    if not_asked:
        print()
        print(
            "Not asked at this cadence (a different obligation, NOT counted here): "
            + ", ".join(f"`{c}`" for c in not_asked)
        )
    if minority:
        print()
        print(
            "These instruments did not report. Their silence is NOT a clean floor —"
        )
        print("R is not 0 for them, R is UNMEASURED:")
        for cls in minority:
            print(f"- `{cls}` ({HEAVY_ROSTER[cls]})")
        return 0 if args.advisory else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
