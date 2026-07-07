// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Minimal CBOR decoder for .proof catalog reading. We only need the
// major types we emit: unsigned int, byte string, text string, array,
// and map. Tag dispatch and float / negative int / simple values are
// rejected loud (no .proof should contain them).
//
// Mirrors implementations/cpp/.../proof-envelope/cbor_decoder.cpp at
// the level of detail the verifier needs (decode the catalog map and
// pull out `members`).

use std::collections::BTreeMap;

#[derive(Debug, thiserror::Error)]
pub enum CborDecodeError {
    #[error("cbor: unexpected EOF")]
    UnexpectedEof,
    #[error("cbor: unsupported major type {0}")]
    UnsupportedMajor(u8),
    #[error("cbor: bad utf-8 in tstr")]
    BadUtf8,
    #[error("cbor: indefinite-length items not permitted in deterministic encoding")]
    IndefiniteLength,
    #[error("cbor: duplicate map key {0:?}")]
    DuplicateMapKey(String),
    #[error("cbor: length prefix overflows available bytes")]
    LengthOverflow,
}

#[derive(Debug, Clone)]
pub enum CborValue {
    Uint(u64),
    Bstr(Vec<u8>),
    Tstr(String),
    Array(Vec<CborValue>),
    Map(BTreeMap<String, CborValue>),
}

impl CborValue {
    pub fn as_map(&self) -> Option<&BTreeMap<String, CborValue>> {
        match self {
            CborValue::Map(m) => Some(m),
            _ => None,
        }
    }
    pub fn as_bstr(&self) -> Option<&[u8]> {
        match self {
            CborValue::Bstr(b) => Some(b),
            _ => None,
        }
    }
    pub fn as_tstr(&self) -> Option<&str> {
        match self {
            CborValue::Tstr(s) => Some(s),
            _ => None,
        }
    }
}

pub(crate) fn decode(bytes: &[u8]) -> Result<CborValue, CborDecodeError> {
    let mut idx = 0;
    let v = decode_value(bytes, &mut idx)?;
    Ok(v)
}

/// Bounds-check helper: `idx + len` computed with an overflow-safe checked
/// add rather than `idx + len > bytes.len()`, which can wrap in release
/// builds when `len` derives from an attacker-controlled CBOR length prefix
/// (flagged in the cbor_index.rs soundness review; fixed here at the shared
/// source so every caller -- eager `decode_value` and the lazy index scan in
/// `cbor_index.rs` -- gets the fix for free).
pub(crate) fn checked_end(idx: usize, len: usize, total: usize) -> Result<usize, CborDecodeError> {
    let end = idx.checked_add(len).ok_or(CborDecodeError::LengthOverflow)?;
    if end > total {
        return Err(CborDecodeError::UnexpectedEof);
    }
    Ok(end)
}

pub(crate) fn read_head(bytes: &[u8], idx: &mut usize) -> Result<(u8, u64), CborDecodeError> {
    if *idx >= bytes.len() {
        return Err(CborDecodeError::UnexpectedEof);
    }
    let ib = bytes[*idx];
    *idx += 1;
    let major = ib >> 5;
    let info = ib & 0x1F;
    let arg = match info {
        0..=23 => info as u64,
        24 => {
            if *idx >= bytes.len() {
                return Err(CborDecodeError::UnexpectedEof);
            }
            let v = bytes[*idx] as u64;
            *idx += 1;
            v
        }
        25 => {
            if *idx + 2 > bytes.len() {
                return Err(CborDecodeError::UnexpectedEof);
            }
            let v = ((bytes[*idx] as u64) << 8) | (bytes[*idx + 1] as u64);
            *idx += 2;
            v
        }
        26 => {
            if *idx + 4 > bytes.len() {
                return Err(CborDecodeError::UnexpectedEof);
            }
            let v = ((bytes[*idx] as u64) << 24)
                | ((bytes[*idx + 1] as u64) << 16)
                | ((bytes[*idx + 2] as u64) << 8)
                | (bytes[*idx + 3] as u64);
            *idx += 4;
            v
        }
        27 => {
            if *idx + 8 > bytes.len() {
                return Err(CborDecodeError::UnexpectedEof);
            }
            let mut v = 0u64;
            for i in 0..8 {
                v = (v << 8) | (bytes[*idx + i] as u64);
            }
            *idx += 8;
            v
        }
        31 => return Err(CborDecodeError::IndefiniteLength),
        _ => return Err(CborDecodeError::UnsupportedMajor(ib)),
    };
    Ok((major, arg))
}

pub(crate) fn decode_value(bytes: &[u8], idx: &mut usize) -> Result<CborValue, CborDecodeError> {
    let (major, arg) = read_head(bytes, idx)?;
    match major {
        0 => Ok(CborValue::Uint(arg)),
        2 => {
            let len = arg as usize;
            let end = checked_end(*idx, len, bytes.len())?;
            let out = bytes[*idx..end].to_vec();
            *idx = end;
            Ok(CborValue::Bstr(out))
        }
        3 => {
            let len = arg as usize;
            let end = checked_end(*idx, len, bytes.len())?;
            let s = std::str::from_utf8(&bytes[*idx..end])
                .map_err(|_| CborDecodeError::BadUtf8)?
                .to_string();
            *idx = end;
            Ok(CborValue::Tstr(s))
        }
        4 => {
            let count = arg as usize;
            let mut out = Vec::with_capacity(count);
            for _ in 0..count {
                out.push(decode_value(bytes, idx)?);
            }
            Ok(CborValue::Array(out))
        }
        5 => {
            let count = arg as usize;
            let mut out = BTreeMap::new();
            for _ in 0..count {
                let key = decode_value(bytes, idx)?;
                let val = decode_value(bytes, idx)?;
                let key_s = match key {
                    CborValue::Tstr(s) => s,
                    _ => return Err(CborDecodeError::UnsupportedMajor(0xff)),
                };
                if out.insert(key_s.clone(), val).is_some() {
                    return Err(CborDecodeError::DuplicateMapKey(key_s));
                }
            }
            Ok(CborValue::Map(out))
        }
        m => Err(CborDecodeError::UnsupportedMajor(m)),
    }
}
