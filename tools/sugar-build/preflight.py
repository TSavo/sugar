#!/usr/bin/env python3
"""Authenticate managed task preconditions before subject execution."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REFUSAL = 70


def _load_json_text(raw: str, label: str) -> object:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} is not valid JSON: {exc}") from exc


def falsify(plan: object, axes: object) -> int:
    if not isinstance(plan, dict) or not isinstance(plan.get("checks"), list):
        raise ValueError("precondition plan lacks checks")
    if not isinstance(axes, dict) or axes.get("schemaVersion") != 1:
        raise ValueError("precondition axes schemaVersion must be 1")
    rows = axes.get("axes")
    if not isinstance(rows, list):
        raise ValueError("precondition axes must be a list")
    checks = plan["checks"]
    uncovered = []
    for ordinal, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"precondition axis {ordinal} is not an object")
        axis = row.get("axis")
        kind = row.get("expectedKind")
        source = row.get("expectedSourcePrefix")
        if not all(isinstance(value, str) and value for value in (axis, kind, source)):
            raise ValueError(f"precondition axis {ordinal} is malformed")
        if not any(
            isinstance(check, dict)
            and check.get("kind") == kind
            and isinstance(check.get("source"), str)
            and check["source"].startswith(source)
            for check in checks
        ):
            uncovered.append(row)
            print(
                "sugarbin: crime=unpredicted-precondition-axis "
                f"axis={axis} expectedKind={kind} expectedSourcePrefix={source}",
                file=sys.stderr,
            )
    print(f"R_precondition_axes_discovered={len(rows)}")
    print(f"R_precondition_axes_predicted={len(rows) - len(uncovered)}")
    print(f"R_unpredicted_precondition_axes={len(uncovered)}")
    return REFUSAL if uncovered else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    falsifier = subparsers.add_parser("falsify")
    falsifier.add_argument("--plan-json", required=True)
    falsifier.add_argument("--axes", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        plan = _load_json_text(args.plan_json, "precondition plan")
        axes = json.loads(args.axes.read_text(encoding="utf-8"))
        return falsify(plan, axes)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        print(f"sugarbin: crime=precondition-instrument-invalid error={exc}", file=sys.stderr)
        return REFUSAL


if __name__ == "__main__":
    raise SystemExit(main())
