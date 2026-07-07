// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Lazy CID-range index over a `.proof` catalog's deterministic-CBOR bytes.
//
// INCREMENT 1 of the "path to the parts you need" plan: this module is
// ADDITIVE and INERT. It is not called from `ProofGraph::read`,
// `load_all_proofs.rs`, `MementoPool`, or `consistency.rs`. Nothing in the
// production load path changes; the whole-file BLAKE3-512 gate
// (`load_all_proofs.rs`) remains the sole active trust mechanism for the
// eager loader. This module exists so a later, separately-reviewed
// increment can wire a lazy `MementoPool` population path against it.
//
// What it does:
//
//   1. `build_index` makes ONE linear pass over the catalog's `atoms`,
//      `body`, and `members` CBOR maps and records the **byte range**
//      (start, len) of each entry's `bstr` payload -- it never
//      JSON-parses or copies a payload. This is the piece that makes
//      "index without deserializing values" true.
//
//   2. `fetch_one` takes a `CatalogIndex`-derived range plus the CID the
//      caller expects at that range, seeks to it, and returns the payload
//      bytes **only after** recomputing that entry's own CID (and, for
//      members, verifying signer/signature) and checking it against the
//      caller-supplied CID. A byte range alone is never trusted; CID
//      equality is what is load-bearing, per the soundness review's
//      finding (c).
//
// Reuse, not reimplementation, of the audited decoder:
//
//   - The top-level map walk and the leaf-length arithmetic reuse
//     `cbor_decode::read_head` / `cbor_decode::decode_value` /
//     `cbor_decode::checked_end` verbatim (all made `pub(crate)` for this
//     purpose). The ONLY new decoding logic here is the inner
//     `scan_range_map`, which is structurally identical to
//     `decode_value`'s major-type-5 (map) case except it records a byte
//     range for each `bstr` value instead of copying it -- unavoidably
//     different from `decode_value` (which always materializes), but nothing
//     else is reimplemented, and the same duplicate-key check
//     (`insert(..).is_some()`) is preserved verbatim.
//
//   - CID recomputation reuses the exact functions the eager loader already
//     uses and that are covered by the existing test suite:
//     `sugar_canonicalizer::jcs_cid_of_json` for atoms and bodies (both are
//     `blake3_512(JCS(canonical(json)))` over the raw entry bytes -- the
//     same rule `AtomCid`/`ContractBodyCid` apply), and
//     `crate::proof_graph::recompute_member_cid` /
//     `crate::proof_graph::verify_member_signature` for members (the exact
//     functions `AnchoredMember::new` calls).
//
// Soundness note on members (fixes a gap `AnchoredMember::new` has today):
// `AnchoredMember::new` only verifies a signature if the envelope *carries*
// one -- an absent-signature member with an unmodified CID passes silently.
// `fetch_one` closes that gap for the lazy path: it requires
// `member_signature(&envelope).is_some()` unconditionally before calling
// `verify_member_signature`, rejecting unsigned members outright rather than
// delegating to `AnchoredMember::new`'s permissive check. This does not fix
// `AnchoredMember::new` itself (out of scope for this increment; it remains
// the eager eager path's behavior), but this module's own gate does not
// inherit the bug.
//
// Known, stated (not silent) weakening versus the eager path: per-entry CID
// (and, for members, signature) verification alone is STRICTLY WEAKER than
// the eager loader's whole-file BLAKE3-512 gate -- an attacker could still
// splice together a catalog whose individual entries are each internally
// self-consistent but which never existed as a single hash-recorded file.
// Increment 2 (a streaming whole-file hash folded into `build_index`'s single
// pass) closes that gap; until it lands and is wired in, `fetch_one`'s
// guarantee is "this entry is what it claims to be", not "this file is
// blessed".

use std::collections::{BTreeMap, BTreeSet};

use serde_json::Value as Json;
use sugar_canonicalizer::jcs_cid_of_json;

use crate::cbor_decode::{checked_end, decode_value, read_head, CborDecodeError, CborValue};
use crate::proof_graph::{member_signature, recompute_member_cid, verify_member_signature};

/// A half-open byte range `[start, start+len)` into the catalog's raw bytes,
/// naming exactly one CBOR `bstr` payload (no header bytes included).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct EntryRange {
    pub start: usize,
    pub len: usize,
}

