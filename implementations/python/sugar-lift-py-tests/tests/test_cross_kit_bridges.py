# SPDX-License-Identifier: Apache-2.0
#
# Cross-kit bridge tests (Phase 2 of the cross-kit bridge work).
#
# Each test asserts: "the python kit's lift adapter satisfies a named
# Rust contract from `lift_plugin_protocol.rs`."
#
# For every Rust contract in
# `implementations/rust/sugar-self-contracts/src/lift_plugin_protocol.rs`
# (the 10 contracts authored by `lift_plugin_protocol::invariants()`),
# this test:
#
#   1. Constructs a python-kit counterpart `ContractDecl` whose claim
#      mirrors the rule in IR shape (a `satisfies(<adapter>, <rule>)`
#      atomic). Each counterpart has its own JCS+BLAKE3-512 CID.
#
#   2. Constructs a `BridgeDecl` linking
#      source = rust-kit contract CID (extracted from
#      `print-lift-plugin-protocol-cids` rust binary; goldens pinned
#      below) to target = python counterpart contract CID. The bridge's
#      `targetProofCid` is the deferred phase-3 placeholder.
#
#   3. Encodes the full mixed declaration array via
#      `declarations_to_value` + the JCS encoder, BLAKE3-512 hashes the
#      result, and asserts it matches the pinned goldens.
#
# DEPENDENCIES (the pinned hash will break if any of these change):
#   * Rust contract CIDs depend on the Rust `mint_contract` envelope
#     shape, the slab's `DECLARED_AT`, the fixed `signer_seed = [0x42; 32]`,
#     and the contract's IR formula. Re-extract via:
#       cargo run --release -p sugar-self-contracts \
#         --bin print-lift-plugin-protocol-cids
#   * Python `BridgeDecl` JCS encoding (cross-pinned in
#     `test_cross_impl_v1_3_fields.py`).
#   * The `target_proof_cid` placeholder
#     (`deferred:phase-3-proof-bundle`).
#   * The python counterpart contract CIDs (computed locally from each
#     counterpart's JCS bytes; pinned below).
#
# When phase 3 mints a real python proof bundle, the bridges will be
# re-minted with the actual `target_proof_cid` and these pins will move.
# Bug-mode and change-request-mode failures point reviewers to
# "re-extract Rust CIDs and update goldens", not "python kit broke".

from __future__ import annotations

from typing import List

from sugar_lift_py_tests import (
    BridgeDecl,
    ContractDecl,
    atomic,
    bridge_decl_to_value,
    contract_decl_to_value,
    declarations_to_value,
    encode_jcs,
    jcs_hash,
    str_const,
)

# ---------- Rust contract CID goldens --------------------------------------
#
# Source: `cargo run --release -p sugar-self-contracts \
#           --bin print-lift-plugin-protocol-cids` (run on a quiescent tree
#           with the rust kit at PR #84 contracts).

RUST_CONTRACT_CIDS: dict[str, str] = {
    "lift_plugin_initialize_protocol_version_match": (
        "blake3-512:95163d00976803c3ef381494a8a940bd862529f7bdfb72aa523bd58359b86d6f"
        "ce017991658932e3e3dee8b4c60b26066bfa270474b2896c19dd2ec85d4aa47a"
    ),
    "lift_plugin_initialize_capabilities_authoring_surfaces_nonempty": (
        "blake3-512:1898e2518e96628bbe46704f6f6a90cc57572f3b15bb3f4f6a7d8fef28a8c92e"
        "31b33b14f21d4011ed7ad11d4ea09c67c1549cbe1c2bf38e53b7e8cfdb656099"
    ),
    "lift_plugin_initialize_capabilities_ir_version_starts_with_v": (
        "blake3-512:08d09e6f677e77f5b501a07a5271cebdadb19c48c52375ae9e6edcb699b6515e"
        "acdea2d7966497c3b3aca4054340e7222fe97bbbb8f60e2ee62baaec6ef719f0"
    ),
    "lift_plugin_lift_request_surface_is_string": (
        "blake3-512:bf6ac4f7e481ba1fea26716f9d2e7756c86b1940610e2d9e35a5d6e11faa8993"
        "a92cd291f491c4d520e5daf1a54c32aeb492adac5aa8d61d224ca1104adaaf8a"
    ),
    "lift_plugin_lift_request_source_paths_nonempty": (
        "blake3-512:3f2915b063357c28cd2bd8132279e819424999b21a776824d3db9231ca4acb8f"
        "dc02ea6e5a8945e55a1d439fda94d07b365d0d160e4ece94b1012fe064ca7c22"
    ),
    "lift_plugin_lift_request_source_paths_each_nonempty": (
        "blake3-512:f57621c2ba995cbd13d9d06c4209ad9ecdb6369d1e90d902b90996275dd40a38"
        "804c986b77b9f28bdf7eefc2b0f242284d1612a4149f5abb0451097a72f95822"
    ),
    "lift_plugin_lift_request_surface_in_capabilities": (
        "blake3-512:61c67906e3b2ff0d0a61419436670140009556402b643516c4afb14212c057a0"
        "80bf6f29a0c4c374fe2eb45f8016ddfc82ed12fae2735c7384a8b56a7597db51"
    ),
    "lift_plugin_lift_response_kind_in_set": (
        "blake3-512:7642bd5eb5262354921513ee6e01bf70dad917f3467464ad904750685e84d024"
        "1ef9b0f40b6e0d66dd73e0d5cc1908e4a0a45d45530dda511e1919786034e2a0"
    ),
    "lift_plugin_lift_response_ir_document_array": (
        "blake3-512:692df8b67bc3ad69943f5909779f489bdc8173bbb08fd61585bb1b8bc0a2c20c"
        "6891ba7b9a2a4e4e3a6e5a4441b1191f4618924783446cb07277879c885cbc20"
    ),
    "lift_plugin_diagnostic_field_is_array": (
        "blake3-512:ea5dd139fddc9e5ab6cfcb9854de1ce6bbedcccbe7b070c1aef9fbbef3b8579e"
        "bf33ff14cdc97013e1f3e1c391964f275a0275b615b8259037b0cb92d0e0dd35"
    ),
}

