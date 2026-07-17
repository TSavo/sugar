"""#4264: shared recovered-audit goldens round-trip in Python.

Fixtures live once under ``protocol/conformance/recovered-audit/`` and are
also exercised by the Rust leaf/tree readers. A writer field the reader
cannot parse must fail here before merge.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sugar_lift_py_tests.kit_rpc import RecoveredAuditDto, RecoveredFrontierAuditDto

_FIXTURES = (
    Path(__file__).resolve().parents[4]
    / "protocol"
    / "conformance"
    / "recovered-audit"
)


def _load(name: str) -> dict:
    path = _FIXTURES / name
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", ["leaf-clean.json", "leaf-full.json"])
def test_leaf_goldens_round_trip_without_loss(name: str) -> None:
    fixture = _load(name)
    audit = RecoveredAuditDto.from_rpc(fixture)
    assert audit.to_rpc() == fixture


def test_leaf_golden_rejects_unknown_fields() -> None:
    fixture = _load("bad-leaf-unknown-field.json")
    with pytest.raises(ValueError, match="unknown field"):
        RecoveredAuditDto.from_rpc(fixture)


@pytest.mark.parametrize(
    "name",
    [
        "tree-valid-empty.json",
        "tree-complete-effects.json",
        "tree-failed-full.json",
    ],
)
def test_tree_goldens_round_trip_without_loss(name: str) -> None:
    fixture = _load(name)
    audit = RecoveredFrontierAuditDto.from_rpc(fixture)
    assert audit.to_rpc() == fixture


def test_tree_golden_rejects_unknown_fields() -> None:
    fixture = _load("bad-tree-unknown-field.json")
    with pytest.raises(ValueError, match="unknown field"):
        RecoveredFrontierAuditDto.from_rpc(fixture)


def test_leaf_writer_shape_is_closed_for_rust_reader() -> None:
    """Writer-side bad twin: inventing a lane must fail the closed leaf decoder."""
    wire = RecoveredAuditDto().to_rpc()
    wire["inventedLane"] = []
    with pytest.raises(ValueError, match="unknown field"):
        RecoveredAuditDto.from_rpc(wire)
