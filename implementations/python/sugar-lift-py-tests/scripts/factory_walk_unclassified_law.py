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
shard, or bare row list). Pure functions are for recensus / tests. Without a
measurement payload the auditor refuses (exit 2) rather than faking R=0.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

# Wire + internal names for the same red residue.
UNCLASSIFIED_STATUSES = frozenset({"unclassified", "unresolved"})


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


def is_unclassified_row(row: Any) -> bool:
    return _status_of(row) in UNCLASSIFIED_STATUSES


def r_factory_walk_unclassified(rows: Sequence[Any] | Iterable[Any]) -> int:
    return sum(1 for row in rows if is_unclassified_row(row))


def extract_walk_rows(payload: Any) -> list[Any]:
    """Pull factory-walk rows from common recensus / audit / DTO shapes."""
    if payload is None:
        return []
    if isinstance(payload, list):
        return list(payload)
    if not isinstance(payload, Mapping):
        return []

    # Direct walk lists
    for key in ("factoryWalk", "factory_walk", "rows", "walk"):
        value = payload.get(key)
        if isinstance(value, list):
            return list(value)

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

    # statusCounts-only summary: synthesize opaque rows for the count
    counts = payload.get("statusCounts") or payload.get("status_counts")
    if isinstance(counts, Mapping):
        synthetic: list[dict[str, str]] = []
        for status_name in ("unclassified", "unresolved"):
            n = int(counts.get(status_name) or 0)
            synthetic.extend({"status": status_name} for _ in range(n))
        if synthetic:
            return synthetic

    # recensus shard: factory_walk_red_statuses.unclassified
    red = payload.get("factory_walk_red_statuses")
    if isinstance(red, Mapping):
        synthetic = []
        for status_name in ("unclassified", "unresolved"):
            n = int(red.get(status_name) or 0)
            synthetic.extend({"status": status_name} for _ in range(n))
        if synthetic:
            return synthetic

    # R already computed
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
            lines.append(
                f"{file}:{line}:unclassified ast={ast_kind!s} selected={selected!s} "
                f"— {reason}"
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
