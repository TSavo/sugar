#!/usr/bin/env python3
"""CommitMeasurement — one door for READING measurement state of a commit.

THE GAP THIS CLOSES
===================

We have one door for TAKING a measurement (the heavy lease). We had NO door
for READING the state. "How are we doing?" was answered with workflow colour,
``gh run list``, a log tail, a green check — none authoritative. Summing axis
R when any axis was never measured produces a number that can *drop* when a
silent unmeasured axis is discovered, and that drop reads as progress.

This module is the composition object. It does not take measurements. It does
not re-scan product offenders. It makes illegal readings unconstructible.

    CommitMeasurement / CompleteVector / PartialVector
    AxisReading = Measured(value, receipt_cid, collected, exit_code) | Unmeasured(reason)

THREE CONSTRUCTOR LAWS
======================

1. An R reading IS a (value, receipt) pair, unconstructible apart.
   ``Measured`` refuses without a non-empty ``receipt_cid`` that names the
   lease/artifact receipt proving the class was acquired for that commit,
   plus ``collected`` (denominator evidence) and ``exit_code`` captured
   pre-pipe. Precedent: 255 red rows with no grounds (#3540) — a lie with a
   stack trace; the fix is a type.

2. ``Unmeasured`` is a THIRD VALUE, not zero. Distinct constructor, not
   coercible to ``Measured(0, ...)``. Absence yields Unmeasured, never blank
   and never green — the presenter carries the burden.

3. THE TOTAL IS UNCONSTRUCTIBLE when any axis is Unmeasured. Not "total with
   an asterisk" — no total. ``CompleteVector`` has ``.total``;
   ``PartialVector`` does not. R_total=208 was a sum; one silently-unmeasured
   axis makes a sum drop, which reads as progress.

ONE DOOR
========

``commit_measurement(commit_sha, roster_cid, axes)`` is the only public
constructor for the vector. It returns ``CompleteVector | PartialVector``.
There is no way to get a total from a partial vector without first supplying
a Measured reading for every Unmeasured axis.

Not a scoreboard. SCOREBOARD_AUTHORITY = False. The sole product corpus
scoreboard remains scripts/control_effect_recensus.py.

Ladder: this is a TYPE (construction closure). It retires the false "sum of
axis counts from mixed measured/unmeasured surfaces" practice. No auditor
required for the invariant "total only when complete" — the method does not
exist on PartialVector.
"""

from __future__ import annotations

SCOREBOARD_AUTHORITY = False

from dataclasses import dataclass
from typing import Mapping, Union


class CommitMeasurementError(TypeError):
    """Illegal measurement reading — refused at construction."""


def _require_nonempty_str(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CommitMeasurementError(
            f"{name} must be a non-empty str (presenter burden); "
            f"got {type(value).__name__!r}={value!r}"
        )
    return value.strip()


def _require_int(name: str, value: object, *, min_value: int | None = None) -> int:
    if type(value) is not int:  # bool is subclass of int — refuse bool
        raise CommitMeasurementError(
            f"{name} must be int (not {type(value).__name__}); "
            f"exit codes and counts are not booleans or floats"
        )
    if min_value is not None and value < min_value:
        raise CommitMeasurementError(f"{name} must be >= {min_value}; got {value}")
    return value


@dataclass(frozen=True, slots=True)
class Measured:
    """A measured axis reading: value with lease/receipt testimony.

    Unconstructible without receipt_cid, collected count, and pre-pipe exit_code.
    """

    value: int
    receipt_cid: str
    collected: int
    exit_code: int

    def __post_init__(self) -> None:
        _require_int("value", self.value, min_value=0)
        cid = _require_nonempty_str("receipt_cid", self.receipt_cid)
        object.__setattr__(self, "receipt_cid", cid)
        _require_int("collected", self.collected, min_value=0)
        _require_int("exit_code", self.exit_code)

    def is_measured(self) -> bool:
        return True


@dataclass(frozen=True, slots=True)
class Unmeasured:
    """Third value: this axis was not measured. Not zero. Not coercible."""

    reason: str

    def __post_init__(self) -> None:
        reason = _require_nonempty_str("reason", self.reason)
        object.__setattr__(self, "reason", reason)

    def is_measured(self) -> bool:
        return False


AxisReading = Union[Measured, Unmeasured]


def _require_axes_map(axes: object) -> dict[str, AxisReading]:
    if not isinstance(axes, Mapping) or not axes:
        raise CommitMeasurementError(
            "axes must be a non-empty mapping of axis name -> AxisReading"
        )
    out: dict[str, AxisReading] = {}
    for name, reading in axes.items():
        key = _require_nonempty_str("axis name", name)
        if not isinstance(reading, (Measured, Unmeasured)):
            raise CommitMeasurementError(
                f"axis {key!r}: reading must be Measured or Unmeasured; "
                f"got {type(reading).__name__} — there is no third construction "
                f"path and no blank/green default"
            )
        out[key] = reading
    return out


@dataclass(frozen=True, slots=True)
class CompleteVector:
    """Every axis Measured. The only shape that may report a total."""

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
            if not isinstance(reading, Measured):
                raise CommitMeasurementError(
                    f"CompleteVector refuses Unmeasured axis {key!r}; "
                    f"use PartialVector or supply a Measured reading"
                )
            sealed[key] = reading
        object.__setattr__(self, "axes", sealed)

    @property
    def total(self) -> int:
        """Sum of measured R values. Exists only when every axis is Measured."""
        return sum(reading.value for reading in self.axes.values())

    def is_complete(self) -> bool:
        return True


@dataclass(frozen=True, slots=True)
class PartialVector:
    """At least one Unmeasured axis. No total — the method does not exist."""

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
                "PartialVector requires at least one Unmeasured axis; "
                "all-Measured vectors are CompleteVector (use commit_measurement)"
            )
        object.__setattr__(self, "axes", sealed)

    def is_complete(self) -> bool:
        return False

    def unmeasured_axes(self) -> tuple[str, ...]:
        return tuple(
            name
            for name, reading in self.axes.items()
            if isinstance(reading, Unmeasured)
        )


# Public alias for the composition: either complete or partial.
CommitMeasurement = Union[CompleteVector, PartialVector]


def commit_measurement(
    commit_sha: str,
    roster_cid: str,
    axes: Mapping[str, AxisReading],
) -> CommitMeasurement:
    """ONE DOOR for commit measurement state.

    Returns CompleteVector when every axis is Measured (``.total`` available).
    Returns PartialVector when any axis is Unmeasured (no total).
    """
    sha = _require_nonempty_str("commit_sha", commit_sha)
    roster = _require_nonempty_str("roster_cid", roster_cid)
    sealed = _require_axes_map(axes)
    if any(isinstance(r, Unmeasured) for r in sealed.values()):
        return PartialVector(sha, roster, sealed)
    measured = {name: reading for name, reading in sealed.items()}
    # type narrowed: all Measured
    return CompleteVector(sha, roster, measured)  # type: ignore[arg-type]


def measured(
    value: int,
    *,
    receipt_cid: str,
    collected: int,
    exit_code: int,
) -> Measured:
    """Named door for Measured (keyword-forced testimony fields)."""
    return Measured(value, receipt_cid, collected, exit_code)


def unmeasured(reason: str) -> Unmeasured:
    """Named door for Unmeasured — absence with a named reason."""
    return Unmeasured(reason)
