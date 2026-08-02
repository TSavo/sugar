#!/usr/bin/env python3
"""S1.1 re-rank input format — provenance-bound axes only (no bare integers).

THE GAP
=======

Parked residual numbers lived in chat and PR bodies (criterion 4/5/3/1, parent
vector 208). Axes were ranked as bare integers with no instrument, no commit,
and no Measured/Unmeasured distinction — the same shape as R_total over mixed
testimony.

CommitMeasurement already refuses to total over Unmeasured tip axes. This
module extends that discipline to **re-rank inputs**: every axis entering an
advisor re-rank must be either:

  MeasuredAxis(value, provenance)  — instrument + commit + body/field path
                                       + declared scan_scope (population)
  UnmeasuredAxis(reason)           — third value, not zero, not a chat integer

A bare int has no constructor. A chat-sourced claim has no Measured door.
An R without a declared root set (InstrumentScanScope provenance) has no
Measured door either — advisor S1.1 re-rank requires population as well as
instrument and commit (vendor 23→~0 class).

THIS MODULE DOES NOT
====================

- Populate residual numbers
- Rank or re-rank anything
- Fire compose / lease / recensus / sole-construction
- Claim SCOREBOARD_AUTHORITY (False)

Advisor owns S1.1 re-rank. This is only the input **format**.

ONE DOOR
========

``rerank_input(tip_sha, axes) -> CompleteRerankInput | PartialRerankInput``

CompleteRerankInput: every enrolled axis is Measured (``.rankable_axes()``).
PartialRerankInput: any Unmeasured — **no** rankable projection that pretends
completeness (no silent drop of Unmeasured into a total or ordered list of ints).
"""

from __future__ import annotations

SCOREBOARD_AUTHORITY = False

from dataclasses import dataclass
from typing import Mapping, Union


class RerankInputError(TypeError):
    """Illegal re-rank input — refused at construction."""


_SEAL = object()


def _require_nonempty_str(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RerankInputError(
            f"{name} must be a non-empty str; got {type(value).__name__!r}={value!r}"
        )
    return value.strip()


def _require_int_ge0(name: str, value: object) -> int:
    if type(value) is not int:
        raise RerankInputError(f"{name} must be int, not {type(value).__name__}")
    if value < 0:
        raise RerankInputError(f"{name} must be >= 0; got {value}")
    return value


@dataclass(frozen=True, slots=True)
class ScanScopeRecord:
    """Declared instrument population — required on every Measured axis.

    Mirrors InstrumentScanScope.to_provenance(): an R is meaningless without
    declared_roots; self_exclusion and auth_pin_exclusion are structural True.
    """

    declared_roots: tuple[str, ...]
    self_exclusion: bool
    auth_pin_exclusion: bool

    def __post_init__(self) -> None:
        if not self.declared_roots:
            raise RerankInputError(
                "scan_scope.declared_roots must be non-empty; an R without a "
                "declared population is unconstructible (wrong-population class)"
            )
        cleaned: list[str] = []
        for root in self.declared_roots:
            cleaned.append(_require_nonempty_str("scan_scope.declared_roots item", root))
        object.__setattr__(self, "declared_roots", tuple(cleaned))
        if self.self_exclusion is not True:
            raise RerankInputError(
                "scan_scope.self_exclusion must be True by construction; "
                "cannot rank product R that admits instrument-self"
            )
        if self.auth_pin_exclusion is not True:
            raise RerankInputError(
                "scan_scope.auth_pin_exclusion must be True by construction; "
                "cannot rank product R that admits auth-pin inventory"
            )

    def to_json(self) -> dict:
        return {
            "declaredRoots": list(self.declared_roots),
            "selfExclusion": True,
            "authPinExclusion": True,
        }


def scan_scope_record(
    *,
    declared_roots: tuple[str, ...] | list[str],
    self_exclusion: bool = True,
    auth_pin_exclusion: bool = True,
) -> ScanScopeRecord:
    """One door for re-rank scan-scope provenance."""
    return ScanScopeRecord(
        declared_roots=tuple(declared_roots),
        self_exclusion=self_exclusion,
        auth_pin_exclusion=auth_pin_exclusion,
    )


@dataclass(frozen=True, slots=True)
class InstrumentProvenance:
    """Where a Measured axis number came from — not a chat message.

    instrument_id: repo path or stable id of the owning instrument
      (e.g. scripts/self_sealing_instrument_law.py).
    commit_sha: commit at which that instrument was run.
    body_artifact_cid: content address of the report body that owns the value.
    value_field_path: field path inside that body (cite-compose).
    scan_scope: declared population (InstrumentScanScope provenance).
    receipt_cid: optional lease receipt CID when the run was under heavy lease.
    """

    instrument_id: str
    commit_sha: str
    body_artifact_cid: str
    value_field_path: str
    scan_scope: ScanScopeRecord
    receipt_cid: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "instrument_id",
            _require_nonempty_str("instrument_id", self.instrument_id),
        )
        object.__setattr__(
            self, "commit_sha", _require_nonempty_str("commit_sha", self.commit_sha)
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
        if not isinstance(self.scan_scope, ScanScopeRecord):
            raise RerankInputError(
                "InstrumentProvenance requires ScanScopeRecord "
                f"(got {type(self.scan_scope).__name__}); re-rank MUST declare "
                "root set + self/auth-pin exclusion by construction"
            )
        if self.receipt_cid is not None:
            object.__setattr__(
                self,
                "receipt_cid",
                _require_nonempty_str("receipt_cid", self.receipt_cid),
            )

    def to_json(self) -> dict:
        out = {
            "instrumentId": self.instrument_id,
            "commitSha": self.commit_sha,
            "bodyArtifactCid": self.body_artifact_cid,
            "valueFieldPath": self.value_field_path,
            "scanScope": self.scan_scope.to_json(),
        }
        if self.receipt_cid is not None:
            out["receiptCid"] = self.receipt_cid
        return out


@dataclass(frozen=True, slots=True)
class MeasuredAxis:
    """A residual count with sealed provenance. Unconstructible as a bare int."""

    axis: str
    value: int
    provenance: InstrumentProvenance
    _seal: object

    def __post_init__(self) -> None:
        if self._seal is not _SEAL:
            raise RerankInputError(
                "MeasuredAxis is sealed: use measured_axis(...); "
                "a bare integer from chat/PR body has no constructor"
            )
        object.__setattr__(self, "axis", _require_nonempty_str("axis", self.axis))
        _require_int_ge0("value", self.value)
        if not isinstance(self.provenance, InstrumentProvenance):
            raise RerankInputError(
                "MeasuredAxis requires InstrumentProvenance "
                f"(got {type(self.provenance).__name__})"
            )

    def is_measured(self) -> bool:
        return True

    def to_json(self) -> dict:
        return {
            "status": "measured",
            "axis": self.axis,
            "value": self.value,
            "provenance": self.provenance.to_json(),
        }


@dataclass(frozen=True, slots=True)
class UnmeasuredAxis:
    """Third value: this axis has no re-derived number at the tip. Not zero."""

    axis: str
    reason: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "axis", _require_nonempty_str("axis", self.axis))
        object.__setattr__(
            self, "reason", _require_nonempty_str("reason", self.reason)
        )

    def is_measured(self) -> bool:
        return False

    def to_json(self) -> dict:
        return {
            "status": "unmeasured",
            "axis": self.axis,
            "reason": self.reason,
        }


