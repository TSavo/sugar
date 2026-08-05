#!/usr/bin/env python3
"""CommitMeasurement — sealed composition of tip measurement testimony.

Cite-compose only. SCOREBOARD_AUTHORITY = False. Never recompute product R.

    AxisReading = Measured(...) | Unmeasured(reason)
    commit_measurement(...) -> CompleteVector | PartialVector

Measured is authenticated by WHAT IT PRODUCED + declared population + unit:

  - identity: which measurement class this axis is
  - unit: what the integer counts (incommensurable across axes)
  - population_id + population_size: declared denominator
  - body_cid: content address of the report body
  - value_field_path / value / exit_code

There is no machine-wide lease. Free-floating value without a body is
unconstructible. Axes with different units are not comparable and must not be
summed into a single residual.

Criterion-2 tip enrollment (``CRITERION2_AXIS_SPECS`` / ``TIP_AXIS_SPECS``):

  silent              assert-function-locus  (locus over asserts / fn bodies)
  native-crash        corpus-file            (file over corpus)
  bare-exception      corpus-file
  timeout             corpus-file
  R_construction_panics  construction-panic  (control-effect recensus board ONLY)

The four process floors do **not** observe panics that resolve to typed gaps
(they complete with exit 0). A vector with four green floors and no
R_construction_panics body is PARTIAL — never Complete. That axis comes from
the control-effect recensus board, which is the sole producer.

CompleteVector has no scalar .total across mixed units.
PartialVector has no .total.
Unmeasured is a third value, not zero.

One door: ``commit_measurement`` / ``compose_tip_from_artifacts_dir``.
"""

from __future__ import annotations

SCOREBOARD_AUTHORITY = False

import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence, Union

_TOOLS = Path(__file__).resolve().parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))
from sugar_repo_root import resolve_repo_root  # noqa: E402

_PACKAGE_SRC = resolve_repo_root() / "implementations/python/sugar-lift-py-tests/src"
if str(_PACKAGE_SRC) not in sys.path:
    sys.path.insert(0, str(_PACKAGE_SRC))

from sugar_lift_py_tests.conservation_mint import decode_conserved_body  # noqa: E402
from run_authority import (  # noqa: E402
    ManagedRunAuthority,
    RunAuthorityRefusal,
    require_managed_run_authority,
)

# ---------------------------------------------------------------------------
# Units — incommensurable. Presenting two Measured.values without their units
# is the misreading that treats silent loci as if they were corpus files.
# ---------------------------------------------------------------------------

UNIT_CORPUS_FILE = "corpus-file"
"""Residual count of files over the authenticated corpus (native/bare/timeout)."""

UNIT_ASSERT_FUNCTION_LOCUS = "assert-function-locus"
"""Residual count of loci over asserts and function bodies (silent floor)."""

UNIT_CONSTRUCTION_PANIC = "construction-panic"
"""Residual construction panics from the control-effect recensus board only."""

UNIT_SUITE_NODE = "suite-node"
"""Failed / residual suite node-ids (package suite; not criterion-2)."""

KNOWN_UNITS = frozenset(
    {
        UNIT_CORPUS_FILE,
        UNIT_ASSERT_FUNCTION_LOCUS,
        UNIT_CONSTRUCTION_PANIC,
        UNIT_SUITE_NODE,
    }
)

# Free-floating board residual names CM must not invent. Citing an *enrolled*
# axis (R_construction_panics) from its producer body is allowed; inventing
# R_construction / R_desugar as if CM were a second scoreboard is not.
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

_UNSET_RUN_AUTHORITY = object()
"""Distinguishes "caller said nothing" from "caller supplied None" (absent)."""


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


