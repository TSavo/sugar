// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Ed25519 signing helper tests. Pins the spec invariants:
//   - "ed25519:" prefix on string-form signatures and pubkeys
//   - base64-stdpad encoding of the 64-byte signature / 32-byte pubkey
//   - deterministic from a fixed seed
//   - signature actually verifies under the derived public key
//   - signature does NOT verify under a different key

use base64::{engine::general_purpose::STANDARD as B64, Engine as _};
use ed25519_dalek::{Signature, SigningKey, Verifier, VerifyingKey};
use sugar_proof_envelope::{
    ed25519_pubkey_string, ed25519_sign_string, ed25519_sign_with_seed, Ed25519Seed,
    ED25519_SIG_PREFIX,
};

const SEED_A: Ed25519Seed = [0x42; 32];
const SEED_B: Ed25519Seed = [0x99; 32];

// ---------------------------------------------------------------------------
// Determinism
// ---------------------------------------------------------------------------

#[test]
fn deterministic_signature_for_fixed_seed_and_message() {
    let a = ed25519_sign_with_seed(&SEED_A, b"hello");
    let b = ed25519_sign_with_seed(&SEED_A, b"hello");
    assert_eq!(a, b);
}

#[test]
fn deterministic_signature_string_form() {
    let a = ed25519_sign_string(&SEED_A, b"hello");
    let b = ed25519_sign_string(&SEED_A, b"hello");
    assert_eq!(a, b);
}

#[test]
fn distinct_messages_distinct_signatures() {
    let a = ed25519_sign_with_seed(&SEED_A, b"hello");
    let b = ed25519_sign_with_seed(&SEED_A, b"world");
    assert_ne!(a, b);
}

#[test]
fn distinct_seeds_distinct_signatures() {
    let a = ed25519_sign_with_seed(&SEED_A, b"hello");
    let b = ed25519_sign_with_seed(&SEED_B, b"hello");
    assert_ne!(a, b);
}

// ---------------------------------------------------------------------------
// String-form invariants
// ---------------------------------------------------------------------------

#[test]
fn signature_string_has_ed25519_prefix() {
    let s = ed25519_sign_string(&SEED_A, b"hello");
    assert!(s.starts_with(ED25519_SIG_PREFIX));
    assert!(s.starts_with("ed25519:"));
}

#[test]
fn signature_string_payload_is_88_chars_base64() {
    // 64 bytes -> 88 base64 chars (with padding `==`).
    let s = ed25519_sign_string(&SEED_A, b"hello");
    let payload = s.trim_start_matches("ed25519:");
    assert_eq!(payload.len(), 88);
    // Base64 of a multiple-of-3 input ends with `=` padding here.
    assert!(payload.ends_with('='));
}

#[test]
fn signature_string_base64_round_trips() {
    let raw = ed25519_sign_with_seed(&SEED_A, b"hello");
    let s = ed25519_sign_string(&SEED_A, b"hello");
    let decoded = B64
        .decode(s.trim_start_matches("ed25519:"))
        .expect("base64 decode");
    assert_eq!(decoded.len(), 64);
    assert_eq!(decoded.as_slice(), &raw[..]);
}

#[test]
fn pubkey_string_has_ed25519_prefix() {
    let s = ed25519_pubkey_string(&SEED_A);
    assert!(s.starts_with("ed25519:"));
}

#[test]
fn pubkey_string_payload_is_44_chars_base64() {
    let s = ed25519_pubkey_string(&SEED_A);
    let payload = s.trim_start_matches("ed25519:");
    assert_eq!(payload.len(), 44);
    assert!(payload.ends_with('='));
}

#[test]
fn pubkey_string_base64_decodes_to_32_bytes() {
    let s = ed25519_pubkey_string(&SEED_A);
    let decoded = B64
        .decode(s.trim_start_matches("ed25519:"))
        .expect("base64 decode");
    assert_eq!(decoded.len(), 32);
}

#[test]
fn distinct_seeds_distinct_pubkeys() {
    assert_ne!(
        ed25519_pubkey_string(&SEED_A),
        ed25519_pubkey_string(&SEED_B)
    );
}

#[test]
fn pubkey_for_fixed_seed_is_deterministic() {
    assert_eq!(
        ed25519_pubkey_string(&SEED_A),
        ed25519_pubkey_string(&SEED_A)
    );
}

// ---------------------------------------------------------------------------
// Verify (loop back through ed25519-dalek's Verifier)
// ---------------------------------------------------------------------------

#[test]
fn signature_verifies_under_correct_public_key() {
    let sig_bytes = ed25519_sign_with_seed(&SEED_A, b"some message");
    let sk = SigningKey::from_bytes(&SEED_A);
    let vk: VerifyingKey = sk.verifying_key();
    let sig = Signature::from_bytes(&sig_bytes);
    assert!(vk.verify(b"some message", &sig).is_ok());
}

#[test]
fn signature_fails_to_verify_under_wrong_public_key() {
    let sig_bytes = ed25519_sign_with_seed(&SEED_A, b"some message");
    let sk_other = SigningKey::from_bytes(&SEED_B);
    let vk_other: VerifyingKey = sk_other.verifying_key();
    let sig = Signature::from_bytes(&sig_bytes);
    assert!(vk_other.verify(b"some message", &sig).is_err());
}

#[test]
fn signature_fails_to_verify_against_modified_message() {
    let sig_bytes = ed25519_sign_with_seed(&SEED_A, b"some message");
    let sk = SigningKey::from_bytes(&SEED_A);
    let vk: VerifyingKey = sk.verifying_key();
    let sig = Signature::from_bytes(&sig_bytes);
    assert!(vk.verify(b"some message TAMPERED", &sig).is_err());
}

#[test]
fn empty_message_signature_verifies() {
    let sig_bytes = ed25519_sign_with_seed(&SEED_A, b"");
    let sk = SigningKey::from_bytes(&SEED_A);
    let vk: VerifyingKey = sk.verifying_key();
    let sig = Signature::from_bytes(&sig_bytes);
    assert!(vk.verify(b"", &sig).is_ok());
}

#[test]
fn long_message_signature_verifies() {
    let msg = vec![0xAAu8; 100_000];
    let sig_bytes = ed25519_sign_with_seed(&SEED_A, &msg);
    let sk = SigningKey::from_bytes(&SEED_A);
    let vk: VerifyingKey = sk.verifying_key();
    let sig = Signature::from_bytes(&sig_bytes);
    assert!(vk.verify(&msg, &sig).is_ok());
}
