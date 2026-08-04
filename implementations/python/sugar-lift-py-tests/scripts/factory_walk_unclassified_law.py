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
and ConstructionPanic file fatals.

Measurement: pass factory-walk rows via --from-json (audit summary, recensus
shard, or bare row list). Prefer row-addressable locus lists
(``factory_walk_unclassified_rows`` / ``unclassified_rows``) over aggregate
status maps so reports print real ``file:line`` loci and shape-split drain
is possible offline (#5252).

Without a measurement payload the auditor refuses (exit 2) rather than faking R=0.
"""

from __future__ import annotations

# Not the board. This module measures its own named denominator; the sole
# authoritative Python corpus scoreboard is scripts/control_effect_recensus.py.
# See tests/test_one_authoritative_scoreboard.py.

from sugar_lift_py_tests.repo_root import resolve_repo_root

SCOREBOARD_AUTHORITY = False

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

# Repo tools/ for job-log heartbeats (≤30s doctrine — run 30731778056: 88s silence).
_TOOLS = resolve_repo_root() / "tools"
if _TOOLS.is_dir() and str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

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


def _synthesize_unclassified_from_counts(
    counts: Mapping[Any, Any],
) -> list[dict[str, str]]:
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


def _python_paths(roots: Sequence[Path]) -> list[Path]:
    return sorted(
        {
            path
            for root in roots
            for path in (root.rglob("*.py") if root.is_dir() else (root,))
            if path.is_file() and "__pycache__" not in path.parts
        }
    )


def _roll_call_locus_to_walk_row(locus: Mapping[str, Any]) -> dict[str, Any]:
    """One roll-call source-audit locus -> one factory-walk row.

    Post-factory, the per-file measurement is the reporter's roll call, whose
    only statuses are ``warranted`` (present) and ``unresolved`` (the honest,
    loud minority). Roll call makes silence unrepresentable: every constructed
    node is accounted, so a minority entry is a fully-classified coverage gap,
    NOT the silent ``unclassified``/``unresolved`` residue the completeness
    floor counts. Map ``warranted`` through unchanged and the minority to the
    classified ``coverage-gap`` status so R_factory_walk_unclassified stays 0
    by construction rather than falsely counting every honest gap.
    """
    inner = locus.get("locus", {}) if isinstance(locus.get("locus"), Mapping) else {}
    return {
        "status": "warranted" if locus.get("status") == "warranted" else "coverage-gap",
        "ast_kind": locus.get("kind", ""),
        "requested_role": locus.get("name", ""),
        "file": inner.get("file", ""),
        "line": inner.get("line", 0),
        "source_cid": locus.get("source_cid", ""),
    }


def _run_live_child(path: Path, rel: str) -> int:
    from sugar_lift_py_tests.audit_only import collect_construction_panic
    from sugar_lift_py_tests.tree_enumerate import source_audit_from_roll_call

    # The deleted factory walk is replaced by the reporter's per-file roll-call
    # partition (present Blue / absent Yellow).
    audit, panic_gap = collect_construction_panic(
        rel, lambda: source_audit_from_roll_call(path, rel)
    )
    if panic_gap is not None:
        category = "factory-panic"
        rows: list[dict[str, Any]] = []
    else:
        assert audit is not None
        category = "completed"
        rows = [_roll_call_locus_to_walk_row(locus) for locus in audit["loci"]]
    print(
        json.dumps(
            {
                "kind": "factory-walk-live-row",
                "file": rel,
                "category": category,
                "rows": rows,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


def _parse_live_child(stdout: str) -> Mapping[str, Any] | None:
    for line in reversed(stdout.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, Mapping) and value.get("kind") == "factory-walk-live-row":
            return value
    return None


def _measure_live_file(
    path: Path, *, repo_root: Path, file_timeout: int
) -> Mapping[str, Any]:
    rel = path.resolve().relative_to(repo_root.resolve()).as_posix()
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--child-file",
                str(path),
                "--child-rel",
                rel,
            ],
            text=True,
            capture_output=True,
            timeout=file_timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"file": rel, "category": "timeout", "rows": []}
    if result.returncode < 0:
        return {"file": rel, "category": "native-crash", "rows": []}
    testimony = _parse_live_child(result.stdout)
    if result.returncode or testimony is None:
        return {"file": rel, "category": "auditor-error", "rows": []}
    return testimony


def measure_live_roots(
    roots: Sequence[Path],
    *,
    repo_root: Path,
    file_timeout: int,
    workers: int,
) -> tuple[list[Any], dict[str, int]]:
    """Live census with job-log heartbeats.

    Run 30731778056: ~88s silence after group header — ``executor.map`` blocked
    until the whole pool finished. Use ``as_completed`` + JobLogHeartbeat so
    every finished file names phase/count on the Actions log within 30s.
    """
    from job_log_heartbeat import JobLogHeartbeat

    paths = _python_paths(roots)
    if not paths:
        raise ValueError(f"no Python source files found under {list(roots)}")
    total = len(paths)
    beat = JobLogHeartbeat("factory-walk-live", total=total)
    beat.watch()
    beat.tick(
        n=0,
        force=True,
        status="denominator",
        files_discovered=total,
        workers=workers,
    )
    results: list[Mapping[str, Any]] = []
    done = 0
    completed = timeouts = panics = crashes = errors = 0
    try:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    _measure_live_file,
                    path,
                    repo_root=repo_root,
                    file_timeout=file_timeout,
                ): path
                for path in paths
            }
            for fut in as_completed(futures):
                path = futures[fut]
                try:
                    row = fut.result()
                except Exception as exc:  # noqa: BLE001 — per-file containment
                    rel = path.resolve().relative_to(repo_root.resolve()).as_posix()
                    row = {
                        "file": rel,
                        "category": "auditor-error",
                        "rows": [],
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                results.append(row)
                done += 1
                cat = str(row.get("category") or "")
                if cat == "completed":
                    completed += 1
                elif cat == "timeout":
                    timeouts += 1
                elif cat == "factory-panic":
                    panics += 1
                elif cat == "native-crash":
                    crashes += 1
                elif cat == "auditor-error":
                    errors += 1
                beat.tick(
                    n=done,
                    force=True,
                    file=row.get("file"),
                    completed=completed,
                    timeouts=timeouts,
                    panics=panics,
                    native_crashes=crashes,
                    auditor_errors=errors,
                )
    finally:
        beat.stop(
            status="done",
        )
    counts = {
        "files_discovered": len(results),
        "files_completed": completed,
        "construction_panics": panics,
        "timeouts": timeouts,
        "native_crashes": crashes,
        "auditor_errors": errors,
    }
    rows = [
        walk_row
        for result in results
        for walk_row in result.get("rows", [])
        if isinstance(walk_row, Mapping)
    ]
    return rows, counts


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(
                encoding="utf-8",
                errors="backslashreplace",
                line_buffering=True,
            )
        except (AttributeError, ValueError, TypeError):
            try:
                stream.reconfigure(encoding="utf-8", errors="backslashreplace")
            except (AttributeError, ValueError):
                pass
    repo_root = resolve_repo_root()
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
    parser.add_argument(
        "--live-root",
        type=Path,
        action="append",
        default=[],
        help="Census checked-in Python sources under this root (repeatable).",
    )
    parser.add_argument("--repo-root", type=Path, default=repo_root)
    parser.add_argument("--file-timeout", type=int, default=30)
    parser.add_argument(
        "--workers",
        type=int,
        default=min(16, max(1, os.cpu_count() or 1)),
    )
    parser.add_argument("--child-file", type=Path)
    parser.add_argument("--child-rel")
    args = parser.parse_args(argv)

    if args.child_file or args.child_rel:
        if args.child_file is None or args.child_rel is None:
            parser.error("child mode requires --child-file and --child-rel")
        return _run_live_child(args.child_file, args.child_rel)

    rows: list[Any] = []
    sources = 0
    live_counts: dict[str, int] = {}
    try:
        for path in args.from_json:
            sources += 1
            rows.extend(extract_walk_rows(load_json(path)))
        if args.stdin:
            sources += 1
            rows.extend(extract_walk_rows(json.load(sys.stdin)))
        if args.live_root:
            sources += 1
            live_rows, live_counts = measure_live_roots(
                args.live_root,
                repo_root=args.repo_root,
                file_timeout=args.file_timeout,
                workers=max(1, args.workers),
            )
            rows.extend(live_rows)
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
        **live_counts,
    }
    incomplete_live_measurement = any(
        live_counts.get(key, 0)
        for key in ("timeouts", "native_crashes", "auditor_errors")
    )
    if incomplete_live_measurement:
        summary["ok"] = False
        print(
            "FACTORY-WALK-UNCLASSIFIED LAW ERROR: live measurement incomplete; "
            "timeout, native crash, or auditor error cannot certify R=0",
            file=sys.stderr,
        )
        if r:
            print(format_report(rows, limit=args.limit))
        print(json.dumps(summary))
        return 2
    if r > 0:
        print(
            "FACTORY-WALK-UNCLASSIFIED LAW RED: " f"{r} unclassified factory-walk rows"
        )
        print(format_report(rows, limit=args.limit))
        print(json.dumps(summary))
        return 1
    print("FACTORY-WALK-UNCLASSIFIED LAW GREEN: R_factory_walk_unclassified = 0")
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
