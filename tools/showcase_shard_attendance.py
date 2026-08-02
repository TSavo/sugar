#!/usr/bin/env python3
"""Enrollment roll call for showcase CI shards.

Roster: shard-00 .. shard-(N-1) (default N=4).
Attended: identity-bound body with measurementClass=test-showcases and
matching shardIndex. Missing shard = UNMEASURED.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DEFAULT_SHARD_COUNT = 4


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports-dir", type=Path, required=True)
    parser.add_argument("--shard-count", type=int, default=DEFAULT_SHARD_COUNT)
    parser.add_argument("--require-commit", default=None)
    args = parser.parse_args(argv)

    roster = list(range(args.shard_count))
    attended: dict[int, Path] = {}
    if args.reports_dir.is_dir():
        for path in sorted(args.reports_dir.rglob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if payload.get("measurementClass") != "test-showcases":
                continue
            idx = payload.get("shardIndex")
            if isinstance(idx, int):
                attended.setdefault(idx, path)

    missing = [i for i in roster if i not in attended]
    crimes: list[str] = []
    for idx, path in attended.items():
        body = json.loads(path.read_text(encoding="utf-8"))
        if args.require_commit and body.get("measuredCommit") not in (
            None,
            args.require_commit,
        ):
            crimes.append(
                f"shard-{idx:02d}: measuredCommit {body.get('measuredCommit')!r} "
                f"!= {args.require_commit!r}"
            )
            if idx not in missing:
                missing.append(idx)
        if body.get("exitCode") not in (0, "0"):
            crimes.append(
                f"shard-{idx:02d}: exitCode={body.get('exitCode')} (showcase red)"
            )

    print("### showcase shard enrollment")
    print(f"- roster: `{args.shard_count}` shards")
    print(f"- attended: `{len(attended)}`")
    print(f"**R_showcase_shard_attendance = {len(set(missing))}**")
    for i in roster:
        spoke = "yes" if i in attended and i not in missing else "NO — UNMEASURED"
        print(f"- `shard-{i:02d}`: {spoke}")
    if missing or crimes:
        for c in crimes:
            print(f"::error::{c}", file=sys.stderr)
        return 1
    print("All showcase shards attended with exit 0.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
