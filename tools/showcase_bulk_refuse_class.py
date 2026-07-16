#!/usr/bin/env python3
"""Bulk-crate consistency refuse class instrument (Lane A / A2).

Measures the prove/durable law split that made good twins pass prove (no
unsatisfied) and fail durable (required all discharged) under #2813 vacuity.

Modes:
  --self-test     planted receipts trip parity + classify buckets
  --from-receipt  classify refuse reasons in one verify/prove JSON
  --from-dir      classify every *.json under a directory

R = count of non-vacuous refuse buckets + parity-offender flag when a receipt
would fail the old all-discharged durable law but pass the aligned law.

Exit 0 when self-test passes / classification completes.
Exit 1 on self-test failure.
Exit 2 on bad usage.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.showcase.durable_consistency import (  # noqa: E402
    check_durable_consistency,
    classify_refuse_reasons,
    is_consistency_row,
)
from tools.showcase.json_get import load_receipt  # noqa: E402

SCHEMA = "sugar.showcase.bulk_refuse.v1"


def old_all_discharged_fails(statuses: list[str]) -> bool:
    return bool(statuses) and any(s != "discharged" for s in statuses)


def analyze_receipt(path: Path) -> dict[str, object]:
    receipt = load_receipt(path)
    rows = receipt.get("rows") or []
    consistency = [r for r in rows if is_consistency_row(r)]
    statuses = [str(r.get("status") or "") for r in consistency]
    buckets = classify_refuse_reasons(rows)
    parity_offender = False
    aligned_ok = False
    try:
        check_durable_consistency(rows, suite=path.name, expect="DISCHARGE")
        aligned_ok = True
    except SystemExit:
        aligned_ok = False
    if aligned_ok and old_all_discharged_fails(statuses):
        # Would pass prove-aligned law, fail old durable-all-discharged law.
        parity_offender = True
    return {
        "path": str(path),
        "n_consistency": len(consistency),
        "statuses": {
            "discharged": statuses.count("discharged"),
            "refused": statuses.count("refused"),
            "unsatisfied": statuses.count("unsatisfied"),
            "other": sum(
                1
                for s in statuses
                if s not in ("discharged", "refused", "unsatisfied")
            ),
        },
        "refuse_buckets": buckets,
        "parity_offender": parity_offender,
        "aligned_discharge_ok": aligned_ok,
    }


def self_test() -> None:
    # Good: substantive + honest vacuous refuse → aligned OK, old law fails.
    mixed = [
        {
            "property": "consistency:a#euf#x::assertion",
            "status": "discharged",
            "reason": "sat",
        },
        {
            "property": "consistency:b#euf#y::assertion",
            "status": "refused",
            "reason": (
                "consistency check vacuous: single constraint has no sibling "
                "to contradict and no covering universe joins the left-operand "
                "term — not a substantive discharge"
            ),
        },
    ]
    statuses = check_durable_consistency(mixed, suite="plant", expect="DISCHARGE")
    assert "discharged" in statuses and "refused" in statuses
    assert old_all_discharged_fails(statuses)
    assert classify_refuse_reasons(mixed) == {"vacuous-no-sibling": 1}

    # Good: all discharged → both laws OK.
    all_d = [
        {
            "property": "consistency:a#euf#x::assertion",
            "status": "discharged",
            "reason": "sat",
        }
    ]
    check_durable_consistency(all_d, suite="plant", expect="DISCHARGE")
    assert not old_all_discharged_fails(["discharged"])

    # Bad twin: need unsatisfied.
    bad = [
        {
            "property": "consistency:a#euf#x::assertion",
            "status": "unsatisfied",
            "reason": "equals both",
        }
    ]
    check_durable_consistency(bad, suite="plant", expect="REFUSE")

    # Non-vacuous refuse must stay red under DISCHARGE.
    prov = [
        {
            "property": "consistency:a#euf#x::assertion",
            "status": "discharged",
            "reason": "sat",
        },
        {
            "property": "consistency:b#euf#y::assertion",
            "status": "refused",
            "reason": "contract memento lacks required provenance KIND",
        },
    ]
    try:
        check_durable_consistency(prov, suite="plant", expect="DISCHARGE")
        raise AssertionError("provenance refuse must not pass DISCHARGE")
    except SystemExit as e:
        assert "non-vacuously" in str(e)

    # Pure vacuous wall (no discharge) is the honest #2813 lone-EUF floor.
    pure = [
        {
            "property": "consistency:a#euf#x::assertion",
            "status": "refused",
            "reason": "consistency check vacuous: single constraint has no sibling",
        }
    ]
    check_durable_consistency(pure, suite="plant", expect="DISCHARGE")

    # Pure refuse without reason text (verify receipt often omits reason) is OK.
    pure_silent = [
        {"property": "consistency:a#euf#x::assertion", "status": "refused", "reason": ""},
    ]
    check_durable_consistency(pure_silent, suite="plant", expect="DISCHARGE")

    print("PASS: bulk refuse class instrument (parity + buckets)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--from-receipt", type=Path, default=None)
    ap.add_argument("--from-dir", type=Path, default=None)
    ap.add_argument("--json-only", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        try:
            self_test()
        except Exception as e:
            print(f"FAIL: {e}", file=sys.stderr)
            return 1
        if not args.from_receipt and not args.from_dir:
            return 0

    reports: list[dict[str, object]] = []
    if args.from_receipt:
        reports.append(analyze_receipt(args.from_receipt))
    if args.from_dir:
        for path in sorted(args.from_dir.rglob("*.json")):
            try:
                reports.append(analyze_receipt(path))
            except SystemExit:
                continue

    if not reports and not args.self_test:
        print(
            "usage: showcase_bulk_refuse_class.py --self-test "
            "[--from-receipt PATH | --from-dir DIR]",
            file=sys.stderr,
        )
        return 2

    payload = {
        "schema": SCHEMA,
        "R_parity_offenders": sum(1 for r in reports if r.get("parity_offender")),
        "reports": reports,
    }
    if args.json_only:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print("BULK REFUSE CLASS SCOREBOARD")
    print(f"schema: {SCHEMA}")
    print(f"R_parity_offenders={payload['R_parity_offenders']}  receipts={len(reports)}")
    for r in reports:
        print(
            f"  {r['path']}: statuses={r['statuses']} "
            f"buckets={r['refuse_buckets']} "
            f"parity_offender={r['parity_offender']} "
            f"aligned_ok={r['aligned_discharge_ok']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