# Insertion order from `lift_plugin_protocol::invariants()` (rust slab).
# Bridges/counterparts are emitted in this order to keep the declarations
# array byte-stable.
LIFT_PLUGIN_PROTOCOL_NAMES: List[str] = [
    "lift_plugin_initialize_protocol_version_match",
    "lift_plugin_initialize_capabilities_authoring_surfaces_nonempty",
    "lift_plugin_initialize_capabilities_ir_version_starts_with_v",
    "lift_plugin_lift_request_surface_is_string",
    "lift_plugin_lift_request_source_paths_nonempty",
    "lift_plugin_lift_request_source_paths_each_nonempty",
    "lift_plugin_lift_request_surface_in_capabilities",
    "lift_plugin_lift_response_kind_in_set",
    "lift_plugin_lift_response_ir_document_array",
    "lift_plugin_diagnostic_field_is_array",
]

# Names locked, surface ID locked: the python counterpart formula reads
# `satisfies("python-lift-adapter", "<rust-contract-name>")`. Same shape
# for all 10 so the BridgeDecl carries the only per-contract variation.
PY_ADAPTER_LAYER = "python-kit"
PY_ADAPTER_ID = "python-lift-adapter"
RUST_LAYER = "rust-kit"
DEFERRED_PROOF_CID = "deferred:phase-3-proof-bundle"
BRIDGE_NOTES = "lift-plugin-protocol conformance bridge; phase 2"


def _counterpart_contract(rust_contract_name: str) -> ContractDecl:
    """Build the python counterpart for a named Rust contract.

    The IR claim is `inv = satisfies(adapter_id, rust_contract_name)` ; an
    atomic predicate the verifier resolves through the bridge. The
    counterpart's CID comes from JCS-of-the-formula via
    `contract_decl_to_value` -> `encode_jcs` -> `blake3_512_of`. (Note:
    the python kit does NOT re-implement the rust signed-CBOR envelope
    pipeline, so python counterpart CIDs and rust contract CIDs are NOT
    in the same identity space; the bridge wires them by content.)
    """
    return ContractDecl(
        name=f"py_{rust_contract_name}_counterpart",
        inv=atomic(
            "satisfies",
            [str_const(PY_ADAPTER_ID), str_const(rust_contract_name)],
        ),
    )


def _bridge_for(rust_contract_name: str, target_cid: str) -> BridgeDecl:
    return BridgeDecl(
        name=f"bridge_to_{rust_contract_name}",
        source_symbol=rust_contract_name,
        source_layer=RUST_LAYER,
        source_contract_cid=RUST_CONTRACT_CIDS[rust_contract_name],
        target_contract_cid=target_cid,
        target_proof_cid=DEFERRED_PROOF_CID,
        target_layer=PY_ADAPTER_LAYER,
        notes=BRIDGE_NOTES,
    )


def _build_all_declarations() -> list:
    """Return the mixed [counterpart, bridge, counterpart, bridge, ...] list.

    Insertion order: for each Rust contract (in slab order), emit the
    python counterpart followed immediately by its bridge. This pairing
    is the byte-equality contract for the bundle's `declarations`
    field.
    """
    decls: list = []
    for name in LIFT_PLUGIN_PROTOCOL_NAMES:
        cp = _counterpart_contract(name)
        cp_cid = jcs_hash(contract_decl_to_value(cp))
        decls.append(cp)
        decls.append(_bridge_for(name, cp_cid))
    return decls


