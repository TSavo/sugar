#!/usr/bin/env python3
"""CommitMeasurement — sealed composition of tip measurement testimony.

Cite-compose only. SCOREBOARD_AUTHORITY = False. Never recompute product R.

    AxisReading = Measured(...) | Unmeasured(reason)
    commit_measurement(...) -> CompleteVector | PartialVector

Measured is authenticated by WHAT IT PRODUCED + declared population:

  - identity: which measurement class this axis is
  - population_id + population_size: declared denominator
  - body_cid: content address of the report body
  - value_field_path / value / exit_code

There is no machine-wide lease. No lease_receipt_cid in the seal (deleted with
the lease architecture). Free-floating value without a body is unconstructible.

CompleteVector has .total. PartialVector has no .total.
Unmeasured is a third value, not zero.

One door: ``commit_measurement`` / ``compose_tip_from_artifacts_dir``.
"""

from __future__ import annotations

SCOREBOARD_AUTHORITY = False

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Union

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

_MEASURED_SEAL = object()


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
    if isinstance(payload, Mapping):
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    elif isinstance(payload, str):
        raw = payload.encode("utf-8")
    else:
        raw = payload
    digest = hashlib.blake2b(raw, digest_size=32).hexdigest()
    return f"blake2b-256:{digest}"


def _lookup_path(body: Mapping[str, Any], field_path: str) -> Any:
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
    """Measured axis: identity + declared population + body_cid of produced report.

    No lease receipt. Sealed construction only via measured(body=...).
    """

    value: int
    identity: str
    population_id: str
    population_size: int
    body_cid: str
    value_field_path: str
    exit_code: int
    _seal: object

    def __post_init__(self) -> None:
        if self._seal is not _MEASURED_SEAL:
            raise CommitMeasurementError(
                "Measured is sealed: use measured(body=...) or measured_from_body(...)"
            )
        _require_int("value", self.value, min_value=0)
        object.__setattr__(
            self, "identity", _require_nonempty_str("identity", self.identity)
        )
        object.__setattr__(
            self,
            "population_id",
            _require_nonempty_str("population_id", self.population_id),
        )
        _require_int("population_size", self.population_size, min_value=0)
        object.__setattr__(
            self, "body_cid", _require_nonempty_str("body_cid", self.body_cid)
        )
        object.__setattr__(
            self,
            "value_field_path",
            _require_nonempty_str("value_field_path", self.value_field_path),
        )
        _require_int("exit_code", self.exit_code)

    # Back-compat alias used by older JSON readers / tests
    @property
    def body_artifact_cid(self) -> str:
        return self.body_cid

    @property
    def collected(self) -> int:
        return self.population_size

    def is_measured(self) -> bool:
        return True


@dataclass(frozen=True, slots=True)
class Unmeasured:
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
    identity: str,
    population_id: str,
    population_size: int,
    body: Mapping[str, Any],
    value_field_path: str,
    exit_code: int,
) -> Measured:
    """Build Measured from parsed body + declared population. No lease param."""
    if not isinstance(body, Mapping):
        raise CommitMeasurementError(
            f"Measured requires a parsed body mapping; got {type(body).__name__}. "
            "NoReport is Unmeasured."
        )
    path_s = _require_nonempty_str("value_field_path", value_field_path)
    try:
        raw = _lookup_path(body, path_s)
    except KeyError as exc:
        raise CommitMeasurementError(
            f"Measured refuses: body missing value field {path_s!r} (NoReport)"
        ) from exc
    if type(raw) is not int or raw < 0:
        raise CommitMeasurementError(
            f"Measured refuses: body field {path_s!r} is not a non-negative int: {raw!r}"
        )
    if type(value) is not int or value != raw:
        raise CommitMeasurementError(
            f"Measured refuses: value {value!r} does not match body[{path_s!r}]={raw!r}"
        )
    return Measured(
        value,
        identity,
        population_id,
        population_size,
        content_cid(body),
        path_s,
        exit_code,
        _MEASURED_SEAL,
    )


def unmeasured(reason: str) -> Unmeasured:
    return Unmeasured(reason)