impl EntryRange {
    fn end(&self) -> Result<usize, FetchError> {
        self.start
            .checked_add(self.len)
            .ok_or(FetchError::RangeOverflow)
    }
}

/// Which of the catalog's three CID maps an entry came from. Verification
/// differs per kind: atoms and bodies are unsigned content, members carry a
/// signer/signature that must additionally verify.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EntryKind {
    Atom,
    Body,
    Member,
}

/// The CID -> byte-range index for one catalog's `atoms`, `body`, and
/// `members` maps. Built by a single pass over the raw bytes with no
/// payload copying (`build_index`); consumed by `fetch_one`.
#[derive(Debug, Clone, Default)]
pub struct CatalogIndex {
    pub atoms: BTreeMap<String, EntryRange>,
    pub bodies: BTreeMap<String, EntryRange>,
    pub members: BTreeMap<String, EntryRange>,
}

impl CatalogIndex {
    pub fn is_empty(&self) -> bool {
        self.atoms.is_empty() && self.bodies.is_empty() && self.members.is_empty()
    }

    pub fn len(&self) -> usize {
        self.atoms.len() + self.bodies.len() + self.members.len()
    }
}

/// Errors from `fetch_one`. Every variant means "refuse to hand back bytes";
/// there is no code path in `fetch_one` that returns a payload without a
/// passing CID (and, for members, signature) check.
#[derive(Debug, thiserror::Error)]
pub enum FetchError {
    #[error("cbor-index: range overflows usize")]
    RangeOverflow,
    #[error("cbor-index: range [{start}, {end}) out of bounds for {total} catalog bytes")]
    RangeOutOfBounds {
        start: usize,
        end: usize,
        total: usize,
    },
    #[error("cbor-index: entry bytes are not JSON: {0}")]
    NotJson(serde_json::Error),
    #[error("cbor-index: expected CID {expected}, entry recomputes to {actual}")]
    CidMismatch { expected: String, actual: String },
    #[error("cbor-index: member {0} has no signature; unsigned members are refused")]
    SignatureMissing(String),
    #[error("cbor-index: member {cid}: {reason}")]
    SignatureInvalid { cid: String, reason: String },
}

/// Build a `CatalogIndex` over a `.proof` catalog's raw CBOR bytes.
///
/// Single linear pass. For the `atoms`, `body`, and `members` top-level
/// keys, records `(cid -> EntryRange)` for each entry's `bstr` payload
/// without copying it. Every other top-level key (`kind`, `name`,
/// `version`, `signer`, `declaredAt`, `metadata`, `binaryCid`, `signature`,
/// ...) is skipped structurally via the existing, audited `decode_value`
/// (which does allocate for those -- they are small catalog-identity
/// fields, not the multi-megabyte payload maps this index exists to avoid
/// materializing).
pub fn build_index(bytes: &[u8]) -> Result<CatalogIndex, CborDecodeError> {
    let mut idx = 0usize;
    let (major, arg) = read_head(bytes, &mut idx)?;
    if major != 5 {
        return Err(CborDecodeError::UnsupportedMajor(major << 5));
    }
    let count = arg as usize;

    let mut index = CatalogIndex::default();
    let mut seen_top_keys: BTreeSet<String> = BTreeSet::new();

    for _ in 0..count {
        let key = decode_value(bytes, &mut idx)?;
        let key_s = match key {
            CborValue::Tstr(s) => s,
            _ => return Err(CborDecodeError::UnsupportedMajor(0xff)),
        };
        if !seen_top_keys.insert(key_s.clone()) {
            return Err(CborDecodeError::DuplicateMapKey(key_s));
        }
        match key_s.as_str() {
            "atoms" => index.atoms = scan_range_map(bytes, &mut idx)?,
            "body" => index.bodies = scan_range_map(bytes, &mut idx)?,
            "members" => index.members = scan_range_map(bytes, &mut idx)?,
            _ => {
                // Not one of the three payload maps this index covers:
                // decode (and discard) structurally so `idx` advances past
                // it correctly, reusing the audited decoder rather than a
                // second hand-rolled skip routine.
                let _ = decode_value(bytes, &mut idx)?;
            }
        }
    }

    Ok(index)
}