AxisEntry = Union[MeasuredAxis, UnmeasuredAxis]


def measured_axis(
    axis: str,
    value: int,
    *,
    instrument_id: str,
    commit_sha: str,
    body_artifact_cid: str,
    value_field_path: str,
    scan_scope: ScanScopeRecord,
    receipt_cid: str | None = None,
) -> MeasuredAxis:
    """One door for a measured re-rank axis — provenance + population required."""
    prov = InstrumentProvenance(
        instrument_id=instrument_id,
        commit_sha=commit_sha,
        body_artifact_cid=body_artifact_cid,
        value_field_path=value_field_path,
        scan_scope=scan_scope,
        receipt_cid=receipt_cid,
    )
    return MeasuredAxis(axis, value, prov, _SEAL)


def unmeasured_axis(axis: str, reason: str) -> UnmeasuredAxis:
    """One door for Unmeasured — chat-only cites belong here, not as integers."""
    return UnmeasuredAxis(axis, reason)


def unmeasured_chat_cite(axis: str, *, source: str = "chat/PR body") -> UnmeasuredAxis:
    """Explicit constructor for the R_total=208 failure mode: chat-parked numbers."""
    return UnmeasuredAxis(
        axis,
        f"chat-cite only ({source}): not re-derived by an instrument at tip; "
        f"cannot enter re-rank as a bare integer",
    )


@dataclass(frozen=True, slots=True)
class CompleteRerankInput:
    """Every axis Measured — the only shape that may expose rankable axes."""

    tip_sha: str
    axes: Mapping[str, MeasuredAxis]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "tip_sha", _require_nonempty_str("tip_sha", self.tip_sha)
        )
        if not isinstance(self.axes, Mapping) or not self.axes:
            raise RerankInputError("CompleteRerankInput.axes must be non-empty")
        sealed: dict[str, MeasuredAxis] = {}
        for name, entry in self.axes.items():
            key = _require_nonempty_str("axis key", name)
            if not isinstance(entry, MeasuredAxis):
                raise RerankInputError(
                    f"CompleteRerankInput refuses Unmeasured axis {key!r}"
                )
            if entry.axis != key:
                raise RerankInputError(
                    f"axis key {key!r} != entry.axis {entry.axis!r}"
                )
            sealed[key] = entry
        object.__setattr__(self, "axes", sealed)

    def is_complete(self) -> bool:
        return True

    def rankable_axes(self) -> tuple[MeasuredAxis, ...]:
        """Advisor may re-rank these — all have instrument provenance at a commit."""
        return tuple(self.axes[k] for k in sorted(self.axes))

    def to_json(self) -> dict:
        return {
            "kind": "rerank-input",
            "status": "complete",
            "tipSha": self.tip_sha,
            "scoreboardAuthority": False,
            "axes": {k: v.to_json() for k, v in sorted(self.axes.items())},
        }