def measured_from_body(
    *,
    identity: str,
    population_id: str,
    population_size: int,
    body: Mapping[str, Any],
    body_cid: str | None = None,
    value_field_path: str,
    exit_code: int = 0,
    # ignored legacy kwargs so call sites mid-transition do not crash
    commit_sha: str | None = None,
    body_artifact_cid: str | None = None,
    collected_field_path: str | None = None,
    lease_record: Any = None,
    lease_receipt_cid: str | None = None,
) -> AxisReading:
    """Cite one axis from a produced report body. No lease required."""
    del commit_sha, lease_record, lease_receipt_cid  # explicitly unused
    if body_artifact_cid is not None and body_cid is None:
        body_cid = body_artifact_cid
    if not isinstance(body, Mapping):
        return unmeasured(f"NoReport: body is {type(body).__name__}, not a mapping")
    expected = content_cid(body)
    if body_cid is not None and body_cid != expected:
        return unmeasured(
            f"NoReport: body_cid mismatch (presented {body_cid!r}, content {expected!r})"
        )
    path = _require_nonempty_str("value_field_path", value_field_path)
    try:
        raw_value = _lookup_path(body, path)
    except KeyError:
        return unmeasured(f"NoReport: body missing value field {path!r}")
    if type(raw_value) is not int or raw_value < 0:
        return unmeasured(
            f"NoReport: body field {path!r} is not a non-negative int: {raw_value!r}"
        )
    pop_size = population_size
    if collected_field_path:
        try:
            c = _lookup_path(body, collected_field_path)
            if type(c) is int and c >= 0:
                pop_size = c
        except KeyError:
            return unmeasured(
                f"NoReport: body missing collected field {collected_field_path!r}"
            )
    try:
        return measured(
            raw_value,
            identity=identity,
            population_id=population_id,
            population_size=pop_size,
            body=body,
            value_field_path=path,
            exit_code=exit_code,
        )
    except CommitMeasurementError as exc:
        return unmeasured(str(exc))


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
                f"(SCOREBOARD_AUTHORITY=False)."
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
    population_roster_id: str
    axes: Mapping[str, Measured]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "commit_sha", _require_nonempty_str("commit_sha", self.commit_sha)
        )
        object.__setattr__(
            self,
            "population_roster_id",
            _require_nonempty_str("population_roster_id", self.population_roster_id),
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
    def roster_cid(self) -> str:
        return self.population_roster_id

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
            "populationRosterId": self.population_roster_id,
            "rosterCid": self.population_roster_id,
            "total": self.total,
            "axes": {
                name: {
                    "status": "measured",
                    "value": r.value,
                    "identity": r.identity,
                    "populationId": r.population_id,
                    "populationSize": r.population_size,
                    "bodyCid": r.body_cid,
                    "bodyArtifactCid": r.body_cid,
                    "valueFieldPath": r.value_field_path,
                    "collected": r.population_size,
                    "exitCode": r.exit_code,
                }
                for name, r in self.axes.items()
            },
        }


@dataclass(frozen=True, slots=True)
class PartialVector:
    commit_sha: str
    population_roster_id: str
    axes: Mapping[str, AxisReading]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "commit_sha", _require_nonempty_str("commit_sha", self.commit_sha)
        )
        object.__setattr__(
            self,
            "population_roster_id",
            _require_nonempty_str("population_roster_id", self.population_roster_id),
        )
        sealed = _require_axes_map(self.axes)
        if not any(isinstance(r, Unmeasured) for r in sealed.values()):
            raise CommitMeasurementError(
                "PartialVector requires ≥1 Unmeasured; use CompleteVector"
            )
        object.__setattr__(self, "axes", sealed)

    @property
    def roster_cid(self) -> str:
        return self.population_roster_id

    def is_complete(self) -> bool:
        return False

    def unmeasured_axes(self) -> tuple[str, ...]:
        return tuple(
            name for name, r in self.axes.items() if isinstance(r, Unmeasured)
        )

    def to_json(self) -> dict[str, Any]:
        axes_out: dict[str, Any] = {}
        for name, r in self.axes.items():
            if isinstance(r, Measured):
                axes_out[name] = {
                    "status": "measured",
                    "value": r.value,
                    "identity": r.identity,
                    "populationId": r.population_id,
                    "populationSize": r.population_size,
                    "bodyCid": r.body_cid,
                    "bodyArtifactCid": r.body_cid,
                    "valueFieldPath": r.value_field_path,
                    "collected": r.population_size,
                    "exitCode": r.exit_code,
                }
            else:
                axes_out[name] = {"status": "unmeasured", "reason": r.reason}
        return {
            "kind": "commit-measurement",
            "status": "partial",
            "commitSha": self.commit_sha,
            "populationRosterId": self.population_roster_id,
            "rosterCid": self.population_roster_id,
            "unmeasuredAxes": list(self.unmeasured_axes()),
            "axes": axes_out,
        }


