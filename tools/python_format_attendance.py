#!/usr/bin/env python3
"""Enrollment roll call for python-format package shards."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from python_format_shards import format_units  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports-dir", type=Path, required=True)
    parser.add_argument("--require-commit", default=None)
    args = parser.parse_args(argv)

    roster = [Path(u).name for u in format_units()]
    attended: dict[str, Path] = {}
    if args.reports_dir.is_dir():
        for path in sorted(args.reports_dir.rglob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if payload.get("measurementClass") != "python-format":
                continue
            pkg = payload.get("package")
            if isinstance(pkg, str):
                attended.setdefault(pkg, path)

    missing = [p for p in roster if p not in attended]
    crimes = []
    for pkg, path in attended.items():
        body = json.loads(path.read_text(encoding="utf-8"))
        if args.require_commit and body.get("measuredCommit") not in (
            None,
            args.require_commit,
        ):
            crimes.append(f"{pkg}: commit mismatch")
            missing.append(pkg)
        elif body.get("exitCode") not in (0, "0"):
            crimes.append(f"{pkg}: black exitCode={body.get('exitCode')}")

    print("### python-format package enrollment")
    print(f"**R_python_format_attendance = {len(set(missing))}**")
    for p in roster:
        spoke = "yes" if p in attended and p not in missing else "NO"
        print(f"- `{p}`: {spoke}")
    if missing or crimes:
        for c in crimes:
            print(f"::error::{c}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