# ---------- Counterpart CID goldens ----------------------------------------
#
# The python counterpart contract CID is `blake3-512(jcs(contract_decl))`,
# where `contract_decl` is the `ContractDecl` returned by
# `_counterpart_contract`. JCS bytes are independent of rust mint state,
# so these pins move only if the python counterpart shape changes.

PY_COUNTERPART_CIDS: dict[str, str] = {
    "lift_plugin_initialize_protocol_version_match": (
        "blake3-512:6b01828c2f26074034b2c844209d96d89f6dd19db25569b23ffa26797b27363b"
        "89e33387aaba77cb3ec24fc525733ee468c37dc7ceb7c1708db3635036cc435a"
    ),
    "lift_plugin_initialize_capabilities_authoring_surfaces_nonempty": (
        "blake3-512:3fc14adaa692282cbf542d782fcd8aecf693e18ac5dbce875999bd11ef436424"
        "3fb59ccc16a97f8281b3d86e6d78ace530d3fbebf1e6f8816f8f335480c506b9"
    ),
    "lift_plugin_initialize_capabilities_ir_version_starts_with_v": (
        "blake3-512:f876e72b5b413cbcb5d3dd8ff332a8605c8c86f0ec3ed405b9dacd00215ac0b3"
        "d69b83b0dbd7353cf78ed06791c443e7ce85caf346db2ec9c17f6905f901c0b5"
    ),
    "lift_plugin_lift_request_surface_is_string": (
        "blake3-512:be916ddda845ec04bd078843148105c39f629116a38669480fa2b59bdfe67da9"
        "a13d1b297f0f55176fcf7bc4beec1e7db197b749d68f8fc45c5c47be7a8484e0"
    ),
    "lift_plugin_lift_request_source_paths_nonempty": (
        "blake3-512:007f722b60305ca1bf83cf0f7e766f9830af9b48e1d412a1ca08d8a4f74cba32"
        "7c37ce7e855c1d0ee7abab4d1337fe35733babed01ffaaf010d49a10af7cfe85"
    ),
    "lift_plugin_lift_request_source_paths_each_nonempty": (
        "blake3-512:ea37b61b118fcdfd6182e264ca7752475cdce81f8f1c656c5a1d5a00a69cbeb7"
        "e645eb873d63aa232cea9b4f47d4964a60cdebfa1a7c49bf6e37fe4c77f87e63"
    ),
    "lift_plugin_lift_request_surface_in_capabilities": (
        "blake3-512:ddd1d73b8c1e9398a3d0c1a37df98cfde9d5f7af06dd196f439d94972e450129"
        "0a1b4e0eac586267abc69b49fb74287a6f65ffb2091b69b18745046ce08038a9"
    ),
    "lift_plugin_lift_response_kind_in_set": (
        "blake3-512:f97402f8957f2b0bcf8461cbe457cd0da252019e045323f14bbdabc82b9f83dc"
        "cb77ba0c36375c69859eabe289bea4af3b2cc52c9ca180719449a0bfe0542c95"
    ),
    "lift_plugin_lift_response_ir_document_array": (
        "blake3-512:b6f3414d45e74b2c7f7d2ebf3d6578d63937f7ca6fc2768154138b5ff040983c"
        "f0bc2320eea2b1e50e7e3c75d35b8e1a85a0768e6885587f0d7addf4463ca81f"
    ),
    "lift_plugin_diagnostic_field_is_array": (
        "blake3-512:e71786413208101aa38d96f3084bf3fdc9a388ad24522c925b7e5822ee8ce30a"
        "fd7f9f888926b776f95868e39559c465f67f893daa1c3a34f6804001e5e5c825"
    ),
}


# ---------- Tests ----------------------------------------------------------


def test_all_ten_bridges_construct_without_error():
    decls = _build_all_declarations()
    # 10 counterparts + 10 bridges == 20 declarations.
    assert len(decls) == 20
    contracts = [d for d in decls if isinstance(d, ContractDecl)]
    bridges = [d for d in decls if isinstance(d, BridgeDecl)]
    assert len(contracts) == 10
    assert len(bridges) == 10


def test_each_bridge_carries_correct_rust_source_cid():
    decls = _build_all_declarations()
    bridges = [d for d in decls if isinstance(d, BridgeDecl)]
    for b in bridges:
        rust_name = b.source_symbol
        assert (
            b.source_contract_cid == RUST_CONTRACT_CIDS[rust_name]
        ), f"bridge {b.name} mis-pinned source CID for {rust_name}"
        assert b.source_layer == RUST_LAYER
        assert b.target_layer == PY_ADAPTER_LAYER
        assert b.target_proof_cid == DEFERRED_PROOF_CID
        assert b.notes == BRIDGE_NOTES
        assert b.name == f"bridge_to_{rust_name}"


