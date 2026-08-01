"""Construction teeth for S1.1 re-rank input format (CI; no local agent pytest)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "rerank_input", ROOT / "tools" / "rerank_input.py"
)
assert _SPEC is not None and _SPEC.loader is not None
RI = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = RI
_SPEC.loader.exec_module(RI)


def test_scoreboard_authority_false() -> None:
    assert RI.SCOREBOARD_AUTHORITY is False


def test_bare_integer_axis_unconstructible() -> None:
    with pytest.raises(RI.RerankInputError, match="bare integer"):
        RI.rerank_input("deadbeef", {"criterion4.spelling_dispatch": 74})  # type: ignore[dict-item]


def test_chat_cite_is_unmeasured_not_integer() -> None:
    u = RI.unmeasured_chat_cite("criterion4.spelling_dispatch")
    assert isinstance(u, RI.UnmeasuredAxis)
    assert "chat-cite" in u.reason
    v = RI.rerank_input("deadbeef", {"criterion4.spelling_dispatch": u})
    assert isinstance(v, RI.PartialRerankInput)
    assert "rankable_axes" not in type(v).__dict__
    assert not hasattr(RI.PartialRerankInput, "rankable_axes")


def test_measured_requires_instrument_and_commit() -> None:
    with pytest.raises(RI.RerankInputError, match="instrument_id"):
        RI.measured_axis(
            "criterion4.swallowed_throw",
            1,
            instrument_id="",
            commit_sha="abc",
            body_artifact_cid="body:1",
            value_field_path="R",
        )
    m = RI.measured_axis(
        "criterion4.swallowed_throw",
        1,
        instrument_id="scripts/swallowed_throw_second_mechanism_law.py",
        commit_sha="deadbeef",
        body_artifact_cid="blake2b-256:abc",
        value_field_path="R_swallowed_throw_second_mechanism",
    )
    assert m.value == 1
    assert m.provenance.instrument_id.endswith("swallowed_throw_second_mechanism_law.py")


def test_direct_measured_axis_without_seal_refuses() -> None:
    prov = RI.InstrumentProvenance(
        instrument_id="scripts/x.py",
        commit_sha="sha",
        body_artifact_cid="b",
        value_field_path="R",
    )
    with pytest.raises(RI.RerankInputError, match="sealed"):
        RI.MeasuredAxis("ax", 1, prov, object())


def test_complete_exposes_rankable_partial_does_not() -> None:
    m = RI.measured_axis(
        "criterion4.finite_cap_opaque",
        1,
        instrument_id="scripts/finite_cap_opaque_completion_law.py",
        commit_sha="deadbeef",
        body_artifact_cid="body:1",
        value_field_path="R",
    )
    complete = RI.rerank_input("deadbeef", {"criterion4.finite_cap_opaque": m})
    assert isinstance(complete, RI.CompleteRerankInput)
    assert len(complete.rankable_axes()) == 1
    partial = RI.rerank_input(
        "deadbeef",
        {
            "criterion4.finite_cap_opaque": m,
            "criterion1.authenticated_denominator": RI.unmeasured_axis(
                "criterion1.authenticated_denominator",
                "UNMEASURED: no authenticated denominator at tip",
            ),
        },
    )
    assert isinstance(partial, RI.PartialRerankInput)
    with pytest.raises(AttributeError):
        _ = partial.rankable_axes()  # type: ignore[attr-defined]
    assert "rankableAxes" not in partial.to_json()
    assert "total" not in partial.to_json()


def test_enrolled_axis_ids_are_names_only_no_numbers() -> None:
    """Format enrolls slots without parking chat integers."""
    assert RI.ENROLLED_RERANK_AXIS_IDS
    for axis_id in RI.ENROLLED_RERANK_AXIS_IDS:
        assert isinstance(axis_id, str)
        assert axis_id  # non-empty name
    # No integer values in the enrollment tuple
    assert all(not isinstance(x, int) for x in RI.ENROLLED_RERANK_AXIS_IDS)
