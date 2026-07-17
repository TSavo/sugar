"""Rank live FactoryPanic fronts for isolation and fatal recensus.

The production gap is a typed ``FactoryGapInfo``. Live isolation (#4013) and
fatal triage (#4684/#4775) must rank the same fingerprint so recensus and
drain work from one owner map:

  (owner, gap_kind, gap_locus, observed, requested)

Owner-family totals collapse the fingerprint to its owner only. Exact-front
totals preserve the full five-tuple. Neither axis softens the panic; both
name construction residual so the next floor has a measured address.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

# Fields that form the exact-front identity (order is load-bearing for display).
FINGERPRINT_FIELDS: tuple[str, ...] = (
    "owner",
    "gap_kind",
    "gap_locus",
    "observed",
    "requested",
)


def fingerprint_from_gap(gap: Mapping[str, Any] | None) -> tuple[str, ...]:
    """Exact-front identity from a gap JSON / ``FactoryGapInfo.to_json()`` map."""
    payload = gap if isinstance(gap, Mapping) else {}
    return tuple(str(payload.get(field) or "") for field in FINGERPRINT_FIELDS)


def fingerprint_from_panic_info(info: Any) -> tuple[str, ...]:
    """Exact-front identity from a live ``FactoryGapInfo`` (or gap-like object)."""
    if info is None:
        return fingerprint_from_gap(None)
    to_json = getattr(info, "to_json", None)
    if callable(to_json):
        return fingerprint_from_gap(to_json())
    return fingerprint_from_gap(
        {
            "owner": getattr(info, "owner", ""),
            "gap_kind": getattr(info, "gap_kind", ""),
            "gap_locus": getattr(info, "gap_locus", ""),
            "observed": getattr(info, "observed", ""),
            "requested": getattr(info, "requested", ""),
        }
    )


def fingerprint_label(fingerprint: tuple[str, ...]) -> str:
    """Human rank line: ``owner / kind / locus / observed / requested``."""
    parts = list(fingerprint) + [""] * (len(FINGERPRINT_FIELDS) - len(fingerprint))
    return " / ".join(parts[: len(FINGERPRINT_FIELDS)])


def rank_factory_panic_fronts(
    rows: Iterable[Mapping[str, Any]],
    *,
    fingerprint_key: str = "fingerprint",
    file_key: str = "file",
    owner_key: str = "owner",
    examples_per_front: int = 5,
) -> dict[str, Any]:
    """Aggregate ranked owner families and exact fronts from panic rows.

    Each row should carry either:
    - ``fingerprint``: 5-tuple / sequence, or
    - ``gap``: mapping with the fingerprint fields, or
    - ``owner`` alone (degrades to owner-only exact front).

    Returns a closed ranking payload for instruments and recensus docs.
    """
    owner_counts: Counter[str] = Counter()
    front_counts: Counter[tuple[str, ...]] = Counter()
    front_examples: dict[tuple[str, ...], list[str]] = defaultdict(list)
    owner_examples: dict[str, list[str]] = defaultdict(list)

    total = 0
    for row in rows:
        total += 1
        fingerprint = _row_fingerprint(row, fingerprint_key=fingerprint_key)
        owner = str(row.get(owner_key) or fingerprint[0] or "unknown")
        rel = str(row.get(file_key) or "")
        owner_counts[owner] += 1
        front_counts[fingerprint] += 1
        if rel and len(owner_examples[owner]) < examples_per_front:
            owner_examples[owner].append(rel)
        if rel and len(front_examples[fingerprint]) < examples_per_front:
            front_examples[fingerprint].append(rel)

    owner_families = [
        {
            "owner": owner,
            "count": count,
            "representative_files": list(owner_examples[owner]),
        }
        for owner, count in owner_counts.most_common()
    ]
    exact_fronts = [
        {
            "owner": fingerprint[0],
            "gap_kind": fingerprint[1] if len(fingerprint) > 1 else "",
            "gap_locus": fingerprint[2] if len(fingerprint) > 2 else "",
            "observed": fingerprint[3] if len(fingerprint) > 3 else "",
            "requested": fingerprint[4] if len(fingerprint) > 4 else "",
            "label": fingerprint_label(fingerprint),
            "count": count,
            "representative_files": list(front_examples[fingerprint]),
        }
        for fingerprint, count in sorted(
            front_counts.items(), key=lambda item: (-item[1], item[0])
        )
    ]
    return {
        "R_live_factory_panic_files": total,
        "owner_family_count": len(owner_families),
        "exact_front_count": len(exact_fronts),
        "owner_families": owner_families,
        "exact_fronts": exact_fronts,
        # Compact map for log lines / prior instrument shape.
        "owners": {row["owner"]: row["count"] for row in owner_families},
    }


def _row_fingerprint(
    row: Mapping[str, Any], *, fingerprint_key: str
) -> tuple[str, ...]:
    raw = row.get(fingerprint_key)
    if isinstance(raw, (list, tuple)) and len(raw) >= 1:
        padded = tuple(str(part) for part in raw[: len(FINGERPRINT_FIELDS)])
        if len(padded) < len(FINGERPRINT_FIELDS):
            padded = padded + ("",) * (len(FINGERPRINT_FIELDS) - len(padded))
        return padded
    gap = row.get("gap")
    if isinstance(gap, Mapping):
        return fingerprint_from_gap(gap)
    owner = str(row.get("owner") or "unknown")
    return (owner, "", "", "", "")
