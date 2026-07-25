#!/usr/bin/env python3
"""Gate: suite-report.json is authoritative only when identity is resolved.

Fails (exit 1) before an artifact may be labeled authoritative if any required
identity field is absent, malformed, or ``{"unavailable": ...}``.

Also re-reads the report after optional promotion so a populated intermediate
value cannot be lost when writing ``suite-report.json``.

Usage:
    python3 tools/suite_measurement_identity_gate.py \\
        --report suite-report.json \\
        --require-commit "$GITHUB_SHA" \\
        [--promote] \\
        [--require-authoritative]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from suite_measurement_identity import (
    identity_errors,
    is_authoritative,
    load_report,
    promote_identity_fields,
    rewrite_promoted,
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument(
        "--require-commit",
        default=None,
        help="40-char hex SHA the report must name as measuredCommit",
    )
    parser.add_argument(
        "--promote",
        action="store_true",
        help="rewrite the report with promoted top-level identity fields first",
    )
    parser.add_argument(
        "--require-authoritative",
        action="store_true",
        default=True,
        help="exit non-zero when identity is unresolved (default: true)",
    )
    parser.add_argument(
        "--allow-provisional",
        action="store_true",
        help="print errors but exit 0 (provisional evidence; not authoritative)",
    )
    args = parser.parse_args(argv)

    if not args.report.is_file():
        print(
            f"suite-measurement-identity-gate: missing report {args.report}",
            file=sys.stderr,
        )
        return 1

    if args.promote:
        report = rewrite_promoted(str(args.report))
    else:
        report = load_report(str(args.report))
        # Still re-read after a no-op write? promote path covers serialization.
        # For gate-only, re-read is the post-serialization check against disk.
        report = load_report(str(args.report))

    errors = identity_errors(report, require_commit=args.require_commit)
    payload = {
        "schemaVersion": 1,
        "report": str(args.report),
        "authoritative": not errors,
        "errors": errors,
        "measuredCommit": report.get("measuredCommit"),
        "sourceStamp": (
            (report.get("sourceStamp") or {}).get("value")
            if isinstance(report.get("sourceStamp"), dict)
            else report.get("sourceStamp")
        ),
        "testExtraInputHash": report.get("testExtraInputHash"),
        "environmentIdentityHash": report.get("environmentIdentityHash"),
        "counts": report.get("counts"),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))

    if errors and not args.allow_provisional:
        print(
            "suite-measurement-identity-gate: RED — identity unresolved; "
            "do not publish as authoritative:",
            file=sys.stderr,
        )
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    if errors and args.allow_provisional:
        print(
            "suite-measurement-identity-gate: provisional (identity unresolved); "
            "not authoritative",
            file=sys.stderr,
        )
        return 0
    print("suite-measurement-identity-gate: GREEN — authoritative identity resolved")
    return 0


if __name__ == "__main__":
    # Allow `python tools/suite_measurement_identity_gate.py` from repo root
    # with tools/ on sys.path (workflow already sets PYTHONPATH=tools).
    sys.exit(main())
