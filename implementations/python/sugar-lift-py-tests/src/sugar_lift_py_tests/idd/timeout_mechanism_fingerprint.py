"""Shared timeout-mechanism fingerprints from ``sugar.engine.log.v1`` (#5306).

The pandas timeout cohort (130 files that passed the old ``python.factory``
front and now exhaust the child bound) is not 130 independent bugs. Heartbeat
``active_stack`` + enter roles collapse into a small set of *multiplicative*
lift mechanisms. This module is the instrument: given engine JSONL events, it
names the dominant stack fingerprint and supporting counters so a fix can be
aimed once and re-measured.

Buckets (stack-role patterns observed on live hang heartbeats):

- ``recursive_function_construct`` — dig.resolve_value → dig.construct.function
  → dig.construct.function.factory → statement → dig.resolve_value …
  Eager install-source *function floor* construction factories the callee body
  and re-enters resolve for nested imports.
- ``module_seed_cascade`` — dig.module_seed on the live stack while seeding
  module bindings for a construct (eager free-name / decorator seed walk).
- ``assign_construct`` — dig.construct.assign path dominating the hang tip.
- ``other_dig`` — dig.* present but not the shapes above.
- ``factory_build`` — factory.select / factory.new.* without dig on the stack
  (local AST factory volume; common on large test modules).
- ``reduce_body`` — statement/term reduce without dig/factory tip.
- ``root_or_other`` — file root or unclassified.

Never invents a fix. Never reclassifies timeout as complete. Pure report.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping, Sequence

# Stable labels for ledger / PR conservation tables.
MECHANISM_RECURSIVE_FUNCTION_CONSTRUCT = "recursive_function_construct"
MECHANISM_MODULE_SEED_CASCADE = "module_seed_cascade"
MECHANISM_ASSIGN_CONSTRUCT = "assign_construct"
MECHANISM_OTHER_DIG = "other_dig"
MECHANISM_FACTORY_BUILD = "factory_build"
MECHANISM_REDUCE_BODY = "reduce_body"
MECHANISM_ROOT_OR_OTHER = "root_or_other"

MECHANISM_LABELS = (
    MECHANISM_RECURSIVE_FUNCTION_CONSTRUCT,
    MECHANISM_MODULE_SEED_CASCADE,
    MECHANISM_ASSIGN_CONSTRUCT,
    MECHANISM_OTHER_DIG,
    MECHANISM_FACTORY_BUILD,
    MECHANISM_REDUCE_BODY,
    MECHANISM_ROOT_OR_OTHER,
)


def _roles_from_stack(active_stack: Sequence[Any] | None) -> list[str]:
    """Extract role segments from ``sugar|role|site`` fingerprints."""
    roles: list[str] = []
    for item in active_stack or ():
        text = str(item)
        if "|" in text:
            parts = text.split("|")
            roles.append(parts[1] if len(parts) >= 2 else text)
        else:
            roles.append(text)
    return roles


def classify_stack_roles(roles: Sequence[str]) -> str:
    """Map one heartbeat's role stack to a mechanism bucket."""
    if any(r.startswith("dig.") or r == "dig.resolve_value" for r in roles):
        if any("module_seed" in r for r in roles):
            return MECHANISM_MODULE_SEED_CASCADE
        if any("construct.function" in r for r in roles):
            return MECHANISM_RECURSIVE_FUNCTION_CONSTRUCT
        if any("construct.assign" in r for r in roles):
            return MECHANISM_ASSIGN_CONSTRUCT
        return MECHANISM_OTHER_DIG
    if any(r.startswith("factory.") for r in roles):
        return MECHANISM_FACTORY_BUILD
    if any(r in ("statement", "term") for r in roles):
        return MECHANISM_REDUCE_BODY
    return MECHANISM_ROOT_OR_OTHER


def collapse_role_stack(roles: Sequence[str], *, tip: int = 8) -> str:
    """Collapse consecutive duplicate roles; keep the deepest ``tip`` frames."""
    collapsed: list[str] = []
    for role in roles:
        if not collapsed or collapsed[-1] != role:
            collapsed.append(role)
    return ">".join(collapsed[-tip:])


def fingerprint_engine_events(
    events: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Aggregate mechanism buckets + supporting counters from engine events.

    Supporting counters (for fix design, not reclassification):
      - resolve_value_miss / resolve_value_hit
      - multi_miss_targets: import targets with miss count > 1 (None not
        published → re-resolve waste; not a success cache)
      - construct_function / module_seed / factory_select enters
      - top stack_role patterns on heartbeats
    """
    mechanism_hb: Counter[str] = Counter()
    stack_patterns: Counter[str] = Counter()
    enter_roles: Counter[str] = Counter()
    resolve_miss: Counter[str] = Counter()
    resolve_hit: Counter[str] = Counter()
    heartbeat_count = 0
    event_count = 0

    for raw in events:
        if not isinstance(raw, Mapping):
            continue
        event_count += 1
        event = raw.get("event")
        role = (
            raw.get("role")
            if isinstance(raw.get("role"), str)
            else str(raw.get("role") or "")
        )
        sugar = str(raw.get("sugar") or "?")
        if event == "enter":
            enter_roles[role or "?"] += 1
            if role == "dig.resolve_value":
                resolve_miss[sugar] += 1
            elif role == "dig.resolve_value.hit":
                resolve_hit[sugar] += 1
        elif event == "heartbeat":
            heartbeat_count += 1
            roles = _roles_from_stack(raw.get("active_stack"))
            bucket = classify_stack_roles(roles)
            mechanism_hb[bucket] += 1
            stack_patterns[collapse_role_stack(roles)] += 1

    multi_miss = {name: count for name, count in resolve_miss.items() if count > 1}
    wasted_reresolves = sum(count - 1 for count in multi_miss.values())
    dominant = (
        mechanism_hb.most_common(1)[0][0] if mechanism_hb else MECHANISM_ROOT_OR_OTHER
    )
    miss_total = sum(resolve_miss.values())
    hit_total = sum(resolve_hit.values())
    return {
        "schema": "sugar.timeout.mechanism.v1",
        "event_count": event_count,
        "heartbeat_count": heartbeat_count,
        "dominant_mechanism": dominant,
        "mechanism_heartbeat_counts": {
            label: int(mechanism_hb.get(label, 0)) for label in MECHANISM_LABELS
        },
        "stack_role_patterns": [
            {"pattern": pattern, "heartbeat_count": count}
            for pattern, count in stack_patterns.most_common(12)
        ],
        "enter_role_counts": {
            name: count for name, count in enter_roles.most_common(24)
        },
        "resolve_value_miss": miss_total,
        "resolve_value_hit": hit_total,
        "resolve_hit_rate": round(hit_total / max(hit_total + miss_total, 1), 4),
        "multi_miss_target_count": len(multi_miss),
        "wasted_reresolves": wasted_reresolves,
        "top_multi_miss_targets": [
            {"target": name, "miss_count": count}
            for name, count in Counter(multi_miss).most_common(12)
        ],
        "construct_function_enters": int(enter_roles.get("dig.construct.function", 0)),
        "module_seed_enters": int(enter_roles.get("dig.module_seed", 0)),
        "factory_select_enters": int(enter_roles.get("factory.select", 0)),
    }


def fingerprint_engine_log_text(text: str) -> dict[str, Any]:
    """Parse JSONL text and fingerprint; empty/malformed lines are skipped."""
    import json

    events: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and (
            payload.get("schema") == "sugar.engine.log.v1" or "event" in payload
        ):
            events.append(payload)
    return fingerprint_engine_events(events)
