// SPDX-License-Identifier: Apache-2.0

use sugar_proof_envelope::decode_for_conformance;

#[test]
fn duplicate_cbor_map_key_is_rejected() {
    // { "a": 1, "a": 2 } hand-encoded as definite-length CBOR.
    // A BTreeMap-backed decoder must not silently collapse this to one entry.
    let bytes = [0xa2, 0x61, b'a', 0x01, 0x61, b'a', 0x02];

    let err = decode_for_conformance(&bytes)
        .expect_err("duplicate CBOR map key must be a loud decode error");
    let msg = err.to_string();
    assert!(msg.contains("duplicate map key"), "{msg}");
    assert!(msg.contains("a"), "{msg}");
}