def _require_unit(unit: object) -> str:
    u = _require_nonempty_str("unit", unit)
    if u not in KNOWN_UNITS:
        raise CommitMeasurementError(
            f"unit {u!r} is not a known measurement unit; "
            f"known={sorted(KNOWN_UNITS)}. Axes with different units are not "
            f"comparable — do not invent a free-floating unit to force a sum."
        )
    return u


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
    """Measured axis: identity + unit + population + body_cid of produced report.

    ``unit`` is load-bearing: silent (locus) and native (file) are not the same
    kind of number. No lease receipt. Sealed via measured(body=...).
    """

    value: int
    identity: str
    unit: str
    population_id: str
    population_size: int
    body_cid: str
    value_field_path: str
    exit_code: int
    run_authority: ManagedRunAuthority
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
        object.__setattr__(self, "unit", _require_unit(self.unit))
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
        # Not a guard: the type admits no other inhabitant. A Measured cannot be
        # spelled without a ManagedRunAuthority, which cannot be spelled without
        # authenticated managed testimony.
        if not isinstance(self.run_authority, ManagedRunAuthority):
            raise CommitMeasurementError(
                "Measured requires an authenticated ManagedRunAuthority; got "
                f"{type(self.run_authority).__name__}. THE ARTIFACT MUST PROVE "
                "WHAT IT CONSUMED."
            )

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
    unit: str,
    population_id: str,
    population_size: int,
    body: Mapping[str, Any],
    value_field_path: str,
    exit_code: int,
    run_authority: Any,
    task_command_resolver: Any = None,
) -> Measured:
    """Build Measured from parsed body + declared population + unit. No lease.

    ``run_authority`` is the run-authority/v1 testimony the producing run
    carried. It is authenticated here and must be MANAGED: an ad-hoc command
    ran under no declared task, so it selected no task capability image and
    installed no precondition plan, and nothing it produced is a measurement.
    """
    try:
        authority = require_managed_run_authority(
            run_authority, task_command_resolver=task_command_resolver
        )
    except RunAuthorityRefusal as error:
        raise CommitMeasurementError(f"Measured refuses: {error}") from error
    if not isinstance(body, Mapping):
        raise CommitMeasurementError(
            f"Measured requires a parsed body mapping; got {type(body).__name__}. "
            "NoReport is Unmeasured."
        )
    if (
        identity == "R_construction_panics"
        or body.get("measurementClass") == "control-effect-recensus"
    ):
        try:
            decode_conserved_body(body)
        except ValueError as error:
            raise CommitMeasurementError(
                f"Measured refuses unconserved recensus body: {error}"
            ) from error
    path_s = _require_nonempty_str("value_field_path", value_field_path)
    unit_s = _require_unit(unit)
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
        unit_s,
        population_id,
        population_size,
        content_cid(body),
        path_s,
        exit_code,
        authority,
        _MEASURED_SEAL,
    )


def unmeasured(reason: str) -> Unmeasured:
    return Unmeasured(reason)


def measured_from_body(
    *,
    identity: str,
    unit: str,
    population_id: str,
    population_size: int,
    body: Mapping[str, Any],
    body_cid: str | None = None,
    value_field_path: str,
    exit_code: int = 0,
    commit_sha: str | None = None,
    body_artifact_cid: str | None = None,
    collected_field_path: str | None = None,
    lease_record: Any = None,
    lease_receipt_cid: str | None = None,
    run_authority: Any = _UNSET_RUN_AUTHORITY,
    task_command_resolver: Any = None,
) -> AxisReading:
    """Cite one axis from a produced report body. No lease required.

    The run-authority testimony is read from the body itself when the caller
    does not supply it: the receipt is the durable carrier, not the caller's
    memory of how the run was launched. A body carrying none is Unmeasured by
    absence, which is a different reading from Unmeasured by ad-hoc execution.
    """
    del commit_sha, lease_record, lease_receipt_cid  # explicitly unused
    if run_authority is _UNSET_RUN_AUTHORITY:
        run_authority = body.get("runAuthority") if isinstance(body, Mapping) else None
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
            unit=unit,
            population_id=population_id,
            population_size=pop_size,
            body=body,
            value_field_path=path,
            exit_code=exit_code,
            run_authority=run_authority,
            task_command_resolver=task_command_resolver,
        )
    except CommitMeasurementError as exc:
        return unmeasured(str(exc))


