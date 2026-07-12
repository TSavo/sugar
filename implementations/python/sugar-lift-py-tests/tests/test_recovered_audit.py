from __future__ import annotations

import pytest

from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.kit_rpc import LiftReportPayloadDto
from sugar_lift_py_tests.lift_rpc import audit_lift_file, lift_file_payload, main


def test_normal_lift_stops_at_first_factory_panic() -> None:
    source = "def first():\n    nonlocal x\n\ndef second():\n    nonlocal y\n"

    with pytest.raises(FactoryPanic) as raised:
        lift_file_payload(source, "bad_twins.py")

    assert raised.value.info.blame == "bad_twins.py:2:4"


def test_recovered_audit_records_independent_panics_without_lift_payload() -> None:
    source = "def first():\n    nonlocal x\n\ndef second():\n    nonlocal y\n"

    audit = audit_lift_file(source, "bad_twins.py", recover_panics=True)
    wire = audit.to_rpc()

    assert not isinstance(audit, LiftReportPayloadDto)
    assert wire["kind"] == "recovered-construction-audit"
    assert wire["recoveryOverride"] is True
    assert "ir" not in wire
    assert [item["locus"] for item in wire["panics"]] == [
        "bad_twins.py:1:0",
        "bad_twins.py:4:0",
    ]
    assert all(item["kind"] == "FactoryPanic" for item in wire["panics"])
    assert all(item["status"] == "mandatory-panic" for item in wire["panics"])


def test_panicked_parent_suppresses_descendants() -> None:
    source = (
        "def parent():\n"
        "    nonlocal x\n"
        "    def child():\n"
        "        nonlocal y\n"
        "\n"
        "def independent():\n"
        "    nonlocal z\n"
    )

    wire = audit_lift_file(source, "poison.py", recover_panics=True).to_rpc()

    assert [item["locus"] for item in wire["panics"]] == [
        "poison.py:1:0",
        "poison.py:6:0",
    ]
    assert wire["suppressedDescendants"] == [
        {"locus": "poison.py:3:4", "reason": "ancestor FactoryPanic poisoned this source locus"}
    ]


def test_legacy_audit_only_is_not_a_recovery_backdoor() -> None:
    with pytest.raises(SystemExit, match="continue-on-construction-gaps"):
        main(["--audit-only"])


def test_good_twin_constructs_normally() -> None:
    payload = lift_file_payload("def implemented():\n    return 1\n", "good.py")

    assert isinstance(payload, LiftReportPayloadDto)
    assert payload.to_rpc()["kind"] == "ir-document"
