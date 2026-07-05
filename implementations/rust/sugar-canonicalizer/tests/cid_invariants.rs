// SPDX-License-Identifier: MIT OR Apache-2.0
//
// CID-shape invariants for blake3_512_of. These tests pin the spec
// invariants: the self-identifying tag prefix, lowercase hex, exact
// 128-hex-character length, prefix regex compliance.

use sugar_canonicalizer::{blake3_512_hex, blake3_512_of, BLAKE3_512_PREFIX};

const PREFIX: &str = "blake3-512:";

#[test]
fn prefix_constant_matches_spec() {
    assert_eq!(BLAKE3_512_PREFIX, PREFIX);
}

#[test]
fn cid_starts_with_prefix() {
    let h = blake3_512_of(b"x");
    assert!(h.starts_with(PREFIX));
}

#[test]
fn cid_total_length_is_prefix_plus_128_hex() {
    let h = blake3_512_of(b"x");
    assert_eq!(h.len(), PREFIX.len() + 128);
}

#[test]
fn cid_hex_is_exactly_128_chars() {
    for input in &[
        b"".as_ref(),
        b"x".as_ref(),
        b"hello world".as_ref(),
        b"\x00".as_ref(),
    ] {
        let h = blake3_512_of(input);
        let hex = h.trim_start_matches(PREFIX);
        assert_eq!(hex.len(), 128, "hex length wrong for {input:?}");
    }
}

#[test]
fn cid_hex_is_lowercase_only() {
    for input in &[
        b"".as_ref(),
        b"x".as_ref(),
        b"hello world".as_ref(),
        b"ABCDEF".as_ref(),
    ] {
        let h = blake3_512_of(input);
        let hex = h.trim_start_matches(PREFIX);
        for c in hex.chars() {
            assert!(
                matches!(c, '0'..='9' | 'a'..='f'),
                "non-lowercase-hex char {c:?} in {h}"
            );
        }
    }
}

#[test]
fn cid_regex_compliance() {
    // Spec: `blake3-512:[0-9a-f]{128}`. We don't pull in a regex crate
    // for this sanity check.
    let h = blake3_512_of(b"sample");
    let mut chars = h.chars();
    for expected in PREFIX.chars() {
        assert_eq!(chars.next(), Some(expected));
    }
    let mut count = 0;
    for c in chars {
        assert!(c.is_ascii_hexdigit() && !c.is_ascii_uppercase());
        count += 1;
    }
    assert_eq!(count, 128);
}

#[test]
fn cid_string_form_for_empty_is_well_known() {
    let h = blake3_512_of(b"");
    assert_eq!(
        h,
        "blake3-512:af1349b9f5f9a1a6a0404dea36dcc9499bcb25c9adc112b7cc9a93cae41f3262\
         e00f03e7b69af26b7faaf09fcd333050338ddfe085b8cc869ca98b206c08243a"
    );
}

#[test]
fn blake3_512_hex_helper_matches_blake3_512_of() {
    // The string-input and bytes-input helpers must agree.
    let s = "hello";
    assert_eq!(blake3_512_hex(s), blake3_512_of(s.as_bytes()));
    assert_eq!(blake3_512_hex(""), blake3_512_of(b""));
}

#[test]
fn cid_distinguishes_byte_strings_from_text() {
    // The hash function operates on bytes — hashing the same bytes
    // through different APIs (str vs &[u8]) yields the same CID.
    let s: &str = "abc";
    let b: &[u8] = b"abc";
    assert_eq!(blake3_512_hex(s), blake3_512_of(b));
}

#[test]
fn cid_length_independent_of_input_length() {
    // Empty / 1-byte / 1KB / 1MB all produce the same-length CID.
    let lengths = [0usize, 1, 1024, 1024 * 1024];
    for n in &lengths {
        let buf = vec![0u8; *n];
        let h = blake3_512_of(&buf);
        assert_eq!(h.len(), PREFIX.len() + 128);
    }
}
