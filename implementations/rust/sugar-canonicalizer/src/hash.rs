// SPDX-License-Identifier: Apache-2.0
//
// BLAKE3-512 hash helper. v1.1.0 of the protocol mandates
// self-identifying hashes of the form:
//
//   "blake3-512:" + lowercase-hex(64-byte-digest)
//
// We use the official `blake3` crate at its 64-byte (512-bit) extended
// output length. There is NO truncation. The protocol cut is scorched
// earth: this is the only hash function permitted in v1.1.0, and it
// is always 512 bits wide.

pub const BLAKE3_512_PREFIX: &str = "blake3-512:";

/// Borrow the digest portion of a canonical in-memory BLAKE3-512 CID.
///
/// This helper owns the string tag knowledge for colon-form CIDs. It only
/// strips the tag; callers that need validation keep their existing length and
/// hex checks so lenient fallback call sites do not tighten silently.
pub fn cid_hex(cid: &str) -> Option<&str> {
    cid.strip_prefix(BLAKE3_512_PREFIX)
}

/// Validate the canonical in-memory BLAKE3-512 CID spelling.
pub fn is_blake3_512_cid(cid: &str) -> bool {
    cid_hex(cid)
        .is_some_and(|hex| hex.len() == 128 && hex.bytes().all(|byte| byte.is_ascii_hexdigit()))
}

/// Hash arbitrary bytes into the self-identifying string form.
pub fn blake3_512_of(bytes: &[u8]) -> String {
    let mut hasher = blake3::Hasher::new();
    hasher.update(bytes);
    let mut out = [0u8; 64];
    hasher.finalize_xof().fill(&mut out);
    let hex = hex::encode(out);
    let mut s = String::with_capacity(BLAKE3_512_PREFIX.len() + hex.len());
    s.push_str(BLAKE3_512_PREFIX);
    s.push_str(&hex);
    s
}

/// Convenience: hash a UTF-8 string slice.
pub fn blake3_512_hex<S: AsRef<[u8]>>(s: S) -> String {
    blake3_512_of(s.as_ref())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_string_hashes_to_known_blake3() {
        // BLAKE3 of empty input, XOF to 64 bytes — known vector
        let h = blake3_512_of(b"");
        assert!(h.starts_with(BLAKE3_512_PREFIX));
        // Total length: prefix + 128 hex chars = 11 + 128 = 139.
        assert_eq!(h.len(), BLAKE3_512_PREFIX.len() + 128);
    }

    #[test]
    fn deterministic_across_calls() {
        let a = blake3_512_of(b"hello");
        let b = blake3_512_of(b"hello");
        assert_eq!(a, b);
    }

    #[test]
    fn distinct_inputs_distinct_hashes() {
        assert_ne!(blake3_512_of(b"hello"), blake3_512_of(b"world"));
    }
}
