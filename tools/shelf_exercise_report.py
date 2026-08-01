#!/usr/bin/env python3
"""Was the filesystem shelf actually exercised in this run?

THE DEFECT THIS FIXES
=====================

After #6977 (peer-evictable publish) and #6982 (content-addressed cell) landed,
two heavy runs failed before they ever touched the binary shelf. From the
outside those logs read the same as a successful load-clear:

    no shelf crimes  ==  "shelf looks fine"  ==  silence as testimony

That is the attendance roll call's confusion one layer down. A run that never
entered ``pull_from_filesystem_shelf`` / ``publish_to_filesystem_shelf`` cannot
clear those doors; it can only fail to exercise them. The clean-looking
absence of ``crime=unevictable-*`` is not a measurement.

Existing receipts do NOT answer this question:

* ``leaseRecord``  -- did a heavy class acquire the machine-wide lease?
* suite / environment identity -- did ``sourceStamp`` resolve?
* ``*.sugarbin.json`` -- is the binary's identity field-equal?

None of those fire only when the filesystem shelf path is entered. A fourth
schema is required; this is it. It is not a lease and not a drain.

Verdict vocabulary (closed; callers exhaustive over these four)::

    SHELF_EXERCISED_CLEAN   -- at least one pull/publish event; zero crimes
    SHELF_EXERCISED_CRIME   -- shelf path entered and a shelf crime fired
    SHELF_NEVER_TOUCHED     -- resolve opened (or log is present) but no
                              filesystem-shelf event
    SHELF_UNMEASURED        -- no receipt and no usable log; silence is not clean

Receipt schema (``schemaVersion`` 1)::

    {
      "schemaVersion": 1,
      "kind": "shelf-exercise",
      "resolveOpened": true,
      "owner": { "githubRunId", "githubWorkflow", "githubJob", "measuredCommit" },
      "events": [
        {"op": "pull"|"publish"|"crime", "outcome": "...", "crime": null|str,
         "name": str, "contentKey": str|null, "atUnix": float|null}
      ]
    }

Producer: ``bin/sugarbin`` appends events when the filesystem shelf path is
entered; it opens the receipt on every resolve so NEVER_TOUCHED is a positive
claim, not an absent file.

Log fallback: classify a CI transcript by the same ``sugarbin:`` lines the
producer emits, so runs that predate the receipt can still be scored without
pretending a missing receipt was clean.

Usage::

    python3 tools/shelf_exercise_report.py open --output path.json
    python3 tools/shelf_exercise_report.py event --output path.json \\
        --op pull --outcome hit --name sugar --content-key KEY
    python3 tools/shelf_exercise_report.py classify --receipt path.json
    python3 tools/shelf_exercise_report.py classify --log path.txt
    python3 tools/shelf_exercise_report.py classify --receipt path.json --require-exercised-clean

Exit: 0 green under the asked question, 1 red, 2 usage/IO.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Optional, Sequence

SCHEMA_VERSION = 1
KIND = "shelf-exercise"

VERDICT_EXERCISED_CLEAN = "SHELF_EXERCISED_CLEAN"
VERDICT_EXERCISED_CRIME = "SHELF_EXERCISED_CRIME"
VERDICT_NEVER_TOUCHED = "SHELF_NEVER_TOUCHED"
VERDICT_UNMEASURED = "SHELF_UNMEASURED"

# Outcomes that prove the filesystem shelf path was entered (not local-target-only).
SHELF_OPS = frozenset({"pull", "publish", "crime"})

# sugarbin log lines that are positive shelf-path testimony (not mere resolve).
_LOG_EXERCISE = (
    re.compile(r"sugarbin:\s*filesystem shelf hit\b"),
    re.compile(r"sugarbin:\s*filesystem shelf miss\b"),
    re.compile(r"sugarbin:\s*filesystem shelf already has content\b"),
    re.compile(r"sugarbin:\s*published \S+ content \S+ to filesystem shelf\b"),
    re.compile(r"sugarbin:\s*filesystem shelf publish raced\b"),
    re.compile(r"sugarbin:\s*filesystem shelf publication failed\b"),
    re.compile(r"sugarbin:\s*evicting regenerable shelf cell\b"),
    re.compile(r"sugarbin:\s*prebuilt cache hit\b"),  # local cache in front of shelf path
    re.compile(r"sugarbin:\s*prebuilt cache rejected\b"),
)
# Crimes that mean the shelf path was entered and refused.
_LOG_CRIME = re.compile(
    r"sugarbin:\s*crime=(?:unevictable-shelf-|private-filesystem-shelf-|"
    r"cas-address-payload-mismatch|corrupt-shelf-cell|"
    r"uncreatable-filesystem-shelf-|private-shared-cache-cell)"
)
# Evidence the binary resolve path ran at all (so NEVER_TOUCHED is claimable).
_LOG_RESOLVE = (
    re.compile(r"sugarbin:\s*local target cache hit\b"),
    re.compile(r"sugarbin:\s*building \S+ once for this session\b"),
    re.compile(r"sugarbin:\s*no matching \S+ binary for stamp\b"),
    re.compile(r"sugarbin:\s*shelf miss for\b"),
    re.compile(r"sugarbin:\s*filesystem shelf\b"),
    re.compile(r"sugarbin:\s*prebuilt cache\b"),
    re.compile(r"sugarbin:\s*published \S+"),
)


def default_receipt_path() -> Optional[Path]:
    """Where a CI run should leave the receipt when no --output is given."""
    explicit = os.environ.get("SUGAR_SHELF_EXERCISE_RECEIPT")
    if explicit:
        return Path(explicit)
    workspace = os.environ.get("GITHUB_WORKSPACE")
    if workspace:
        return Path(workspace) / ".sugar" / "shelf-exercise.json"
    return None


def empty_receipt() -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": KIND,
        "resolveOpened": False,
        "owner": {
            "githubRunId": os.environ.get("GITHUB_RUN_ID"),
            "githubWorkflow": os.environ.get("GITHUB_WORKFLOW"),
            "githubJob": os.environ.get("GITHUB_JOB"),
            "measuredCommit": os.environ.get("GITHUB_SHA"),
        },
        "events": [],
    }


def load_receipt(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: not an object")
    if payload.get("kind") != KIND:
        raise ValueError(f"{path}: kind={payload.get('kind')!r}, expected {KIND!r}")
    if payload.get("schemaVersion") != SCHEMA_VERSION:
        raise ValueError(
            f"{path}: unsupported schemaVersion {payload.get('schemaVersion')!r}"
        )
    if not isinstance(payload.get("events"), list):
        raise ValueError(f"{path}: events must be a list")
    return payload


def write_receipt(path: Path, receipt: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(receipt, handle, indent=2, sort_keys=False)
        handle.write("\n")
    tmp.replace(path)


def open_receipt(path: Path) -> dict[str, Any]:
    """Mark that a binary resolve session started. NEVER_TOUCHED needs this."""
    if path.is_file():
        try:
            receipt = load_receipt(path)
        except ValueError:
            receipt = empty_receipt()
    else:
        receipt = empty_receipt()
    receipt["resolveOpened"] = True
    # Refresh owner from current env if fields were empty.
    owner = receipt.setdefault("owner", {})
    for key, env in (
        ("githubRunId", "GITHUB_RUN_ID"),
        ("githubWorkflow", "GITHUB_WORKFLOW"),
        ("githubJob", "GITHUB_JOB"),
        ("measuredCommit", "GITHUB_SHA"),
    ):
        if not owner.get(key):
            owner[key] = os.environ.get(env)
    write_receipt(path, receipt)
    return receipt


def append_event(
    path: Path,
    *,
    op: str,
    outcome: str,
    name: str = "",
    content_key: Optional[str] = None,
    crime: Optional[str] = None,
) -> dict[str, Any]:
    if op not in SHELF_OPS:
        raise ValueError(f"op must be one of {sorted(SHELF_OPS)}, got {op!r}")
    if path.is_file():
        receipt = load_receipt(path)
    else:
        receipt = empty_receipt()
    receipt["resolveOpened"] = True
    event = {
        "op": op,
        "outcome": outcome,
        "name": name or None,
        "contentKey": content_key,
        "crime": crime,
        "atUnix": round(time.time(), 6),
    }
    receipt.setdefault("events", []).append(event)
    write_receipt(path, receipt)
    return receipt


def classify_receipt(receipt: Mapping[str, Any]) -> tuple[str, list[str]]:
    """Return (verdict, reasons)."""
    reasons: list[str] = []
    events = receipt.get("events") or []
    crimes = [
        e
        for e in events
        if isinstance(e, dict)
        and (e.get("op") == "crime" or e.get("crime") or str(e.get("outcome", "")).startswith("crime"))
    ]
    shelf_events = [
        e
        for e in events
        if isinstance(e, dict) and e.get("op") in SHELF_OPS
    ]

    if crimes:
        reasons.append(f"{len(crimes)} shelf crime event(s) in receipt")
        return VERDICT_EXERCISED_CRIME, reasons

    if shelf_events:
        reasons.append(f"{len(shelf_events)} filesystem-shelf event(s); zero crimes")
        return VERDICT_EXERCISED_CLEAN, reasons

    if receipt.get("resolveOpened") is True:
        reasons.append(
            "resolveOpened=true but events[] has no pull/publish/crime — "
            "shelf path never entered (local target / override / never resolved)"
        )
        return VERDICT_NEVER_TOUCHED, reasons

    reasons.append("receipt present but resolveOpened is not true and events empty")
    return VERDICT_UNMEASURED, reasons


def classify_log(text: str) -> tuple[str, list[str]]:
    """Classify a CI transcript. Absence of crimes is not EXERCISED_CLEAN."""
    reasons: list[str] = []
    exercise_hits = [p for p in _LOG_EXERCISE if p.search(text)]
    resolve_hits = [p for p in _LOG_RESOLVE if p.search(text)]

    # Extract crime= tags for the reason line.
    crime_tags = re.findall(
        r"sugarbin:\s*(crime=(?:unevictable-shelf-|private-filesystem-shelf-|"
        r"cas-address-payload-mismatch|corrupt-shelf-cell|"
        r"uncreatable-filesystem-shelf-|private-shared-cache-cell)[^\s]*)",
        text,
    )

    if crime_tags:
        reasons.append(f"log shelf crime(s): {', '.join(sorted(set(crime_tags)))}")
        return VERDICT_EXERCISED_CRIME, reasons

    if exercise_hits:
        reasons.append(
            f"log shows {len(exercise_hits)} filesystem-shelf / prebuilt-cache "
            "exercise pattern(s); zero shelf crimes"
        )
        return VERDICT_EXERCISED_CLEAN, reasons

    if resolve_hits:
        reasons.append(
            "sugarbin resolve lines present but no filesystem-shelf hit/miss/"
            "publish — shelf never touched"
        )
        return VERDICT_NEVER_TOUCHED, reasons

    # A CI log that only has identity/b3sum/checkout has no sugarbin resolve.
    if "sugarbin:" in text:
        reasons.append(
            "sugarbin: lines present but none are resolve or shelf — "
            "treat as never-touched (e.g. --print-source-stamp only)"
        )
        return VERDICT_NEVER_TOUCHED, reasons

    reasons.append(
        "no shelf-exercise receipt and no sugarbin shelf/resolve lines in log; "
        "silence is SHELF_UNMEASURED, not clean"
    )
    return VERDICT_UNMEASURED, reasons


def classify(
    *,
    receipt: Optional[Mapping[str, Any]] = None,
    log_text: Optional[str] = None,
) -> tuple[str, list[str]]:
    """Prefer receipt; fall back to log; never invent EXERCISED_CLEAN from silence."""
    if receipt is not None:
        return classify_receipt(receipt)
    if log_text is not None:
        return classify_log(log_text)
    return VERDICT_UNMEASURED, [
        "no --receipt and no --log; cannot distinguish EXERCISED from NEVER_TOUCHED"
    ]


def lease_record_is_silent_on_shelf(lease: Mapping[str, Any]) -> bool:
    """Live instrument: a lease receipt carries no shelf-exercise axis."""
    # Explicit: none of the lease fields name shelf traffic.
    shelf_keys = {k for k in lease if "shelf" in k.lower()}
    return not shelf_keys and "events" not in lease


def print_report(verdict: str, reasons: Sequence[str], *, source: str) -> None:
    print(f"### shelf exercise report")
    print()
    print(f"- source: `{source}`")
    print(f"- verdict: **{verdict}**")
    print()
    print("| reason |")
    print("| --- |")
    for reason in reasons:
        print(f"| {reason} |")
    print()
    if verdict == VERDICT_EXERCISED_CLEAN:
        print(
            "SHELF EXERCISED AND CLEAN: filesystem shelf path ran; "
            "no shelf crime in testimony."
        )
    elif verdict == VERDICT_EXERCISED_CRIME:
        print(
            "SHELF EXERCISED AND DIRTY: path ran and a crime fired — "
            "this is a door regression, not silence."
        )
    elif verdict == VERDICT_NEVER_TOUCHED:
        print(
            "SHELF NEVER TOUCHED: this run cannot load-clear #6977/#6982. "
            "Absence of crimes is not a green shelf."
        )
    else:
        print(
            "SHELF UNMEASURED: no receipt and no usable log. "
            "Do not read this as clean."
        )


def cmd_open(args: argparse.Namespace) -> int:
    path = Path(args.output) if args.output else default_receipt_path()
    if path is None:
        print(
            "shelf-exercise: open requires --output or "
            "SUGAR_SHELF_EXERCISE_RECEIPT / GITHUB_WORKSPACE",
            file=sys.stderr,
        )
        return 2
    open_receipt(path)
    print(f"shelf-exercise: opened {path}", file=sys.stderr)
    return 0


def cmd_event(args: argparse.Namespace) -> int:
    path = Path(args.output) if args.output else default_receipt_path()
    if path is None:
        print(
            "shelf-exercise: event requires --output or "
            "SUGAR_SHELF_EXERCISE_RECEIPT / GITHUB_WORKSPACE",
            file=sys.stderr,
        )
        return 2
    append_event(
        path,
        op=args.op,
        outcome=args.outcome,
        name=args.name or "",
        content_key=args.content_key,
        crime=args.crime,
    )
    return 0


def cmd_classify(args: argparse.Namespace) -> int:
    receipt = None
    log_text = None
    source = "none"
    if args.receipt:
        path = Path(args.receipt)
        if not path.is_file():
            print(f"shelf-exercise: receipt missing: {path}", file=sys.stderr)
            # Missing receipt under --receipt is UNMEASURED, not IO error:
            # the question was asked and the answer is "no testimony".
            verdict, reasons = VERDICT_UNMEASURED, [f"receipt path does not exist: {path}"]
            print_report(verdict, reasons, source=str(path))
            return _exit_for(verdict, args)
        try:
            receipt = load_receipt(path)
        except (OSError, ValueError) as exc:
            print(f"shelf-exercise: unreadable receipt: {exc}", file=sys.stderr)
            return 2
        source = str(path)
    elif args.log:
        path = Path(args.log)
        try:
            log_text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            print(f"shelf-exercise: cannot read log: {exc}", file=sys.stderr)
            return 2
        source = str(path)
    else:
        default = default_receipt_path()
        if default and default.is_file():
            try:
                receipt = load_receipt(default)
                source = str(default)
            except ValueError as exc:
                print(f"shelf-exercise: unreadable default receipt: {exc}", file=sys.stderr)
                return 2
        else:
            verdict, reasons = classify()
            print_report(verdict, reasons, source="none")
            return _exit_for(verdict, args)

    verdict, reasons = classify(receipt=receipt, log_text=log_text)
    print_report(verdict, reasons, source=source)
    return _exit_for(verdict, args)


def _exit_for(verdict: str, args: argparse.Namespace) -> int:
    if args.advisory:
        return 0
    if args.require_exercised_clean:
        return 0 if verdict == VERDICT_EXERCISED_CLEAN else 1
    # Default: UNMEASURED and CRIME are red; NEVER_TOUCHED is red when asking
    # the load-clear question (default), CLEAN is green.
    if verdict == VERDICT_EXERCISED_CLEAN:
        return 0
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    open_p = sub.add_parser("open", help="mark resolveOpened on the receipt")
    open_p.add_argument("--output", default=None)
    open_p.set_defaults(func=cmd_open)

    event_p = sub.add_parser("event", help="append one filesystem-shelf event")
    event_p.add_argument("--output", default=None)
    event_p.add_argument("--op", required=True, choices=sorted(SHELF_OPS))
    event_p.add_argument("--outcome", required=True)
    event_p.add_argument("--name", default="")
    event_p.add_argument("--content-key", default=None)
    event_p.add_argument("--crime", default=None)
    event_p.set_defaults(func=cmd_event)

    class_p = sub.add_parser(
        "classify",
        help="print verdict: EXERCISED_CLEAN | EXERCISED_CRIME | NEVER_TOUCHED | UNMEASURED",
    )
    class_p.add_argument("--receipt", default=None, help="shelf-exercise receipt JSON")
    class_p.add_argument("--log", default=None, help="CI / sugarbin transcript")
    class_p.add_argument(
        "--require-exercised-clean",
        action="store_true",
        help="exit 0 only for SHELF_EXERCISED_CLEAN (load-clear question)",
    )
    class_p.add_argument(
        "--advisory",
        action="store_true",
        help="always exit 0 after printing the verdict (telemetry mode)",
    )
    class_p.set_defaults(func=cmd_classify)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
