#!/usr/bin/env python3
"""Enrollment roll call for suite shards — completeness without a shared hub.

THE LAW
-------
Each shard writes its own identity-bound suite-report.json. There is no merge
into a singleton report (a shared identity hub). Completeness is enrollment:

    roster = {shard-00, ..., shard-(N-1)}
    attended = shards with a present, identity-resolved report for this commit
    R_suite_shard_attendance = |roster \\ attended|

A missing shard is UNMEASURED, not a smaller pass count. Silence is not a
clean suite. Same shape as ``tools/heavy_measurement_attendance.py`` for heavy
measurement classes: enrollment is existence.

Usage:
    python3 tools/python_package_suite_shard_attendance.py \\
        --reports-dir runs/ \\
        --shard-count 8 \\
        --require-commit "$GITHUB_SHA" \\
        --order canonical
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Local imports: tools/ is on PYTHONPATH in CI; load by path when not.
_TOOLS = Path(__file__).resolve().parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from python_package_suite_shards import SHARD_COUNT, roster_ids  # noqa: E402
from python_suite_identity_gate import gate, render_resolved_receipt  # noqa: E402


class ShardAttendanceError(RuntimeError):
    """Roll call failed: missing shards or unresolved identity."""


def _load_report(path: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def find_shard_reports(reports_dir: Path, order: str) -> dict[int, tuple[Path, dict]]:
    """Map shard_index -> (path, report) for reports under reports_dir.

    Accepts either:
      runs/python-package-suite-{order}-shard-07/suite-report.json
      runs/**/suite-report.json with label/shardIndex fields
    """
    found: dict[int, tuple[Path, dict]] = {}
    if not reports_dir.is_dir():
        return found

    for path in sorted(reports_dir.rglob("suite-report.json")):
        report = _load_report(path)
        if report is None:
            continue
        # Prefer explicit shardIndex when the reporter recorded it.
        shard_index = report.get("shardIndex")
        label = str(report.get("label") or "")
        report_order = report.get("order") or "canonical"

        if order and report_order != order and f"-{order}" not in label:
            # Discrimination uploads use order in the artifact dirname/label.
            parent = path.parent.name
            if order not in parent and order not in label:
                continue

        if shard_index is None:
            # Parse ...-shard-07 or shard-07 from path / label.
            import re

            match = re.search(r"shard-(\d+)", f"{path.parent.name} {label}")
            if not match:
                continue
            shard_index = int(match.group(1))
        else:
            shard_index = int(shard_index)

        # Keep the first path; prefer identity-richer later if needed.
        if shard_index not in found:
            found[shard_index] = (path, report)
    return found


def attendance(
    *,
    reports_dir: Path,
    shard_count: int,
    require_commit: str | None,
    order: str,
) -> tuple[list[str], list[str], list[str]]:
    """Return (attended_ids, missing_ids, crimes).

    crimes non-empty means at least one present shard failed the identity gate
    or disagreed about commit/shard metadata — still not a clean suite.
    """
    roster = roster_ids(shard_count)
    found = find_shard_reports(reports_dir, order)
    attended: list[str] = []
    missing: list[str] = []
    crimes: list[str] = []

    for i, shard_id in enumerate(roster):
        if i not in found:
            missing.append(shard_id)
            continue
        path, report = found[i]
        # Identity gate per shard — each proves its own provenance.
        gate_crimes = gate(report, require_commit)
        if gate_crimes:
            crimes.append(f"{shard_id} at {path}: identity UNRESOLVED")
            for crime in gate_crimes:
                crimes.append(f"  {crime}")
            # Present but unresolved is not attendance.
            missing.append(shard_id)
            continue
        receipt_path = path.with_name("identity-gate.md")
        try:
            receipt = receipt_path.read_text(encoding="utf-8")
        except OSError as error:
            crimes.append(
                f"{shard_id} at {receipt_path}: identity gate receipt missing: {error}"
            )
            missing.append(shard_id)
            continue
        if not receipt:
            crimes.append(
                f"{shard_id} at {receipt_path}: identity gate receipt empty; "
                "presence is not testimony"
            )
            missing.append(shard_id)
            continue
        expected_receipt = render_resolved_receipt(report) + "\n"
        if receipt != expected_receipt:
            crimes.append(
                f"{shard_id} at {receipt_path}: identity gate receipt "
                "unparseable or disagrees with suite-report.json"
            )
            missing.append(shard_id)
            continue
        # Shard self-description must match enrollment seat when present.
        if report.get("shardIndex") is not None and int(report["shardIndex"]) != i:
            crimes.append(
                f"{shard_id}: report shardIndex {report.get('shardIndex')} "
                f"!= enrolled seat {i}"
            )
            missing.append(shard_id)
            continue
        if (
            report.get("shardCount") is not None
            and int(report["shardCount"]) != shard_count
        ):
            crimes.append(
                f"{shard_id}: report shardCount {report.get('shardCount')} "
                f"!= roster size {shard_count}"
            )
            missing.append(shard_id)
            continue
        attended.append(shard_id)

    return attended, missing, crimes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reports-dir",
        required=True,
        type=Path,
        help="directory of downloaded per-shard artifacts",
    )
    parser.add_argument(
        "--shard-count",
        type=int,
        default=SHARD_COUNT,
        help=f"enrolled shard count (default {SHARD_COUNT})",
    )
    parser.add_argument(
        "--require-commit",
        default=None,
        help="commit each shard report must bind",
    )
    parser.add_argument(
        "--order",
        default="canonical",
        help="suite-order label filter (canonical / reversed / shuffled)",
    )
    parser.add_argument(
        "--advisory",
        action="store_true",
        help="print minority without failing",
    )
    args = parser.parse_args(argv)

    attended, missing, crimes = attendance(
        reports_dir=args.reports_dir,
        shard_count=args.shard_count,
        require_commit=args.require_commit,
        order=args.order,
    )
    roster = roster_ids(args.shard_count)

    print(f"### suite shard attendance ({args.order}) — enrollment is existence")
    print()
    print(f"- roster size: `{len(roster)}`")
    print(f"- attended (identity-resolved): `{len(attended)}`")
    print(f"- missing / unresolved: `{len(missing)}`")
    print()
    print("| shard | spoke |")
    print("| --- | --- |")
    for shard_id in roster:
        spoke = "yes" if shard_id in attended else "NO — UNMEASURED"
        print(f"| `{shard_id}` | {spoke} |")
    print()
    print(f"**R_suite_shard_attendance = {len(missing)}**")
    if missing:
        print()
        print(
            "These shards did not report an identity-resolved suite-report. "
            "Their silence is NOT a smaller suite — R is UNMEASURED:"
        )
        for shard_id in missing:
            print(f"- `{shard_id}`")
    if crimes:
        print()
        print("Identity / enrollment crimes on present artifacts:")
        for crime in crimes:
            print(f"- `{crime}`")
            print(f"::error::{crime}", file=sys.stderr)

    if missing or crimes:
        return 0 if args.advisory else 1
    print()
    print(
        f"All {len(roster)} shards attended; each is identity-resolved. "
        "No shared aggregate was required."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