@dataclass(frozen=True, slots=True)
class PartialRerankInput:
    """Any Unmeasured axis — no rankable projection that drops silence."""

    tip_sha: str
    axes: Mapping[str, AxisEntry]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "tip_sha", _require_nonempty_str("tip_sha", self.tip_sha)
        )
        if not isinstance(self.axes, Mapping) or not self.axes:
            raise RerankInputError("PartialRerankInput.axes must be non-empty")
        sealed: dict[str, AxisEntry] = {}
        saw_unmeasured = False
        for name, entry in self.axes.items():
            key = _require_nonempty_str("axis key", name)
            if not isinstance(entry, (MeasuredAxis, UnmeasuredAxis)):
                raise RerankInputError(
                    f"axis {key!r}: must be MeasuredAxis or UnmeasuredAxis; "
                    f"got {type(entry).__name__} — bare int unconstructible"
                )
            if isinstance(entry, UnmeasuredAxis):
                saw_unmeasured = True
            if entry.axis != key:
                raise RerankInputError(
                    f"axis key {key!r} != entry.axis {entry.axis!r}"
                )
            sealed[key] = entry
        if not saw_unmeasured:
            raise RerankInputError(
                "PartialRerankInput requires ≥1 UnmeasuredAxis; "
                "use CompleteRerankInput when all measured"
            )
        object.__setattr__(self, "axes", sealed)

    def is_complete(self) -> bool:
        return False

    def unmeasured_axes(self) -> tuple[str, ...]:
        return tuple(
            k for k, v in self.axes.items() if isinstance(v, UnmeasuredAxis)
        )

    def to_json(self) -> dict:
        return {
            "kind": "rerank-input",
            "status": "partial",
            "tipSha": self.tip_sha,
            "scoreboardAuthority": False,
            # deliberately no rankableAxes / total
            "unmeasuredAxes": list(self.unmeasured_axes()),
            "axes": {k: v.to_json() for k, v in sorted(self.axes.items())},
        }


RerankInput = Union[CompleteRerankInput, PartialRerankInput]


def rerank_input(
    tip_sha: str,
    axes: Mapping[str, AxisEntry],
) -> RerankInput:
    """ONE DOOR for S1.1 re-rank input. Bare integers never enter."""
    sha = _require_nonempty_str("tip_sha", tip_sha)
    if not isinstance(axes, Mapping) or not axes:
        raise RerankInputError("axes must be a non-empty mapping")
    sealed: dict[str, AxisEntry] = {}
    for name, entry in axes.items():
        key = _require_nonempty_str("axis key", name)
        if isinstance(entry, int):
            raise RerankInputError(
                f"axis {key!r}: bare integer {entry!r} is unconstructible; "
                f"use measured_axis(...) with instrument provenance or "
                f"unmeasured_axis/unmeasured_chat_cite(...)"
            )
        if not isinstance(entry, (MeasuredAxis, UnmeasuredAxis)):
            raise RerankInputError(
                f"axis {key!r}: must be MeasuredAxis or UnmeasuredAxis; "
                f"got {type(entry).__name__}"
            )
        if entry.axis != key:
            raise RerankInputError(
                f"axis key {key!r} != entry.axis {entry.axis!r}"
            )
        sealed[key] = entry
    if any(isinstance(e, UnmeasuredAxis) for e in sealed.values()):
        return PartialRerankInput(sha, sealed)
    return CompleteRerankInput(sha, sealed)  # type: ignore[arg-type]


# Enrolled criterion *slots* for S1.1 (names only — no numbers).
# Population with Measured values is advisor S1.1 after live re-derivation.
# Chat-parked figures must use unmeasured_chat_cite until re-derived.
ENROLLED_RERANK_AXIS_IDS: tuple[str, ...] = (
    # Criterion 4 — second-mechanism residual classes (instrument-owned when measured)
    "criterion4.vendor_special_case",
    "criterion4.spelling_dispatch",
    "criterion4.space_hunting",
    "criterion4.finite_cap_opaque",
    "criterion4.swallowed_throw",
    "criterion4.compatibility_door",
    # Criterion 5 — twin / hatch inventory
    "criterion5.missing_lying_twins",
    "criterion5.honest_with_hatch_unsealed",
    "criterion5.opt_outs",
    # Criterion 3 — split R (see docs/path-forward.md Criterion 3 section)
    # naming_nothing: superseded by #7022 sealed grounds; held on #6988 disposition
    "criterion3.naming_nothing_drained_but_held",
    # kit incomplete: NOT C3 finality — write sugar/floor or delete hierarchy-lie arm
    "criterion3.R_kit_incomplete",
    # true C3: runtime sealed grounds that holds(world) + enrolled honest residual classes
    "criterion3.R_source_undecidable_refusals",
    # floor: mints where holds(world) was false (must stay empty)
    "criterion3.R_refusals_over_decidable_source",
    # Criterion 1 — authenticated denominator
    "criterion1.authenticated_denominator",
)
