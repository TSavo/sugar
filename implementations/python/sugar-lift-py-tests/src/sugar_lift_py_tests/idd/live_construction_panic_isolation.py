"""Live per-file isolation measure for #4013 residual.

Full-tree multi-file ``sugar lift --report`` still dies on the first
ConstructionPanic. Isolation lifts every assert-bearing file on the production
``lift_file_payload`` path so conservation can be gated while
``R_live_construction_panic_files`` stays a named residual axis.

Panic residual is ranked by structured ConstructionGap fingerprints (same
axes as ``corpus_fatal_triage`` / ``construction_panic_fronts``) so fatal
recensus and floor drain share one owner map.
"""

from __future__ import annotations

# Not the board. This module measures its own named denominator; the sole
# authoritative Python corpus scoreboard is scripts/control_effect_recensus.py.
# See tests/test_one_authoritative_scoreboard.py.
SCOREBOARD_AUTHORITY = False

import ast
import json
import os
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from sugar_lift_py_tests.audit_only import collect_construction_panic
from sugar_lift_py_tests.idd.construction_panic_fronts import (
    fingerprint_from_gap,
    fingerprint_label,
    rank_construction_panic_fronts,
)
from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source


def assert_bearing_py_files(root: Path) -> list[Path]:
    """Independent AST walk: every ``*.py`` under root that contains ``ast.Assert``."""
    out: list[Path] = []
    for path in sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        if any(isinstance(node, ast.Assert) for node in ast.walk(tree)):
            out.append(path)
    return out


def factory_engaged_empty_report() -> dict[str, Any]:
    """Factory instrument engaged, no spoken assert rows → gap partition."""
    return {
        "factoryAuditSummary": {"statusCounts": {"unresolved": 1}},
        "auditOnlyGaps": [],
    }


def panic_owner_from_message(message: str) -> str:
    """Fallback owner parse when structured gap is unavailable."""
    if "owner=" not in message:
        return "unknown"
    return message.split("owner=", 1)[1].split()[0]


def live_per_file_isolation_conservation(
    files: Sequence[Path],
    *,
    root: Path,
    package: str,
    progress_every: int = 20,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Production lift path per assert-bearing file; conservation + panic residual.

    Completed files feed the real lift payload into ``account_lift_coverage``.
    ConstructionPanic / other hard fails engage gap for that file's on-disk
    asserts (panic is loud, not silent). Aggregate delta must be 0.

    Returns a closed ranking payload including ``R_live_construction_panic_files``,
    ``owner_families``, and ``exact_fronts``.
    """
    from sugar_lift_py_tests.lift_rpc import lift_file_payload

    # Keep isolation telemetry readable; panics still raise, only log noise drops.
    os.environ.setdefault("SUGAR_ENGINE_LOG", os.devnull)

    completed = 0
    panic_rows: list[dict[str, Any]] = []
    other_rows: list[dict[str, Any]] = []
    on_disk_total = 0
    accounted_total = 0
    per_file: list[dict[str, Any]] = []
    engaged = factory_engaged_empty_report()
    file_list = list(files)

    for index, path in enumerate(file_list, start=1):
        rel = f"{package}/{path.relative_to(root).as_posix()}"
        src = path.read_text(encoding="utf-8", errors="replace")
        disk = census_source(src, file=rel)
        file_on_disk = len(disk.asserts)
        on_disk_total += file_on_disk
        try:
            payload, panic_gap = collect_construction_panic(
                rel,
                lambda: lift_file_payload(src, rel),
            )
            if panic_gap is None:
                assert payload is not None
                report = payload.to_rpc()
                body = account_lift_coverage(disk, report).to_json()
                status = "completed"
                completed += 1
            else:
                body = account_lift_coverage(disk, engaged).to_json()
                status = "construction_panic"
                gap = panic_gap.info
                fingerprint = fingerprint_from_gap(gap)
                panic_rows.append(
                    {
                        "file": rel,
                        "onDisk": file_on_disk,
                        "owner": gap.get("owner")
                        or panic_owner_from_message(panic_gap.message),
                        "gap": gap,
                        "fingerprint": list(fingerprint),
                        "front": fingerprint_label(fingerprint),
                        "message": panic_gap.message.splitlines()[0][:200],
                    }
                )
        except Exception as exc:  # noqa: BLE001 — residual taxonomy, not swallow
            body = account_lift_coverage(disk, engaged).to_json()
            status = "other"
            other_rows.append(
                {
                    "file": rel,
                    "onDisk": file_on_disk,
                    "kind": type(exc).__name__,
                    "message": str(exc).splitlines()[0][:200],
                }
            )

        totals = body["totals"]
        delta = int(totals["delta"])
        accounted = int(totals["accounted"])
        accounted_total += accounted
        per_file.append(
            {
                "file": rel,
                "onDisk": int(totals["onDisk"]),
                "accounted": accounted,
                "delta": delta,
                "status": status,
            }
        )
        if delta != 0:
            raise AssertionError(
                f"live isolation conservation delta must be 0 for {rel} "
                f"status={status}; onDisk={totals['onDisk']} accounted={accounted} "
                f"delta={delta}"
            )
        if progress_every > 0 and (
            index % progress_every == 0 or index == len(file_list)
        ):
            print(
                f"  [{package}-live-isolation] {index}/{len(file_list)} "
                f"completed={completed} panic={len(panic_rows)} "
                f"other={len(other_rows)}",
                flush=True,
            )

    ranking = rank_construction_panic_fronts(panic_rows)
    result: dict[str, Any] = {
        "package": package,
        "assert_files": len(file_list),
        "completed": completed,
        "construction_panic_files": len(panic_rows),
        "other_fail_files": len(other_rows),
        "onDisk": on_disk_total,
        "accounted": accounted_total,
        "delta": on_disk_total - accounted_total,
        "R_live_construction_panic_files": ranking["R_live_construction_panic_files"],
        # Prior instrument shape + structured ranking for fatal recensus.
        "owners": ranking["owners"],
        "owner_families": ranking["owner_families"],
        "exact_fronts": ranking["exact_fronts"],
        "owner_family_count": ranking["owner_family_count"],
        "exact_front_count": ranking["exact_front_count"],
        "panic_rows": panic_rows,
        "other_rows": other_rows,
        "perFile": per_file,
    }
    if meta:
        result["meta"] = dict(meta)
    top_fronts = [
        f"{row['count']}×{row['label']}" for row in ranking["exact_fronts"][:8]
    ]
    print(
        f"R[{package}-live-isolation]: onDisk={on_disk_total} "
        f"accounted={accounted_total} delta={result['delta']} "
        f"assert_files={len(file_list)} completed={completed} "
        f"R_live_construction_panic_files={len(panic_rows)} "
        f"R_other_fail_files={len(other_rows)} "
        f"owner_families={ranking['owners']} "
        f"exact_fronts={top_fronts}"
    )
    return result


def write_isolation_receipt(result: dict[str, Any], path: Path | str) -> Path:
    """Write ranked isolation result JSON (orientation receipt for recensus)."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return out


def maybe_write_isolation_receipt_from_env(
    result: dict[str, Any],
    *,
    env_var: str = "SUGAR_4013_ISOLATION_OUT",
) -> Path | None:
    """If ``SUGAR_4013_ISOLATION_OUT`` is set, write the ranked isolation JSON."""
    raw = os.environ.get(env_var)
    if not raw:
        return None
    return write_isolation_receipt(result, raw)
