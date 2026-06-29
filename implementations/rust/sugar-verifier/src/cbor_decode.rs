// SPDX-License-Identifier: Apache-2.0
//
// Minimal CBOR decoder for .proof catalog reading. The implementation
// moved to `sugar-proof-envelope::cbor_decode` so it can be reused
// from libsugar (which depends on proof-envelope but not verifier).
// This module re-exports the public types so existing `crate::cbor_decode::*`
// type paths inside sugar-verifier keep working. `decode` is now pub(crate)
// in sugar-proof-envelope; proof_conformance routes through
// sugar_proof_envelope::decode_for_conformance (the sanctioned raw site).

pub use sugar_proof_envelope::cbor_decode::{CborDecodeError, CborValue};
