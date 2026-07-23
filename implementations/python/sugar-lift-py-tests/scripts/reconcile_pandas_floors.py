#!/usr/bin/env python3
"""Reconcile five native pandas floor reports without interpreting absence as zero."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from pandas_floor_summary import SCHEMA, write_json

FLOORS = ("control-effect", "fatal-triage", "silent", "native-crash", "timeout")


def _summary(raw: Mapping[str, Any]) -> Mapping[str, Any]:
    nested = raw.get("floorSummary")
    return nested if isinstance(nested, Mapping) else raw


def reconcile(reports: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    missing = sorted(set(FLOORS) - set(reports))
    errors: list[str] = [f"missing floor: {name}" for name in missing]
    summaries: dict[str, Mapping[str, Any]] = {}
    for name in FLOORS:
        if name not in reports:
            continue
        row = _summary(reports[name])
        summaries[name] = row
        if row.get("kind") != SCHEMA:
            errors.append(f"{name}: wrong or absent native schema")
        if row.get("floor") != name:
            errors.append(f"{name}: floor identity mismatch")
        if row.get("measurement") != "measured":
            errors.append(f"{name}: measurement is not complete")
        corpus = row.get("corpus")
        rows = row.get("rows")
        if not isinstance(corpus, Mapping) or not isinstance(rows, list):
            errors.append(f"{name}: absent corpus or per-site rows")
            continue
        files = corpus.get("files")
        if not isinstance(files, list) or not files:
            errors.append(f"{name}: empty corpus is not a measured zero")
        elif len(rows) != len(files):
            errors.append(f"{name}: per-site row conservation failure")
    manifests = {
        str(row.get("corpus", {}).get("manifestCid"))
        for row in summaries.values()
        if isinstance(row.get("corpus"), Mapping)
    }
    if len(manifests) != 1 or "None" in manifests:
        errors.append("five floors do not name one identical corpus manifest")
    totals = {
        name: dict(row.get("totals", {}))
        for name, row in summaries.items()
        if isinstance(row.get("totals"), Mapping)
    }
    r_total = sum(
        value
        for floor_totals in totals.values()
        for key, value in floor_totals.items()
        if key.startswith("R_") and isinstance(value, int)
    )
    return {
        "kind": "pandas-validated-summary-v1",
        "measurement": "measured" if not errors else "unmeasurable",
        "corpusManifestCid": next(iter(manifests)) if len(manifests) == 1 else None,
        "floors": totals,
        "R_total": r_total,
        "verdict": "green" if not errors and r_total == 0 else "red",
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for floor in FLOORS:
        parser.add_argument("--" + floor, type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("validated-summary.json"))
    args = parser.parse_args()
    reports = {
        floor: json.loads(getattr(args, floor.replace("-", "_")).read_text(encoding="utf-8"))
        for floor in FLOORS
    }
    result = reconcile(reports)
    write_json(args.output, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["verdict"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
