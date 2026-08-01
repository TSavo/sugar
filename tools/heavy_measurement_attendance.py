#!/usr/bin/env python3
"""A heavy floor that was EVICTED must not read the same as a floor that RAN.

THE DEFECT THIS FIXES
=====================

Five ``python-package-suite`` runs were cancelled before they started. Three
``Python sole-construction floors`` runs were cancelled before they started, on
one PR, in under two minutes. Nobody noticed either, and the reason is that
from the outside a heavy instrument that never ran is indistinguishable from
one that ran and found nothing:

    absent artifact  ==  "no failures reported"  ==  looks like a clean floor

That is silence being read as testimony, and for a *floor* it is the worst
possible confusion: R is not 0, R is UNMEASURED.

This is the roll call. The roster is the set of heavy classes that must speak
about a commit; attendance is which of them produced a lease receipt. The
minority report -- roster minus attended -- is the set of instruments whose
silence we would otherwise have mistaken for a clean bill.

    R_attendance = |roster \\ attended|

Usage::

    python3 tools/heavy_measurement_attendance.py --commit "$GITHUB_SHA"
    python3 tools/heavy_measurement_attendance.py --commit SHA --receipts-dir runs/

``--receipts-dir`` believes only artifacts: a class counts as present when a
lease receipt for it exists AND says the lease was acquired. Without a
receipts directory the roll call falls back to ``gh run list``, which can still
tell a *cancelled* run from a completed one -- the exact distinction the eight
lost runs above needed somebody to draw.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

# The roster. Every heavy class that runs under the machine-wide lease, keyed
# by the `--class` name its workflow passes to tools/heavy_measurement_lease.py.
# Adding a heavy workflow without adding it here is how an instrument goes
# quiet unnoticed, so tests/test_heavy_measurement_concurrency_topology.py
# checks this roster against the workflows themselves.
# A roster entry carries its CADENCE, because two different obligations were
# being asked one question. A PER_COMMIT class owes testimony about THIS TIP.
# A NIGHTLY class owes testimony about the most recent scheduled WINDOW and is
# not asked about any particular commit at all.
#
# Conflating them made the roll call permanently red for a non-defect: three of
# the five classes are cron/dispatch-only, so a per-commit R_attendance floored
# at 3 forever. A permanently red instrument is tuned out, and a tuned-out
# instrument is decorative -- the death this module exists to prevent.
#
# So the minority is computed ONLY over the classes OWED for the question being
# asked, and the two cadences are NEVER SUMMED. A single number mixing "did not
# speak when it owed us" with "was never asked" is not a measurement, it is a
# mood.
PER_COMMIT = "per-commit"
NIGHTLY_WINDOW = "nightly-window"

HEAVY_ROSTER = {
    "python-package-suite": "Python package suite (authoritative)",
    "python-sole-construction-floors": "Python sole-construction floors (R>0 red)",
    "numpy-wall": "NumPy Wall Ratchet",
    "pandas-wall": "Pandas Wall Ratchet",
    "restored-suite-scoreboard": "Restored Suite Scoreboard",
    "control-effect-recensus": "Control-effect recensus (authoritative scoreboard)",
}

# Cadence per class. Verified against each workflow's own triggers by
# tests/test_heavy_measurement_concurrency_topology.py: a class typed
# PER_COMMIT whose workflow has no `push: branches: [main]` is a contradiction
# the roll call cannot detect at runtime, so the test makes it uncompilable.
HEAVY_CADENCE = {
    "python-package-suite": PER_COMMIT,
    "python-sole-construction-floors": PER_COMMIT,
    "numpy-wall": NIGHTLY_WINDOW,
    "pandas-wall": NIGHTLY_WINDOW,
    "restored-suite-scoreboard": NIGHTLY_WINDOW,
    # THE AUTHORITY ITSELF. control_effect_recensus.py declares
    # SCOREBOARD_AUTHORITY = True and is the sole producer of
    # R_construction_panics, yet it was in no workflow and on no roster -- a
    # hand-run tool, which is why product R was last measured 2026-07-26. Its
    # silence was not even a question anybody asked.
    "control-effect-recensus": NIGHTLY_WINDOW,
}


def owed(cadence):
    """The classes that owe testimony for the question being asked."""
    return [c for c in HEAVY_ROSTER if HEAVY_CADENCE[c] == cadence]


def receipts_attendance(receipts_dir):
    """Which classes produced a receipt saying the lease was acquired."""
    attended, testimony = {}, []
    for path in sorted(Path(receipts_dir).rglob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(payload, dict) and "leaseRecord" in payload:
            payload = payload["leaseRecord"]
        if not isinstance(payload, dict) or "leaseClass" not in payload:
            continue
        lease_class = payload.get("leaseClass")
        testimony.append((lease_class, str(path), payload.get("acquired")))
        if payload.get("acquired") is True:
            attended[lease_class] = str(path)
    return attended, testimony


def workflow_runs(commit, repo=None):
    """Fall back to the run list. `cancelled` here is the eviction signature.

    THE API, NOT ``gh run list``. On 2026-08-01 ``gh run list --limit 200``
    reported 6 non-completed runs for this repository while the REST API
    reported 234 (182 queued + 52 in progress). A CI bankruptcy was declared
    complete on the strength of that 6, the 228 real runs kept every one of
    the 25 available runners busy, and the measurement everybody was waiting
    on never got a slot.

    Under-reporting is the worst possible failure for a ROLL CALL. A missing
    run reads as "no run at all for this commit", which is indistinguishable
    from an evicted one -- the precise confusion this module exists to end.
    So the fallback asks the paginated API and treats an unavailable API as
    unknown (``None``), never as absence.
    """
    slug = repo or "${GITHUB_REPOSITORY}"
    argv = ["gh", "api", f"repos/{slug}/actions/runs?head_sha={commit}&per_page=100",
            "--paginate", "--jq",
            ".workflow_runs[]?|{name,status,conclusion,databaseId:.id,workflowName:.name}"]
    try:
        completed = subprocess.run(argv, capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"heavy-measurement-attendance: GitHub API unavailable: {exc}",
              file=sys.stderr)
        return None
    runs = []
    for line in completed.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            runs.append(json.loads(line))
        except ValueError:
            # A page we cannot parse is unknown testimony, not absence.
            print("heavy-measurement-attendance: unparseable run row; "
                  "treating the run list as unavailable rather than empty",
                  file=sys.stderr)
            return None
    return runs


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", required=True, help="the commit the roll call is about")
    parser.add_argument("--receipts-dir", default=None,
                        help="directory of downloaded lease receipts (artifacts believed first)")
    parser.add_argument("--repo", default=None)
    parser.add_argument("--advisory", action="store_true",
                        help="report the minority without failing (nightly telemetry mode)")
    parser.add_argument("--cadence", choices=(PER_COMMIT, NIGHTLY_WINDOW),
                        default=PER_COMMIT,
                        help="which obligation the roll call is about. Per-commit "
                             "classes owe testimony about this tip; nightly classes "
                             "owe testimony about their last scheduled window. The "
                             "two are never summed.")
    args = parser.parse_args(argv)

    attended, testimony = ({}, [])
    if args.receipts_dir:
        attended, testimony = receipts_attendance(args.receipts_dir)

    runs = workflow_runs(args.commit, args.repo) if not attended else None
    run_state = {}
    if runs:
        for run in runs:
            name = run.get("workflowName") or run.get("name")
            for lease_class, workflow_name in HEAVY_ROSTER.items():
                if name == workflow_name:
                    run_state.setdefault(lease_class, []).append(
                        f"{run.get('status')}/{run.get('conclusion')} (#{run.get('databaseId')})"
                    )

    obliged = owed(args.cadence)
    minority = [c for c in obliged if c not in attended]

    print(f"### heavy-measurement attendance ({args.cadence}) for `{args.commit}`")
    print()
    print("| heavy class | spoke | testimony |")
    print("| --- | --- | --- |")
    for lease_class in obliged:
        if lease_class in attended:
            detail = f"receipt `{attended[lease_class]}`, lease acquired"
            spoke = "yes"
        else:
            states = run_state.get(lease_class)
            spoke = "NO"
            if states:
                detail = "; ".join(states) + " — no lease receipt"
            elif runs is not None:
                detail = "no run at all for this commit"
            else:
                detail = "no receipt (and no run list available)"
        print(f"| `{lease_class}` | {spoke} | {detail} |")
    print()

    for lease_class, path, acquired in testimony:
        if acquired is not True:
            print(f"- `{lease_class}` produced a receipt at `{path}` with "
                  f"`acquired={acquired}` — it REFUSED rather than measured. "
                  f"That is honest silence, and it is still silence.")

    print()
    axis = "R_attendance_commit" if args.cadence == PER_COMMIT else "R_attendance_nightly"
    print(f"**{axis} = {len(minority)}**")
    not_asked = [c for c in HEAVY_ROSTER if c not in obliged]
    if not_asked:
        print()
        print("Not asked at this cadence (a different obligation, NOT counted here): "
              + ", ".join(f"`{c}`" for c in not_asked))
    if minority:
        print()
        print("These instruments did not report. Their silence is NOT a clean floor —")
        print("R is not 0 for them, R is UNMEASURED:")
        for lease_class in minority:
            print(f"- `{lease_class}` ({HEAVY_ROSTER[lease_class]})")
        return 0 if args.advisory else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