def _axis_name_forbidden(key: str) -> bool:
    """Board residual names CM must not invent — enrolled cite identities ok."""
    if key in CRITERION2_ENROLLED_IDENTITIES:
        return False
    if key in FORBIDDEN_BOARD_AXIS_NAMES:
        return True
    # Unenrolled R_construction* / R_desugar* names still look like a second board.
    if key.startswith("R_construction") or key.startswith("R_desugar"):
        return True
    return False


def _require_axes_map(axes: object) -> dict[str, AxisReading]:
    if not isinstance(axes, Mapping) or not axes:
        raise CommitMeasurementError(
            "axes must be a non-empty mapping of axis name -> AxisReading"
        )
    out: dict[str, AxisReading] = {}
    for name, reading in axes.items():
        key = _require_nonempty_str("axis name", name)
        if _axis_name_forbidden(key):
            raise CommitMeasurementError(
                f"axis {key!r} is a corpus-board residual name; "
                f"CommitMeasurement is cite-compose only "
                f"(SCOREBOARD_AUTHORITY=False). Enrolled criterion-2 cite "
                f"identities: {sorted(CRITERION2_ENROLLED_IDENTITIES)}."
            )
        if not isinstance(reading, (Measured, Unmeasured)):
            raise CommitMeasurementError(
                f"axis {key!r}: must be Measured or Unmeasured; "
                f"got {type(reading).__name__}"
            )
        out[key] = reading
    return out


def _measured_json(r: Measured) -> dict[str, Any]:
    return {
        "status": "measured",
        "value": r.value,
        "unit": r.unit,
        "identity": r.identity,
        "populationId": r.population_id,
        "populationSize": r.population_size,
        "bodyCid": r.body_cid,
        "bodyArtifactCid": r.body_cid,
        "valueFieldPath": r.value_field_path,
        "collected": r.population_size,
        "exitCode": r.exit_code,
        "runAuthority": r.run_authority.as_json(),
    }


@dataclass(frozen=True, slots=True)
class CompleteVector:
    """Every enrolled axis Measured. No scalar total across mixed units."""

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
            if _axis_name_forbidden(key):
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
        # Heterogeneous units (locus vs file vs construction-panic) must not
        # collapse to one integer — that is the false-comparable reading.
        units = {r.unit for r in self.axes.values()}
        raise CommitMeasurementError(
            "CompleteVector has no scalar total across measurement units; "
            "read each Measured.value with its .unit. "
            f"units_present={sorted(units)}. Use values_by_unit() only as a "
            "per-unit bag, never as a cross-unit sum of residuals."
        )

    def values_by_unit(self) -> dict[str, int]:
        """Per-unit bag of values. Not a criterion residual; not cross-unit."""
        out: dict[str, int] = {}
        for r in self.axes.values():
            out[r.unit] = out.get(r.unit, 0) + r.value
        return dict(sorted(out.items()))

    def is_complete(self) -> bool:
        return True

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": "commit-measurement",
            "status": "complete",
            "commitSha": self.commit_sha,
            "populationRosterId": self.population_roster_id,
            "rosterCid": self.population_roster_id,
            # Explicit: no scalar total. Callers that sum axes are wrong.
            "total": None,
            "valuesByUnit": self.values_by_unit(),
            "axes": {name: _measured_json(r) for name, r in self.axes.items()},
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
                axes_out[name] = _measured_json(r)
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


# ---------------------------------------------------------------------------
# Criterion-2 tip enrollment
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TipAxisSpec:
    """One enrolled tip axis: identity, unit, cite path, body match rules."""

    identity: str
    unit: str
    value_field_path: str
    # Floor axis reports: match body["axisId"]
    match_axis_id: str | None = None
    # Campaign / recensus: match body["measurementClass"]
    match_measurement_class: str | None = None
    # Board field presence (R_construction_panics top-level on recensus JSON)
    match_field: str | None = None


