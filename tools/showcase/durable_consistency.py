#!/usr/bin/env python3
"""Durable consistency law for bulk crate showcases (Lane A / A2).

Prove and durable verify must use the SAME consistency law for the good twin:

  DISCHARGE  = no `unsatisfied` (no false refutation)
             + at least one `discharged` (substantive row)
             + every `refused` row is honest vacuity (#2813 NoSibling)
  REFUSE     = at least one `unsatisfied`

Historically durable required *every* consistency row `discharged`, while prove
only forbade `unsatisfied`. Under #2813 lone-EUF vacuity that made good twins
pass prove and fail durable on the same receipt (A2 expected-discharge-got-refused
for url/semver/uuid/num-integer/bitflags/forall-loop).
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

VACUOUS_MARKERS = (
    "vacuous",
    "no sibling to contradict",
    "NoSiblingToContradict",
)


def is_consistency_row(row: Mapping[str, Any]) -> bool:
    prop = row.get("property") or ""
    return prop.startswith("consistency:") and "witness-package" not in prop


def is_witness_package_row(row: Mapping[str, Any]) -> bool:
    return "witness-package" in (row.get("property") or "")


def is_honest_vacuous_refuse(row: Mapping[str, Any]) -> bool:
    if row.get("status") != "refused":
        return False
    reason = str(row.get("reason") or "")
    return any(marker in reason for marker in VACUOUS_MARKERS)


def check_durable_consistency(
    rows: Sequence[Mapping[str, Any]],
    *,
    suite: str,
    expect: str,
) -> list[str]:
    """Return consistency statuses, or raise SystemExit with FAIL[...] text.

    ``expect`` is ``DISCHARGE`` (good twin) or ``REFUSE`` (bad twin).
    """
    consistency_rows = [r for r in rows if is_consistency_row(r)]
    statuses = [str(r.get("status") or "") for r in consistency_rows]
    if not consistency_rows:
        raise SystemExit(f"FAIL[{suite}]: durable verify has no consistency rows")

    if expect == "DISCHARGE":
        if "unsatisfied" in statuses:
            raise SystemExit(
                f"FAIL[{suite}]: durable consistency has unsatisfied "
                f"(false refutation of a true claim): {statuses}"
            )
        if "discharged" not in statuses:
            raise SystemExit(
                f"FAIL[{suite}]: durable consistency has no discharged row "
                f"(need at least one substantive discharge): {statuses}"
            )
        bad_refuses = [
            r
            for r in consistency_rows
            if r.get("status") == "refused" and not is_honest_vacuous_refuse(r)
        ]
        if bad_refuses:
            sample = bad_refuses[0]
            raise SystemExit(
                f"FAIL[{suite}]: durable consistency refused non-vacuously "
                f"({sample.get('property')}: {sample.get('reason')})"
            )
    elif expect == "REFUSE":
        if "unsatisfied" not in statuses:
            raise SystemExit(
                f"FAIL[{suite}]: durable consistency statuses {statuses}"
            )
    else:
        raise SystemExit(
            f"FAIL[{suite}]: unknown expect_consistency={expect!r} "
            f"(want DISCHARGE or REFUSE)"
        )
    return statuses


def classify_refuse_reasons(
    rows: Iterable[Mapping[str, Any]],
) -> dict[str, int]:
    """Bucket refused consistency rows by reason class (instrument R)."""
    counts: dict[str, int] = {}
    for row in rows:
        if not is_consistency_row(row) or row.get("status") != "refused":
            continue
        reason = str(row.get("reason") or "")
        if any(m in reason for m in VACUOUS_MARKERS):
            key = "vacuous-no-sibling"
        elif "lacks required provenance" in reason or "provenance KIND" in reason:
            key = "missing-provenance-kind"
        elif "witness" in reason.lower():
            key = "witness-related"
        elif reason:
            key = "other-refused"
        else:
            key = "refused-no-reason"
        counts[key] = counts.get(key, 0) + 1
    return counts