/// Structurally identical to `decode_value`'s map case (major type 5),
/// including its duplicate-key check, except each value MUST be a `bstr`
/// (major type 2) and is recorded as a byte range instead of being copied.
fn scan_range_map(
    bytes: &[u8],
    idx: &mut usize,
) -> Result<BTreeMap<String, EntryRange>, CborDecodeError> {
    let (major, arg) = read_head(bytes, idx)?;
    if major != 5 {
        return Err(CborDecodeError::UnsupportedMajor(major << 5));
    }
    let count = arg as usize;
    let mut out = BTreeMap::new();
    for _ in 0..count {
        let key = decode_value(bytes, idx)?;
        let key_s = match key {
            CborValue::Tstr(s) => s,
            _ => return Err(CborDecodeError::UnsupportedMajor(0xff)),
        };
        let (vmajor, vlen) = read_head(bytes, idx)?;
        if vmajor != 2 {
            return Err(CborDecodeError::UnsupportedMajor(vmajor << 5));
        }
        let len = vlen as usize;
        let end = checked_end(*idx, len, bytes.len())?;
        let range = EntryRange { start: *idx, len };
        *idx = end;
        if out.insert(key_s.clone(), range).is_some() {
            return Err(CborDecodeError::DuplicateMapKey(key_s));
        }
    }
    Ok(out)
}

