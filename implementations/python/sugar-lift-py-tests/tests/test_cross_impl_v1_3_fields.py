# SPDX-License-Identifier: Apache-2.0
#
# Cross-impl conformance tests for the v1.3.0 protocol-additive fields:
#   - EvidenceTerm (IR-level proof certificate)
#   - BridgeDecl with sourceContractCid + targetProofCid (cross-bundle pin)
#   - ContractDecl carrying optional evidence
#   - ProofEnvelopeInput with binaryCid (stored-only stub; see
#     proof_envelope.py docstring for the CBOR caveat)
#
# Pinned JCS bytes and BLAKE3-512 hashes are Rust-emitted goldens
# produced by:
#   tools/v1-3-fields-probe/
#
# That probe constructs the same Value trees the Python kit builds (using
# the canonicalizer's JCS encoder + BLAKE3-512 hasher) and emits the
# literal bytes/hashes this file pins. If the Python impl ever diverges
# from the Rust output, these tests fail -- the Rust kit is the canonical
# reference implementation.

from __future__ import annotations

from sugar_lift_py_tests import (
    BridgeDecl,
    ContractDecl,
    EvidenceCertificate,
    EvidenceTerm,
    ProofEnvelopeInput,
    bridge_decl_to_value,
    contract_decl_to_value,
    declarations_to_value,
    encode_jcs,
    envelope_body_to_value,
    evidence_to_value,
    gt,
    jcs_hash,
    make_var,
    num,
)

# ---------- EvidenceTerm ----------------------------------------------------
# Rust-emitted goldens (tools/v1-3-fields-probe)

EVIDENCE_JCS = (
    '{"certificate":{"formulaHash":"blake3-512:aa",'
    '"proofData":"(proof ...)","tool":"z3","version":"4.13.0"},'
    '"kind":"evidence","proofType":"smt-lib"}'
)
EVIDENCE_HASH = (
    "blake3-512:6eef40cc18b6d32e7d96a98b3bcf27613415273feed7723327ca23c909b92ba7"
    "a21036c5298e1291a93ae00641fa583ea4e3867f40889fbe4960e945813795c5"
)


def _sample_evidence() -> EvidenceTerm:
    return EvidenceTerm(
        proof_type="smt-lib",
        certificate=EvidenceCertificate(
            tool="z3",
            version="4.13.0",
            formula_hash="blake3-512:aa",
            proof_data="(proof ...)",
        ),
    )


def test_evidence_term_jcs_keys_alphabetical():
    ev = _sample_evidence()
    out = encode_jcs(evidence_to_value(ev))
    # Top-level keys: certificate, kind, proofType in alphabetical order.
    assert out.startswith('{"certificate":')
    assert out == EVIDENCE_JCS


def test_evidence_term_hash_pinned():
    ev = _sample_evidence()
    assert jcs_hash(evidence_to_value(ev)) == EVIDENCE_HASH


def test_evidence_proof_type_smt_lib_coq_custom_round_trip():
    for pt in ("smt-lib", "coq", "custom"):
        ev = EvidenceTerm(
            proof_type=pt,
            certificate=EvidenceCertificate(
                tool="t", version="v", formula_hash="h", proof_data="p"
            ),
        )
        out = encode_jcs(evidence_to_value(ev))
        # proofType emits verbatim.
        assert f'"proofType":"{pt}"' in out


# ---------- BridgeDecl ------------------------------------------------------
# Rust-emitted goldens (tools/v1-3-fields-probe)
#
# Bridge WITH notes. Locked emit-order key set:
#   kind, name, sourceSymbol, sourceLayer, sourceContractCid,
#   targetContractCid, targetProofCid, targetLayer, notes
# JCS sorts alphabetically:
#   kind, name, notes, sourceContractCid, sourceLayer, sourceSymbol,
#   targetContractCid, targetLayer, targetProofCid
BRIDGE_WITH_NOTES_JCS = (
    '{"kind":"bridge",'
    '"name":"myParseInt-implements-node24",'
    '"notes":"shim bridge",'
    '"sourceContractCid":"blake3-512:aaa",'
    '"sourceLayer":"javascript",'
    '"sourceSymbol":"myParseInt",'
    '"targetContractCid":"blake3-512:bbb",'
    '"targetLayer":"javascript",'
    '"targetProofCid":"blake3-512:ccc"}'
)
BRIDGE_WITH_NOTES_HASH = (
    "blake3-512:2171a6fd01c081f3e427bc3104d7da9025d9cb646de1b5f8f4981e9c2f0533a2"
    "addd8b1a1e2594c98b066bfdd3a7baa52a15b2e8cfc59897ccbde58830c54d38"
)

