#!/usr/bin/env python3
"""CommitMeasurement — sealed composition of tip measurement testimony.

Cite-compose only. SCOREBOARD_AUTHORITY = False. Never recompute product R
(control_effect_recensus owns the corpus board). Never emit board axis names
as computed residual.

    AxisReading = Measured(...) | Unmeasured(reason)
    commit_measurement(...) -> CompleteVector | PartialVector

Measured requires BOTH:
  - lease receipt CID (proves lease acquired / ran under lease at commit)
  - body artifact CID + value_field_path (the report that owns the number)

A lease without a body is Unmeasured (today's package-suite: ran, no
suite-report.json). A free-floating value without both digests is unconstructible.

CompleteVector has .total. PartialVector has no .total.
Unmeasured is a third value, not zero.

One door: ``commit_measurement`` / ``compose_tip_from_receipts_dir``.

CI: ``tools/commit_measurement_gate.py --require-complete`` fails closed.
Enrollment: heavy-measurement-attendance.yml composes + gates after roll call.
"""

from __future__ import annotations

SCOREBOARD_AUTHORITY = False

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Union

# Board residual keys this composition must never invent as its own axes.
_MEASURED_SEAL = object()

FORBIDDEN_BOARD_AXIS_NAMES = frozenset(
    {
        "R_construction",
        "R_desugar",
        "R_construction_gaps",
        "functionsClean",
        "functionsTotal",
        "R_backend_defects",
    }
)


class CommitMeasurementError(TypeError):
    """Illegal measurement reading — refused at construction."""


def _require_nonempty_str(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CommitMeasurementError(
            f"{name} must be a non-empty str; got {type(value).__name__!r}={value!r}"
        )
    return value.strip()


def _require_int(name: str, value: object, *, min_value: int | None = None) -> int:
    if type(value) is not int:
        raise CommitMeasurementError(
            f"{name} must be int (not {type(value).__name__})"
        )
    if min_value is not None and value < min_value:
        raise CommitMeasurementError(f"{name} must be >= {min_value}; got {value}")
    return value


def content_cid(payload: bytes | str | Mapping[str, Any]) -> str:
    """Content address for sealed artifacts (blake2b hex, schema-local)."""
    if isinstance(payload, Mapping):
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    elif isinstance(payload, str):
        raw = payload.encode("utf-8")
    else:
        raw = payload
    digest = hashlib.blake2b(raw, digest_size=32).hexdigest()
    return f"blake2b-256:{digest}"


def _lookup_path(body: Mapping[str, Any], field_path: str) -> Any:
    """Dot-path lookup; ``summary.failed`` or ``failedNodeIds`` (len if list)."""
    cur: Any = body
    for part in field_path.split("."):
        if part == "len" and isinstance(cur, (list, tuple, set, dict)):
            return len(cur)
        if not isinstance(cur, Mapping) or part not in cur:
            raise KeyError(field_path)
        cur = cur[part]
    if isinstance(cur, (list, tuple)):
        return len(cur)
    return cur


@dataclass(frozen=True, slots=True)
class Measured:
    """Measured axis: value cited from a body artifact under a lease receipt.

    Unconstructible without lease receipt_cid AND a parsed body that owns the
    value (body_artifact_cid is content-address of that body). Lease alone does
    not prove the number — use ``measured(...)`` / ``measured_from_sealed_pair``.
    Direct construction without the module seal is refused.
    """

    value: int
    receipt_cid: str
    body_artifact_cid: str
    value_field_path: str
    collected: int
    exit_code: int
    _seal: object

    def __post_init__(self) -> None:
        if self._seal is not _MEASURED_SEAL:
            raise CommitMeasurementError(
                "Measured is sealed: construct via measured(body=...) or "
                "measured_from_sealed_pair only — free-floating value+receipt "
                "without a parsed report body is Unmeasured(NoReport)"
            )
        _require_int("value", self.value, min_value=0)
        object.__setattr__(
            self, "receipt_cid", _require_nonempty_str("receipt_cid", self.receipt_cid)
        )
        object.__setattr__(
            self,
            "body_artifact_cid",
            _require_nonempty_str("body_artifact_cid", self.body_artifact_cid),
        )
        object.__setattr__(
            self,
            "value_field_path",
            _require_nonempty_str("value_field_path", self.value_field_path),
        )
        _require_int("collected", self.collected, min_value=0)
        _require_int("exit_code", self.exit_code)

    def is_measured(self) -> bool:
        return True


@dataclass(frozen=True, slots=True)
class Unmeasured:
    """Third value: not measured. Not zero. Not coercible to Measured."""

    reason: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "reason", _require_nonempty_str("reason", self.reason)
        )

    def is_measured(self) -> bool:
        return False


