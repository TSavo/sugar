// SPDX-License-Identifier: MIT OR Apache-2.0
//
// SEAL-TIME MANIFEST (lane 1 of the join-manifest design). Per-proof
// projection index sealed into the `.proof` envelope at mint time, so
// cross-proof consistency at verify time can fetch exactly the closure it
// needs instead of scanning the whole pool.
//
//   manifest: BTreeMap<EufName, EufGroup { member_cids, contributor_bundle }>
//   ambient:  { closed_forall_cids, ground_callsite_fact_cids } -- UN-BUCKETED
//   version:  u32 semantics tag
//
// `manifest_cid` is `BLAKE3-512(canonical CBOR bytes)`, computed the same
// way every other catalog entry is content-addressed
// (`sugar_canonicalizer::blake3_512_of`). The manifest slot is embedded in
// the envelope's signed root (see `proof.rs`), so a byte-flip anywhere in it
// fails the whole-proof trust root (G4), not just a local integrity check.
//
// Ambient sets are NOT bucketed by EUF name: `with_ambient_foralls` (see
// sugar-verifier/src/consistency.rs) applies every closed forall pool-wide
// and lets the solver's MBQI decide relevance, and ground callsite facts are
// matched by inv-content + scope at solve time. Bucketing either would drop
// refutations a projection-based reader needs -> false PROVEN. So they are
// carried as flat, un-keyed CID sets that every group's projection unions in.
//
// Old `.proof` files minted before this slot existed simply have no
// `"manifest"` top-level key; readers treat `None` as "no manifest, fall
// back to pool scan" (see cbor_index.rs `CatalogIndex::manifest`). No
// behavior change for proofs that predate this lane.

use std::collections::{BTreeMap, BTreeSet};

use sugar_canonicalizer::blake3_512_of;

use crate::cbor::{cbor_encode_map_head, cbor_encode_tstr, cbor_encode_uint};
use crate::cbor_decode::{decode, CborDecodeError, CborValue};

/// Current manifest wire-format version. Bump on any incompatible change to
/// the shape below; readers that see an unknown version must fall back to
/// pool-scan (ConsistencyMode::PoolScanFallback), never guess.
pub const MANIFEST_VERSION: u32 = 1;

/// One `#euf#` bucket's projection index: which members (by CID) belong to
/// this EUF-named callsite group in THIS proof, and the CID of the
/// contributor's own bundle (the proof this group's members were minted
/// into) -- carried so a consumer can detect "this group's contributor was
/// re-minted since I last loaded it" without re-scanning bodies.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct EufGroup {
    pub member_cids: BTreeSet<String>,
    pub contributor_bundle: String,
}

/// The un-bucketed ambient sets: every closed universal and every closed
/// ground-callsite fact this proof contributes, regardless of which EUF
/// name(s) they happen to mention. Projected into every group's fetch, pool-
/// wide, exactly as `verify_consistency` conjoins them into every obligation
/// today.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct AmbientSets {
    pub closed_forall_cids: BTreeSet<String>,
    pub ground_callsite_fact_cids: BTreeSet<String>,
}

/// The full per-proof manifest sealed into the envelope at mint time.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Manifest {
    pub version: u32,
    pub groups: BTreeMap<String, EufGroup>,
    pub ambient: AmbientSets,
}

impl Manifest {
    pub fn new() -> Self {
        Manifest {
            version: MANIFEST_VERSION,
            groups: BTreeMap::new(),
            ambient: AmbientSets::default(),
        }
    }

    /// Canonical deterministic-CBOR encoding of this manifest. Same
    /// discipline as `proof.rs::emit_sorted_map`: keys sorted by bytewise
    /// CBOR-encoded-key form, definite-length, shortest-form integers.
    pub fn to_canonical_cbor(&self) -> Vec<u8> {
        let mut out = Vec::new();
        encode_manifest(&mut out, self);
        out
    }

    /// `blake3-512:<hex>` CID of this manifest's canonical CBOR bytes. This
    /// is the value sealed as `manifestCid` alongside the raw `manifest`
    /// bstr, and is what G1 (recompute-from-pool == stored manifest) and G4
    /// (byte-flip) check against.
    pub fn cid(&self) -> String {
        blake3_512_of(&self.to_canonical_cbor())
    }
}

// Encodes a sorted BTreeSet<String> as a CBOR array of tstr, sorted
// lexicographically (BTreeSet iteration order is already that).
fn encode_cid_set(out: &mut Vec<u8>, set: &BTreeSet<String>) {
    crate::cbor::cbor_encode_array_head(out, set.len() as u64);
    for cid in set {
        cbor_encode_tstr(out, cid);
    }
}

