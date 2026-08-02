#!/usr/bin/env python3
"""Enrollment roll call for claim-mass tripwire shards.

Roster = every pin in tools/claim_mass_tripwire_shards.pin_names().
Attended = identity-bound body with measurementClass=claim-mass-tripwires
and matching pin. Missing pin = UNMEASURED.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from claim_mass_tripwire_shards import pin_names  # noqa: E402


def find_attended(reports_dir: Path) -> dict[str, Path]:
    attended: dict[str, Path] = {}
    if not reports_dir.is_dir():
        return attended
    for path in sorted(reports_dir.rglob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        if payload.get("measurementClass") != "claim-mass-tripwires":
            continue
        pin = payload.get("pin")
        if isinstance(pin, str):
            attended.setdefault(pin, path)
    return attended


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports-dir", type=Path, required=True)
    parser.add_argument("--require-commit", default=None)
    args = parser.parse_args(argv)

    roster = pin_names()
    attended = find_attended(args.reports_dir)
    missing = [p for p in roster if p not in attended]
    crimes: list[str] = []

    for pin, path in attended.items():
        body = json.loads(path.read_text(encoding="utf-8"))
        if args.require_commit and body.get("measuredCommit") not in (
            None,
            args.require_commit,
        ):
            crimes.append(
                f"{pin}: measuredCommit {body.get('measuredCommit')!r} "
                f"!= {args.require_commit!r}"
            )
            missing.append(pin)
            continue
        if body.get("exitCode") not in (0, "0"):
            crimes.append(f"{pin}: exitCode={body.get('exitCode')} (tripwire red)")

    print("### claim-mass tripwire enrollment")
    print()
    print(f"- roster: `{len(roster)}` pins")
    print(f"- attended: `{len(attended)}`")
    print(f"- missing: `{len(missing)}`")
    print()
    print("| pin | spoke |")
    print("| --- | --- |")
    for pin in roster:
        spoke = "yes" if pin in attended and pin not in missing else "NO — UNMEASURED"
        print(f"| `{pin}` | {spoke} |")
    print()
    print(f"**R_claim_mass_pin_attendance = {len(set(missing))}**")
    if missing or crimes:
        for c in crimes:
            print(f"- `{c}`")
            print(f"::error::{c}", file=sys.stderr)
        for pin in sorted(set(missing)):
            print(f"- missing pin `{pin}`")
        return 1
    print("All claim-mass pins attended with exit 0.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