# Bridge WITHOUT notes. notes is OMITTED (never emitted as null) per spec
# line 347-350: this is the byte-equality rule that keeps the kits in sync.
BRIDGE_NO_NOTES_JCS = (
    '{"kind":"bridge",'
    '"name":"js-parseInt-to-ref",'
    '"sourceContractCid":"blake3-512:js-parseInt-v24",'
    '"sourceLayer":"javascript",'
    '"sourceSymbol":"parseInt",'
    '"targetContractCid":"blake3-512:ref-parseInt-v1",'
    '"targetLayer":"reference",'
    '"targetProofCid":"blake3-512:ecma262-v14-proof"}'
)
BRIDGE_NO_NOTES_HASH = (
    "blake3-512:22b71234d6001ad34d1fa2d27f0bf4781d7da96d38f9149d4017dde178fd295a"
    "c39799ee3c47d2dd769f44b6b65f80aeeb9ad8d0a591240aaf3b41b7ff1b7d6d"
)


def test_bridge_with_notes_jcs_pinned():
    b = BridgeDecl(
        name="myParseInt-implements-node24",
        source_symbol="myParseInt",
        source_layer="javascript",
        source_contract_cid="blake3-512:aaa",
        target_contract_cid="blake3-512:bbb",
        target_proof_cid="blake3-512:ccc",
        target_layer="javascript",
        notes="shim bridge",
    )
    assert encode_jcs(bridge_decl_to_value(b)) == BRIDGE_WITH_NOTES_JCS
    assert jcs_hash(bridge_decl_to_value(b)) == BRIDGE_WITH_NOTES_HASH


def test_bridge_without_notes_omits_field():
    """notes is omitted (NOT emitted as null) when None, per spec.

    This is the cross-impl byte-equality rule. If Python emits "notes":null
    here, the JCS bytes diverge from Rust/TS and the four kits no longer
    agree on the bridge CID.
    """
    b = BridgeDecl(
        name="js-parseInt-to-ref",
        source_symbol="parseInt",
        source_layer="javascript",
        source_contract_cid="blake3-512:js-parseInt-v24",
        target_contract_cid="blake3-512:ref-parseInt-v1",
        target_proof_cid="blake3-512:ecma262-v14-proof",
        target_layer="reference",
    )
    out = encode_jcs(bridge_decl_to_value(b))
    assert "notes" not in out
    assert "null" not in out
    assert out == BRIDGE_NO_NOTES_JCS
    assert jcs_hash(bridge_decl_to_value(b)) == BRIDGE_NO_NOTES_HASH


def test_bridge_required_fields_all_appear():
    b = BridgeDecl(
        name="b",
        source_symbol="s",
        source_layer="sl",
        source_contract_cid="scc",
        target_contract_cid="tcc",
        target_proof_cid="tpc",
        target_layer="tl",
    )
    out = encode_jcs(bridge_decl_to_value(b))
    for required in (
        "kind",
        "name",
        "sourceSymbol",
        "sourceLayer",
        "sourceContractCid",
        "targetContractCid",
        "targetProofCid",
        "targetLayer",
    ):
        assert f'"{required}"' in out, f"missing required field {required}"


# ---------- ContractDecl with optional evidence -----------------------------


