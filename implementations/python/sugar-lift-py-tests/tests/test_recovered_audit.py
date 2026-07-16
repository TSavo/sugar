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


def test_legacy_hold_panic_cannot_return_a_partial_lift_artifact() -> None:
    source = "def clean():\n    return 1\n\ndef broken():\n    nonlocal x\n"

    with pytest.raises(TypeError, match="recover_panics=True"):
        audit_lift_file(source, "held.py", hold_panic=True)


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


@pytest.mark.parametrize(
    ("source", "demanded_source", "observed"),
    [
        ("bound = (yield missing)\n", "binding:bound", "Yield"),
        ("assert missing\n", "assert:1:0", "missing"),
    ],
)
def test_module_seed_panics_are_recovered_as_immutable_evidence(
    source: str, demanded_source: str, observed: str
) -> None:
    wire = audit_lift_file(source, "module_seed.py", recover_panics=True).to_rpc()

    assert wire["status"] == "failed"
    assert len(wire["panics"]) == 1
    assert wire["panics"][0]["locus"] == "module_seed.py:1:0"
    assert wire["panics"][0]["demandedSource"] == demanded_source
    assert wire["panics"][0]["gap"]["observed"] == observed


def test_recovered_audit_does_not_mark_unsupported_async_definition_clean() -> None:
    source = "async def omitted():\n    nonlocal missing\n"

    wire = audit_lift_file(source, "async_gap.py", recover_panics=True).to_rpc()

    assert wire["status"] == "failed"
    assert [item["locus"] for item in wire["panics"]] == ["async_gap.py:1:0"]
    assert wire["panics"][0]["gap"]["observed"] == "AsyncFunctionDef"


def test_recovered_audit_preserves_conservation_producer_gaps() -> None:
    # Function annotation expressions are source-owned but are not part of the
    # current per-function construction walk.  The independent conservation
    # producer therefore emits one ListComp gap; recovery must not discard it
    # and report an impossible clean frontier.
    source = "def annotated(value: [item for item in [1]]):\n    return value\n"

    wire = audit_lift_file(source, "annotation_gap.py", recover_panics=True).to_rpc()

    assert wire["status"] == "failed"
    assert len(wire["panics"]) == 1
    assert wire["panics"][0]["locus"] == "annotation_gap.py:1:21:ListComp"
    assert wire["panics"][0]["gap"] == {
        "gap_kind": "Conservation",
        "gap_locus": "annotation_gap.py:1:21:ListComp",
        "observed": "ListComp",
        "requested": "source→factory classification",
        "fix": "remove the pre-factory skip or classify an explicit boundary",
    }


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
        {
            "locus": "poison.py:3:4",
            "reason": "ancestor FactoryPanic poisoned this source locus",
        }
    ]


def test_panicked_parent_accounts_for_suppressed_control_flow_owner() -> None:
    source = (
        "def parent(flag):\n"
        "    nonlocal missing\n"
        "    if flag:\n"
        "        return 1\n"
    )

    wire = audit_lift_file(source, "poison_if.py", recover_panics=True).to_rpc()

    assert [item["locus"] for item in wire["panics"]] == ["poison_if.py:1:0"]
    assert wire["suppressedDescendants"] == [
        {
            "locus": "poison_if.py:3:4",
            "reason": "ancestor FactoryPanic poisoned this source locus",
        }
    ]


def test_recovered_audit_keeps_typed_effects_out_of_construction_gaps() -> None:
    source = (
        "import pytest\n"
        "import pandas as pd\n"
        "\n"
        "@pytest.fixture(\n"
        "    params=[getattr(pd.offsets, name) for name in pd.offsets.__all__]\n"
        ")\n"
        "def runtime_getattr(request):\n"
        "    pass\n"
        "\n"
        "def independent_gap():\n"
        "    nonlocal missing\n"
    )

    wire = audit_lift_file(source, "effects.py", recover_panics=True).to_rpc()

    assert [item["locus"] for item in wire["panics"]] == ["effects.py:10:0"]
    assert wire["panics"][0]["gap"]["observed"] == "Nonlocal"
    assert wire["effects"] == [
        {
            "locus": "effects.py:7:0",
            "effect": "GetattrRuntimeEffect",
            "category": "RuntimeEffect",
            "status": "runtime-effect",
            "reason": (
                "getattr runtime boundary: attribute name expression `Name` "
                "is runtime; blame=effects.py:5:12"
            ),
        }
    ]


def test_legacy_audit_only_is_not_a_recovery_backdoor() -> None:
    with pytest.raises(SystemExit, match="allowed-broken-components"):
        main(["--audit-only"])


def test_good_twin_constructs_normally() -> None:
    payload = lift_file_payload("def implemented():\n    return 1\n", "good.py")

    assert isinstance(payload, LiftReportPayloadDto)
    assert payload.to_rpc()["kind"] == "ir-document"
