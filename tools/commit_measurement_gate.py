#!/usr/bin/env python3
"""Gate: tip measurement composition is required, not advisory.

Exit 1 if:
  - composition file missing / unreadable (silence ≠ clean)
  - status is partial (any Unmeasured) when --require-complete
  - JSON claims a total while status is partial (lie)

Exit 0 only for CompleteVector (--require-complete) or any readable composition
when --require-complete is omitted (inspect mode).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--composition",
        type=Path,
        required=True,
        help="path to commit-measurement.json from compose_tip_from_receipts_dir",
    )
    parser.add_argument(
        "--require-complete",
        action="store_true",
        help="red unless status==complete (every tip axis Measured)",
    )
    args = parser.parse_args(argv)
    path = args.composition
    if not path.is_file():
        print(
            f"commit-measurement-gate RED: composition missing at {path} "
            f"(silence is not a clean tip — Unmeasured by absence)",
            file=sys.stderr,
        )
        return 1
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"commit-measurement-gate RED: unreadable {path}: {exc}", file=sys.stderr)
        return 1
    if not isinstance(payload, dict) or payload.get("kind") != "commit-measurement":
        print(
            f"commit-measurement-gate RED: {path} is not a commit-measurement object",
            file=sys.stderr,
        )
        return 1
    status = payload.get("status")
    if status == "partial" and "total" in payload:
        print(
            "commit-measurement-gate RED: partial composition claims total "
            "(total while Unmeasured is a lie)",
            file=sys.stderr,
        )
        return 1
    if args.require_complete:
        if status != "complete":
            unmeasured = payload.get("unmeasuredAxes") or list(
                (payload.get("axes") or {}).keys()
            )
            print(
                f"commit-measurement-gate RED: require-complete but status={status!r} "
                f"unmeasuredAxes={unmeasured!r}",
                file=sys.stderr,
            )
            return 1
        if "total" not in payload:
            print(
                "commit-measurement-gate RED: complete composition missing total",
                file=sys.stderr,
            )
            return 1
        print(
            f"commit-measurement-gate GREEN: complete total={payload.get('total')} "
            f"commit={payload.get('commitSha')}"
        )
        return 0
    print(f"commit-measurement-gate OK: status={status} (not require-complete)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