AxisReading = Union[Measured, Unmeasured]


def measured(
    value: int,
    *,
    receipt_cid: str,
    body: Mapping[str, Any],
    value_field_path: str,
    collected: int | None = None,
    exit_code: int,
) -> Measured:
    """Build Measured only from a parsed body artifact + lease receipt CID.

    Free-floating value + fake body CID is unconstructible: the body must be
    present, parse as a mapping, and ``value`` must equal the field path.
    Lease alone without a report body is Unmeasured(NoReport), never Measured.
    """
    if not isinstance(body, Mapping):
        raise CommitMeasurementError(
            "Measured requires a parsed body mapping (report artifact); "
            f"got {type(body).__name__}. Lease alone is not enough — "
            "NoReport is Unmeasured."
        )
    path_s = _require_nonempty_str("value_field_path", value_field_path)
    try:
        raw = _lookup_path(body, path_s)
    except KeyError as exc:
        raise CommitMeasurementError(
            f"Measured refuses: body missing value field {path_s!r} "
            f"(NoReport/partial body)"
        ) from exc
    if type(raw) is not int or raw < 0:
        raise CommitMeasurementError(
            f"Measured refuses: body field {path_s!r} is not a non-negative int: {raw!r}"
        )
    if type(value) is not int or value != raw:
        raise CommitMeasurementError(
            f"Measured refuses: value {value!r} does not match body[{path_s!r}]={raw!r}; "
            f"cite the body, do not invent the number"
        )
    if collected is None:
        try:
            collected = _lookup_path(body, "totals.collected")
        except KeyError:
            collected = 0
    if type(collected) is not int or collected < 0:
        raise CommitMeasurementError(
            f"collected must be non-negative int; got {collected!r}"
        )
    return Measured(
        value,
        receipt_cid,
        content_cid(body),
        path_s,
        collected,
        exit_code,
        _MEASURED_SEAL,
    )


def unmeasured(reason: str) -> Unmeasured:
    return Unmeasured(reason)


def measured_from_sealed_pair(
    *,
    commit_sha: str,
    lease_record: Mapping[str, Any],
    lease_receipt_cid: str,
    body: Mapping[str, Any],
    body_artifact_cid: str,
    value_field_path: str,
    collected_field_path: str | None = None,
    exit_code: int | None = None,
) -> AxisReading:
    """Cite-compose one axis from lease receipt + body artifact.

    Returns Unmeasured when lease not acquired, commit mismatch, or body
    lacks the value field — never Measured without both digests.
    """
    sha = _require_nonempty_str("commit_sha", commit_sha)
    _require_nonempty_str("lease_receipt_cid", lease_receipt_cid)
    _require_nonempty_str("body_artifact_cid", body_artifact_cid)
    path = _require_nonempty_str("value_field_path", value_field_path)

    if lease_record.get("acquired") is not True:
        return unmeasured(
            f"lease not acquired (acquired={lease_record.get('acquired')!r})"
        )
    lease_commit = lease_record.get("commit") or lease_record.get("gitCommit")
    if isinstance(lease_commit, str) and lease_commit and lease_commit != sha:
        return unmeasured(
            f"lease commit {lease_commit!r} != composition commit {sha!r}"
        )
    try:
        raw_value = _lookup_path(body, path)
    except KeyError:
        return unmeasured(f"body missing value field {path!r}")
    if type(raw_value) is not int or raw_value < 0:
        return unmeasured(
            f"body field {path!r} is not a non-negative int: {raw_value!r}"
        )
    collected = 0
    if collected_field_path:
        try:
            c = _lookup_path(body, collected_field_path)
            if type(c) is int and c >= 0:
                collected = c
        except KeyError:
            return unmeasured(f"body missing collected field {collected_field_path!r}")
    else:
        # Prefer suite-report totals.collected when present
        try:
            c = _lookup_path(body, "totals.collected")
            if type(c) is int and c >= 0:
                collected = c
        except KeyError:
            collected = 0
    code = exit_code
    if code is None:
        status = lease_record.get("measurementStatus") or ""
        code = 0 if status == "completed/zero-findings" else 1
    if type(code) is not int:
        return unmeasured(f"exit_code not int: {code!r}")
    expected_cid = content_cid(body)
    if body_artifact_cid != expected_cid:
        return unmeasured(
            "NoReport: body_artifact_cid mismatch "
            f"(presented {body_artifact_cid!r}, content {expected_cid!r})"
        )
    return measured(
        raw_value,
        receipt_cid=lease_receipt_cid,
        body=body,
        value_field_path=path,
        collected=collected,
        exit_code=code,
    )