fn encode_euf_group(out: &mut Vec<u8>, group: &EufGroup) {
    // Two keys: "memberCids" (array of tstr, sorted), "contributorBundle"
    // (tstr). Sorted below by bytewise CBOR-encoded-key form, same as every
    // other map in this module.
    let mut pairs: Vec<(Vec<u8>, Vec<u8>)> = Vec::new();
    {
        let mut k = Vec::new();
        cbor_encode_tstr(&mut k, "contributorBundle");
        let mut v = Vec::new();
        cbor_encode_tstr(&mut v, &group.contributor_bundle);
        pairs.push((k, v));
    }
    {
        let mut k = Vec::new();
        cbor_encode_tstr(&mut k, "memberCids");
        let mut v = Vec::new();
        encode_cid_set(&mut v, &group.member_cids);
        pairs.push((k, v));
    }
    pairs.sort_by(|a, b| a.0.cmp(&b.0));
    cbor_encode_map_head(out, pairs.len() as u64);
    for (k, v) in pairs {
        out.extend_from_slice(&k);
        out.extend_from_slice(&v);
    }
}

fn encode_ambient(out: &mut Vec<u8>, ambient: &AmbientSets) {
    let mut pairs: Vec<(Vec<u8>, Vec<u8>)> = Vec::new();
    {
        let mut k = Vec::new();
        cbor_encode_tstr(&mut k, "closedForallCids");
        let mut v = Vec::new();
        encode_cid_set(&mut v, &ambient.closed_forall_cids);
        pairs.push((k, v));
    }
    {
        let mut k = Vec::new();
        cbor_encode_tstr(&mut k, "groundCallsiteFactCids");
        let mut v = Vec::new();
        encode_cid_set(&mut v, &ambient.ground_callsite_fact_cids);
        pairs.push((k, v));
    }
    pairs.sort_by(|a, b| a.0.cmp(&b.0));
    cbor_encode_map_head(out, pairs.len() as u64);
    for (k, v) in pairs {
        out.extend_from_slice(&k);
        out.extend_from_slice(&v);
    }
}

fn encode_groups(out: &mut Vec<u8>, groups: &BTreeMap<String, EufGroup>) {
    let mut pairs: Vec<(Vec<u8>, Vec<u8>)> = Vec::new();
    for (name, group) in groups {
        let mut k = Vec::new();
        cbor_encode_tstr(&mut k, name);
        let mut v = Vec::new();
        encode_euf_group(&mut v, group);
        pairs.push((k, v));
    }
    pairs.sort_by(|a, b| a.0.cmp(&b.0));
    cbor_encode_map_head(out, pairs.len() as u64);
    for (k, v) in pairs {
        out.extend_from_slice(&k);
        out.extend_from_slice(&v);
    }
}

fn encode_manifest(out: &mut Vec<u8>, manifest: &Manifest) {
    let mut pairs: Vec<(Vec<u8>, Vec<u8>)> = Vec::new();
    {
        let mut k = Vec::new();
        cbor_encode_tstr(&mut k, "version");
        let mut v = Vec::new();
        cbor_encode_uint(&mut v, manifest.version as u64);
        pairs.push((k, v));
    }
    {
        let mut k = Vec::new();
        cbor_encode_tstr(&mut k, "groups");
        let mut v = Vec::new();
        encode_groups(&mut v, &manifest.groups);
        pairs.push((k, v));
    }
    {
        let mut k = Vec::new();
        cbor_encode_tstr(&mut k, "ambient");
        let mut v = Vec::new();
        encode_ambient(&mut v, &manifest.ambient);
        pairs.push((k, v));
    }
    pairs.sort_by(|a, b| a.0.cmp(&b.0));
    cbor_encode_map_head(out, pairs.len() as u64);
    for (k, v) in pairs {
        out.extend_from_slice(&k);
        out.extend_from_slice(&v);
    }
}

fn decode_cid_set(v: &CborValue) -> Result<BTreeSet<String>, CborDecodeError> {
    let CborValue::Array(items) = v else {
        return Err(CborDecodeError::UnsupportedMajor(0xff));
    };
    let mut out = BTreeSet::new();
    for item in items {
        let s = item.as_tstr().ok_or(CborDecodeError::UnsupportedMajor(0xff))?;
        out.insert(s.to_string());
    }
    Ok(out)
}