# Four process floors + R_construction_panics. Absence of any → Partial.
# static-laws is enrollment for sole-construction campaign attendance, not
# criterion-2 process completeness (mr_blue: panics invisible to the four).
CRITERION2_AXIS_SPECS: tuple[TipAxisSpec, ...] = (
    TipAxisSpec(
        identity="silent",
        unit=UNIT_ASSERT_FUNCTION_LOCUS,
        value_field_path="totals.failed",
        match_axis_id="silent",
        match_measurement_class="python-sole-construction-floors",
    ),
    TipAxisSpec(
        identity="native-crash",
        unit=UNIT_CORPUS_FILE,
        value_field_path="totals.failed",
        match_axis_id="native-crash",
        match_measurement_class="python-sole-construction-floors",
    ),
    TipAxisSpec(
        identity="bare-exception",
        unit=UNIT_CORPUS_FILE,
        value_field_path="totals.failed",
        match_axis_id="bare-exception",
        match_measurement_class="python-sole-construction-floors",
    ),
    TipAxisSpec(
        identity="timeout",
        unit=UNIT_CORPUS_FILE,
        value_field_path="totals.failed",
        match_axis_id="timeout",
        match_measurement_class="python-sole-construction-floors",
    ),
    TipAxisSpec(
        identity="R_construction_panics",
        unit=UNIT_CONSTRUCTION_PANIC,
        value_field_path="R_construction_panics",
        match_measurement_class="control-effect-recensus",
        match_field="R_construction_panics",
    ),
)

CRITERION2_ENROLLED_IDENTITIES: frozenset[str] = frozenset(
    s.identity for s in CRITERION2_AXIS_SPECS
)

# Tip compose door uses criterion-2 enrollment. Complete ⇒ every C2 axis
# Measured, including R_construction_panics from the recensus board.
TIP_AXIS_SPECS: tuple[TipAxisSpec, ...] = CRITERION2_AXIS_SPECS


def _body_matches_spec(body: Mapping[str, Any], spec: TipAxisSpec) -> bool:
    # Refuse recensus-path-smoke BEFORE match_field short-circuit. A smoke seal
    # that still carries R_construction_panics (stripped/malformed) must not
    # Measure panics — _is_candidate_body already refuses, but match_field alone
    # used to return True first.
    smoke_cls = body.get("measurementClass") or body.get("leaseClass")
    if (
        smoke_cls == "recensus-path-smoke"
        or body.get("kind") == "recensus-path-smoke-verdict"
    ):
        return False
    if spec.match_axis_id is not None:
        if body.get("axisId") == spec.match_axis_id:
            return True
        # Reject other floor-axis reports that share measurementClass.
        if body.get("kind") == "sole-construction-floor-axis-report":
            return False
        if body.get("axisId") is not None and body.get("axisId") != spec.match_axis_id:
            return False
    if spec.match_field is not None and spec.match_field in body:
        return True
    if spec.match_measurement_class is not None:
        cls = body.get("measurementClass") or body.get("leaseClass")
        if isinstance(body.get("leaseRecord"), Mapping):
            cls = cls or body["leaseRecord"].get("leaseClass")
        if cls == spec.match_measurement_class and spec.match_axis_id is None:
            return True
        # Recensus measurement.json is a thin attendance stub without the board
        # field — only accept class match when the value path is present.
        if cls == spec.match_measurement_class and spec.match_field is not None:
            return spec.match_field in body
    return False


def _is_candidate_body(payload: Mapping[str, Any]) -> bool:
    # recensus-path-smoke is PATH integrity only — never a panics/board candidate.
    cls = payload.get("measurementClass") or payload.get("leaseClass")
    if cls == "recensus-path-smoke" or payload.get("kind") == "recensus-path-smoke-verdict":
        return False
    if "totals" in payload or "failedNodeIds" in payload:
        return True
    if "R_construction_panics" in payload:
        return True
    if payload.get("measurementClass") == "control-effect-recensus":
        return True
    if payload.get("kind") == "sole-construction-floor-axis-report":
        return True
    if payload.get("axisId") in CRITERION2_ENROLLED_IDENTITIES:
        return True
    return False