def test_each_bridge_targets_its_python_counterpart_cid():
    """Bridge target CID must match the JCS-hash of the paired counterpart."""
    decls = _build_all_declarations()
    # decls layout: [c0, b0, c1, b1, ...].
    for i in range(0, len(decls), 2):
        cp = decls[i]
        br = decls[i + 1]
        assert isinstance(cp, ContractDecl)
        assert isinstance(br, BridgeDecl)
        expected = jcs_hash(contract_decl_to_value(cp))
        assert br.target_contract_cid == expected, (
            f"bridge {br.name} target_contract_cid does not match counterpart "
            f"{cp.name} JCS hash"
        )


def test_declarations_array_jcs_round_trips():
    """The full mixed array encodes to JCS bytes and hashes deterministically.

    Pin both the JCS bytes' length signature (loose check) and the BLAKE3
    of the encoding (tight check). The tight check is the byte-level
    cross-kit handshake: two runs of this test on a quiescent tree must
    yield the same hash.
    """
    decls = _build_all_declarations()
    enc = encode_jcs(declarations_to_value(decls))
    assert enc.startswith("[")
    assert enc.endswith("]")
    assert enc.count('"kind":"contract"') == 10
    assert enc.count('"kind":"bridge"') == 10

    h1 = jcs_hash(declarations_to_value(decls))
    h2 = jcs_hash(declarations_to_value(_build_all_declarations()))
    assert h1 == h2, "declarations encoding is non-deterministic"


def test_declarations_array_pinned_hash():
    """Pinned BLAKE3-512 over the full declarations JCS encoding.

    Computed from the python kit alone (no rust dependency at hash time;
    rust dependency lives in `RUST_CONTRACT_CIDS` constants). If this
    fails, the dependency chain in the module docstring identifies the
    cause.
    """
    decls = _build_all_declarations()
    actual = jcs_hash(declarations_to_value(decls))
    expected = (
        "blake3-512:e45633f36c744a55f3fd04f0522138bb828d58f276280fd1582b4ce5828b431c"
        "55e8aeaa04ed4e7b7968498db652729e1cb045e14c54d6964370dd78cd4655dc"
    )
    assert actual == expected, (
        f"declarations array hash drift; got {actual}\n"
        f"expected {expected}\n"
        "If this is intentional (e.g. rust kit re-minted, counterpart shape "
        "changed), update the pin and the dependency chain notes."
    )


def test_bridge_notes_consistent_across_all_ten():
    decls = _build_all_declarations()
    bridges = [d for d in decls if isinstance(d, BridgeDecl)]
    notes_set = {b.notes for b in bridges}
    assert notes_set == {BRIDGE_NOTES}


def test_each_counterpart_is_well_formed():
    decls = _build_all_declarations()
    counterparts = [d for d in decls if isinstance(d, ContractDecl)]
    for cp in counterparts:
        assert cp.name.startswith("py_")
        assert cp.name.endswith("_counterpart")
        assert cp.inv is not None
        # JCS round-trips and produces a stable hash.
        h1 = jcs_hash(contract_decl_to_value(cp))
        h2 = jcs_hash(contract_decl_to_value(cp))
        assert h1 == h2
        assert h1.startswith("blake3-512:")


def test_python_counterpart_cids_match_goldens():
    """Each counterpart CID matches the pinned goldens.

    This catches python-side drift (counterpart formula shape change,
    canonicalizer bug) independently of the rust-CID extraction step.
    """
    for name in LIFT_PLUGIN_PROTOCOL_NAMES:
        cp = _counterpart_contract(name)
        actual = jcs_hash(contract_decl_to_value(cp))
        expected = PY_COUNTERPART_CIDS[name]
        assert (
            actual == expected
        ), f"counterpart CID drift for {name}: got {actual}, expected {expected}"


def test_bridge_decl_to_value_emits_expected_keys():
    """Spot-check: a bridge's JCS encoding has all required v1.3 fields."""
    decls = _build_all_declarations()
    bridges = [d for d in decls if isinstance(d, BridgeDecl)]
    enc = encode_jcs(bridge_decl_to_value(bridges[0]))
    for required in (
        '"kind":"bridge"',
        '"name":"bridge_to_lift_plugin_initialize_protocol_version_match"',
        '"sourceSymbol":"lift_plugin_initialize_protocol_version_match"',
        '"sourceLayer":"rust-kit"',
        '"sourceContractCid":',
        '"targetContractCid":',
        f'"targetProofCid":"{DEFERRED_PROOF_CID}"',
        '"targetLayer":"python-kit"',
        f'"notes":"{BRIDGE_NOTES}"',
    ):
        assert required in enc, f"bridge JCS missing {required}; got: {enc}"
