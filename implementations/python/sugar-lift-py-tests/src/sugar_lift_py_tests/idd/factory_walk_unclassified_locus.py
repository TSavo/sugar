"""Row-addressable factory-walk unclassified locus schema (#5252).

Historical recensus shards only emitted aggregate ``factory_walk_statuses``
maps. That is enough for ``R_factory_walk_unclassified`` but not for
shape-split drain: synthetic rows print as ``?:?:``.

Every unclassified / unresolved walk row MUST retain a locus object:

.. code-block:: json

    {
      "status": "unclassified",
      "selected": "<Sugar name or empty when no owner>",
      "ast_kind": "<AST node kind or observed native shape>",
      "role": "<requested factory role: statement|term|...>",
      "reason": "<why walk left the row unclassified>",
      "file": "<repo-relative path>",
      "line": 1234,
      "resolution_kind": "<recognizer's own resolution outcome, or '' when the producer computes none>"
    }

Canonical print form: ``file:line`` (e.g. ``pandas/core/frame.py:1234``).

``resolution_kind`` (#5252/#5913 audit) carries the recognition outcome
``recognize_callee_universe`` already computed and previously discarded once
it decided pass/fail — e.g. ``imported_unresolved`` (resolves to an imported/
assigned definition but no recognizer family covers it — the genuine drain
frontier), ``local_binding``, ``builtin``, ``chained_receiver``, or
``unresolved_other``. It is additive: empty when a producer (e.g. a
conservation-violation gap) computes no callee resolution. Its presence
never changes ``factory_walk_statuses.unclassified`` or the locus count.

Acceptance for next recensus producer:
1. ``factory_walk_statuses.unclassified`` equals the count of locus rows.
2. Every locus has non-empty ``file``, integer ``line``, non-empty ``role``
   or ``selected``, non-empty ``ast_kind``, and non-empty ``reason``.
3. Instrument ``--from-json`` prints real loci, not ``?:?:``.
4. Shape-split ``groupby(ast_kind, role, selected, reason)`` works offline.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

# Wire + internal names for the same red residue.
UNCLASSIFIED_STATUSES = frozenset({"unclassified", "unresolved"})

# Keys producers may use for retained locus lists (preferred over aggregates).
LOCUS_LIST_KEYS = (
    "factory_walk_unclassified_rows",
    "unclassified_rows",
    "factory_walk_unclassified_loci",
)

LOCUS_FIELD_NAMES = (
    "status",
    "selected",
    "ast_kind",
    "role",
    "reason",
    "file",
    "line",
    # Recognition outcome for this row's callee, when a producer computes one
    # (#5252/#5913 audit). Additive only: empty string when a producer does
    # not carry it, never required for addressability (locus_is_addressable
    # does not gate on it), so its presence never changes any count.
    "resolution_kind",
)


def _status_of(row: Any) -> str:
    if isinstance(row, Mapping):
        status = row.get("status")
    else:
        status = getattr(row, "status", None)
    if status is None:
        return ""
    if hasattr(status, "value"):
        return str(status.value)
    return str(status)


def is_unclassified_status(status: str) -> bool:
    return status in UNCLASSIFIED_STATUSES


def is_unclassified_row(row: Any) -> bool:
    return is_unclassified_status(_status_of(row))


def project_unclassified_locus(row: Any) -> dict[str, Any] | None:
    """Project a factory-walk row DTO / mapping to the locus schema.

    Returns None when the row is not unclassified/unresolved residue.
    """
    status = _status_of(row)
    if not is_unclassified_status(status):
        return None

    if isinstance(row, Mapping):
        file = row.get("file") or row.get("path") or ""
        line = row.get("line")
        selected = row.get("selected")
        if selected is None:
            selected = ""
        ast_kind = row.get("ast_kind") or row.get("astKind") or ""
        role = (
            row.get("role")
            or row.get("requested_role")
            or row.get("requestedRole")
            or ""
        )
        reason = row.get("reason") or ""
        extra = row.get("extra") if isinstance(row.get("extra"), Mapping) else {}
        resolution_kind = (
            row.get("resolution_kind") or extra.get("resolution_kind") or ""
        )
    else:
        file = getattr(row, "file", None) or getattr(row, "path", None) or ""
        line = getattr(row, "line", None)
        selected = getattr(row, "selected", None)
        if selected is None:
            selected = ""
        ast_kind = getattr(row, "ast_kind", None) or getattr(row, "astKind", None) or ""
        role = (
            getattr(row, "role", None)
            or getattr(row, "requested_role", None)
            or getattr(row, "requestedRole", None)
            or ""
        )
        reason = getattr(row, "reason", None) or ""
        row_extra = getattr(row, "extra", None)
        extra = row_extra if isinstance(row_extra, Mapping) else {}
        resolution_kind = (
            getattr(row, "resolution_kind", None) or extra.get("resolution_kind") or ""
        )

    try:
        line_int = int(line) if line is not None and line != "" else 0
    except (TypeError, ValueError):
        line_int = 0

    # Keep internal "unclassified" as the canonical product status; wire
    # "unresolved" is accepted on input and normalized the same way law does.
    return {
        "status": "unclassified" if status == "unresolved" else status,
        "selected": str(selected),
        "ast_kind": str(ast_kind),
        "role": str(role),
        "reason": str(reason),
        "file": str(file),
        "line": line_int,
        "resolution_kind": str(resolution_kind),
    }


def project_unclassified_loci(rows: Iterable[Any]) -> list[dict[str, Any]]:
    """Project every unclassified/unresolved walk row to a retained locus."""
    out: list[dict[str, Any]] = []
    for row in rows:
        locus = project_unclassified_locus(row)
        if locus is not None:
            out.append(locus)
    return out


def locus_is_addressable(locus: Mapping[str, Any]) -> bool:
    """True when a locus has enough fields for offline shape-split drain."""
    file = str(locus.get("file") or locus.get("path") or "").strip()
    line = locus.get("line")
    try:
        line_ok = isinstance(line, int) or (line is not None and str(line).isdigit())
        line_int = int(line) if line_ok else 0
    except (TypeError, ValueError):
        line_int = 0
    ast_kind = str(locus.get("ast_kind") or locus.get("astKind") or "").strip()
    role = str(
        locus.get("role") or locus.get("requested_role") or locus.get("selected") or ""
    ).strip()
    reason = str(locus.get("reason") or "").strip()
    return (
        bool(file) and line_int > 0 and bool(ast_kind) and bool(role) and bool(reason)
    )


def shape_split_unclassified(
    rows: Sequence[Any] | Iterable[Any],
    *,
    example_limit: int = 5,
) -> list[dict[str, Any]]:
    """Group unclassified loci by (ast_kind, role, selected, reason).

    Enables fleet claims on families without re-running vendor walls.
    """
    counts: Counter[tuple[str, str, str, str]] = Counter()
    examples: dict[tuple[str, str, str, str], list[str]] = defaultdict(list)
    for row in rows:
        locus = project_unclassified_locus(row)
        if locus is None:
            continue
        key = (
            str(locus.get("ast_kind") or ""),
            str(locus.get("role") or ""),
            str(locus.get("selected") or ""),
            str(locus.get("reason") or ""),
        )
        counts[key] += 1
        print_form = f"{locus.get('file')}:{locus.get('line')}"
        bucket = examples[key]
        if print_form not in bucket and len(bucket) < example_limit:
            bucket.append(print_form)

    split: list[dict[str, Any]] = []
    for (ast_kind, role, selected, reason), count in sorted(
        counts.items(), key=lambda item: (-item[1], item[0])
    ):
        split.append(
            {
                "ast_kind": ast_kind,
                "role": role,
                "selected": selected,
                "reason": reason,
                "count": count,
                "examples": examples[(ast_kind, role, selected, reason)],
            }
        )
    return split


def extract_locus_list(payload: Mapping[str, Any]) -> list[Any] | None:
    """Return a retained locus list when the payload carries one, else None."""
    for key in LOCUS_LIST_KEYS:
        value = payload.get(key)
        if isinstance(value, list) and value and _looks_like_locus_row(value[0]):
            return list(value)
        if isinstance(value, list) and not value:
            return []
    return None


def _looks_like_locus_row(row: Any) -> bool:
    if isinstance(row, Mapping):
        return "status" in row and (
            "file" in row or "path" in row or "line" in row or "ast_kind" in row
        )
    return hasattr(row, "status") and (
        hasattr(row, "file") or hasattr(row, "line") or hasattr(row, "ast_kind")
    )
