#!/usr/bin/env python3
"""R_factory_walk_unclassified — permanent product-completeness floor.

silent=0 is necessary but not sufficient. Explicitly-unclassified factory-walk
rows (wire status ``unresolved``; internal status ``unclassified``) are honest
red residue — never success. Done requires them to reach zero: every source
site must resolve to warranted | support | inert | typed-effect | loud-panic,
none left unclassified.

R_factory_walk_unclassified = count of factory-walk rows whose status is
unclassified or unresolved. Exit 1 whenever R > 0. No baseline, no threshold,
no allowlist. Keep this axis separate from crashes, bare exceptions, timeouts,
and FactoryPanic file fatals.

Measurement: pass factory-walk rows via --from-json (audit summary, recensus
shard, or bare row list). Prefer row-addressable locus lists
(``factory_walk_unclassified_rows`` / ``unclassified_rows``) over aggregate
status maps so reports print real ``file:line`` loci and shape-split drain
is possible offline (#5252).

Without a measurement payload the auditor refuses (exit 2) rather than faking R=0.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from sugar_lift_py_tests.idd.factory_walk_unclassified_locus import (
    UNCLASSIFIED_STATUSES,
    extract_locus_list,
    is_unclassified_row,
    project_unclassified_locus,
    shape_split_unclassified,
)

# Re-export for tests and producers that import the law module by path.
__all__ = [
    "UNCLASSIFIED_STATUSES",
    "extract_walk_rows",
    "format_report",
    "is_unclassified_row",
    "main",
    "project_unclassified_locus",
    "r_factory_walk_unclassified",
    "shape_split_unclassified",
]


def _status_of(row: Any) -> str:
    if isinstance(row, Mapping):
        status = row.get("status")
        if status is None:
            return ""
        if hasattr(status, "value"):
            return str(status.value)
        return str(status)
    status = getattr(row, "status", None)
    if status is None:
        return ""
    if hasattr(status, "value"):
        return str(status.value)
    return str(status)


def r_factory_walk_unclassified(rows: Sequence[Any] | Iterable[Any]) -> int:
    return sum(1 for row in rows if is_unclassified_row(row))


def _synthesize_unclassified_from_counts(counts: Mapping[Any, Any]) -> list[dict[str, str]]:
    """Expand a status→count map into opaque unclassified/unresolved rows."""
    synthetic: list[dict[str, str]] = []
    for status_name in ("unclassified", "unresolved"):
        n = int(counts.get(status_name) or 0)
        synthetic.extend({"status": status_name} for _ in range(n))
    return synthetic


def _looks_like_walk_row(row: Any) -> bool:
    """True when a list element is a walk locus (has status), not a terminal-file row."""
    if isinstance(row, Mapping):
        return "status" in row
    return hasattr(row, "status")


def extract_walk_rows(payload: Any) -> list[Any]:
    """Pull factory-walk rows from common recensus / audit / DTO shapes.

    Preference order (shape-split capable first):
    1. Retained unclassified locus lists (row-addressable evidence)
    2. Full walk row lists
    3. Aggregate status maps (historical shards; synthesize opaque rows)
    4. Nested audit / R-only fallbacks
    """
    if payload is None:
        return []
    if isinstance(payload, list):
        return list(payload)
    if not isinstance(payload, Mapping):
        return []

    # Prefer retained locus lists so next-recensus shards print real file:line.
    loci = extract_locus_list(payload)
    if loci is not None:
        return list(loci)

    # Full walk lists (row objects with status) before aggregates when present.
    for key in ("factoryWalk", "factory_walk", "walk"):
        value = payload.get(key)
        if isinstance(value, list) and value and _looks_like_walk_row(value[0]):
            return list(value)
        if isinstance(value, list) and not value:
            return []

    # Bare "rows" only when elements look like walk loci (have status).
    rows = payload.get("rows")
    if isinstance(rows, list) and rows and _looks_like_walk_row(rows[0]):
        return list(rows)
    if isinstance(rows, list) and not rows:
        return []

    # Historical aggregate status maps — honest red count, opaque loci.
    for key in (
        "statusCounts",
        "status_counts",
        "factory_walk_statuses",
        "factory_walk_red_statuses",
        "factory_accounting",
    ):
        counts = payload.get(key)
        if isinstance(counts, Mapping):
            synthetic = _synthesize_unclassified_from_counts(counts)
            if synthetic:
                return synthetic

    # map-shaped factory_walk after list arm failed
    for key in ("factoryWalk", "factory_walk", "walk"):
        value = payload.get(key)
        if isinstance(value, Mapping):
            synthetic = _synthesize_unclassified_from_counts(value)
            if synthetic:
                return synthetic

    # nested accounting.factory (requests/datetime ledger shape)
    accounting = payload.get("accounting")
    if isinstance(accounting, Mapping):
        factory_counts = accounting.get("factory")
        if isinstance(factory_counts, Mapping):
            synthetic = _synthesize_unclassified_from_counts(factory_counts)
            if synthetic:
                return synthetic

    # Nested audit summary
    for key in ("factoryAuditSummary", "factory_audit_summary", "audit"):
        nested = payload.get(key)
        if isinstance(nested, Mapping):
            nested_rows = extract_walk_rows(nested)
            if nested_rows:
                return nested_rows

    # unresolvedSites alone still count (they are unclassified)
    sites = payload.get("unresolvedSites") or payload.get("unresolved_sites")
    if isinstance(sites, list):
        return list(sites)

    # R already computed (last resort — no loci)
    if "R_factory_walk_unclassified" in payload:
        n = int(payload["R_factory_walk_unclassified"] or 0)
        return [{"status": "unclassified"} for _ in range(n)]

    return []


def format_report(rows: Sequence[Any], *, limit: int = 50) -> str:
    r = r_factory_walk_unclassified(rows)
    offenders = [row for row in rows if is_unclassified_row(row)]
    lines = [
        f"R_factory_walk_unclassified = {r}",
        (
            "Replacement: register the missing source shape as a Sugar; factory "
            "constructs Sugar + SugarBody children; floor dispatch; cited value "
            "or genuine typed runtime effect. Unclassified is honest red residue "
            "— drain it, never reclassify as success."
        ),
        "",
        f"Unclassified rows (first {min(limit, len(offenders))} of {len(offenders)}):",
    ]
    for row in offenders[:limit]:
        if isinstance(row, Mapping):
            file = row.get("file") or row.get("path") or "?"
            line = row.get("line") or "?"
            reason = row.get("reason") or ""
            ast_kind = row.get("ast_kind") or row.get("astKind") or ""
            selected = row.get("selected") or ""
            role = row.get("role") or row.get("requested_role") or ""
            lines.append(
                f"{file}:{line}:unclassified ast={ast_kind!s} role={role!s} "
                f"selected={selected!s} — {reason}"
            )
        else:
            file = getattr(row, "file", "?")
            line = getattr(row, "line", "?")
            reason = getattr(row, "reason", "") or ""
            lines.append(f"{file}:{line}:unclassified — {reason}")
    return "\n".join(lines)


def load_json(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    return json.loads(text)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--from-json",
        type=Path,
        action="append",
        default=[],
        help=(
            "JSON path: factory-walk list, audit summary, or recensus shard. "
            "Repeatable; rows are concatenated."
        ),
    )
    parser.add_argument(
        "--stdin",
        action="store_true",
        help="Read one JSON document from stdin.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Max unclassified loci to print (default 50).",
    )
    args = parser.parse_args(argv)

    rows: list[Any] = []
    sources = 0
    try:
        for path in args.from_json:
            sources += 1
            rows.extend(extract_walk_rows(load_json(path)))
        if args.stdin:
            sources += 1
            rows.extend(extract_walk_rows(json.load(sys.stdin)))
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        # Loud structured failure — never a raw traceback-only process crash.
        print(
            "FACTORY-WALK-UNCLASSIFIED LAW ERROR: "
            f"failed to load measurement payload: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        print(
            json.dumps(
                {
                    "instrument": "R_factory_walk_unclassified",
                    "ok": False,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "R_factory_walk_unclassified": None,
                }
            )
        )
        return 2

    if sources == 0:
        print(
            "FACTORY-WALK-UNCLASSIFIED LAW ERROR: no measurement payload. "
            "Pass --from-json PATH and/or --stdin. Refusing to claim R=0 "
            "without measured factory-walk rows.",
            file=sys.stderr,
        )
        print(
            json.dumps(
                {
                    "instrument": "R_factory_walk_unclassified",
                    "ok": False,
                    "error_type": "MissingMeasurement",
                    "error": "no --from-json / --stdin payload",
                    "R_factory_walk_unclassified": None,
                }
            )
        )
        return 2

    r = r_factory_walk_unclassified(rows)
    summary = {
        "instrument": "R_factory_walk_unclassified",
        "ok": r == 0,
        "R_factory_walk_unclassified": r,
        "rows_measured": len(rows),
    }
    if r > 0:
        print(
            "FACTORY-WALK-UNCLASSIFIED LAW RED: "
            f"{r} unclassified factory-walk rows"
        )
        print(format_report(rows, limit=args.limit))
        print(json.dumps(summary))
        return 1
    print("FACTORY-WALK-UNCLASSIFIED LAW GREEN: R_factory_walk_unclassified = 0")
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
