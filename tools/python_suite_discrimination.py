"""Order-discrimination check for the authoritative Python package suite.

The per-merge cadence runs ONE canonical whole-package sweep. That is cheap and
it is the number we report. What it cannot see on its own is cache- or
order-dependence: a verdict that changes because of what ran before it is not a
verdict about the test, it is a verdict about the schedule.

So a SCHEDULED run executes the same package in canonical order and in
reversed / shuffled order, each in its own cold process, and this script
requires the verdict sets to be IDENTICAL. Sets, not sequences -- order is
exactly what is allowed to differ.

Divergence is red and names every diverging node ID. It is never summarised
into a count, and never tolerated as flake: an order-dependent verdict means
one of the two runs told the truth and we do not know which.

Usage:
    python tools/python_suite_discrimination.py \
        --baseline canonical/suite-report.json \
        --candidate reversed/suite-report.json \
        --candidate shuffled/suite-report.json
"""

from __future__ import annotations

import argparse
import json
import sys

# Verdict axes compared as sets. `collectedNodeIds` is here because a package
# whose collected SET depends on execution order has a collection-time
# dependence, which is strictly worse than an ordering-dependent verdict.
VERDICT_AXES = (
    "collectedNodeIds",
    "failedNodeIds",
    "errorNodeIds",
    "skippedNodeIds",
    "collectionErrorNodeIds",
)


def _load(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _identity_hash(report):
    return (report.get("environmentIdentity") or {}).get("environmentIdentityHash")


def compare(baseline, candidate):
    """Return a list of divergence strings; empty means identical verdicts."""
    divergences = []

    base_id = _identity_hash(baseline)
    cand_id = _identity_hash(candidate)
    if base_id != cand_id:
        # Not a flake and not a divergence -- it is an invalid comparison.
        divergences.append(
            "environmentIdentityHash differs: "
            f"baseline={base_id} candidate={cand_id} -- these two runs are not "
            "comparable measurements; re-measure both at one identity"
        )

    for axis in VERDICT_AXES:
        base = set(baseline.get(axis, []))
        cand = set(candidate.get(axis, []))
        only_base = sorted(base - cand)
        only_cand = sorted(cand - base)
        for nodeid in only_base:
            divergences.append(f"{axis}: only in {baseline_label(baseline)}: {nodeid}")
        for nodeid in only_cand:
            divergences.append(f"{axis}: only in {baseline_label(candidate)}: {nodeid}")
    return divergences


def baseline_label(report):
    return report.get("label") or report.get("order") or "<unlabelled>"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--candidate", action="append", required=True)
    args = parser.parse_args(argv)

    baseline = _load(args.baseline)
    failures = 0
    for path in args.candidate:
        candidate = _load(path)
        divergences = compare(baseline, candidate)
        header = (
            f"{baseline_label(baseline)} (order={baseline.get('order')}) vs "
            f"{baseline_label(candidate)} (order={candidate.get('order')}, "
            f"seed={candidate.get('shuffleSeed')})"
        )
        if divergences:
            failures += 1
            print(f"ORDER-DEPENDENCE: {header}")
            for line in divergences:
                print(f"  {line}")
        else:
            print(f"identical verdict sets: {header}")

    if failures:
        print(
            f"\ndiscrimination FAILED: {failures} candidate run(s) disagreed with "
            "the canonical run. The suite's verdicts depend on execution order "
            "or on cache state. Fix the dependence; do not re-run until green."
        )
        return 1
    print("\ndiscrimination PASSED: every order produced identical verdict sets.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