def _require_axes_map(axes: object) -> dict[str, AxisReading]:
    if not isinstance(axes, Mapping) or not axes:
        raise CommitMeasurementError(
            "axes must be a non-empty mapping of axis name -> AxisReading"
        )
    out: dict[str, AxisReading] = {}
    for name, reading in axes.items():
        key = _require_nonempty_str("axis name", name)
        if key in FORBIDDEN_BOARD_AXIS_NAMES or key.startswith("R_construction"):
            raise CommitMeasurementError(
                f"axis {key!r} is a corpus-board residual name; "
                f"CommitMeasurement is cite-compose only "
                f"(SCOREBOARD_AUTHORITY=False). Use control_effect_recensus."
            )
        if not isinstance(reading, (Measured, Unmeasured)):
            raise CommitMeasurementError(
                f"axis {key!r}: must be Measured or Unmeasured; "
                f"got {type(reading).__name__}"
            )
        out[key] = reading
    return out


@dataclass(frozen=True, slots=True)
class CompleteVector:
    commit_sha: str
    roster_cid: str
    axes: Mapping[str, Measured]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "commit_sha", _require_nonempty_str("commit_sha", self.commit_sha)
        )
        object.__setattr__(
            self, "roster_cid", _require_nonempty_str("roster_cid", self.roster_cid)
        )
        if not isinstance(self.axes, Mapping) or not self.axes:
            raise CommitMeasurementError("CompleteVector.axes must be non-empty")
        sealed: dict[str, Measured] = {}
        for name, reading in self.axes.items():
            key = _require_nonempty_str("axis name", name)
            if key in FORBIDDEN_BOARD_AXIS_NAMES:
                raise CommitMeasurementError(f"forbidden board axis {key!r}")
            if not isinstance(reading, Measured):
                raise CommitMeasurementError(
                    f"CompleteVector refuses Unmeasured axis {key!r}"
                )
            sealed[key] = reading
        object.__setattr__(self, "axes", sealed)

    @property
    def total(self) -> int:
        return sum(r.value for r in self.axes.values())

    def is_complete(self) -> bool:
        return True

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": "commit-measurement",
            "status": "complete",
            "commitSha": self.commit_sha,
            "rosterCid": self.roster_cid,
            "total": self.total,
            "axes": {
                name: {
                    "status": "measured",
                    "value": r.value,
                    "receiptCid": r.receipt_cid,
                    "bodyArtifactCid": r.body_artifact_cid,
                    "valueFieldPath": r.value_field_path,
                    "collected": r.collected,
                    "exitCode": r.exit_code,
                }
                for name, r in self.axes.items()
            },
        }


@dataclass(frozen=True, slots=True)
class PartialVector:
    commit_sha: str
    roster_cid: str
    axes: Mapping[str, AxisReading]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "commit_sha", _require_nonempty_str("commit_sha", self.commit_sha)
        )
        object.__setattr__(
            self, "roster_cid", _require_nonempty_str("roster_cid", self.roster_cid)
        )
        sealed = _require_axes_map(self.axes)
        if not any(isinstance(r, Unmeasured) for r in sealed.values()):
            raise CommitMeasurementError(
                "PartialVector requires ≥1 Unmeasured; use CompleteVector"
            )
        object.__setattr__(self, "axes", sealed)

    def is_complete(self) -> bool:
        return False

    def unmeasured_axes(self) -> tuple[str, ...]:
        return tuple(
            n for n, r in self.axes.items() if isinstance(r, Unmeasured)
        )

    def to_json(self) -> dict[str, Any]:
        axes_out: dict[str, Any] = {}
        for name, r in self.axes.items():
            if isinstance(r, Measured):
                axes_out[name] = {
                    "status": "measured",
                    "value": r.value,
                    "receiptCid": r.receipt_cid,
                    "bodyArtifactCid": r.body_artifact_cid,
                    "valueFieldPath": r.value_field_path,
                    "collected": r.collected,
                    "exitCode": r.exit_code,
                }
            else:
                axes_out[name] = {"status": "unmeasured", "reason": r.reason}
        return {
            "kind": "commit-measurement",
            "status": "partial",
            "commitSha": self.commit_sha,
            "rosterCid": self.roster_cid,
            # deliberately no "total" key
            "unmeasuredAxes": list(self.unmeasured_axes()),
            "axes": axes_out,
        }


