import json

import pytest

from sugar_lift_py_tests.context_manager_contract import (
    ContextManagerContractError,
    decode_context_manager_contract,
    publish_never_suppresses_context_manager_contract,
)
from sugar_lift_py_tests.ir import PrimitiveSort
from sugar_lift_py_tests.signing import Signer


SEED = bytes(range(32))


def _publish():
    return publish_never_suppresses_context_manager_contract(
        name="NeverClosingManager",
        kit="fixture-python-kit",
        bridge_source_symbol="context-manager:fixture_python.never_closing",
        constructor_formals=(),
        constructor_sorts=(),
        enter_result_sort=PrimitiveSort("Value"),
        source_warrants=(),
        signer=Signer(seed=SEED, producer_id="fixture-python-kit"),
        declared_at="2026-07-22T00:00:00.000Z",
    )


def test_publish_and_decode_sealed_context_manager_contract():
    sealed = _publish()
    decoded = decode_context_manager_contract(sealed.canonical_bytes, sealed.cid)
    assert decoded.name == "NeverClosingManager"
    assert decoded.kit == "fixture-python-kit"
    assert decoded.exit_disposition == "never-suppresses"
    assert decoded.enter_result_sort == PrimitiveSort("Value")
    assert decoded.contract_cid == sealed.contract_cid


def test_payload_has_exact_architect_shape_plus_sealing_cid():
    raw = json.loads(_publish().canonical_bytes)
    header = raw["header"]
    assert header["schemaVersion"] == "1"
    assert header["kind"] == "context-manager-contract"
    assert header["constructorSignature"] == {"formals": [], "sorts": []}
    assert header["enter"] == {
        "outcome": "total",
        "result": {
            "kind": "projection",
            "projection": "enter_result",
            "sort": {"kind": "primitive", "name": "Value"},
        },
    }
    assert header["exit"] == {
        "outcome": "total",
        "disposition": {"kind": "never-suppresses"},
    }
    assert raw["metadata"] == {}


def test_stale_content_cid_is_loud_even_when_shape_is_valid():
    sealed = _publish()
    raw = json.loads(sealed.canonical_bytes)
    raw["header"]["cid"] = "blake3-512:" + "0" * 128
    with pytest.raises(ContextManagerContractError):
        decode_context_manager_contract(json.dumps(raw).encode(), sealed.cid)


def test_absent_or_non_total_exit_is_not_never_suppresses():
    sealed = _publish()
    raw = json.loads(sealed.canonical_bytes)
    del raw["header"]["exit"]
    with pytest.raises(ContextManagerContractError):
        decode_context_manager_contract(json.dumps(raw).encode(), sealed.cid)

    raw = json.loads(sealed.canonical_bytes)
    raw["header"]["exit"]["outcome"] = "unknown"
    with pytest.raises(ContextManagerContractError):
        decode_context_manager_contract(json.dumps(raw).encode(), sealed.cid)