/// Seek to `range` in `bytes`, parse it as JSON, recompute its CID (and, for
/// members, verify signer/signature), and return the raw payload bytes only
/// on a passing match. `cid` is the CID the caller (index lookup) expects to
/// find there -- range/offset metadata is never itself trusted; CID equality
/// is.
pub fn fetch_one(
    bytes: &[u8],
    kind: EntryKind,
    cid: &str,
    range: EntryRange,
) -> Result<Vec<u8>, FetchError> {
    let end = range.end()?;
    if end > bytes.len() {
        return Err(FetchError::RangeOutOfBounds {
            start: range.start,
            end,
            total: bytes.len(),
        });
    }
    let raw = &bytes[range.start..end];

    match kind {
        EntryKind::Atom | EntryKind::Body => {
            // Atoms and bodies are both unsigned content whose CID is
            // `blake3_512(JCS(canonical(json)))` -- the same rule
            // `AtomCid::from_bytes` / `ContractBodyCid::from_bytes` apply to
            // the bytes the eager loader re-encodes. Since the eager loader
            // recomputes those bytes via the SAME canonicalization the raw
            // stored bytes were produced with, `jcs_cid_of_json` over the raw
            // bytes reproduces the identical CID without needing to
            // reconstruct a `FlatAtom`/`ContractBody` value here.
            let json: Json = serde_json::from_slice(raw).map_err(FetchError::NotJson)?;
            let actual = jcs_cid_of_json(&json);
            if actual != cid {
                return Err(FetchError::CidMismatch {
                    expected: cid.to_string(),
                    actual,
                });
            }
            Ok(raw.to_vec())
        }
        EntryKind::Member => {
            let envelope: Json = serde_json::from_slice(raw).map_err(FetchError::NotJson)?;
            let actual = recompute_member_cid(&envelope);
            if actual != cid {
                return Err(FetchError::CidMismatch {
                    expected: cid.to_string(),
                    actual,
                });
            }
            // Unconditional signature requirement: unlike
            // `AnchoredMember::new` (which only verifies a signature if one
            // is present, silently no-op'ing on an absent signature), this
            // gate refuses any member without one. Closes the confirmed gap
            // the soundness review flagged: a legacy-format member's CID
            // hash excludes `producerSignature`, so deleting the signature
            // does not change the CID -- CID match alone must never be
            // accepted as authentication for members.
            if member_signature(&envelope).is_none() {
                return Err(FetchError::SignatureMissing(cid.to_string()));
            }
            verify_member_signature(&envelope).map_err(|reason| FetchError::SignatureInvalid {
                cid: cid.to_string(),
                reason,
            })?;
            Ok(raw.to_vec())
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::cbor::{cbor_encode_bstr, cbor_encode_map_head, cbor_encode_tstr};
    use crate::proof::{build_proof_envelope, ProofEnvelopeInput};
    use crate::proof_graph::{AtomMemento, ContractBody, ContractMemento, FlatAtom, ProofGraph};
    use std::collections::BTreeMap as StdBTreeMap;

    // ---- hand-built synthetic catalogs -----------------------------------

    fn small_catalog(atoms: &[(&str, &[u8])], members: &[(&str, &[u8])]) -> Vec<u8> {
        let mut out = Vec::new();
        cbor_encode_map_head(&mut out, 2);
        cbor_encode_tstr(&mut out, "atoms");
        cbor_encode_map_head(&mut out, atoms.len() as u64);
        for (cid, bytes) in atoms {
            cbor_encode_tstr(&mut out, cid);
            cbor_encode_bstr(&mut out, bytes);
        }
        cbor_encode_tstr(&mut out, "members");
        cbor_encode_map_head(&mut out, members.len() as u64);
        for (cid, bytes) in members {
            cbor_encode_tstr(&mut out, cid);
            cbor_encode_bstr(&mut out, bytes);
        }
        out
    }

    #[test]
    fn build_index_on_empty_maps_yields_empty_index() {
        let bytes = small_catalog(&[], &[]);
        let index = build_index(&bytes).expect("empty catalog indexes");
        assert!(index.is_empty());
    }

    #[test]
    fn build_index_records_ranges_that_slice_back_to_original_bytes() {
        let bytes = small_catalog(&[("cid-a", b"{\"x\":1}")], &[("cid-m", b"{\"y\":2}")]);
        let index = build_index(&bytes).expect("indexes");
        assert_eq!(index.len(), 2);
        let a = index.atoms.get("cid-a").expect("atom present");
        assert_eq!(&bytes[a.start..a.start + a.len], b"{\"x\":1}");
        let m = index.members.get("cid-m").expect("member present");
        assert_eq!(&bytes[m.start..m.start + m.len], b"{\"y\":2}");
    }

    #[test]
    fn build_index_rejects_duplicate_inner_key() {
        // Hand-build a catalog whose `atoms` map has the same key twice --
        // not expressible through `small_catalog`'s slice-of-pairs input, so
        // encode it directly.
        let mut out = Vec::new();
        cbor_encode_map_head(&mut out, 1);
        cbor_encode_tstr(&mut out, "atoms");
        cbor_encode_map_head(&mut out, 2);
        cbor_encode_tstr(&mut out, "dup");
        cbor_encode_bstr(&mut out, b"{}");
        cbor_encode_tstr(&mut out, "dup");
        cbor_encode_bstr(&mut out, b"{}");
        let err = build_index(&out).expect_err("duplicate key must be rejected");
        assert!(matches!(err, CborDecodeError::DuplicateMapKey(_)));
    }

    #[test]
    fn build_index_rejects_duplicate_top_level_key() {
        // Two "atoms" keys at the catalog root.
        let mut out = Vec::new();
        cbor_encode_map_head(&mut out, 2);
        cbor_encode_tstr(&mut out, "atoms");
        cbor_encode_map_head(&mut out, 0);
        cbor_encode_tstr(&mut out, "atoms");
        cbor_encode_map_head(&mut out, 0);
        let err = build_index(&out).expect_err("duplicate top-level key must be rejected");
        assert!(matches!(err, CborDecodeError::DuplicateMapKey(_)));
    }

    #[test]
    fn build_index_skips_non_payload_top_level_keys() {
        let mut out = Vec::new();
        cbor_encode_map_head(&mut out, 2);
        cbor_encode_tstr(&mut out, "kind");
        cbor_encode_tstr(&mut out, "catalog");
        cbor_encode_tstr(&mut out, "members");
        cbor_encode_map_head(&mut out, 1);
        cbor_encode_tstr(&mut out, "cid-m");
        cbor_encode_bstr(&mut out, b"{}");
        let index = build_index(&out).expect("indexes past a skipped scalar key");
        assert_eq!(index.members.len(), 1);
    }

    #[test]
    fn build_index_handles_nested_array_value_under_a_skipped_key() {
        // A top-level key whose value is an array (major type 4), to
        // exercise decode_value's recursive dispatch through the "skip"
        // path.
        let mut out = Vec::new();
        cbor_encode_map_head(&mut out, 2);
        cbor_encode_tstr(&mut out, "tags");
        crate::cbor::cbor_encode_array_head(&mut out, 2);
        cbor_encode_tstr(&mut out, "a");
        cbor_encode_tstr(&mut out, "b");
        cbor_encode_tstr(&mut out, "members");
        cbor_encode_map_head(&mut out, 0);
        let index = build_index(&out).expect("indexes past a nested array value");
        assert!(index.members.is_empty());
    }

    // ---- adversarial length fields -----------------------------------

    #[test]
    fn build_index_rejects_truncated_bstr_length_without_panicking() {
        let mut out = Vec::new();
        cbor_encode_map_head(&mut out, 1);
        cbor_encode_tstr(&mut out, "atoms");
        cbor_encode_map_head(&mut out, 1);
        cbor_encode_tstr(&mut out, "cid-a");
        // Claim a 9-byte bstr but supply none of the payload.
        out.push((2u8 << 5) | 25); // major 2, 2-byte length follows
        out.push(0x00);
        out.push(0x09);
        let err = build_index(&out).expect_err("truncated length must error, not panic");
        assert!(matches!(err, CborDecodeError::UnexpectedEof));
    }

    #[test]
    fn build_index_rejects_length_prefix_that_would_overflow_usize() {
        let mut out = Vec::new();
        cbor_encode_map_head(&mut out, 1);
        cbor_encode_tstr(&mut out, "atoms");
        cbor_encode_map_head(&mut out, 1);
        cbor_encode_tstr(&mut out, "cid-a");
        // major 2 (bstr), 8-byte length field = u64::MAX.
        out.push((2u8 << 5) | 27);
        out.extend_from_slice(&u64::MAX.to_be_bytes());
        let err =
            build_index(&out).expect_err("u64::MAX length must error, not panic or wrap");
        assert!(
            matches!(
                err,
                CborDecodeError::LengthOverflow | CborDecodeError::UnexpectedEof
            ),
            "{err:?}"
        );
    }

    #[test]
    fn fetch_one_rejects_out_of_bounds_range_without_panicking() {
        let bytes = small_catalog(&[("cid-a", b"{}")], &[]);
        let bogus = EntryRange {
            start: bytes.len(),
            len: 10,
        };
        let err = fetch_one(&bytes, EntryKind::Atom, "cid-a", bogus)
            .expect_err("out-of-bounds range must be refused");
        assert!(matches!(err, FetchError::RangeOutOfBounds { .. }));
    }

    #[test]
    fn fetch_one_rejects_range_whose_start_plus_len_overflows_usize() {
        let bytes = small_catalog(&[("cid-a", b"{}")], &[]);
        let bogus = EntryRange {
            start: usize::MAX - 1,
            len: 10,
        };
        let err = fetch_one(&bytes, EntryKind::Atom, "cid-a", bogus)
            .expect_err("overflowing range must be refused");
        assert!(matches!(err, FetchError::RangeOverflow));
    }

    // ---- fetch_one CID / signature verification --------------------------

    #[test]
    fn fetch_one_rejects_cid_mismatch_on_atom() {
        let bytes = small_catalog(&[("wrong-cid", b"{\"x\":1}")], &[]);
        let range = *small_catalog_atom_range(&bytes);
        let err = fetch_one(&bytes, EntryKind::Atom, "wrong-cid", range)
            .expect_err("a made-up CID must not verify");
        assert!(matches!(err, FetchError::CidMismatch { .. }));
    }

    fn small_catalog_atom_range(bytes: &[u8]) -> Box<EntryRange> {
        let index = build_index(bytes).expect("indexes");
        Box::new(*index.atoms.get("wrong-cid").expect("range present"))
    }

    fn real_atom_fixture() -> (Vec<u8>, String) {
        let atom = FlatAtom::result_eq_int(1);
        let cid = atom.cid().as_str().to_string();
        (atom.bytes().to_vec(), cid)
    }

    #[test]
    fn fetch_one_accepts_a_real_atom_at_its_correct_cid() {
        let (atom_bytes, cid) = real_atom_fixture();
        let bytes = small_catalog(&[(cid.as_str(), atom_bytes.as_slice())], &[]);
        let index = build_index(&bytes).expect("indexes");
        let range = *index.atoms.get(cid.as_str()).expect("range present");
        let fetched =
            fetch_one(&bytes, EntryKind::Atom, &cid, range).expect("real atom verifies");
        assert_eq!(fetched, atom_bytes);
    }

    #[test]
    fn fetch_one_rejects_bit_flipped_entry_without_touching_the_rest_of_the_file() {
        let (atom_bytes, cid) = real_atom_fixture();
        let other_atom = FlatAtom::result_eq_int(2);
        let other_cid = other_atom.cid().as_str().to_string();
        let mut bytes = small_catalog(
            &[
                (cid.as_str(), atom_bytes.as_slice()),
                (other_cid.as_str(), other_atom.bytes()),
            ],
            &[],
        );
        let index = build_index(&bytes).expect("indexes");
        let flipped_range = *index.atoms.get(cid.as_str()).expect("range present");
        let untouched_range = *index.atoms.get(other_cid.as_str()).expect("range present");

        // Flip one bit inside the FIRST atom's payload only.
        let flip_at = flipped_range.start;
        bytes[flip_at] ^= 0x01;

        let err = fetch_one(&bytes, EntryKind::Atom, &cid, flipped_range)
            .expect_err("bit-flipped entry must be rejected");
        assert!(matches!(err, FetchError::CidMismatch { .. } | FetchError::NotJson(_)));

        // The untouched entry elsewhere in the same file must still verify.
        let fetched = fetch_one(&bytes, EntryKind::Atom, &other_cid, untouched_range)
            .expect("untouched entry in the same file still verifies");
        assert_eq!(fetched, other_atom.bytes());
    }

    /// Builds a real `.proof` file (via the actual envelope builder, not a
    /// hand-rolled approximation) containing: one formula atom, one metadata
    /// atom, a body over the formula atom, and a signed layered contract
    /// member over that body, then cross-checks the lazy index against the
    /// eager `ProofGraph::read` path. Every member in this fixture is signed
    /// (unsigned members are a separate, deliberately-refused case covered by
    /// `fetch_one_rejects_legacy_shape_member_with_signature_and_cid_field_both_stripped`)
    /// so the "every fetched payload matches the eager path" assertion below
    /// exercises the passing case end to end.
    fn real_proof_fixture() -> (Vec<u8>, ProofGraph) {
        let mut graph = ProofGraph::new();

        let atom = FlatAtom::result_eq_int(1);
        let atom_memento = AtomMemento::new(&atom);
        let body = ContractBody::new(&atom_memento);
        let metadata_atom = FlatAtom::empty_metadata();
        let contract = ContractMemento::new("crate::f", &body, [0x11; 32]);

        graph.register_atom(atom);
        graph.register_atom(metadata_atom);
        graph.register_body(body);
        graph.register_contract(contract);

        let input = ProofEnvelopeInput {
            name: "@x/y".to_string(),
            version: "0.0.1".to_string(),
            binary_cid: None,
            metadata: None,
            graph: graph.clone(),
            signer_cid: "blake3-512:bb".to_string(),
            signer_seed: [0x22; 32],
            declared_at: "2026-04-30T00:00:00.000Z".to_string(),
        };
        let out = build_proof_envelope(&input);
        (out.bytes, graph)
    }

    #[test]
    fn lazy_index_yields_the_same_cid_set_as_eager_read_for_a_real_proof_file() {
        let (bytes, expected_graph) = real_proof_fixture();
        let index = build_index(&bytes).expect("real proof indexes");

        let eager_atoms: BTreeMap<String, Vec<u8>> = expected_graph
            .atoms()
            .map(|a| (a.cid().as_str().to_string(), a.bytes().to_vec()))
            .collect();
        let eager_bodies: BTreeMap<String, Vec<u8>> = expected_graph
            .bodies()
            .map(|b| (b.cid().as_str().to_string(), b.bytes().to_vec()))
            .collect();
        let eager_members: StdBTreeMap<String, Vec<u8>> = expected_graph
            .members()
            .map(|(cid, bytes)| (cid.as_str().to_string(), bytes.to_vec()))
            .collect();

        assert_eq!(
            index.atoms.keys().cloned().collect::<Vec<_>>(),
            eager_atoms.keys().cloned().collect::<Vec<_>>()
        );
        assert_eq!(
            index.bodies.keys().cloned().collect::<Vec<_>>(),
            eager_bodies.keys().cloned().collect::<Vec<_>>()
        );
        assert_eq!(
            index.members.keys().cloned().collect::<Vec<_>>(),
            eager_members.keys().cloned().collect::<Vec<_>>()
        );

        // Also cross-check directly against what ProofGraph::read() (the
        // production eager path) produces from these exact bytes.
        let eager_read = ProofGraph::read(&bytes).expect("eager read of the same bytes");
        let eager_read_members: StdBTreeMap<String, Vec<u8>> = eager_read
            .members()
            .map(|(cid, bytes)| (cid.as_str().to_string(), bytes.to_vec()))
            .collect();
        assert_eq!(
            index.members.keys().cloned().collect::<Vec<_>>(),
            eager_read_members.keys().cloned().collect::<Vec<_>>()
        );

        for (cid, range) in &index.atoms {
            let fetched = fetch_one(&bytes, EntryKind::Atom, cid, *range)
                .unwrap_or_else(|e| panic!("real atom {cid} must verify: {e}"));
            assert_eq!(&fetched, eager_atoms.get(cid).unwrap());
        }
        for (cid, range) in &index.bodies {
            let fetched = fetch_one(&bytes, EntryKind::Body, cid, *range)
                .unwrap_or_else(|e| panic!("real body {cid} must verify: {e}"));
            assert_eq!(&fetched, eager_bodies.get(cid).unwrap());
        }
        for (cid, range) in &index.members {
            let fetched = fetch_one(&bytes, EntryKind::Member, cid, *range)
                .unwrap_or_else(|e| panic!("real member {cid} must verify: {e}"));
            assert_eq!(&fetched, eager_members.get(cid).unwrap());
            assert_eq!(&fetched, eager_read_members.get(cid).unwrap());
        }
    }

    #[test]
    fn fetch_one_rejects_member_with_signature_stripped() {
        let (bytes, _graph) = real_proof_fixture();
        let index = build_index(&bytes).expect("real proof indexes");
        let (cid, range) = index
            .members
            .iter()
            .next()
            .map(|(c, r)| (c.clone(), *r))
            .expect("at least one member");

        let end = range.start + range.len;
        let raw = &bytes[range.start..end];
        let mut envelope: Json = serde_json::from_slice(raw).expect("member is JSON");
        // Strip the layered signature -- this member's CID hash covers the
        // whole `envelope` object unstripped (proof_graph.rs's layered
        // branch), so this SHOULD also change the CID and get caught by the
        // CID check. Assert it is refused either way (CID mismatch or,
        // if some future member shape's CID happened to be insensitive to
        // this field, the unconditional signature-presence gate).
        if let Some(env) = envelope.get_mut("envelope") {
            if let Some(map) = env.as_object_mut() {
                map.remove("signature");
            }
        }
        let mut spliced = bytes.clone();
        let stripped_bytes = serde_json::to_vec(&envelope).expect("reserialize");
        // Splice requires equal length to keep other ranges valid; instead of
        // an in-place splice (lengths differ), just call fetch_one against a
        // synthetic single-entry catalog carrying the stripped bytes so we
        // exercise fetch_one's own gate directly.
        let _ = &mut spliced; // unused; direct fetch_one call below instead.
        let synthetic = small_catalog(&[], &[(cid.as_str(), stripped_bytes.as_slice())]);
        let synthetic_index = build_index(&synthetic).expect("synthetic indexes");
        let synthetic_range = *synthetic_index.members.get(cid.as_str()).unwrap();
        let err = fetch_one(&synthetic, EntryKind::Member, &cid, synthetic_range)
            .expect_err("member with signature stripped must be refused");
        assert!(
            matches!(
                err,
                FetchError::CidMismatch { .. }
                    | FetchError::SignatureMissing(_)
                    | FetchError::SignatureInvalid { .. }
            ),
            "{err:?}"
        );
    }

    #[test]
    fn fetch_one_rejects_legacy_shape_member_with_signature_and_cid_field_both_stripped() {
        // The soundness review's CONFIRMED gap: a legacy/flat-format member's
        // CID hash computation strips `cid` and `producerSignature` before
        // hashing, so an attacker who deletes `producerSignature` produces
        // a member whose CID re-derives to the SAME value. `fetch_one` must
        // refuse it anyway via the unconditional signature-presence gate
        // (not by delegating to `AnchoredMember::new`, which would silently
        // accept this).
        let legacy = serde_json::json!({
            "header": { "kind": "witness-memento" },
            "body": { "ok": true }
        });
        // No `producerSignature` field at all: CID is computed over the
        // object with `cid`/`producerSignature` stripped (no-ops here since
        // neither is present), so this is exactly the legacy shape's CID.
        let cid = recompute_member_cid(&legacy);
        let raw = serde_json::to_vec(&legacy).expect("legacy JSON bytes");
        let synthetic = small_catalog(&[], &[(cid.as_str(), raw.as_slice())]);
        let index = build_index(&synthetic).expect("indexes");
        let range = *index.members.get(cid.as_str()).unwrap();

        let err = fetch_one(&synthetic, EntryKind::Member, &cid, range)
            .expect_err("unsigned legacy member must be refused despite a matching CID");
        assert!(matches!(err, FetchError::SignatureMissing(_)));
    }
}