CommitMeasurement = Union[CompleteVector, PartialVector]


def commit_measurement(
    commit_sha: str,
    roster_cid: str,
    axes: Mapping[str, AxisReading],
) -> CommitMeasurement:
    """ONE DOOR: CompleteVector if all Measured, else PartialVector (no total)."""
    sha = _require_nonempty_str("commit_sha", commit_sha)
    roster = _require_nonempty_str("roster_cid", roster_cid)
    sealed = _require_axes_map(axes)
    if any(isinstance(r, Unmeasured) for r in sealed.values()):
        return PartialVector(sha, roster, sealed)
    return CompleteVector(sha, roster, sealed)  # type: ignore[arg-type]


def _load_json(path: Path) -> Mapping[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, Mapping) else None


def _lease_from_payload(payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
    if "leaseRecord" in payload and isinstance(payload["leaseRecord"], Mapping):
        return payload["leaseRecord"]
    if "leaseClass" in payload or "acquired" in payload:
        return payload
    return None


# Per-commit tip axes only (nightlies are a different obligation).
TIP_AXIS_SPECS: tuple[tuple[str, str, str], ...] = (
    # axis_name, leaseClass, value_field_path on body
    ("python-package-suite", "python-package-suite", "totals.failed"),
    (
        "python-sole-construction-floors",
        "python-sole-construction-floors",
        "totals.failed",
    ),
)


def compose_tip_from_receipts_dir(
    commit_sha: str,
    receipts_dir: Path,
    *,
    roster_cid: str = "heavy-roster:per-commit",
) -> CommitMeasurement:
    """Cite-compose tip axes from a directory of downloaded artifacts.

    For each enrolled per-commit class: find a lease-acquired receipt and a
    body (suite-report style JSON). Missing either → Unmeasured for that axis.
    Never recomputes product residual; values are field-paths on sealed bodies.
    """
    sha = _require_nonempty_str("commit_sha", commit_sha)
    root = Path(receipts_dir)
    # Index lease records and body reports by leaseClass / presence
    leases: dict[str, tuple[Path, Mapping[str, Any]]] = {}
    bodies: list[tuple[Path, Mapping[str, Any]]] = []
    if root.is_dir():
        for path in sorted(root.rglob("*.json")):
            payload = _load_json(path)
            if payload is None:
                continue
            lease = _lease_from_payload(payload)
            if lease is not None and lease.get("leaseClass"):
                cls = str(lease["leaseClass"])
                # Prefer acquired true if multiple
                prev = leases.get(cls)
                if prev is None or lease.get("acquired") is True:
                    leases[cls] = (path, lease)
            # Body candidates: have totals or failedNodeIds
            if "totals" in payload or "failedNodeIds" in payload:
                bodies.append((path, payload))

    axes: dict[str, AxisReading] = {}
    for axis_name, lease_class, value_path in TIP_AXIS_SPECS:
        if lease_class not in leases:
            axes[axis_name] = unmeasured(
                f"no lease receipt for class {lease_class!r} at commit {sha}"
            )
            continue
        lease_path, lease_rec = leases[lease_class]
        lease_cid = content_cid(lease_rec)
        # Body: embed on same file, or separate suite-report in same run dir
        body_path: Path | None = None
        body: Mapping[str, Any] | None = None
        full = _load_json(lease_path)
        if full and ("totals" in full or "failedNodeIds" in full):
            body_path, body = lease_path, full
        else:
            run_dir = lease_path.parent
            for cand in sorted(run_dir.rglob("*.json")):
                payload = _load_json(cand)
                if payload and ("totals" in payload or "failedNodeIds" in payload):
                    body_path, body = cand, payload
                    break
            if body is None:
                # last resort: any body in tree with matching commit field
                for bpath, bpay in bodies:
                    if bpay.get("gitCommit") == sha or bpay.get("commit") == sha:
                        body_path, body = bpath, bpay
                        break
        if body is None or body_path is None:
            axes[axis_name] = unmeasured(
                f"NoReport: lease present for {lease_class!r} but no body artifact "
                f"(suite-report / floor report)"
            )
            continue
        axes[axis_name] = measured_from_sealed_pair(
            commit_sha=sha,
            lease_record=lease_rec,
            lease_receipt_cid=lease_cid,
            body=body,
            body_artifact_cid=content_cid(body),
            value_field_path=value_path,
        )
    return commit_measurement(sha, roster_cid, axes)
