// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Deterministic CBOR encoder tests, RFC 8949 §4.2.1.
//
// We exercise:
//   - shortest-form integer encoding at every length boundary
//   - byte-string vs text-string discrimination
//   - array & map heads
//   - definite-length only (we don't expose indefinite-length, so this
//     is asserted by absence: the head byte must be in the canonical
//     additional-info range 0..=27 minus the indefinite-length 31).

use sugar_proof_envelope::{
    cbor_encode_array_head, cbor_encode_bstr, cbor_encode_map_head, cbor_encode_tstr,
    cbor_encode_uint,
};

// ---------------------------------------------------------------------------
// Unsigned int: boundary table per RFC 8949 §4.2.1 (shortest form)
// ---------------------------------------------------------------------------

fn enc_uint(v: u64) -> Vec<u8> {
    let mut o = Vec::new();
    cbor_encode_uint(&mut o, v);
    o
}

#[test]
fn uint_shortest_form_zero() {
    assert_eq!(enc_uint(0), vec![0x00]);
}

#[test]
fn uint_shortest_form_one() {
    assert_eq!(enc_uint(1), vec![0x01]);
}

#[test]
fn uint_shortest_form_23_is_short() {
    // 23 fits in the additional-info field directly.
    assert_eq!(enc_uint(23), vec![0x17]);
}

#[test]
fn uint_shortest_form_24_uses_one_byte() {
    // 24 is the first value requiring a u8 follow-byte.
    assert_eq!(enc_uint(24), vec![0x18, 24]);
}

#[test]
fn uint_shortest_form_255_is_one_byte() {
    assert_eq!(enc_uint(255), vec![0x18, 0xFF]);
}

#[test]
fn uint_shortest_form_256_promotes_to_two_bytes() {
    assert_eq!(enc_uint(256), vec![0x19, 0x01, 0x00]);
}

#[test]
fn uint_shortest_form_65535_is_two_bytes() {
    assert_eq!(enc_uint(65_535), vec![0x19, 0xFF, 0xFF]);
}

#[test]
fn uint_shortest_form_65536_promotes_to_four_bytes() {
    assert_eq!(enc_uint(65_536), vec![0x1A, 0x00, 0x01, 0x00, 0x00]);
}

#[test]
fn uint_shortest_form_u32_max_is_four_bytes() {
    assert_eq!(enc_uint(0xFFFF_FFFF), vec![0x1A, 0xFF, 0xFF, 0xFF, 0xFF]);
}

#[test]
fn uint_shortest_form_u32_max_plus_one_promotes_to_eight_bytes() {
    assert_eq!(
        enc_uint(0x1_0000_0000),
        vec![0x1B, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00]
    );
}

#[test]
fn uint_shortest_form_u64_max_is_eight_bytes() {
    assert_eq!(
        enc_uint(u64::MAX),
        vec![0x1B, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF]
    );
}

// ---------------------------------------------------------------------------
// Byte-string vs text-string discrimination
// ---------------------------------------------------------------------------

#[test]
fn bstr_uses_major_2() {
    let mut o = Vec::new();
    cbor_encode_bstr(&mut o, b"hi");
    // major 2 = 0x40, len 2 fits short = 0x42.
    assert_eq!(o, vec![0x42, b'h', b'i']);
}

#[test]
fn tstr_uses_major_3() {
    let mut o = Vec::new();
    cbor_encode_tstr(&mut o, "hi");
    // major 3 = 0x60, len 2 short = 0x62.
    assert_eq!(o, vec![0x62, b'h', b'i']);
}

#[test]
fn empty_bstr_is_one_byte_head() {
    let mut o = Vec::new();
    cbor_encode_bstr(&mut o, b"");
    assert_eq!(o, vec![0x40]);
}

#[test]
fn empty_tstr_is_one_byte_head() {
    let mut o = Vec::new();
    cbor_encode_tstr(&mut o, "");
    assert_eq!(o, vec![0x60]);
}

#[test]
fn bstr_at_short_boundary() {
    // 23-byte payload still fits short form.
    let payload = vec![0xAAu8; 23];
    let mut o = Vec::new();
    cbor_encode_bstr(&mut o, &payload);
    assert_eq!(o[0], 0x40 | 23);
    assert_eq!(o.len(), 1 + 23);
}

#[test]
fn bstr_at_24_byte_boundary_promotes() {
    let payload = vec![0xBBu8; 24];
    let mut o = Vec::new();
    cbor_encode_bstr(&mut o, &payload);
    assert_eq!(o[0], 0x40 | 24);
    assert_eq!(o[1], 24);
    assert_eq!(o.len(), 2 + 24);
}

#[test]
fn tstr_long_payload() {
    let s = "x".repeat(300);
    let mut o = Vec::new();
    cbor_encode_tstr(&mut o, &s);
    // Major 3, len 300 fits in u16: head = 0x79 0x01 0x2C.
    assert_eq!(o[0], 0x60 | 25);
    assert_eq!(o[1], 0x01);
    assert_eq!(o[2], 0x2C);
    assert_eq!(o.len(), 3 + 300);
}

// ---------------------------------------------------------------------------
// Array & map heads
// ---------------------------------------------------------------------------

#[test]
fn array_head_zero() {
    let mut o = Vec::new();
    cbor_encode_array_head(&mut o, 0);
    assert_eq!(o, vec![0x80]);
}

#[test]
fn array_head_three() {
    let mut o = Vec::new();
    cbor_encode_array_head(&mut o, 3);
    assert_eq!(o, vec![0x83]);
}

#[test]
fn array_head_at_24_boundary() {
    let mut o = Vec::new();
    cbor_encode_array_head(&mut o, 24);
    assert_eq!(o, vec![0x98, 24]);
}

#[test]
fn map_head_zero() {
    let mut o = Vec::new();
    cbor_encode_map_head(&mut o, 0);
    assert_eq!(o, vec![0xA0]);
}

#[test]
fn map_head_seven() {
    // The signed catalog has 7 keys; pin its head byte.
    let mut o = Vec::new();
    cbor_encode_map_head(&mut o, 7);
    assert_eq!(o, vec![0xA7]);
}

#[test]
fn map_head_at_24_boundary() {
    let mut o = Vec::new();
    cbor_encode_map_head(&mut o, 24);
    assert_eq!(o, vec![0xB8, 24]);
}

// ---------------------------------------------------------------------------
// Determinism
// ---------------------------------------------------------------------------

#[test]
fn cbor_encoding_is_deterministic() {
    // Same call sequence must produce identical bytes every time.
    let build = || {
        let mut o = Vec::new();
        cbor_encode_uint(&mut o, 42);
        cbor_encode_tstr(&mut o, "hello");
        cbor_encode_bstr(&mut o, b"\x00\x01\x02");
        cbor_encode_array_head(&mut o, 5);
        cbor_encode_map_head(&mut o, 7);
        o
    };
    let baseline = build();
    for _ in 0..100 {
        assert_eq!(build(), baseline);
    }
}

#[test]
fn no_indefinite_length_marker_in_emitted_heads() {
    // Indefinite-length items use additional-info 31 (0x1F). Our encoder
    // never emits one. Sample at boundary widths and confirm.
    for v in [0u64, 23, 24, 255, 256, 65_535, 65_536, u64::MAX] {
        let mut o = Vec::new();
        cbor_encode_uint(&mut o, v);
        // First byte's low 5 bits must NOT equal 31.
        assert_ne!(o[0] & 0x1F, 0x1F, "indefinite-length leaked at v={v}");
    }
}
