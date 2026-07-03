// SPDX-License-Identifier: Apache-2.0
//
// sugar-canonicalizer
//
// Two responsibilities:
//
// 1. A small JSON value tree (`Value`) and a JCS-JSON encoder (RFC 8785,
//    a.k.a. "JCS"). This is pass 7 of the canonicalization grammar; for
//    the purposes of the kit/mint flow it is the only pass we need
//    (the formula AST has already been built in canonical shape by the
//    kit's IR-JSON serializer).
//
// 2. A BLAKE3-512 hash helper that returns the spec's self-identifying
//    `"blake3-512:" + hex(digest)` string.
//
// The Value tree is intentionally tiny. We keep insertion order on
// objects so callers can build envelopes naturally; the JCS encoder
// re-sorts keys by Unicode code-point at emit time (RFC 8785 §3.2.3).
// Absent fields are simply not inserted; there is no `Null` variant
// for "omit absent" because the spec's envelope shape never emits
// JSON nulls.

pub mod hash;
pub mod jcs;
pub mod json;
pub mod value;

pub use hash::{blake3_512_hex, blake3_512_of, cid_hex, is_blake3_512_cid, BLAKE3_512_PREFIX};
pub use jcs::encode_jcs;
pub use json::jcs_cid_of_json;
pub use value::{Value, ValueKind};

#[derive(Debug, thiserror::Error)]
pub enum CanonicalizerError {
    #[error("canonicalizer: {0}")]
    Other(String),
}
