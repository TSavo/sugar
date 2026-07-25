"""Authoritative suite measurement identity law.

A suite measurement is **attended** when collection and verdicts conserve.
It is **authoritative** only when the authenticated input universe is resolved:

  - measuredCommit          git commit actually measured
  - sourceStamp             source-only identity used by the measured binary
  - testExtraInputHash      declared test extras (+ runtime deps) hash
  - environmentIdentityHash full environment identity CID
  - conservation totals     counts that match the node-ID evidence lists

``{"unavailable": ...}`` is **unresolved**, never a truthy field. A report that
embeds an unavailable stamp is complete-but-identity-unresolved and must not
be published as authoritative.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping

SCHEMA_VERSION = 1

# Top-level fields every authoritative suite-report.json must carry.
REQUIRED_TOP_LEVEL = (
    "measuredCommit",
    "sourceStamp",
    "testExtraInputHash",
    "environmentIdentityHash",
    "counts",
    "collectedNodeIds",
)

# Conservation: counts[key] must equal len(list_key).
COUNT_AXES = (
    ("collected", "collectedNodeIds"),
    ("passed", "passedNodeIds"),
    ("failed", "failedNodeIds"),
    ("error", "errorNodeIds"),
    ("skipped", "skippedNodeIds"),
    ("xfailed", "xfailedNodeIds"),
    ("xpassed", "xpassedNodeIds"),
    ("collectionError", "collectionErrorNodeIds"),
    ("notReported", "notReportedNodeIds"),
)

_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


def is_unavailable(value: Any) -> bool:
    """``{"unavailable": ...}`` is unresolved, never a resolved field."""
    return isinstance(value, Mapping) and "unavailable" in value


def is_resolved_scalar(value: Any) -> bool:
    if value is None:
        return False
    if is_unavailable(value):
        return False
    if isinstance(value, str) and not value.strip():
        return False
    if isinstance(value, Mapping) and not value:
        return False
    return True


def is_resolved_source_stamp(stamp: Any) -> bool:
    """sourceStamp must carry a non-empty value and must not be unavailable."""
    if not isinstance(stamp, Mapping) or is_unavailable(stamp):
        return False
    value = stamp.get("value")
    return isinstance(value, str) and bool(value.strip())


def source_stamp_value(stamp: Any) -> str | None:
    if not is_resolved_source_stamp(stamp):
        return None
    return str(stamp["value"])


def test_extra_input_hash(identity: Mapping[str, Any] | None) -> str | None:
    if not isinstance(identity, Mapping) or is_unavailable(identity):
        return None
    dep = identity.get("dependencyAuthority")
    if not isinstance(dep, Mapping) or is_unavailable(dep):
        return None
    value = dep.get("testExtraInputHash")
    if not isinstance(value, str) or not value.strip() or is_unavailable(value):
        return None
    return value


def environment_identity_hash(identity: Mapping[str, Any] | None) -> str | None:
    if not isinstance(identity, Mapping) or is_unavailable(identity):
        return None
    value = identity.get("environmentIdentityHash")
    if not isinstance(value, str) or not value.strip():
        return None
    return value


def measured_commit_from_report(report: Mapping[str, Any]) -> str | None:
    """Prefer explicit top-level, then leaseRecord, then runnerIdentity."""
    for key in ("measuredCommit",):
        value = report.get(key)
        if isinstance(value, str) and _COMMIT_RE.match(value):
            return value
    lease = report.get("leaseRecord")
    if isinstance(lease, Mapping):
        value = lease.get("measuredCommit")
        if isinstance(value, str) and _COMMIT_RE.match(value):
            return value
    runner = report.get("runnerIdentity")
    if isinstance(runner, Mapping):
        value = runner.get("githubSha")
        if isinstance(value, str) and _COMMIT_RE.match(value):
            return value
    return None


def promote_identity_fields(report: dict[str, Any]) -> dict[str, Any]:
    """Ensure top-level identity fields are present for authoritative readers.

    Does not invent values: only promotes what is already resolved, or leaves
    the field absent so the gate can red.
    """
    out = dict(report)
    identity = out.get("environmentIdentity")
    if not isinstance(identity, Mapping):
        identity = {}

    commit = measured_commit_from_report(out)
    if commit is not None:
        out["measuredCommit"] = commit

    stamp = identity.get("sourceStamp")
    if is_resolved_source_stamp(stamp):
        out["sourceStamp"] = stamp
    extras = test_extra_input_hash(identity)
    if extras is not None:
        out["testExtraInputHash"] = extras
    env_hash = environment_identity_hash(identity)
    if env_hash is not None:
        out["environmentIdentityHash"] = env_hash

    return out


def conservation_errors(report: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    counts = report.get("counts")
    if not isinstance(counts, Mapping):
        return ["counts: absent or not an object"]
    for count_key, list_key in COUNT_AXES:
        node_ids = report.get(list_key)
        if not isinstance(node_ids, list):
            errors.append(f"{list_key}: absent or not a list")
            continue
        expected = counts.get(count_key)
        if expected != len(node_ids):
            errors.append(
                f"conservation: counts[{count_key!r}]={expected!r} "
                f"!= len({list_key})={len(node_ids)}"
            )
    collected = report.get("collectedNodeIds")
    if isinstance(collected, list) and isinstance(counts, Mapping):
        accounted = (
            int(counts.get("passed") or 0)
            + int(counts.get("failed") or 0)
            + int(counts.get("error") or 0)
            + int(counts.get("skipped") or 0)
            + int(counts.get("xfailed") or 0)
            + int(counts.get("xpassed") or 0)
            + int(counts.get("notReported") or 0)
        )
        # collectionError is separate (no test node); not in collected.
        if accounted != len(collected):
            errors.append(
                f"conservation: verdict total {accounted} != collected {len(collected)}"
            )
    return errors


def identity_errors(
    report: Mapping[str, Any],
    *,
    require_commit: str | None = None,
) -> list[str]:
    """Return human-readable reds; empty means identity-resolved."""
    errors: list[str] = []
    identity = report.get("environmentIdentity")
    if not isinstance(identity, Mapping):
        errors.append("environmentIdentity: absent or not an object")
        identity = {}
    elif is_unavailable(identity):
        errors.append(
            f"environmentIdentity: unresolved ({identity.get('unavailable')!r})"
        )

    stamp = report.get("sourceStamp")
    if stamp is None and isinstance(identity, Mapping):
        stamp = identity.get("sourceStamp")
    if not is_resolved_source_stamp(stamp):
        if is_unavailable(stamp):
            errors.append(f"sourceStamp: unresolved ({stamp.get('unavailable')!r})")
        else:
            errors.append("sourceStamp: missing or has no non-empty value")

    extras = report.get("testExtraInputHash")
    if extras is None:
        extras = test_extra_input_hash(
            identity if isinstance(identity, Mapping) else {}
        )
    if not is_resolved_scalar(extras):
        errors.append("testExtraInputHash: missing or null")

    env_hash = report.get("environmentIdentityHash")
    if env_hash is None:
        env_hash = environment_identity_hash(
            identity if isinstance(identity, Mapping) else {}
        )
    if not is_resolved_scalar(env_hash):
        errors.append("environmentIdentityHash: missing or null")

    commit = measured_commit_from_report(report)
    if commit is None:
        errors.append("measuredCommit: missing or not a 40-char lowercase hex sha")
    elif require_commit is not None and commit != require_commit:
        errors.append(
            f"measuredCommit: report {commit!r} contradicts required {require_commit!r}"
        )

    lease = report.get("leaseRecord")
    if isinstance(lease, Mapping):
        lease_commit = lease.get("measuredCommit")
        if (
            isinstance(lease_commit, str)
            and _COMMIT_RE.match(lease_commit)
            and commit is not None
            and lease_commit != commit
        ):
            errors.append(
                f"measuredCommit: leaseRecord {lease_commit!r} contradicts "
                f"report {commit!r}"
            )
        stamp_value = source_stamp_value(stamp)
        lease_stamp = None
        # future: lease may carry sourceStamp; if present must match
        if isinstance(lease.get("sourceStamp"), Mapping):
            lease_stamp = source_stamp_value(lease.get("sourceStamp"))
        if (
            lease_stamp is not None
            and stamp_value is not None
            and lease_stamp != stamp_value
        ):
            errors.append(
                f"sourceStamp: leaseRecord {lease_stamp!r} contradicts report {stamp_value!r}"
            )

    errors.extend(conservation_errors(report))
    return errors


def is_authoritative(
    report: Mapping[str, Any], *, require_commit: str | None = None
) -> bool:
    return not identity_errors(report, require_commit=require_commit)


def load_report(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(
            f"suite report top level is {type(payload).__name__}, not object"
        )
    return payload


def rewrite_promoted(path: str) -> dict[str, Any]:
    """Re-read, promote identity fields, write back, return the new report."""
    report = promote_identity_fields(load_report(path))
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=False)
        handle.write("\n")
    # Post-serialization check: re-read what was written.
    reread = load_report(path)
    return reread


def content_address(report: Mapping[str, Any]) -> str:
    payload = json.dumps(report, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
