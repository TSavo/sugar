import json

import pytest

from sugar_lift_py_tests.canonicalizer import blake3_512_of, encode_jcs, vobj
from sugar_lift_py_tests.claim_envelope import _assemble_layered
from sugar_lift_py_tests.context_manager_contract import (
    ContextManagerContractError,
    ContextManagerSemanticsV1,
    EnterResultContractV1,
    ExitContractV1,
    NeverSuppressesDispositionV1,
    decode_context_manager_contract,
    publish_never_suppresses_context_manager_contract,
)
from sugar_lift_py_tests.ir import PrimitiveSort
from sugar_lift_py_tests.kit_rpc import (
    ContextManagerContractIrV1,
    ImportSignatureV1,
    LiftReportPayloadDto,
)
from sugar_lift_py_tests.signing import Signer
from sugar_lift_py_tests.context_manager_contract import _json_value


SEED = bytes(range(32))
DECLARED_AT = "2026-07-22T00:00:00.000Z"


def _publish():
    return publish_never_suppresses_context_manager_contract(
        bridge_source_symbol="context-manager:fixture_python.never_closing",
        import_signature=ImportSignatureV1(formals=(), sorts=()),
        enter_result_sort=PrimitiveSort("Value"),
        source_warrants=("blake3-512:" + "a" * 128,),
        signer=Signer(seed=SEED, producer_id="fixture-python-kit"),
        declared_at=DECLARED_AT,
    )


def _reseal(mutator):
    raw = json.loads(_publish().canonical_bytes)
    mutator(raw["header"])
    payload = raw["header"]["payload"]
    payload_cid = blake3_512_of(encode_jcs(_json_value(payload)).encode())
    raw["header"]["cid"] = payload_cid
    raw["header"]["payloadCid"] = payload_cid
    return _assemble_layered(
        _json_value(raw["header"]), _json_value(raw["metadata"]), DECLARED_AT, SEED, payload_cid
    )


def test_publish_and_decode_retains_typed_never_suppresses_semantics():
    sealed = _publish()
    decoded = decode_context_manager_contract(sealed.canonical_bytes, sealed.cid)
    assert decoded.semantics == ContextManagerSemanticsV1(
        enter=EnterResultContractV1(sort=PrimitiveSort("Value")),
        exit=ExitContractV1(disposition=NeverSuppressesDispositionV1()),
    )
    assert isinstance(decoded.semantics.exit.disposition, NeverSuppressesDispositionV1)
    assert decoded.payload_cid == sealed.contract_cid


def test_semantic_payload_is_provider_neutral_and_hashed_alone():
    raw = json.loads(_publish().canonical_bytes)
    header = raw["header"]
    assert header["schemaVersion"] == "1.2"
    assert set(header) == {
        "schemaVersion", "kind", "cid", "payloadCid", "bridgeSourceSymbol",
        "importSignature", "payload", "sourceWarrants", "inputCids",
    }
    assert "name" not in header["payload"] and "kit" not in header["payload"]
    assert header["payload"] == {
        "kind": "context-manager-semantics",
        "schemaVersion": "1",
        "enter": {
            "completion": "total",
            "result": {"kind": "projection", "projection": "enter_result", "sort": {"kind": "primitive", "name": "Value"}},
        },
        "exit": {"completion": "total", "disposition": {"kind": "never-suppresses"}},
    }
    assert header["payloadCid"] == blake3_512_of(
        encode_jcs(_json_value(header["payload"])).encode()
    )


def test_correctly_resealed_unknown_disposition_reaches_typed_decoder():
    sealed = _reseal(lambda h: h["payload"]["exit"]["disposition"].update(kind="sometimes"))
    with pytest.raises(ContextManagerContractError, match="unknown exit disposition"):
        decode_context_manager_contract(sealed.canonical_bytes, sealed.cid)


def test_correctly_resealed_missing_enter_reaches_typed_decoder():
    sealed = _reseal(lambda h: h["payload"].pop("enter"))
    with pytest.raises(ContextManagerContractError, match="malformed context-manager semantics"):
        decode_context_manager_contract(sealed.canonical_bytes, sealed.cid)


def test_bad_signature_is_distinct_from_stale_payload_cid():
    sealed = _publish()
    raw = json.loads(sealed.canonical_bytes)
    raw["header"]["bridgeSourceSymbol"] = "context-manager:mutated"
    with pytest.raises(ContextManagerContractError, match="signature"):
        decode_context_manager_contract(json.dumps(raw).encode(), sealed.cid)

    raw = json.loads(sealed.canonical_bytes)
    raw["header"]["payloadCid"] = "blake3-512:" + "0" * 128
    stale = _assemble_layered(_json_value(raw["header"]), _json_value(raw["metadata"]), DECLARED_AT, SEED, raw["header"]["payloadCid"])
    with pytest.raises(ContextManagerContractError, match="payload CID"):
        decode_context_manager_contract(stale.canonical_bytes, stale.cid)


def test_typed_declaration_enters_closed_ir_transport():
    row = ContextManagerContractIrV1.never_suppresses(
        bridge_source_symbol="context-manager:fixture_python.never_closing",
        import_signature=ImportSignatureV1(formals=(), sorts=()),
        enter_result_sort=PrimitiveSort("Value"),
        source_warrants=("blake3-512:" + "a" * 128,),
    )
    wire = LiftReportPayloadDto(ir=[row]).to_rpc()
    assert wire["ir"] == [row.to_rpc_with_term_table(None)]
