// SPDX-License-Identifier: MIT OR Apache-2.0
//
// BLAKE3 known-answer tests against the official BLAKE3 test vectors:
//
//   https://github.com/BLAKE3-team/BLAKE3/blob/master/test_vectors/test_vectors.json
//
// Per the test_vectors README: "The input in each case is filled with
// a repeating sequence of 251 bytes: 0, 1, 2, ..., 249, 250, 0, 1, ...".
// The output is BLAKE3 in XOF mode (default-hash key); we take the
// first 64 bytes (128 hex chars) for the spec's 512-bit output.

use sugar_canonicalizer::{blake3_512_of, BLAKE3_512_PREFIX};

/// Construct an `input_len`-byte input filled with the repeating
/// 0..251 sequence (matches the test_vectors.json convention).
fn vector_input(input_len: usize) -> Vec<u8> {
    let mut out = Vec::with_capacity(input_len);
    for i in 0..input_len {
        out.push((i % 251) as u8);
    }
    out
}

fn assert_known_answer(input_len: usize, expected_hex_first_64_bytes: &str) {
    let input = vector_input(input_len);
    let h = blake3_512_of(&input);
    assert!(h.starts_with(BLAKE3_512_PREFIX), "missing prefix");
    let hex = h.trim_start_matches(BLAKE3_512_PREFIX);
    assert_eq!(
        hex, expected_hex_first_64_bytes,
        "BLAKE3-512 KAT mismatch for input_len={input_len}"
    );
}

#[test]
fn blake3_512_input_len_0() {
    // Empty input.
    assert_known_answer(
        0,
        "af1349b9f5f9a1a6a0404dea36dcc9499bcb25c9adc112b7cc9a93cae41f3262\
         e00f03e7b69af26b7faaf09fcd333050338ddfe085b8cc869ca98b206c08243a",
    );
}

#[test]
fn blake3_512_input_len_1() {
    // Single byte: 0x00.
    assert_known_answer(
        1,
        "2d3adedff11b61f14c886e35afa036736dcd87a74d27b5c1510225d0f592e213\
         c3a6cb8bf623e20cdb535f8d1a5ffb86342d9c0b64aca3bce1d31f60adfa137b",
    );
}

#[test]
fn blake3_512_input_len_2() {
    // Two bytes: 0x00, 0x01.
    assert_known_answer(
        2,
        "7b7015bb92cf0b318037702a6cdd81dee41224f734684c2c122cd6359cb1ee63\
         d8386b22e2ddc05836b7c1bb693d92af006deb5ffbc4c70fb44d0195d0c6f252",
    );
}

#[test]
fn blake3_512_input_len_3() {
    // Three bytes: 0x00, 0x01, 0x02.
    assert_known_answer(
        3,
        "e1be4d7a8ab5560aa4199eea339849ba8e293d55ca0a81006726d184519e647f\
         5b49b82f805a538c68915c1ae8035c900fd1d4b13902920fd05e1450822f36de",
    );
}

#[test]
fn blake3_512_input_len_4() {
    assert_known_answer(
        4,
        "f30f5ab28fe047904037f77b6da4fea1e27241c5d132638d8bedce9d40494f32\
         8f603ba4564453e06cdcee6cbe728a4519bbe6f0d41e8a14b5b225174a566dbf",
    );
}

#[test]
fn blake3_512_input_len_5() {
    assert_known_answer(
        5,
        "b40b44dfd97e7a84a996a91af8b85188c66c126940ba7aad2e7ae6b385402aa2\
         ebcfdac6c5d32c31209e1f81a454751280db64942ce395104e1e4eaca62607de",
    );
}

#[test]
fn blake3_512_input_len_7() {
    assert_known_answer(
        7,
        "3f8770f387faad08faa9d8414e9f449ac68e6ff0417f673f602a646a891419fe\
         66036ef6e6d1a8f54baa9fed1fc11c77cfb9cff65bae915045027046ebe0c01b",
    );
}

// ---------------------------------------------------------------------------
// Avalanche / collision-shape sanity
// ---------------------------------------------------------------------------

#[test]
fn single_bit_flip_changes_most_output_bits() {
    // Not a strict avalanche test (which would compare bit counts), but
    // a smoke check: flipping any byte changes the output substantially.
    let h0 = blake3_512_of(b"the quick brown fox");
    let h1 = blake3_512_of(b"the quick brown Fox"); // capital F
    assert_ne!(h0, h1);
    // First-byte difference catches most common bugs (reused state /
    // returned constant).
    let hex0 = h0.trim_start_matches(BLAKE3_512_PREFIX);
    let hex1 = h1.trim_start_matches(BLAKE3_512_PREFIX);
    assert_ne!(&hex0[..2], &hex1[..2]);
}

#[test]
fn many_distinct_inputs_produce_distinct_outputs() {
    let mut seen = std::collections::HashSet::new();
    for n in 0..1000u32 {
        let input = format!("test-{n}");
        let h = blake3_512_of(input.as_bytes());
        assert!(seen.insert(h), "collision found at n={n}");
    }
}

#[test]
fn deterministic_function_property_over_n_trials() {
    let inputs: Vec<&[u8]> = vec![
        b"",
        b"a",
        b"abc",
        b"hello world",
        b"\x00\x01\x02\x03",
        b"the quick brown fox jumps over the lazy dog",
    ];
    for input in &inputs {
        let first = blake3_512_of(input);
        for _ in 0..50 {
            assert_eq!(blake3_512_of(input), first);
        }
    }
}

// ---------------------------------------------------------------------------
// Large-input smoke test
// ---------------------------------------------------------------------------

#[test]
fn one_megabyte_input_does_not_panic() {
    let mut buf = vec![0u8; 1024 * 1024];
    for (i, b) in buf.iter_mut().enumerate() {
        *b = (i % 251) as u8;
    }
    let h = blake3_512_of(&buf);
    assert!(h.starts_with(BLAKE3_512_PREFIX));
    assert_eq!(h.len(), BLAKE3_512_PREFIX.len() + 128);
}