impl Manifest {
    /// Decode a manifest previously produced by `to_canonical_cbor`. Used by
    /// the reader side (`cbor_index.rs`) to materialize the sealed slot once
    /// its CID has been verified against the caller-supplied `manifestCid`.
    pub fn from_canonical_cbor(bytes: &[u8]) -> Result<Manifest, CborDecodeError> {
        let top = decode(bytes)?;
        let map = top.as_map().ok_or(CborDecodeError::UnsupportedMajor(0xff))?;

        let version = match map.get("version") {
            Some(CborValue::Uint(v)) => *v as u32,
            _ => return Err(CborDecodeError::UnsupportedMajor(0xff)),
        };

        let mut groups = BTreeMap::new();
        if let Some(CborValue::Map(gmap)) = map.get("groups") {
            for (name, gval) in gmap {
                let gmap2 = gval.as_map().ok_or(CborDecodeError::UnsupportedMajor(0xff))?;
                let contributor_bundle = gmap2
                    .get("contributorBundle")
                    .and_then(|v| v.as_tstr())
                    .ok_or(CborDecodeError::UnsupportedMajor(0xff))?
                    .to_string();
                let member_cids = gmap2
                    .get("memberCids")
                    .ok_or(CborDecodeError::UnsupportedMajor(0xff))
                    .and_then(decode_cid_set)?;
                groups.insert(
                    name.clone(),
                    EufGroup {
                        member_cids,
                        contributor_bundle,
                    },
                );
            }
        } else if map.contains_key("groups") {
            return Err(CborDecodeError::UnsupportedMajor(0xff));
        }

        let mut ambient = AmbientSets::default();
        if let Some(CborValue::Map(amap)) = map.get("ambient") {
            if let Some(v) = amap.get("closedForallCids") {
                ambient.closed_forall_cids = decode_cid_set(v)?;
            }
            if let Some(v) = amap.get("groundCallsiteFactCids") {
                ambient.ground_callsite_fact_cids = decode_cid_set(v)?;
            }
        }

        Ok(Manifest {
            version,
            groups,
            ambient,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_manifest_is_deterministic() {
        let m = Manifest::new();
        let a = m.to_canonical_cbor();
        let b = m.to_canonical_cbor();
        assert_eq!(a, b);
        assert!(m.cid().starts_with("blake3-512:"));
    }

    #[test]
    fn cid_changes_on_any_field_change() {
        let base = Manifest::new();
        let base_cid = base.cid();

        let mut with_group = Manifest::new();
        with_group.groups.insert(
            "np.add#euf#(2,3)::assertion".to_string(),
            EufGroup {
                member_cids: BTreeSet::from(["blake3-512:aa".to_string()]),
                contributor_bundle: "blake3-512:bb".to_string(),
            },
        );
        assert_ne!(base_cid, with_group.cid());

        let mut with_ambient = Manifest::new();
        with_ambient
            .ambient
            .closed_forall_cids
            .insert("blake3-512:cc".to_string());
        assert_ne!(base_cid, with_ambient.cid());
        assert_ne!(with_group.cid(), with_ambient.cid());
    }

    #[test]
    fn encoding_is_stable_regardless_of_insertion_order() {
        let mut m1 = Manifest::new();
        m1.groups.insert(
            "b#euf#x".to_string(),
            EufGroup {
                member_cids: BTreeSet::from(["blake3-512:2".to_string(), "blake3-512:1".to_string()]),
                contributor_bundle: "blake3-512:z".to_string(),
            },
        );
        m1.groups.insert(
            "a#euf#y".to_string(),
            EufGroup {
                member_cids: BTreeSet::from(["blake3-512:3".to_string()]),
                contributor_bundle: "blake3-512:z".to_string(),
            },
        );

        // Build the same content via a different insertion order.
        let mut m2 = Manifest::new();
        m2.groups.insert(
            "a#euf#y".to_string(),
            EufGroup {
                member_cids: BTreeSet::from(["blake3-512:3".to_string()]),
                contributor_bundle: "blake3-512:z".to_string(),
            },
        );
        m2.groups.insert(
            "b#euf#x".to_string(),
            EufGroup {
                member_cids: BTreeSet::from(["blake3-512:1".to_string(), "blake3-512:2".to_string()]),
                contributor_bundle: "blake3-512:z".to_string(),
            },
        );

        assert_eq!(m1.to_canonical_cbor(), m2.to_canonical_cbor());
        assert_eq!(m1.cid(), m2.cid());
    }

    #[test]
    fn round_trips_through_canonical_cbor() {
        let mut m = Manifest::new();
        m.groups.insert(
            "np.add#euf#(2,3)::assertion".to_string(),
            EufGroup {
                member_cids: BTreeSet::from([
                    "blake3-512:aa".to_string(),
                    "blake3-512:bb".to_string(),
                ]),
                contributor_bundle: "blake3-512:cc".to_string(),
            },
        );
        m.ambient.closed_forall_cids.insert("blake3-512:dd".to_string());
        m.ambient
            .ground_callsite_fact_cids
            .insert("blake3-512:ee".to_string());

        let bytes = m.to_canonical_cbor();
        let back = Manifest::from_canonical_cbor(&bytes).expect("decodes");
        assert_eq!(m, back);
        assert_eq!(m.cid(), back.cid());
    }

    #[test]
    fn byte_flip_changes_cid() {
        let mut m = Manifest::new();
        m.groups.insert(
            "np.add#euf#(2,3)::assertion".to_string(),
            EufGroup {
                member_cids: BTreeSet::from(["blake3-512:aa".to_string()]),
                contributor_bundle: "blake3-512:cc".to_string(),
            },
        );
        let mut bytes = m.to_canonical_cbor();
        let original_cid = blake3_512_of(&bytes);
        // Flip one bit in the middle of the payload.
        let mid = bytes.len() / 2;
        bytes[mid] ^= 0x01;
        let flipped_cid = blake3_512_of(&bytes);
        assert_ne!(original_cid, flipped_cid);
    }
}
