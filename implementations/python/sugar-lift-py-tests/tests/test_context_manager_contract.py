import dataclasses
import json

import pytest

from sugar_lift_py_tests.context_manager_contract import (
    ContextManagerContractError,
    ContextManagerDerivationProvenanceV1,
    EnterResultContractV1,
    ExitContractV1,
    ImportSignatureV2,
    NeverSuppressesDispositionV1,
    ProtocolResourceSemanticsV1,
    TotalCompletionV1,
    _cid_of_json,
    decode_context_manager_contract,
    derivation_provenance_to_dict,
    seal_derived_context_manager_contract,
)
from sugar_lift_py_tests.context_manager_resolution import SourceFragmentCoordinateV1
from sugar_lift_py_tests.ir import PrimitiveSort
from sugar_lift_py_tests.signing import Signer


def _cid(fill: str) -> str:
    return "blake3-512:" + fill * 128


def _provenance() -> ContextManagerDerivationProvenanceV1:
    definition = SourceFragmentCoordinateV1(_cid("d"), 1, 0, 4, 8)
    use = SourceFragmentCoordinateV1(_cid("u"), 9, 2, 9, 14)
    value = ContextManagerDerivationProvenanceV1(
        _cid("a"),
        _cid("b"),
        _cid("c"),
        _cid("d"),
        (_cid("e"),),
        definition,
        _cid_of_json(definition.wire()),
        _cid("f"),
        _cid("1"),
        _cid("2"),
        use,
        _cid_of_json(use.wire()),
        _cid("3"),
        _cid("0"),
    )
    wire = derivation_provenance_to_dict(value)
    return dataclasses.replace(
        value,
        derivation_cid=_cid_of_json(
            {k: v for k, v in wire.items() if k != "derivationCid"}
        ),
    )


def _seal():
    semantics = ProtocolResourceSemanticsV1(
        EnterResultContractV1(PrimitiveSort("Value"), TotalCompletionV1()),
        ExitContractV1(NeverSuppressesDispositionV1(), TotalCompletionV1()),
    )
    return seal_derived_context_manager_contract(
        import_signature=ImportSignatureV2(()),
        semantics=semantics,
        provenance=_provenance(),
        signer=Signer(bytes(range(32)), "deriver"),
        declared_at="2026-07-22T00:00:00.000Z",
    )


def test_derived_contract_round_trips_construction_provenance():
    member = _seal()
    decoded = decode_context_manager_contract(member.canonical_bytes, member.cid)
    assert decoded.provenance.manager_construction_cid == _cid("f")
    assert decoded.provenance.enter_testimony_cid == _cid("1")
    assert decoded.provenance.exit_testimony_cid == _cid("2")
    assert (
        decoded.contract_cid
        == json.loads(member.canonical_bytes)["header"]["contractCid"]
    )


def test_legacy_or_extra_authority_field_is_loud():
    member = _seal()
    raw = json.loads(member.canonical_bytes)
    raw["header"]["admissionAuthorityCid"] = _cid("9")
    with pytest.raises(
        ContextManagerContractError, match="does not verify|malformed derived"
    ):
        decode_context_manager_contract(json.dumps(raw).encode(), member.cid)