def test_contract_decl_with_evidence_emits_evidence_key():
    c = ContractDecl(
        name="contract1",
        inv=gt(make_var("x"), num(0)),
        evidence=_sample_evidence(),
    )
    out = encode_jcs(contract_decl_to_value(c))
    assert '"evidence":' in out
    # Evidence sub-object has alphabetical keys: certificate, kind, proofType.
    assert '"evidence":{"certificate":' in out


def test_contract_decl_without_evidence_omits_evidence_key():
    c = ContractDecl(name="contract1", inv=gt(make_var("x"), num(0)))
    out = encode_jcs(contract_decl_to_value(c))
    assert "evidence" not in out


def test_contract_decl_with_evidence_pinned_jcs():
    c = ContractDecl(
        name="contract1",
        inv=gt(make_var("x"), num(0)),
        evidence=_sample_evidence(),
    )
    expected = (
        '{"evidence":{"certificate":{"formulaHash":"blake3-512:aa",'
        '"proofData":"(proof ...)","tool":"z3","version":"4.13.0"},'
        '"kind":"evidence","proofType":"smt-lib"},'
        '"inv":{"args":[{"kind":"var","name":"x"},'
        '{"kind":"const","sort":{"kind":"primitive","name":"Int"},"value":0}],'
        '"kind":"atomic","name":">"},'
        '"kind":"contract","name":"contract1","outBinding":"out"}'
    )
    assert encode_jcs(contract_decl_to_value(c)) == expected


# ---------- Mixed declarations array ----------------------------------------


def test_declarations_to_value_mixes_contracts_and_bridges():
    c = ContractDecl(name="c1", inv=gt(make_var("x"), num(0)))
    b = BridgeDecl(
        name="b1",
        source_symbol="s",
        source_layer="sl",
        source_contract_cid="scc",
        target_contract_cid="tcc",
        target_proof_cid="tpc",
        target_layer="tl",
    )
    out = encode_jcs(declarations_to_value([c, b]))
    assert out.startswith("[")
    assert out.endswith("]")
    assert '"kind":"contract"' in out
    assert '"kind":"bridge"' in out


# ---------- ProofEnvelope (stored-only) -------------------------------------
#
# binaryCid lives on the proof envelope. The Rust kit emits SIGNED CBOR
# whose hash is the .proof CID; this Python module is stored-only (see
# proof_envelope.py docstring). The pin below is for the JCS body shape
# and field set, NOT the protocol-normative CID.


ENV_WITH_BINARY_CID_JCS = (
    '{"binaryCid":"blake3-512:binary",'
    '"declaredAt":"2026-05-02T00:00:00.000Z",'
    '"kind":"catalog",'
    '"members":{"blake3-512:mem1":"7b7d"},'
    '"name":"@x/y",'
    '"signer":"blake3-512:signer",'
    '"version":"1.0.0"}'
)


def test_envelope_body_with_binary_cid_jcs_pinned():
    env = ProofEnvelopeInput(
        name="@x/y",
        version="1.0.0",
        members={"blake3-512:mem1": b"{}"},
        signer_cid="blake3-512:signer",
        declared_at="2026-05-02T00:00:00.000Z",
        binary_cid="blake3-512:binary",
    )
    assert encode_jcs(envelope_body_to_value(env)) == ENV_WITH_BINARY_CID_JCS


def test_envelope_body_without_binary_cid_omits_field():
    env = ProofEnvelopeInput(
        name="@x/y",
        version="1.0.0",
        members={"blake3-512:mem1": b"{}"},
        signer_cid="blake3-512:signer",
        declared_at="2026-05-02T00:00:00.000Z",
    )
    out = encode_jcs(envelope_body_to_value(env))
    assert "binaryCid" not in out


def test_envelope_body_with_metadata_emits_sorted_metadata():
    env = ProofEnvelopeInput(
        name="@x/y",
        version="1.0.0",
        members={},
        signer_cid="blake3-512:signer",
        declared_at="2026-05-02T00:00:00.000Z",
        metadata={"build": "ci", "arch": "x86_64"},
    )
    out = encode_jcs(envelope_body_to_value(env))
    # JCS sorts metadata keys: arch before build.
    assert '"metadata":{"arch":"x86_64","build":"ci"}' in out
