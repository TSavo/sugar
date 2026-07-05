// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Deterministic CBOR encoder. RFC 8949 §4.2.1 rules:
//   - shortest-form integer encoding (smallest of short / u8 / u16 / u32 / u64)
//   - definite-length items only
//   - map keys sorted in bytewise lex order of their CBOR-encoded form
//   - we emit only the major types we need: unsigned int, byte string,
//     text string, array, map.
//
// Mirrors implementations/cpp/sugar/proof-envelope/cbor.cpp 1:1.

#[derive(Debug, Clone, Copy)]
pub enum CborMajor {
    UnsignedInt = 0,
    ByteString = 2,
    TextString = 3,
    Array = 4,
    Map = 5,
}

pub fn cbor_append_head(out: &mut Vec<u8>, major: CborMajor, arg: u64) {
    let mt = (major as u8) << 5;
    if arg < 24 {
        out.push(mt | (arg as u8));
        return;
    }
    if arg <= 0xFF {
        out.push(mt | 24);
        out.push(arg as u8);
        return;
    }
    if arg <= 0xFFFF {
        out.push(mt | 25);
        out.push((arg >> 8) as u8);
        out.push(arg as u8);
        return;
    }
    if arg <= 0xFFFF_FFFF {
        out.push(mt | 26);
        out.push((arg >> 24) as u8);
        out.push((arg >> 16) as u8);
        out.push((arg >> 8) as u8);
        out.push(arg as u8);
        return;
    }
    out.push(mt | 27);
    for i in (0..8).rev() {
        out.push((arg >> (i * 8)) as u8);
    }
}

pub fn cbor_encode_uint(out: &mut Vec<u8>, value: u64) {
    cbor_append_head(out, CborMajor::UnsignedInt, value);
}

pub fn cbor_encode_bstr(out: &mut Vec<u8>, bytes: &[u8]) {
    cbor_append_head(out, CborMajor::ByteString, bytes.len() as u64);
    out.extend_from_slice(bytes);
}

pub fn cbor_encode_tstr(out: &mut Vec<u8>, utf8: &str) {
    cbor_append_head(out, CborMajor::TextString, utf8.len() as u64);
    out.extend_from_slice(utf8.as_bytes());
}

pub fn cbor_encode_array_head(out: &mut Vec<u8>, count: u64) {
    cbor_append_head(out, CborMajor::Array, count);
}

pub fn cbor_encode_map_head(out: &mut Vec<u8>, count: u64) {
    cbor_append_head(out, CborMajor::Map, count);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn shortest_form_uint() {
        let mut o = Vec::new();
        cbor_encode_uint(&mut o, 0);
        assert_eq!(o, vec![0x00]);

        let mut o = Vec::new();
        cbor_encode_uint(&mut o, 23);
        assert_eq!(o, vec![0x17]);

        let mut o = Vec::new();
        cbor_encode_uint(&mut o, 24);
        assert_eq!(o, vec![0x18, 24]);

        let mut o = Vec::new();
        cbor_encode_uint(&mut o, 256);
        assert_eq!(o, vec![0x19, 0x01, 0x00]);

        let mut o = Vec::new();
        cbor_encode_uint(&mut o, 65536);
        assert_eq!(o, vec![0x1a, 0x00, 0x01, 0x00, 0x00]);
    }

    #[test]
    fn tstr_round_trip_head() {
        let mut o = Vec::new();
        cbor_encode_tstr(&mut o, "hello");
        // major 3 (text string), len 5 short form: 0x65, then "hello"
        assert_eq!(o, vec![0x65, b'h', b'e', b'l', b'l', b'o']);
    }
}