def _body_declares_unmeasured(body: Mapping[str, Any]) -> str | None:
    """#7034: enrollment mints status=unmeasured / measured=False with a reason.

    A body that declares unmeasured must not be cited as Measured merely because
    totals.failed is present — that was the crash-as-residual lie.
    """
    measured_flag = body.get("measured")
    status = body.get("status")
    if measured_flag is False or status == "unmeasured":
        reason = body.get("unmeasuredReason") or body.get("reason")
        if isinstance(reason, str) and reason.strip():
            return reason.strip()
        return (
            "EnrollmentUnmeasured: axis body declares measured=False "
            f"status={status!r} exitCode={body.get('exitCode')!r} "
            "(scan did not complete — not a residual reading)"
        )
    return None


def compose_tip_from_artifacts_dir(
    commit_sha: str,
    artifacts_dir: Path,
    *,
    population_roster_id: str = "criterion2-roster:per-commit",
    axis_specs: Sequence[TipAxisSpec] | None = None,
) -> CommitMeasurement:
    """Cite criterion-2 tip axes from produced report bodies (no lease).

    Missing any enrolled axis (including R_construction_panics) → Unmeasured
    for that axis → PartialVector. Four green floors alone never Complete.

    #7034 bodies with status=unmeasured / measured=False cite as Unmeasured
    with unmeasuredReason — never Measured from totals.failed alone.
    """
    sha = _require_nonempty_str("commit_sha", commit_sha)
    specs: Sequence[TipAxisSpec] = (
        tuple(axis_specs) if axis_specs is not None else TIP_AXIS_SPECS
    )
    root = Path(artifacts_dir)
    bodies: list[tuple[Path, Mapping[str, Any]]] = []
    if root.is_dir():
        for path in sorted(root.rglob("*.json")):
            payload = _load_json(path)
            if payload is None:
                continue
            if _is_candidate_body(payload):
                bodies.append((path, payload))

    axes: dict[str, AxisReading] = {}
    for spec in specs:
        identity = spec.identity
        value_path = spec.value_field_path
        chosen_measured: Mapping[str, Any] | None = None
        chosen_unmeasured: Mapping[str, Any] | None = None
        for _path, body in bodies:
            if not _body_matches_spec(body, spec):
                continue
            um_reason = _body_declares_unmeasured(body)
            if um_reason is not None:
                chosen_unmeasured = body
                continue
            try:
                _lookup_path(body, value_path)
            except KeyError:
                continue
            chosen_measured = body
            break
        if chosen_measured is None and chosen_unmeasured is not None:
            reason = _body_declares_unmeasured(chosen_unmeasured) or "EnrollmentUnmeasured"
            axes[identity] = unmeasured(
                f"{reason} identity={identity!r} unit={spec.unit} commit={sha}"
            )
            continue
        if chosen_measured is None:
            if identity == "R_construction_panics":
                axes[identity] = unmeasured(
                    f"NoBoard: no control-effect recensus board body for "
                    f"identity {identity!r} (unit={spec.unit}) at commit {sha} "
                    f"— sole producer of R_construction_panics; floors do not measure it"
                )
            else:
                axes[identity] = unmeasured(
                    f"NoReport: no produced completed body for identity "
                    f"{identity!r} (unit={spec.unit}) at commit {sha}"
                )
            continue
        chosen = chosen_measured
        pop_size = 0
        pop_id = f"{identity}:undeclared"
        try:
            c = _lookup_path(chosen, "totals.collected")
            if type(c) is int and c >= 0:
                pop_size = c
                pop_id = f"{identity}:collected"
        except KeyError:
            pass
        # Recensus boards often expose corpus size under enrolledFiles / etc.
        for alt in ("enrolledFiles", "populationSize", "fileCount"):
            if type(chosen.get(alt)) is int and chosen[alt] >= 0:
                pop_size = int(chosen[alt])
                pop_id = f"{identity}:{alt}"
                break
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
            unit=spec.unit,
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
    roster_cid: str = "criterion2-roster:per-commit",
) -> CommitMeasurement:
    """Lease-free alias kept for attendance workflow call sites."""
    return compose_tip_from_artifacts_dir(
        commit_sha, receipts_dir, population_roster_id=roster_cid
    )
