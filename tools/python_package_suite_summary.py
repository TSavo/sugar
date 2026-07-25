"""Render the authoritative suite report: node-ID files plus a counts summary.

The node-ID files are the artifact. The markdown is a reading aid. If the two
ever disagree, the files are right -- every count printed here is `len()` of a
list that is written out in full beside it, so no count can drift away from its
evidence.

Usage:
    python tools/python_package_suite_summary.py \
        --report suite-report.json --pytest-exit 1 --node-id-dir suite-node-ids
"""

from __future__ import annotations

import argparse
import json
import os

# Every axis is written out in FULL. Never truncated, never `head`/`tail`-ed:
# a prior agent's `tail -25` dropped 4 of 28 node IDs and produced a false
# "4 fixed" claim. Truncation of an evidence list is fabrication.
AXES = (
    ("collectedNodeIds", "collected.txt"),
    ("executedOrderNodeIds", "executed-order.txt"),
    ("failedNodeIds", "failed.txt"),
    ("errorNodeIds", "error.txt"),
    ("skippedNodeIds", "skipped.txt"),
    ("xfailedNodeIds", "xfailed.txt"),
    ("xpassedNodeIds", "xpassed.txt"),
    ("passedNodeIds", "passed.txt"),
    ("collectionErrorNodeIds", "collection-error.txt"),
    ("notReportedNodeIds", "not-reported.txt"),
)


def _field(value):
    """Render an identity field, or say UNRESOLVED in words.

    `f"`{value}`"` on a missing field prints the backticked word `None`, which
    reads on a green summary page as a value that happens to be spelled oddly.
    Run 30175741263's summary said `testExtraInputHash: None` and nobody's eye
    caught it. Unresolved says unresolved.
    """
    if value in (None, "", {}, []):
        return "**UNRESOLVED**"
    return f"`{value}`"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True)
    parser.add_argument("--pytest-exit", default=None)
    parser.add_argument("--node-id-dir", required=True)
    args = parser.parse_args(argv)

    with open(args.report, encoding="utf-8") as handle:
        report = json.load(handle)

    os.makedirs(args.node_id_dir, exist_ok=True)
    for axis, filename in AXES:
        node_ids = report.get(axis, [])
        with open(
            os.path.join(args.node_id_dir, filename), "w", encoding="utf-8"
        ) as handle:
            for nodeid in node_ids:
                handle.write(nodeid + "\n")

    identity = report.get("environmentIdentity", {})
    runner = report.get("runnerIdentity", {})
    resources = report.get("resourceTelemetry", {})
    timing = report.get("timing", {})
    counts = report.get("counts", {})

    lines = [
        "### Python package suite (authoritative)",
        "",
        f"- order: `{report.get('order')}`"
        + (
            f" (seed `{report.get('shuffleSeed')}`)"
            if report.get("shuffleSeed") is not None
            else ""
        ),
        f"- pytest exit status: `{args.pytest_exit if args.pytest_exit is not None else report.get('pytestExitStatus')}`"
        " (recorded as evidence; this job reports, it does not gate)",
        f"- measuredCommit: {_field(report.get('measuredCommit'))}",
        f"- environmentIdentityHash: {_field(report.get('environmentIdentityHash'))}",
        f"- sourceStamp: {_field(report.get('sourceStamp'))}"
        f" (binary: {_field(report.get('binarySourceStamp'))})",
        f"- testExtraInputHash: {_field(report.get('testExtraInputHash'))}",
        f"- packageBuildInputs: `{(identity.get('packageBuildInputs') or {}).get('hash')}`",
        f"- python: `{identity.get('pythonImplementation')} {identity.get('pythonVersion')}`"
        f" abi `{(identity.get('pythonAbi') or {}).get('soabi')}`",
        f"- runner: `{runner.get('hostname')}` / `{runner.get('runnerName')}`"
        f" run `{runner.get('githubRunId')}` attempt `{runner.get('githubRunAttempt')}`",
        f"- cpus: `{resources.get('cpuCount')}` affinity `{resources.get('schedAffinityCount')}`"
        f" load `{resources.get('loadAverage1_5_15')}`",
        f"- wall: `{timing.get('wallSeconds')}s`"
        f" cpu user `{timing.get('cpuUserSeconds')}s`"
        f" sys `{timing.get('cpuSystemSeconds')}s`",
        "",
        "Counts are summaries only; the node-ID lists in the artifact are the evidence.",
        "",
        "| axis | count |",
        "| --- | ---: |",
    ]
    for key in (
        "collected",
        "passed",
        "failed",
        "error",
        "skipped",
        "xfailed",
        "xpassed",
        "collectionError",
        "notReported",
    ):
        lines.append(f"| {key} | {counts.get(key)} |")

    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
