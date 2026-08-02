#!/usr/bin/env python3
"""CommitMeasurement — sealed composition of tip measurement testimony.

Cite-compose only. SCOREBOARD_AUTHORITY = False. Never recompute product R
(control_effect_recensus owns the corpus board). Never emit board axis names
as computed residual.

    AxisReading = Measured(...) | Unmeasured(reason)
    commit_measurement(...) -> CompleteVector | PartialVector

Measured requires:
  - body artifact CID + value_field_path (the report that owns the number)
  - identity binding on the body when present (measuredCommit / commit)

There is no machine-wide lease. A free-floating value without a body CID is
unconstructible. lease_receipt_cid is gone from the seal.

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
    """Measured axis: value cited from an identity-bound body artifact.

    Unconstructible without body_artifact_cid AND value_field_path.
    No lease receipt in the seal — the global mutex is gone.
    """

    value: int
    body_artifact_cid: str
    value_field_path: str
    collected: int
    exit_code: int

    def __post_init__(self) -> None:
        _require_int("value", self.value, min_value=0)
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
    body_artifact_cid: str,
    value_field_path: str,
    collected: int,
    exit_code: int,
) -> Measured:
    return Measured(
        value,
        body_artifact_cid,
        value_field_path,
        collected,
        exit_code,
    )


def unmeasured(reason: str) -> Unmeasured:
    return Unmeasured(reason)


def measured_from_body(
    *,
    commit_sha: str,
    body: Mapping[str, Any],
    body_artifact_cid: str,
    value_field_path: str,
    collected_field_path: str | None = None,
    exit_code: int | None = None,
) -> AxisReading:
    """Cite-compose one axis from an identity-bound body artifact.

    Returns Unmeasured on commit mismatch or missing value field.
    """
    sha = _require_nonempty_str("commit_sha", commit_sha)
    _require_nonempty_str("body_artifact_cid", body_artifact_cid)
    path = _require_nonempty_str("value_field_path", value_field_path)

    body_commit = (
        body.get("measuredCommit")
        or body.get("commit")
        or body.get("gitCommit")
    )
    if isinstance(body_commit, str) and body_commit and body_commit != sha:
        return unmeasured(
            f"body commit {body_commit!r} != composition commit {sha!r}"
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
        try:
            c = _lookup_path(body, "totals.collected")
            if type(c) is int and c >= 0:
                collected = c
        except KeyError:
            collected = 0
    code = exit_code
    if code is None:
        code = int(body.get("exitCode") or body.get("pytestExitStatus") or 0)
    if type(code) is not int:
        return unmeasured(f"exit_code not int: {code!r}")
    return measured(
        raw_value,
        body_artifact_cid=body_artifact_cid,
        value_field_path=path,
        collected=collected,
        exit_code=code,
    )


# Back-compat alias during migration of call sites
def measured_from_sealed_pair(**kwargs):
    """Deprecated alias: ignores lease_* kwargs if present."""
    kwargs.pop("lease_record", None)
    kwargs.pop("lease_receipt_cid", None)
    return measured_from_body(**kwargs)


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


# Per-commit tip axes only (nightlies are a different obligation).
TIP_AXIS_SPECS: tuple[tuple[str, str, str], ...] = (
    # axis_name, measurementClass, value_field_path on body
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
    """Cite-compose tip axes from a directory of downloaded measurement bodies.

    For each enrolled per-commit class: find an identity-bound body
    (measurementClass / path hints / suite-report shape). Missing body →
    Unmeasured. Never recomputes product residual; values are field-paths on
    sealed bodies. No lease receipt is consulted.
    """
    sha = _require_nonempty_str("commit_sha", commit_sha)
    root = Path(receipts_dir)
    # measurementClass -> (path, body)
    by_class: dict[str, tuple[Path, Mapping[str, Any]]] = {}
    if root.is_dir():
        for path in sorted(root.rglob("*.json")):
            payload = _load_json(path)
            if payload is None:
                continue
            cls = payload.get("measurementClass")
            if not isinstance(cls, str):
                text = str(path).replace("\\", "/")
                if "suite-report" in path.name or "python-package-suite" in text:
                    cls = "python-package-suite"
                elif "floor-measurement" in path.name or "sole-construction" in text:
                    cls = "python-sole-construction-floors"
                else:
                    continue
            if "totals" not in payload and "failedNodeIds" not in payload:
                # still accept floor-measurement with totals.failed
                if "exitCode" in payload and "totals" not in payload:
                    payload = {
                        **payload,
                        "totals": {"failed": 0 if payload.get("exitCode") == 0 else 1},
                    }
                elif "totals" not in payload and "failedNodeIds" not in payload:
                    continue
            by_class.setdefault(cls, (path, payload))

    axes: dict[str, AxisReading] = {}
    for axis_name, class_name, value_path in TIP_AXIS_SPECS:
        if class_name not in by_class:
            axes[axis_name] = unmeasured(
                f"no measurement body for class {class_name!r} at commit {sha}"
            )
            continue
        _path, body = by_class[class_name]
        axes[axis_name] = measured_from_body(
            commit_sha=sha,
            body=body,
            body_artifact_cid=content_cid(body),
            value_field_path=value_path,
        )
    return commit_measurement(sha, roster_cid, axes)
