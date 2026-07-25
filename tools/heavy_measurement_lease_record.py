#!/usr/bin/env python3
"""Write the heavy-measurement lease receipt.

Called by ``tools/heavy_measurement_lease.sh`` on every exit path -- success,
failure, timeout, signal. The shell passes fields through ``LEASE_*``
environment variables; this module owns their TYPES, so no timing number is
ever a string that happens to look like one.

The receipt is the evidence behind every heavy timing claim in this repo. It
answers, for one measurement:

    who asked (owner), when (request), when it started (acquisition), how long
    it waited, when it let go (release), what commit it measured, and -- the
    load-bearing bit -- whether the lease was ACQUIRED AT ALL.

``acquired: false`` means the measured section was never entered. Any timing
read off a run whose receipt says that is not a measurement. See
``tools/heavy_measurement_lease_gate.py``, which gives that sentence teeth.

Field names mirror ``tools/python_package_suite_report.py`` (camelCase, unix
seconds, node-ID-style explicitness) because this receipt EMBEDS in that
artifact as ``leaseRecord`` rather than starting a second schema.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys

SCHEMA_VERSION = 1


def _float(name):
    raw = os.environ.get(name, "")
    if raw == "":
        return None
    try:
        return round(float(raw), 6)
    except ValueError:
        # Loud, never silent: an unparseable timestamp is testimony too.
        return {"unparseable": raw}


def _int(name):
    raw = os.environ.get(name, "")
    if raw == "":
        return None
    try:
        return int(raw)
    except ValueError:
        return {"unparseable": raw}


def _text(name):
    raw = os.environ.get(name, "")
    return raw if raw != "" else None


def _bool(name):
    return os.environ.get(name, "") == "true"


def _lease_identity(lease_path):
    """Device+inode of the lease file, beside the kernel's boot id.

    A lease is machine-wide only if every runner container on this kernel locks
    the SAME inode. Two receipts sharing ``bootId`` but differing in
    ``device``/``inode`` prove the lease path was not shared and the
    serialization never happened -- a fact we would rather read off artifacts
    than assume from a bind-mount we cannot see from inside the container.
    """
    identity = {
        "path": lease_path,
        "bootId": _text("LEASE_BOOT_ID"),
        "hostname": platform.node(),
        "device": None,
        "inode": None,
    }
    if lease_path:
        try:
            stat = os.stat(lease_path)
            identity["device"] = stat.st_dev
            identity["inode"] = stat.st_ino
        except OSError as exc:
            identity["unavailable"] = f"{type(exc).__name__}: {exc}"
    return identity


def build_record():
    requested = _float("LEASE_REQUESTED_AT")
    acquired_at = _float("LEASE_ACQUIRED_AT")
    released_at = _float("LEASE_RELEASED_AT")
    acquired = _bool("LEASE_ACQUIRED")

    def _span(start, end):
        if isinstance(start, float) and isinstance(end, float):
            return round(end - start, 6)
        return None

    status = _text("LEASE_STATUS") or "unknown"
    zero_claim_status = _text("LEASE_ZERO_CLAIM_STATUS") or "completed/zero-findings"

    return {
        "schemaVersion": SCHEMA_VERSION,
        "leaseClass": _text("LEASE_CLASS"),
        # THE STATUS VOCABULARY.
        #
        #   queued -> lease-waiting -> measuring -> completed/{findings,
        #                                                      zero-findings}
        #   queued / lease-waiting -> cancelled-before-measurement
        #   measuring              -> interrupted-during-measurement
        #
        # `supportsZeroClaim` is the single field a reader has to look at, and
        # it is true for exactly ONE status. An absent artifact, a cancelled
        # run, and an interrupted census are all "no measurement" -- never
        # green, never a floor at zero.
        "measurementStatus": status,
        "supportsZeroClaim": status == zero_claim_status,
        "zeroClaimStatus": zero_claim_status,
        "leaseIdentity": _lease_identity(os.environ.get("LEASE_PATH", "")),
        # THE gate field. False means the measured section was never entered.
        "acquired": acquired,
        "timedOut": _bool("LEASE_TIMED_OUT"),
        "timeoutSeconds": _int("LEASE_TIMEOUT_SECONDS"),
        "requestedAtUnix": requested,
        "acquiredAtUnix": acquired_at,
        "releasedAtUnix": released_at,
        "waitSeconds": _span(requested, acquired_at),
        "heldSeconds": _span(acquired_at, released_at),
        "measuredCommit": os.environ.get("GITHUB_SHA") or "unknown",
        "owner": {
            "githubRunId": os.environ.get("GITHUB_RUN_ID"),
            "githubRunAttempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "githubWorkflow": os.environ.get("GITHUB_WORKFLOW"),
            "githubJob": os.environ.get("GITHUB_JOB"),
            "githubRef": os.environ.get("GITHUB_REF"),
            "runnerName": os.environ.get("RUNNER_NAME"),
            "holderPid": _int("LEASE_HOLDER_PID"),
        },
        "command": _text("LEASE_COMMAND"),
        "commandExitStatus": _int("LEASE_COMMAND_EXIT"),
        # Present only when the lease could not be taken. Diagnostics, never a
        # licence to proceed: the wrapper refuses rather than running beside
        # the holder.
        "staleOwnerDiagnostics": _text("LEASE_STALE_OWNER"),
    }


def embed_into(record, path):
    """Splice the receipt into an existing artifact as ``leaseRecord``.

    This is why there is no second schema: the authoritative suite report keeps
    owning the measurement, and the lease interval rides inside it, so a reader
    holding one artifact never has to go find a second file to learn whether
    the numbers in front of them were taken under the lease.

    Called from the release path, after the measured command has written its
    artifact. A missing target is loud on stderr and not fatal: the standalone
    receipt at ``--output`` is the primary evidence and is already written.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError) as exc:
        print(
            f"heavy-measurement-lease: cannot embed receipt into {path}: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return False
    if not isinstance(payload, dict):
        print(
            f"heavy-measurement-lease: cannot embed receipt into {path}: "
            f"top level is {type(payload).__name__}, not an object",
            file=sys.stderr,
        )
        return False
    payload["leaseRecord"] = record
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=False)
        handle.write("\n")
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--embed-into",
        action="append",
        default=[],
        metavar="PATH",
        help="also splice this receipt into PATH's JSON object as `leaseRecord`",
    )
    args = parser.parse_args(argv)

    record = build_record()
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, sort_keys=False)
        handle.write("\n")
    for path in args.embed_into:
        embed_into(record, path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
