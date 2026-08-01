"""Construction-door teeth for CommitMeasurement.

No local pytest in agent sessions (watchdog). CI / assigned remote runs these.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "commit_measurement", ROOT / "tools" / "commit_measurement.py"
)
assert _SPEC is not None and _SPEC.loader is not None
CM = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(CM)

CommitMeasurementError = CM.CommitMeasurementError
CompleteVector = CM.CompleteVector
Measured = CM.Measured
PartialVector = CM.PartialVector
Unmeasured = CM.Unmeasured
commit_measurement = CM.commit_measurement
measured = CM.measured
unmeasured = CM.unmeasured


def test_measured_refuses_without_receipt_cid() -> None:
    with pytest.raises(CommitMeasurementError, match="receipt_cid"):
        Measured(0, "", 10, 0)
    with pytest.raises(CommitMeasurementError, match="receipt_cid"):
        measured(0, receipt_cid="  ", collected=1, exit_code=0)


def test_measured_requires_value_collected_exit_code_types() -> None:
    ok = measured(3, receipt_cid="blake3-512:abc", collected=12, exit_code=1)
    assert ok.value == 3
    assert ok.receipt_cid == "blake3-512:abc"
    assert ok.collected == 12
    assert ok.exit_code == 1
    with pytest.raises(CommitMeasurementError, match="value"):
        Measured(-1, "cid", 1, 0)
    with pytest.raises(CommitMeasurementError, match="collected"):
        Measured(0, "cid", -1, 0)
    with pytest.raises(CommitMeasurementError, match="exit_code"):
        Measured(0, "cid", 1, True)  # type: ignore[arg-type]


def test_unmeasured_is_third_value_not_zero() -> None:
    u = unmeasured("lease not acquired for python-package-suite at tip")
    assert u.reason
    assert not u.is_measured()
    m = measured(0, receipt_cid="cid:zero", collected=5, exit_code=0)
    assert m.is_measured()
    assert m.value == 0
    assert type(u) is not type(m)
    with pytest.raises(CommitMeasurementError, match="reason"):
        Unmeasured("")


def test_complete_vector_has_total_only_when_all_measured() -> None:
    v = commit_measurement(
        "abc123",
        "roster:tip-v1",
        {
            "spelling": measured(32, receipt_cid="r1", collected=100, exit_code=1),
            "swallowed": measured(79, receipt_cid="r2", collected=100, exit_code=1),
        },
    )
    assert isinstance(v, CompleteVector)
    assert v.total == 111
    assert v.is_complete()


def test_partial_vector_has_no_total_method() -> None:
    """R_total drop-as-progress: unwritable — PartialVector has no .total."""
    v = commit_measurement(
        "abc123",
        "roster:tip-v1",
        {
            "spelling": measured(32, receipt_cid="r1", collected=100, exit_code=1),
            "self_sealing": unmeasured("no lease receipt for class at this commit"),
        },
    )
    assert isinstance(v, PartialVector)
    assert not v.is_complete()
    assert v.unmeasured_axes() == ("self_sealing",)
    assert not hasattr(PartialVector, "total")
    with pytest.raises(AttributeError):
        _ = v.total  # type: ignore[attr-defined]


def test_partial_vector_refuses_all_measured() -> None:
    with pytest.raises(CommitMeasurementError, match="CompleteVector"):
        PartialVector(
            "sha",
            "roster",
            {"a": measured(1, receipt_cid="c", collected=1, exit_code=0)},
        )


def test_complete_vector_refuses_unmeasured_axis() -> None:
    with pytest.raises(CommitMeasurementError, match="Unmeasured"):
        CompleteVector(
            "sha",
            "roster",
            {
                "a": measured(1, receipt_cid="c", collected=1, exit_code=0),
                "b": unmeasured("missing"),  # type: ignore[dict-item]
            },
        )


def test_one_door_commit_measurement() -> None:
    partial = commit_measurement(
        "deadbeef",
        "roster:x",
        {"a": unmeasured("never ran")},
    )
    complete = commit_measurement(
        "deadbeef",
        "roster:x",
        {"a": measured(0, receipt_cid="lease:a", collected=3, exit_code=0)},
    )
    assert isinstance(partial, PartialVector)
    assert isinstance(complete, CompleteVector)
    assert complete.total == 0


def test_scoreboard_authority_is_false() -> None:
    assert CM.SCOREBOARD_AUTHORITY is False
