#!/usr/bin/env python3
"""Validate a recovered wall frontier and render its telemetry vector."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def frontier_vector(path: Path) -> tuple[int, int, int]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("frontier must be a JSON object")
    if payload.get("kind") != "recovered-construction-audit":
        raise ValueError("frontier kind must be recovered-construction-audit")
    if payload.get("recoveryOverride") is not True:
        raise ValueError("frontier must carry the recovery override")
    census = payload.get("census")
    if (
        not isinstance(census, dict)
        or census.get("kind") != "recovered-frontier-census"
    ):
        raise ValueError("frontier must carry a recovered census receipt")
    counts: dict[str, int] = {}
    for field in (
        "sourceFilesEnumerated",
        "sourceBodiesDemanded",
        "auditLeavesCompleted",
    ):
        value = census.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(
                f"frontier census field {field} must be a non-negative integer"
            )
        counts[field] = value
    if counts["sourceFilesEnumerated"] != counts["sourceBodiesDemanded"]:
        raise ValueError("frontier source census does not conserve body demands")
    fields = ("panics", "suppressedDescendants", "effects")
    rows = []
    for field in fields:
        value = payload.get(field)
        if not isinstance(value, list):
            raise TypeError(f"frontier field {field} must be a JSON array")
        rows.append(len(value))
    status = payload.get("status")
    if status == "valid-empty":
        if any(counts.values()) or rows[0] != 0:
            raise ValueError("valid-empty frontier requires a zero census")
    elif status == "complete":
        if counts["sourceFilesEnumerated"] == 0 or rows[0] != 0:
            raise ValueError("complete frontier requires a nonempty clean census")
    elif status == "failed":
        if rows[0] == 0:
            raise ValueError("failed frontier requires typed panic telemetry")
    else:
        raise ValueError(f"frontier terminal status is not closed: {status!r}")
    return rows[0], rows[1], rows[2]


def markdown(wall: str, run_url: str, vector: tuple[int, int, int]) -> str:
    independent, suppressed, effects = vector
    return (
        f"## {wall} wall telemetry\n\n"
        f"- independent: {independent}\n"
        f"- suppressed: {suppressed}\n"
        f"- effects: {effects}\n"
        f"- run: {run_url}\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frontier", type=Path, required=True)
    parser.add_argument("--wall", required=True)
    parser.add_argument("--run-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rendered = markdown(args.wall, args.run_url, frontier_vector(args.frontier))
    args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
