#!/usr/bin/env python3
"""No timing claim is accepted if the lease was not acquired.

That sentence is a rule, and a rule nobody can run is a comment. This is the
executable form: point it at a lease receipt (or at a suite report that embeds
one as ``leaseRecord``) and it exits non-zero unless the measured section was
actually entered under the machine-wide lease.

Two modes:

``--record PATH`` (default)
    One measurement. Red if the receipt is missing, if ``acquired`` is not
    true, if the receipt carries no acquisition/release interval, or if the
    receipt's commit disagrees with ``--require-commit``. Green prints the
    interval so the run summary carries it.

``--scope-check PATH [PATH ...]``
    Several receipts at once. A lease is machine-wide only if every holder on
    the same kernel locked the same inode; receipts sharing ``bootId`` while
    differing in ``device``/``inode`` prove the lease file was NOT shared
    between runner containers and the serialization never happened. Also red
    if two acquisition intervals on the same kernel OVERLAP -- the direct
    observation that two heavy measurements ran at once.

Exit 0 green, 1 red, 2 usage/IO.
"""

from __future__ import annotations

import argparse
import json
import sys

SUPPORTED_SCHEMA_VERSIONS = (1,)


def load_record(path):
    """Accept either a bare lease receipt or an artifact that embeds one."""
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, dict) and "leaseRecord" in payload:
        payload = payload["leaseRecord"]
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: not a lease receipt object")
    return payload


def check_record(record, path, require_commit=None, require_zero_claim=False):
    """Return the list of violations. Empty list means green."""
    violations = []

    version = record.get("schemaVersion")
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        violations.append(
            f"{path}: unsupported lease receipt schemaVersion {version!r}; "
            f"expected one of {SUPPORTED_SCHEMA_VERSIONS}"
        )
        return violations

    if record.get("acquired") is not True:
        violations.append(
            f"{path}: lease NOT acquired (acquired={record.get('acquired')!r}, "
            f"timedOut={record.get('timedOut')!r}). No timing claim from this run "
            f"is a measurement. Stale-owner testimony: "
            f"{record.get('staleOwnerDiagnostics')!r}"
        )

    for field in ("requestedAtUnix", "acquiredAtUnix", "releasedAtUnix"):
        if not isinstance(record.get(field), (int, float)):
            violations.append(
                f"{path}: {field} is {record.get(field)!r}, not a timestamp; the "
                f"lease interval is unreadable, so the measurement is unattributable"
            )

    for field in ("waitSeconds", "heldSeconds"):
        if not isinstance(record.get(field), (int, float)):
            violations.append(f"{path}: {field} is {record.get(field)!r}, not a duration")

    status = record.get("measurementStatus")
    if not status or status == "unknown":
        violations.append(f"{path}: measurementStatus is {status!r}; the run will not "
                          f"say whether it measured anything")
    if require_zero_claim:
        # The whole point of the vocabulary. Cancelled, interrupted, refused and
        # absent are all "no measurement" -- and a zero claim resting on any of
        # them is the five-lost-suite-runs defect wearing a green tick.
        if record.get("supportsZeroClaim") is not True:
            violations.append(
                f"{path}: measurementStatus={status!r} does NOT support a zero "
                f"claim (only {record.get('zeroClaimStatus')!r} does). This run "
                f"did not measure zero; it did not measure."
            )

    owner = record.get("owner") or {}
    if not owner.get("githubRunId"):
        violations.append(f"{path}: owner.githubRunId absent; the lease has no owner of record")

    commit = record.get("measuredCommit")
    if not commit or commit == "unknown":
        violations.append(f"{path}: measuredCommit is {commit!r}; the artifact names no commit")
    elif require_commit and commit != require_commit:
        violations.append(
            f"{path}: measuredCommit {commit} != required {require_commit}; this "
            f"receipt belongs to a different commit than the artifact claims"
        )

    return violations


def check_scope(records):
    """Cross-receipt teeth: same kernel must mean same lock, and no overlap."""
    violations = []
    by_boot = {}
    for path, record in records:
        identity = record.get("leaseIdentity") or {}
        boot = identity.get("bootId")
        if not boot or boot == "unavailable":
            violations.append(
                f"{path}: leaseIdentity.bootId is {boot!r}; without the kernel's "
                f"identity we cannot tell a machine-wide lease from a per-container one"
            )
            continue
        by_boot.setdefault(boot, []).append((path, record, identity))

    for boot, entries in by_boot.items():
        inodes = {(i.get("device"), i.get("inode")) for _, _, i in entries}
        if len(inodes) > 1:
            detail = ", ".join(
                f"{p}=dev{i.get('device')}/ino{i.get('inode')}" for p, _, i in entries
            )
            violations.append(
                f"bootId {boot}: receipts locked DIFFERENT inodes ({detail}). The "
                f"lease path is not shared between runner containers, so the lease "
                f"is per-container theatre and heavy measurements can overlap."
            )

        intervals = []
        for path, record, _ in entries:
            start, end = record.get("acquiredAtUnix"), record.get("releasedAtUnix")
            if record.get("acquired") is True and isinstance(start, (int, float)) \
                    and isinstance(end, (int, float)):
                intervals.append((start, end, path))
        intervals.sort()
        for (a_start, a_end, a_path), (b_start, b_end, b_path) in zip(intervals, intervals[1:]):
            if b_start < a_end:
                violations.append(
                    f"bootId {boot}: lease intervals OVERLAP -- {a_path} held "
                    f"[{a_start}, {a_end}] while {b_path} held [{b_start}, {b_end}]. "
                    f"Two heavy measurements executed at once."
                )
    return violations


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", action="append", default=[],
                        help="lease receipt, or an artifact embedding one as leaseRecord")
    parser.add_argument("--require-commit", default=None,
                        help="the commit the artifact claims to measure")
    parser.add_argument("--require-zero-claim", action="store_true",
                        help="red unless the run reached completed/zero-findings; "
                             "use wherever an R=0 claim is being made")
    parser.add_argument("--scope-check", action="append", default=[],
                        help="receipts to compare for shared-inode and non-overlap")
    args = parser.parse_args(argv)

    if not args.record and not args.scope_check:
        parser.error("give --record and/or --scope-check")

    violations = []
    loaded = []
    for path in list(args.record) + list(args.scope_check):
        try:
            loaded.append((path, load_record(path)))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            violations.append(f"{path}: unreadable lease receipt: {type(exc).__name__}: {exc}")

    by_path = dict(loaded)
    for path in args.record:
        if path in by_path:
            violations.extend(check_record(by_path[path], path, args.require_commit,
                                           args.require_zero_claim))

    scope_records = [(p, by_path[p]) for p in args.scope_check if p in by_path]
    if scope_records:
        violations.extend(check_scope(scope_records))

    print("### heavy-measurement lease gate")
    print()
    for path in args.record:
        record = by_path.get(path)
        if not record:
            continue
        print(
            f"- `{path}`: class `{record.get('leaseClass')}` "
            f"commit `{record.get('measuredCommit')}` "
            f"run `{(record.get('owner') or {}).get('githubRunId')}` "
            f"acquired `{record.get('acquired')}` "
            f"status `{record.get('measurementStatus')}` "
            f"supportsZeroClaim `{record.get('supportsZeroClaim')}` "
            f"waited `{record.get('waitSeconds')}s` held `{record.get('heldSeconds')}s`"
        )
    print()

    if violations:
        print(f"**R_lease = {len(violations)} — measurement REFUSED**")
        print()
        for violation in violations:
            print(f"- {violation}")
        return 1

    print("**R_lease = 0** — every timing claim here was made under an acquired lease.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