CommitMeasurement = Union[CompleteVector, PartialVector]


def commit_measurement(
    commit_sha: str,
    population_roster_id: str,
    axes: Mapping[str, AxisReading],
) -> CommitMeasurement:
    sha = _require_nonempty_str("commit_sha", commit_sha)
    roster = _require_nonempty_str("population_roster_id", population_roster_id)
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


TIP_AXIS_SPECS: tuple[tuple[str, str], ...] = (
    ("python-package-suite", "totals.failed"),
    ("python-sole-construction-floors", "totals.failed"),
)


def compose_tip_from_artifacts_dir(
    commit_sha: str,
    artifacts_dir: Path,
    *,
    population_roster_id: str = "heavy-roster:per-commit",
) -> CommitMeasurement:
    """Cite tip axes from produced report bodies (no lease)."""
    sha = _require_nonempty_str("commit_sha", commit_sha)
    root = Path(artifacts_dir)
    bodies: list[tuple[Path, Mapping[str, Any]]] = []
    if root.is_dir():
        for path in sorted(root.rglob("*.json")):
            payload = _load_json(path)
            if payload is None:
                continue
            if "totals" in payload or "failedNodeIds" in payload:
                bodies.append((path, payload))

    axes: dict[str, AxisReading] = {}
    for identity, value_path in TIP_AXIS_SPECS:
        chosen: Mapping[str, Any] | None = None
        for _path, body in bodies:
            cls = body.get("measurementClass") or body.get("leaseClass")
            if isinstance(body.get("leaseRecord"), Mapping):
                cls = cls or body["leaseRecord"].get("leaseClass")
            if cls == identity or (
                cls is None
                and identity == "python-package-suite"
                and "failedNodeIds" in body
            ):
                try:
                    _lookup_path(body, value_path)
                    chosen = body
                    break
                except KeyError:
                    continue
        if chosen is None:
            axes[identity] = unmeasured(
                f"NoReport: no produced body artifact for identity {identity!r} "
                f"at commit {sha}"
            )
            continue
        pop_size = 0
        pop_id = f"{identity}:undeclared"
        try:
            c = _lookup_path(chosen, "totals.collected")
            if type(c) is int and c >= 0:
                pop_size = c
                pop_id = f"{identity}:collected"
        except KeyError:
            pass
        if isinstance(chosen.get("populationId"), str) and chosen["populationId"]:
            pop_id = str(chosen["populationId"])
        if type(chosen.get("populationSize")) is int and chosen["populationSize"] >= 0:
            pop_size = int(chosen["populationSize"])
        try:
            raw = _lookup_path(chosen, value_path)
            exit_code = 0 if type(raw) is int and raw == 0 else 1
        except KeyError:
            exit_code = 1
        axes[identity] = measured_from_body(
            identity=identity,
            population_id=pop_id,
            population_size=pop_size,
            body=chosen,
            value_field_path=value_path,
            exit_code=exit_code,
        )
    return commit_measurement(sha, population_roster_id, axes)


def compose_tip_from_receipts_dir(
    commit_sha: str,
    receipts_dir: Path,
    *,
    roster_cid: str = "heavy-roster:per-commit",
) -> CommitMeasurement:
    """Lease-free alias kept for attendance workflow call sites."""
    return compose_tip_from_artifacts_dir(
        commit_sha, receipts_dir, population_roster_id=roster_cid
    )
